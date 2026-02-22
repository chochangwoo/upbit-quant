"""
업비트 자동매매 시스템 - 메인 실행 파일
실행 방법: python main.py

[변동성 돌파 전략 흐름]
  오전 09:00 → 새 거래일 시작, 매수 기록 초기화
  09:00~08:49 → 1분마다 매수 조건 체크 (조건 충족 시 매수)
  오전 08:50 → 보유 코인 전량 매도
  종료 후 반복
"""
import os
import sys
import time
import schedule
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

# .env 파일 로드 (가장 먼저 실행)
load_dotenv()

from src.api.upbit_client import (
    get_current_price,
    get_balance_krw,
    get_balance_coin,
    buy_market_order,
    sell_market_order,
)
from src.strategies.volatility_breakout import should_buy, calculate_target_price
from src.notifications.telegram_bot import send_message, send_buy_alert, send_sell_alert, send_error_alert
from src.database.supabase_client import save_trade
from config.settings import TARGET_COINS, ORDER_AMOUNT, LIVE_TRADING

# ─────────────────────────────────────────
# 로그 설정: 콘솔 + 파일 동시 저장
# ─────────────────────────────────────────
logger.remove()  # 기본 핸들러 제거
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/trading_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    level="DEBUG",
    rotation="00:00",   # 매일 자정에 새 파일
    retention="30 days", # 30일치 보관
    encoding="utf-8",
)

# 당일 매수한 코인 기록 (중복 매수 방지)
bought_today: set = set()


def do_sell_all():
    """
    보유 중인 모든 코인을 시장가로 매도합니다.
    매일 오전 8:50에 실행됩니다.
    """
    logger.info("=== 매도 시간 (08:50) - 보유 코인 전량 매도 시작 ===")

    for ticker in TARGET_COINS:
        volume = get_balance_coin(ticker)

        if volume is None or volume < 0.00001:  # 보유량이 없으면 건너뜀
            logger.info(f"[{ticker}] 보유 수량 없음, 매도 생략")
            continue

        current_price = get_current_price(ticker)

        if LIVE_TRADING:
            # 실제 매도 실행
            result = sell_market_order(ticker, volume)
            if result:
                sell_amount = volume * current_price
                save_trade(ticker, "sell", current_price, sell_amount, volume)
                send_sell_alert(ticker, current_price, profit_rate=0)  # 수익률은 추후 계산
                logger.info(f"[{ticker}] 매도 완료: {volume} → {current_price:,.0f}원")
            else:
                send_error_alert(f"{ticker} 매도 실패! 수동으로 확인하세요.")
        else:
            # 시뮬레이션 모드
            sell_amount = volume * current_price
            logger.info(f"[시뮬] [{ticker}] 매도 → 수량: {volume:.6f}, 금액: {sell_amount:,.0f}원")
            send_message(f"[시뮬] {ticker} 매도\n수량: {volume:.6f}\n현재가: {current_price:,.0f}원")


def do_buy_check():
    """
    각 코인의 매수 조건을 확인하고, 조건 충족 시 매수합니다.
    """
    for ticker in TARGET_COINS:

        # 당일 이미 매수한 코인은 건너뜀
        if ticker in bought_today:
            logger.debug(f"[{ticker}] 오늘 이미 매수함, 건너뜀")
            continue

        # 매수 조건 확인
        if not should_buy(ticker):
            continue

        # 매수 가능한 원화 잔고 확인
        krw_balance = get_balance_krw()
        if krw_balance < ORDER_AMOUNT:
            logger.warning(
                f"[{ticker}] 원화 잔고 부족: "
                f"보유 {krw_balance:,.0f}원 < 필요 {ORDER_AMOUNT:,.0f}원"
            )
            continue

        current_price = get_current_price(ticker)

        if LIVE_TRADING:
            # 실제 매수 실행
            result = buy_market_order(ticker, ORDER_AMOUNT)
            if result:
                quantity = ORDER_AMOUNT / current_price
                save_trade(ticker, "buy", current_price, ORDER_AMOUNT, quantity)
                send_buy_alert(ticker, current_price, ORDER_AMOUNT)
                bought_today.add(ticker)
                logger.info(f"[{ticker}] 매수 완료: {ORDER_AMOUNT:,.0f}원")
            else:
                send_error_alert(f"{ticker} 매수 실패!")
        else:
            # 시뮬레이션 모드
            quantity = ORDER_AMOUNT / current_price
            bought_today.add(ticker)
            logger.info(
                f"[시뮬] [{ticker}] 매수 → "
                f"금액: {ORDER_AMOUNT:,.0f}원, 수량: {quantity:.6f}, 가격: {current_price:,.0f}원"
            )
            send_message(
                f"[시뮬] {ticker} 매수 신호\n"
                f"금액: {ORDER_AMOUNT:,.0f}원\n"
                f"수량: {quantity:.6f}\n"
                f"현재가: {current_price:,.0f}원"
            )


def trading_job():
    """
    1분마다 실행되는 메인 트레이딩 로직입니다.
    현재 시각에 따라 매수/매도를 결정합니다.
    """
    now = datetime.now()
    hour, minute = now.hour, now.minute

    # 오전 8:50 ~ 8:59 → 전량 매도
    if hour == 8 and 50 <= minute <= 59:
        do_sell_all()

    # 오전 9:00 → 새 거래일 시작, 매수 기록 초기화
    elif hour == 9 and minute == 0:
        bought_today.clear()
        logger.info("=== 새 거래일 시작 - 매수 기록 초기화 ===")
        send_message("새 거래일 시작! 변동성 돌파 전략 모니터링 중...")

    # 그 외 시간 → 매수 조건 체크
    # (8:50~8:59는 매도 시간이므로 매수 안 함)
    elif not (hour == 8 and minute >= 50):
        do_buy_check()


def print_status():
    """현재 상태를 출력합니다 (1시간마다)."""
    krw = get_balance_krw()
    mode = "실거래" if LIVE_TRADING else "시뮬레이션"
    logger.info(
        f"[상태] 모드: {mode} | "
        f"원화잔고: {krw:,.0f}원 | "
        f"오늘 매수: {bought_today if bought_today else '없음'}"
    )


def main():
    mode_text = "실거래" if LIVE_TRADING else "시뮬레이션"
    logger.info(f"=== 업비트 자동매매 시스템 시작 ({mode_text} 모드) ===")
    logger.info(f"대상 코인: {TARGET_COINS}")
    logger.info(f"1회 매수금액: {ORDER_AMOUNT:,}원 | K값: {os.getenv('VOLATILITY_K', '0.5')}")

    send_message(
        f"자동매매 시작!\n"
        f"모드: {mode_text}\n"
        f"코인: {', '.join(TARGET_COINS)}\n"
        f"매수금액: {ORDER_AMOUNT:,}원"
    )

    # 1분마다 매매 조건 체크
    schedule.every(1).minutes.do(trading_job)
    # 1시간마다 상태 출력
    schedule.every(1).hours.do(print_status)

    # 시작하자마자 한 번 즉시 실행
    trading_job()

    logger.info("스케줄러 시작. Ctrl+C 로 종료합니다.")
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("사용자가 프로그램을 종료했습니다.")
        send_message("자동매매 시스템이 종료되었습니다.")
