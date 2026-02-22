"""
backtest/run_backtest.py - 백테스팅 실행 스크립트

4가지 전략을 한꺼번에 실행하고 결과를 비교합니다.

실행 방법:
    python backtest/run_backtest.py

결과:
    - 콘솔에 전략별 성능 지표 출력
    - logs/ 폴더에 그래프 PNG 저장
    - 텔레그램으로 결과 전송
    - Supabase DB에 결과 저장
"""
import sys
import os
import yaml
from dotenv import load_dotenv
from loguru import logger

# 프로젝트 루트를 Python 경로에 추가 (어디서 실행해도 import 가능하게)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from backtest.engine import BacktestEngine
from backtest.report import BacktestReporter
from backtest.strategies.volatility_breakout import VolatilityBreakoutStrategy
from backtest.strategies.dual_momentum import DualMomentumStrategy
from backtest.strategies.rsi_bollinger import RSIBollingerStrategy
from backtest.strategies.ma_cross import MACrossStrategy


def load_config():
    """config/settings.yaml에서 전체 설정을 읽어옵니다."""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "settings.yaml"
    )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_single(strategy, strategy_name: str, ticker: str,
               start_date: str, end_date: str, cfg: dict):
    """
    단일 전략-코인 조합의 백테스트를 실행하고 리포트합니다.

    매개변수:
        strategy     : 전략 객체
        strategy_name: 표시용 전략 이름
        ticker       : 코인 티커
        start_date   : 시작일
        end_date     : 종료일
        cfg          : settings.yaml 전체 설정
    """
    logger.info(f"\n{'='*50}")
    logger.info(f"실행 중: {strategy_name} | {ticker}")
    logger.info(f"{'='*50}")

    # 1. 백테스트 실행
    engine = BacktestEngine(
        strategy=strategy,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )
    result = engine.run()
    if result is None:
        logger.error(f"{strategy_name} | {ticker} 백테스트 실패")
        return

    # 2. 리포터 생성
    reporter = BacktestReporter(
        result=result,
        strategy_name=strategy_name,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )

    # 3. 그래프 저장
    chart_path = reporter.save_chart()

    # 4. 텔레그램 전송 (설정에 따라)
    if cfg["backtest"].get("notify_on_complete", True):
        reporter.send_to_telegram(chart_path=chart_path)

    # 5. DB 저장 (설정에 따라)
    if cfg["backtest"].get("save_to_db", True):
        reporter.save_to_db()


def main():
    """메인 실행 함수 — 모든 전략을 순서대로 실행합니다."""
    cfg        = load_config()
    bt_cfg     = cfg["backtest"]
    s_cfg      = cfg["strategy"]

    start_date = bt_cfg["start_date"]
    end_date   = bt_cfg["end_date"]
    tickers    = bt_cfg["target_coins"]

    # 실행할 전략 목록: (전략 객체, 표시 이름) 쌍
    strategies = [
        (
            VolatilityBreakoutStrategy(k=s_cfg["volatility_breakout"]["k"]),
            f"변동성돌파 K={s_cfg['volatility_breakout']['k']}",
        ),
        (
            DualMomentumStrategy(
                lookback_days=s_cfg["dual_momentum"]["lookback_days"],
                risk_free_rate=s_cfg["dual_momentum"]["risk_free_rate"],
            ),
            f"듀얼모멘텀 {s_cfg['dual_momentum']['lookback_days']}일",
        ),
        (
            RSIBollingerStrategy(
                rsi_period    =s_cfg["rsi_bollinger"]["rsi_period"],
                rsi_oversold  =s_cfg["rsi_bollinger"]["rsi_oversold"],
                rsi_overbought=s_cfg["rsi_bollinger"]["rsi_overbought"],
                bb_period     =s_cfg["rsi_bollinger"]["bb_period"],
                bb_std        =s_cfg["rsi_bollinger"]["bb_std"],
            ),
            f"RSI+볼린저 RSI{s_cfg['rsi_bollinger']['rsi_period']}",
        ),
        (
            MACrossStrategy(
                short_ma=s_cfg["ma_cross"]["short_ma"],
                long_ma =s_cfg["ma_cross"]["long_ma"],
            ),
            f"이동평균크로스 {s_cfg['ma_cross']['short_ma']}/{s_cfg['ma_cross']['long_ma']}",
        ),
    ]

    logger.info(f"백테스팅 시작: {start_date} ~ {end_date}")
    logger.info(f"대상 코인: {tickers}")
    logger.info(f"전략 수: {len(strategies)}개\n")

    # 모든 전략 × 모든 코인 조합 실행
    for ticker in tickers:
        for strategy, name in strategies:
            run_single(strategy, name, ticker, start_date, end_date, cfg)

    logger.info("\n모든 백테스팅 완료!")


if __name__ == "__main__":
    main()
