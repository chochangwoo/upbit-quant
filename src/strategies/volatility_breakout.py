"""
변동성 돌파 전략 모듈
래리 윌리엄스가 고안한 단기 매매 전략입니다.

전략 원리:
- 매수 조건: 현재가 >= 당일 시가 + (전일 고가 - 전일 저가) × K
- 매도: 매일 오전 8시 50분에 보유 코인 전량 매도
- K값: 보통 0.5 사용 (낮을수록 매매 빈도 높음, 위험 높음)
- 사이클: 매일 오전 9시 초기화 → 당일 매수 → 다음날 8시 50분 매도
"""
import os
from loguru import logger
from src.api.upbit_client import get_ohlcv, get_current_price


def calculate_target_price(ticker: str) -> float:
    """
    매수 목표가를 계산합니다.
    목표가 = 당일 시가 + (전일 고가 - 전일 저가) × K
    """
    k = float(os.getenv("VOLATILITY_K", "0.5"))

    # 최근 2일치 일봉 데이터 가져오기
    df = get_ohlcv(ticker, interval="day", count=2)
    if df is None or len(df) < 2:
        logger.error(f"{ticker} 캔들 데이터를 가져올 수 없습니다.")
        return None

    yesterday_high = df.iloc[-2]["high"]  # 전일 고가
    yesterday_low  = df.iloc[-2]["low"]   # 전일 저가
    today_open     = df.iloc[-1]["open"]  # 당일 시가

    target = today_open + (yesterday_high - yesterday_low) * k

    logger.info(
        f"[{ticker}] 목표가: {target:,.0f}원 "
        f"(시가: {today_open:,.0f} + 전일변동폭: {yesterday_high - yesterday_low:,.0f} × K{k})"
    )
    return target


def should_buy(ticker: str) -> bool:
    """
    매수 조건을 확인합니다.
    현재가가 목표가 이상이면 True 반환
    """
    target_price = calculate_target_price(ticker)
    if target_price is None:
        return False

    current_price = get_current_price(ticker)
    if current_price is None:
        return False

    if current_price >= target_price:
        logger.info(
            f"[{ticker}] 매수 신호! "
            f"현재가 {current_price:,.0f} >= 목표가 {target_price:,.0f}"
        )
        return True
    else:
        logger.debug(
            f"[{ticker}] 매수 조건 미충족. "
            f"현재가 {current_price:,.0f} / 목표가 {target_price:,.0f}"
        )
        return False
