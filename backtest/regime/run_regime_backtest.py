"""
backtest/regime/run_regime_backtest.py - 국면별 백테스트 실행 스크립트

실행 방법:
  python -m backtest.regime.run_regime_backtest
  python -m backtest.regime.run_regime_backtest --method indicator
  python -m backtest.regime.run_regime_backtest --method kmeans
  python -m backtest.regime.run_regime_backtest --adaptive
"""

import os
import sys
import argparse
import pandas as pd
from loguru import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.data_collector import collect_all_data
from backtest.regime.detector import detect_regimes
from backtest.regime.regime_backtest import (
    run_regime_backtest,
    run_regime_comparison,
    AdaptiveRegimeStrategy,
)


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results", "regime")


def setup_logger():
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="INFO",
    )


def save_csv(df, filename):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, filename)
    df.to_csv(path, encoding="utf-8-sig")
    logger.info(f"저장: {path}")


def main():
    parser = argparse.ArgumentParser(description="국면별 백테스트")
    parser.add_argument("--method", default="indicator", help="국면 감지: manual, indicator, kmeans")
    parser.add_argument("--days", type=int, default=800, help="데이터 일수")
    parser.add_argument("--oos", type=int, default=30, help="OOS 기간")
    parser.add_argument("--adaptive", action="store_true", help="적응형 전략 포함")
    args = parser.parse_args()

    setup_logger()

    logger.info("=" * 70)
    logger.info("국면별 백테스트 시작")
    logger.info(f"국면 감지: {args.method} | 데이터: {args.days}일 | OOS: {args.oos}일")
    logger.info("=" * 70)

    # 데이터 수집
    prices, volumes = collect_all_data(days=args.days)
    btc_prices = prices["KRW-BTC"] if "KRW-BTC" in prices.columns else prices.iloc[:, 0]

    # 국면 감지
    regimes = detect_regimes(btc_prices, method=args.method)

    # 국면 시각화 데이터 저장
    regime_df = pd.DataFrame({"date": regimes.index, "regime": regimes.values, "btc_price": btc_prices.values})
    save_csv(regime_df, "regime_timeline.csv")

    # 전략 준비
    from backtest.strategies import get_all_strategy_configs

    configs = get_all_strategy_configs()

    # 대표 전략 선택 (각 유형별 1개)
    representative = {}
    for cfg in configs:
        strategy = cfg["strategy"]
        stype = type(strategy).__name__
        if stype not in representative:
            representative[stype] = strategy

    strategies = [(s.name, s) for s in representative.values()]
    logger.info(f"테스트 전략: {len(strategies)}개")

    # 국면별 비교 실행
    comparison_df = run_regime_comparison(
        strategies, prices, volumes, btc_prices,
        oos_window=args.oos, regime_method=args.method,
    )
    save_csv(comparison_df, "regime_comparison.csv")

    # 적응형 전략 테스트
    if args.adaptive:
        logger.info("\n" + "=" * 70)
        logger.info("적응형 전략 백테스트")
        logger.info("=" * 70)

        # 상승장: 모멘텀, 하락장: 현금(None), 횡보장: 리스크패리티
        from backtest.strategies.cross_sectional_momentum import CrossSectionalMomentum
        from backtest.strategies.risk_parity import RiskParityLite

        bull_strat = CrossSectionalMomentum(lookback=13, top_k=3)
        sideways_strat = RiskParityLite(vol_lookback=23)

        adaptive = AdaptiveRegimeStrategy(
            bull_strategy=bull_strat,
            bear_strategy=None,  # 하락장: 현금
            sideways_strategy=sideways_strat,
            btc_prices=btc_prices,
            regime_method=args.method,
            cash_ratio_bear=0.7,  # 하락장에서 70% 현금
        )

        # 적응형 vs 기존 전략 비교
        adaptive_strategies = [
            (adaptive.name, adaptive),
            (bull_strat.name, bull_strat),
            (sideways_strat.name, sideways_strat),
        ]

        adaptive_df = run_regime_comparison(
            adaptive_strategies, prices, volumes, btc_prices,
            oos_window=args.oos, regime_method=args.method,
        )
        save_csv(adaptive_df, "adaptive_comparison.csv")

    # 국면별 최적 전략 추천
    logger.info("\n" + "=" * 70)
    logger.info("국면별 최적 전략 추천")
    logger.info("=" * 70)

    for regime in ["bull", "bear", "sideways"]:
        regime_data = comparison_df[comparison_df["국면"] == regime]
        if regime_data.empty:
            continue
        best = regime_data.loc[regime_data["샤프비율"].idxmax()]
        emoji = {"bull": "상승장", "bear": "하락장", "sideways": "횡보장"}[regime]
        logger.info(
            f"  {emoji}: {best['전략']} "
            f"(샤프 {best['샤프비율']:.2f}, 수익률 {best['누적수익률']:.1%})"
        )

    logger.info("\n국면별 백테스트 완료!")


if __name__ == "__main__":
    main()
