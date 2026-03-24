"""
업비트 자동매매 시스템 - 메인 실행 파일
실행 방법: python main.py

[전략 모드]
  1. ma_cross    : 이동평균 크로스 5/20 (단일 코인)
  2. portfolio   : 멀티코인 포트폴리오 (백테스트 기반)
     - momentum  : 모멘텀 전략
     - rsi       : RSI 역추세 전략
     - combined  : 복합 전략 (모멘텀 + 저변동성)
     - ml        : ML(LightGBM) 전략

  전략 선택: config/settings.yaml → strategy.name
"""
import signal
import sys
import time
import schedule
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
from src.notifications.telegram_bot import (
    send_message,
    send_golden_cross_alert,
    send_dead_cross_alert,
    send_error_alert,
)
from src.database.supabase_client import save_trade
from config.settings import (
    STRATEGY_NAME,
    SHORT_WINDOW,
    LONG_WINDOW,
    TICKER,
    INVEST_RATIO,
    LIVE_TRADING,
)

# ─────────────────────────────────────────
# 로그 설정: 콘솔 출력 (Railway는 stdout 캡처)
# ─────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=True,
)


# ─────────────────────────────────────────
# 전략 초기화
# ─────────────────────────────────────────

# 포트폴리오 전략 관련 변수
portfolio_executor = None

if STRATEGY_NAME == "adaptive_volume":
    # 적응형 거래량돌파 전략 (국면별 자동 전환)
    from src.strategies.adaptive_volume_strategy import AdaptiveVolumeStrategy
    from src.strategies.risk_manager import RiskManager
    from src.trading.portfolio_executor import PortfolioExecutor

    import yaml
    _yaml_path = "config/settings.yaml"
    with open(_yaml_path, "r", encoding="utf-8") as f:
        _yaml_cfg = yaml.safe_load(f)

    portfolio_cfg = _yaml_cfg.get("portfolio", {})
    risk_cfg = portfolio_cfg.get("risk", {})

    strategy = AdaptiveVolumeStrategy(
        price_lookback=4,
        vol_ratio=1.26,
        top_k=portfolio_cfg.get("top_k", 5),
        rebalance_days=portfolio_cfg.get("rebalance_days", 3),
    )

    risk_manager = RiskManager(config=risk_cfg)
    portfolio_executor = PortfolioExecutor(strategy, risk_manager, LIVE_TRADING)

elif STRATEGY_NAME == "ma_cross":
    from src.strategies.ma_cross import MACrossStrategy
    strategy = MACrossStrategy(short_window=SHORT_WINDOW, long_window=LONG_WINDOW)

elif STRATEGY_NAME.startswith("portfolio_"):
    from src.strategies.portfolio_strategy import PortfolioStrategy
    from src.strategies.risk_manager import RiskManager
    from src.trading.portfolio_executor import PortfolioExecutor

    strategy_type = STRATEGY_NAME.replace("portfolio_", "")

    import yaml
    _yaml_path = "config/settings.yaml"
    with open(_yaml_path, "r", encoding="utf-8") as f:
        _yaml_cfg = yaml.safe_load(f)

    portfolio_cfg = _yaml_cfg.get("portfolio", {})
    risk_cfg = portfolio_cfg.get("risk", {})

    strategy = PortfolioStrategy(
        strategy_type=strategy_type,
        top_k=portfolio_cfg.get("top_k", 5),
        rebalance_days=portfolio_cfg.get("rebalance_days", 3),
        lookback=portfolio_cfg.get("lookback", 14),
        risk_config=risk_cfg,
    )

    risk_manager = RiskManager(config=risk_cfg)
    portfolio_executor = PortfolioExecutor(strategy, risk_manager, LIVE_TRADING)

else:
    from src.strategies.ma_cross import MACrossStrategy
    strategy = MACrossStrategy(short_window=SHORT_WINDOW, long_window=LONG_WINDOW)
    STRATEGY_NAME = "ma_cross"


# ─────────────────────────────────────────
# MA Cross 매매 함수 (기존)
# ─────────────────────────────────────────

def do_buy(info: dict):
    """골든크로스 신호 시 매수를 실행합니다."""
    krw_balance = get_balance_krw()
    invest_amount = krw_balance * INVEST_RATIO

    if invest_amount < 5000:
        logger.warning(f"[{TICKER}] 원화 잔고 부족: {krw_balance:,.0f}원 (최소 5,000원 필요)")
        return

    current_price = get_current_price(TICKER)
    if current_price is None:
        logger.error(f"[{TICKER}] 현재가 조회 실패, 매수 생략")
        return
    ma5  = info.get("ma5", 0)
    ma20 = info.get("ma20", 0)

    if LIVE_TRADING:
        result = buy_market_order(TICKER, invest_amount)
        if result:
            save_trade(
                strategy_name=STRATEGY_NAME,
                ticker=TICKER,
                side="buy",
                price=current_price,
                amount=invest_amount,
                signal="golden_cross",
                ma5=ma5,
                ma20=ma20,
            )
            send_golden_cross_alert(TICKER, current_price, invest_amount, ma5, ma20)
            logger.info(f"[{TICKER}] 매수 완료: {invest_amount:,.0f}원 @ {current_price:,.0f}원")
        else:
            send_error_alert(f"{TICKER} 매수 실패! 수동으로 확인하세요.")
    else:
        quantity = invest_amount / current_price
        logger.info(
            f"[시뮬] [{TICKER}] 골든크로스 매수\n"
            f"  금액: {invest_amount:,.0f}원 | 수량: {quantity:.6f} | 가격: {current_price:,.0f}원\n"
            f"  MA{SHORT_WINDOW}: {ma5:,.0f} | MA{LONG_WINDOW}: {ma20:,.0f}"
        )
        send_message(
            f"[시뮬] {TICKER} 골든크로스 매수\n"
            f"금액: {invest_amount:,.0f}원\n"
            f"가격: {current_price:,.0f}원\n"
            f"MA{SHORT_WINDOW}: {ma5:,.0f}원\n"
            f"MA{LONG_WINDOW}: {ma20:,.0f}원"
        )


def do_sell(info: dict):
    """데드크로스 신호 시 보유 코인 전량 매도합니다."""
    volume = get_balance_coin(TICKER)

    if volume is None or volume < 0.00001:
        logger.info(f"[{TICKER}] 보유 수량 없음, 매도 생략")
        return

    current_price = get_current_price(TICKER)
    if current_price is None:
        logger.error(f"[{TICKER}] 현재가 조회 실패, 매도 생략")
        return
    sell_amount   = volume * current_price
    ma5  = info.get("ma5", 0)
    ma20 = info.get("ma20", 0)

    if LIVE_TRADING:
        result = sell_market_order(TICKER, volume)
        if result:
            save_trade(
                strategy_name=STRATEGY_NAME,
                ticker=TICKER,
                side="sell",
                price=current_price,
                amount=sell_amount,
                signal="dead_cross",
                ma5=ma5,
                ma20=ma20,
            )
            send_dead_cross_alert(TICKER, current_price, sell_amount, ma5, ma20)
            logger.info(f"[{TICKER}] 매도 완료: {volume:.6f} @ {current_price:,.0f}원")
        else:
            send_error_alert(f"{TICKER} 매도 실패! 수동으로 확인하세요.")
    else:
        logger.info(
            f"[시뮬] [{TICKER}] 데드크로스 매도\n"
            f"  수량: {volume:.6f} | 금액: {sell_amount:,.0f}원 | 가격: {current_price:,.0f}원\n"
            f"  MA{SHORT_WINDOW}: {ma5:,.0f} | MA{LONG_WINDOW}: {ma20:,.0f}"
        )
        send_message(
            f"[시뮬] {TICKER} 데드크로스 매도\n"
            f"수량: {volume:.6f}\n"
            f"금액: {sell_amount:,.0f}원\n"
            f"가격: {current_price:,.0f}원\n"
            f"MA{SHORT_WINDOW}: {ma5:,.0f}원\n"
            f"MA{LONG_WINDOW}: {ma20:,.0f}원"
        )


# ─────────────────────────────────────────
# 트레이딩 루프
# ─────────────────────────────────────────

def trading_job():
    """5분마다 실행되는 메인 트레이딩 로직입니다."""
    try:
        if portfolio_executor:
            # 포트폴리오 모드: 리밸런싱 실행
            result = portfolio_executor.run_rebalance()
            if result["action"] != "skip":
                logger.info(f"[포트폴리오] 실행: {result['action']}")
        else:
            # MA Cross 모드: 기존 로직
            sig, info = strategy.check_signal(TICKER)
            if sig == "buy":
                do_buy(info)
            elif sig == "sell":
                do_sell(info)

    except Exception as e:
        logger.exception(f"트레이딩 루프 오류: {e}")
        send_error_alert(f"트레이딩 루프 오류:\n{type(e).__name__}: {e}")


def print_status():
    """현재 상태를 출력합니다 (1시간마다)."""
    if portfolio_executor:
        portfolio_executor.print_status()
    else:
        krw    = get_balance_krw()
        coin   = get_balance_coin(TICKER)
        mode   = "실거래" if LIVE_TRADING else "시뮬레이션"
        values = strategy.get_ma_values(TICKER)

        if values:
            ma5  = values["ma_short"]
            ma20 = values["ma_long"]
            trend = "매수 포지션" if ma5 > ma20 else "현금 대기"
            logger.info(
                f"[상태] 모드: {mode} | "
                f"원화: {krw:,.0f}원 | "
                f"코인: {(coin if coin else 0):.6f} | "
                f"MA{SHORT_WINDOW}: {ma5:,.0f} | "
                f"MA{LONG_WINDOW}: {ma20:,.0f} | "
                f"{trend}"
            )
        else:
            logger.info(f"[상태] 모드: {mode} | 원화: {krw:,.0f}원")


def main():
    mode_text = "실거래" if LIVE_TRADING else "시뮬레이션"

    if portfolio_executor:
        strategy_desc = f"포트폴리오 ({strategy.strategy_type})"
        coins_desc = f"{len(strategy.coins)}개 코인"
    else:
        strategy_desc = f"MA 크로스 {SHORT_WINDOW}/{LONG_WINDOW}"
        coins_desc = TICKER

    logger.info(f"=== 업비트 자동매매 시스템 시작 ({mode_text} 모드) ===")
    logger.info(f"전략: {strategy_desc}")
    logger.info(f"대상: {coins_desc}")

    send_message(
        f"자동매매 시작!\n"
        f"모드: {mode_text}\n"
        f"전략: {strategy_desc}\n"
        f"대상: {coins_desc}\n"
        f"텔레그램 명령어: /help"
    )

    # 텔레그램 명령어 핸들러 시작 (별도 스레드)
    try:
        from notify.command_handler import start_command_handler
        start_command_handler()
        time.sleep(2)  # 폴링 초기화 대기
        logger.info("텔레그램 명령어 핸들러 활성화 완료")
    except Exception as e:
        logger.error(f"텔레그램 명령어 핸들러 시작 실패 (트레이딩은 계속): {e}")

    # 5분마다 신호 체크
    schedule.every(5).minutes.do(trading_job)
    # 1시간마다 상태 출력
    schedule.every(1).hours.do(print_status)

    # 시작 즉시 한 번 실행
    trading_job()
    print_status()

    logger.info("스케줄러 시작. Ctrl+C 로 종료합니다.")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.exception(f"스케줄러 오류: {e}")
        time.sleep(1)


def _shutdown(signum, frame):
    """SIGTERM / SIGINT 수신 시 정상 종료합니다 (Railway 컨테이너 종료 대응)."""
    logger.info("종료 신호 수신. 자동매매 시스템을 종료합니다.")
    send_message("자동매매 시스템이 종료되었습니다.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    main()
