"""
backtest/run_router_backtest.py - 전략 라우터 통합 백테스트

전략 라우터(상승=거래량돌파, 횡보=BB+RSI, 하락=현금보유)의
전체 국면 전환 성과를 백테스트하고 개별 전략과 비교합니다.

비교 대상:
  1. 전략 라우터 (국면별 자동 스위칭)
  2. 거래량돌파 단독 (국면 무시, 상시 적용)
  3. BB+RSI 평균회귀 단독 (국면 무시, 상시 적용)
  4. 현금보유 (비교 벤치마크)
  5. BTC 바이앤홀드 (벤치마크)
  6. 동일비중 바이앤홀드 (벤치마크)

실행 방법:
  python -m backtest.run_router_backtest
  python -m backtest.run_router_backtest --days 800 --oos 30
"""

import sys
import os
import argparse
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

# 로그 설정
logger.remove()
logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO")

from backtest.data_collector import collect_all_data
from backtest.engine import run_backtest, run_benchmark_btc, run_benchmark_equal
from backtest.metrics import calc_all_metrics, classify_regime
from backtest.validators import validate_strategy
from backtest.report import (
    plot_equity_curves,
    plot_window_returns,
    plot_metrics_heatmap,
    plot_regime_comparison,
    plot_validation_chart,
)

from backtest.strategies.strategy_router import StrategyRouterBT
from backtest.strategies.volume_breakout import VolumeBreakout
from backtest.strategies.bb_rsi_mean_reversion import BBRSIMeanReversionBT
from backtest.strategies.cash_hold import CashHoldBT


# 한글 폰트 설정
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def parse_args():
    parser = argparse.ArgumentParser(description="전략 라우터 통합 백테스트")
    parser.add_argument("--days", type=int, default=800, help="데이터 수집 일수 (기본 800)")
    parser.add_argument("--oos", type=int, default=30, help="OOS 윈도우 크기 (기본 30일)")
    parser.add_argument("--force-data", action="store_true", help="데이터 강제 재수집")
    parser.add_argument("--skip-validation", action="store_true", help="통계 검증 생략")
    return parser.parse_args()


def build_strategies():
    """비교할 전략 목록을 생성합니다."""
    strategies = [
        # 1. 전략 라우터 (핵심 테스트 대상)
        StrategyRouterBT(
            sma_period=50,
            momentum_period=20,
            bull_threshold=0.10,
            bear_threshold=-0.10,
            confirmation_days=2,
            vol_price_lookback=4,
            vol_ratio=1.26,
            vol_top_k=5,
            bb_period=20,
            bb_std=2.0,
            rsi_period=14,
            rsi_oversold=30,
            rsi_overbought=70,
            bb_stop_loss=-3.0,
            bb_take_profit=5.0,
            bb_top_k=5,
        ),

        # 2. 거래량돌파 단독 (상시 적용)
        VolumeBreakout(price_lookback=4, vol_ratio=1.26, top_k=5),

        # 3. BB+RSI 단독 (상시 적용)
        BBRSIMeanReversionBT(
            bb_period=20, bb_std=2.0, rsi_period=14,
            rsi_oversold=30, rsi_overbought=70,
            stop_loss_pct=-3.0, take_profit_pct=5.0, top_k=5,
        ),

        # 4. 현금보유 (벤치마크)
        CashHoldBT(),
    ]
    return strategies


def run_regime_analysis(prices: pd.DataFrame, results: list):
    """국면별 상세 분석을 수행합니다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 전략 라우터의 국면 로그 추출
    router_result = None
    for r in results:
        if "전략라우터" in r["strategy_name"]:
            router_result = r
            break

    if router_result is None:
        return

    # 국면 분류를 위해 BTC 가격 사용
    btc = prices.get("KRW-BTC")
    if btc is None:
        return

    equity = router_result["equity_curve"]
    if equity.empty:
        return

    # 매일의 국면을 분류
    regime_data = []
    for date in equity.index:
        regime = classify_regime(btc, date)
        regime_data.append({"date": date, "regime": regime, "equity": equity[date]})

    regime_df = pd.DataFrame(regime_data)

    # 국면별 일별 수익률 분석
    regime_df["daily_return"] = regime_df["equity"].pct_change()

    logger.info("\n" + "=" * 60)
    logger.info("  국면별 상세 분석 (전략 라우터)")
    logger.info("=" * 60)

    for regime in ["불장", "횡보", "하락장"]:
        subset = regime_df[regime_df["regime"] == regime]
        if len(subset) < 2:
            continue

        returns = subset["daily_return"].dropna()
        total_days = len(subset)
        pct_of_total = total_days / len(regime_df) * 100
        mean_daily = returns.mean()
        ann_return = (1 + mean_daily) ** 365 - 1
        volatility = returns.std() * np.sqrt(365)
        sharpe = ann_return / volatility if volatility > 0 else 0
        win_rate = (returns > 0).mean()

        logger.info(
            f"\n  [{regime}] ({total_days}일, 전체의 {pct_of_total:.1f}%)\n"
            f"    연환산 수익률: {ann_return:+.2%}\n"
            f"    연환산 변동성: {volatility:.2%}\n"
            f"    샤프 비율: {sharpe:.2f}\n"
            f"    일별 승률: {win_rate:.1%}\n"
            f"    일평균 수익률: {mean_daily:+.4%}"
        )

    # 국면 전환 타임라인 차트 생성
    _plot_regime_timeline(regime_df, equity, btc)


def _plot_regime_timeline(regime_df: pd.DataFrame, equity: pd.Series, btc: pd.Series):
    """국면 전환 타임라인 + 에쿼티 커브 차트"""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(16, 12), gridspec_kw={"height_ratios": [3, 2, 1]})

    # 1. 에쿼티 커브
    ax1 = axes[0]
    ax1.plot(equity.index, (equity - 1) * 100, linewidth=1.5, color="#2980B9", label="전략 라우터")
    ax1.set_title("전략 라우터 누적 수익률 + 국면 표시", fontsize=14, fontweight="bold")
    ax1.set_ylabel("수익률 (%)")
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="black", linewidth=0.5)

    # 국면별 배경색
    regime_colors = {"불장": "#2ECC7140", "횡보": "#95A5A640", "하락장": "#E74C3C40"}
    prev_regime = None
    start_date = None
    for _, row in regime_df.iterrows():
        if row["regime"] != prev_regime:
            if prev_regime is not None and start_date is not None:
                ax1.axvspan(start_date, row["date"], alpha=0.15,
                           color=regime_colors.get(prev_regime, "#95A5A640"))
            start_date = row["date"]
            prev_regime = row["regime"]
    # 마지막 구간
    if prev_regime is not None and start_date is not None:
        ax1.axvspan(start_date, regime_df.iloc[-1]["date"], alpha=0.15,
                   color=regime_colors.get(prev_regime, "#95A5A640"))

    from matplotlib.patches import Patch
    ax1.legend(handles=[
        Patch(facecolor="#2ECC71", alpha=0.3, label="상승장"),
        Patch(facecolor="#95A5A6", alpha=0.3, label="횡보장"),
        Patch(facecolor="#E74C3C", alpha=0.3, label="하락장"),
        plt.Line2D([0], [0], color="#2980B9", linewidth=1.5, label="전략 라우터"),
    ], loc="upper left", fontsize=9)

    # 2. BTC 가격
    ax2 = axes[1]
    btc_aligned = btc.reindex(equity.index).dropna()
    if len(btc_aligned) > 0:
        ax2.plot(btc_aligned.index, btc_aligned / 1_000_000, linewidth=1, color="#F39C12")
        ax2.set_ylabel("BTC 가격 (백만원)")
        ax2.set_title("BTC 가격 추이", fontsize=12)
        ax2.grid(True, alpha=0.3)

    # 3. 국면 바
    ax3 = axes[2]
    regime_map = {"불장": 1, "횡보": 0, "하락장": -1}
    regime_values = regime_df.set_index("date")["regime"].map(regime_map)
    bar_colors = regime_df["regime"].map(
        {"불장": "#2ECC71", "횡보": "#95A5A6", "하락장": "#E74C3C"}
    ).values
    ax3.bar(regime_df["date"], regime_values.values, color=bar_colors, width=1.5)
    ax3.set_yticks([-1, 0, 1])
    ax3.set_yticklabels(["하락장", "횡보", "상승장"])
    ax3.set_title("시장 국면 변화", fontsize=12)

    plt.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "router_regime_timeline.png"), dpi=150)
    logger.info("  -> 국면 타임라인 차트 저장 완료")
    plt.close(fig)


def _plot_strategy_comparison(results: list, benchmarks: dict):
    """전략별 비교 요약 차트"""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # 데이터 준비
    names = []
    metrics_data = []
    for r in results:
        if "metrics" in r:
            names.append(r["strategy_name"][:20])
            metrics_data.append(r["metrics"])

    if not metrics_data:
        plt.close(fig)
        return

    df = pd.DataFrame(metrics_data, index=names)

    # 1. 누적수익률 비교
    ax = axes[0, 0]
    colors = ["#2980B9" if "라우터" in n else "#95A5A6" for n in names]
    bars = ax.barh(range(len(names)), df["누적수익률"] * 100, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("누적 수익률 (%)")
    ax.set_title("누적 수익률 비교", fontweight="bold")
    ax.axvline(x=0, color="black", linewidth=0.5)
    ax.grid(True, axis="x", alpha=0.3)
    for bar, val in zip(bars, df["누적수익률"]):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val:.1%}", va="center", fontsize=8)

    # 2. 샤프비율 비교
    ax = axes[0, 1]
    colors = ["#2980B9" if "라우터" in n else "#95A5A6" for n in names]
    bars = ax.barh(range(len(names)), df["샤프비율"], color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("샤프 비율")
    ax.set_title("샤프 비율 비교", fontweight="bold")
    ax.axvline(x=0, color="black", linewidth=0.5)
    ax.grid(True, axis="x", alpha=0.3)
    for bar, val in zip(bars, df["샤프비율"]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", fontsize=8)

    # 3. MDD 비교
    ax = axes[1, 0]
    colors = ["#2980B9" if "라우터" in n else "#95A5A6" for n in names]
    bars = ax.barh(range(len(names)), df["MDD"] * 100, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("MDD (%)")
    ax.set_title("최대 낙폭 (MDD) 비교", fontweight="bold")
    ax.axvline(x=0, color="black", linewidth=0.5)
    ax.grid(True, axis="x", alpha=0.3)
    for bar, val in zip(bars, df["MDD"]):
        ax.text(bar.get_width() - 2, bar.get_y() + bar.get_height() / 2,
                f"{val:.1%}", va="center", fontsize=8)

    # 4. 칼마비율 비교
    ax = axes[1, 1]
    colors = ["#2980B9" if "라우터" in n else "#95A5A6" for n in names]
    bars = ax.barh(range(len(names)), df["칼마비율"], color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("칼마 비율")
    ax.set_title("칼마 비율 (수익/리스크)", fontweight="bold")
    ax.axvline(x=0, color="black", linewidth=0.5)
    ax.grid(True, axis="x", alpha=0.3)
    for bar, val in zip(bars, df["칼마비율"]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", fontsize=8)

    plt.suptitle("전략 라우터 vs 개별 전략 비교", fontsize=16, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "router_strategy_comparison.png"), dpi=150)
    logger.info("  -> 전략 비교 차트 저장 완료")
    plt.close(fig)


def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("  전략 라우터 통합 백테스트 시작")
    logger.info("=" * 60)
    logger.info(f"  데이터: {args.days}일 | OOS 윈도우: {args.oos}일")
    logger.info(f"  시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ─── 1. 데이터 수집 ───
    logger.info("\n[1/5] 데이터 수집 중...")
    prices, volumes = collect_all_data(days=args.days, force=args.force_data)
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    logger.info(f"  코인: {len(prices.columns)}개 | 데이터 포인트: {len(prices)}일")

    # ─── 2. 전략 생성 및 백테스트 ───
    logger.info("\n[2/5] 백테스트 실행 중...")
    strategies = build_strategies()
    results = []

    for strategy in strategies:
        logger.info(f"\n  전략: {strategy.name}")

        # 상태 초기화 (이전 실행 잔여 상태 제거)
        if hasattr(strategy, "reset"):
            strategy.reset()

        result = run_backtest(strategy, prices, volumes, oos_window=args.oos)

        if result["equity_curve"].empty:
            logger.warning(f"    → 에쿼티 커브 비어있음, 건너뜀")
            continue

        metrics = calc_all_metrics(result["equity_curve"])
        result["metrics"] = metrics

        logger.info(
            f"    누적수익률: {metrics['누적수익률']:+.2%} | "
            f"샤프: {metrics['샤프비율']:.2f} | "
            f"MDD: {metrics['MDD']:.2%} | "
            f"칼마: {metrics['칼마비율']:.2f} | "
            f"승률: {metrics['일별승률']:.1%}"
        )

        results.append(result)

    if not results:
        logger.error("백테스트 결과가 없습니다!")
        return

    # ─── 3. 벤치마크 ───
    logger.info("\n[3/5] 벤치마크 계산 중...")
    start_date = results[0]["equity_curve"].index[0]
    benchmarks = {
        "BTC B&H": run_benchmark_btc(prices, start_date),
        "동일비중 B&H": run_benchmark_equal(prices, start_date),
    }

    for name, eq in benchmarks.items():
        if len(eq) > 1:
            ret = eq.iloc[-1] / eq.iloc[0] - 1
            logger.info(f"  {name}: {ret:+.2%}")

    # ─── 4. 성과 요약 ───
    logger.info("\n[4/5] 성과 요약 및 차트 생성 중...")

    # 요약 테이블
    summary_rows = []
    for r in results:
        m = r["metrics"]
        summary_rows.append({
            "전략": r["strategy_name"][:30],
            "누적수익률": m["누적수익률"],
            "연환산수익률": m["연환산수익률"],
            "연환산변동성": m["연환산변동성"],
            "샤프비율": m["샤프비율"],
            "소르티노비율": m["소르티노비율"],
            "MDD": m["MDD"],
            "칼마비율": m["칼마비율"],
            "일별승률": m["일별승률"],
        })

    summary_df = pd.DataFrame(summary_rows)

    # 콘솔 출력
    logger.info("\n" + "=" * 80)
    logger.info("  전략 성과 요약")
    logger.info("=" * 80)
    for _, row in summary_df.iterrows():
        logger.info(
            f"  {row['전략']:<30} | "
            f"수익: {row['누적수익률']:>+8.2%} | "
            f"샤프: {row['샤프비율']:>6.2f} | "
            f"MDD: {row['MDD']:>8.2%} | "
            f"칼마: {row['칼마비율']:>6.2f} | "
            f"승률: {row['일별승률']:>5.1%}"
        )

    # 차트 생성
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 에쿼티 커브
    plot_equity_curves(results, benchmarks, suffix=f"router_{args.oos}")

    # 윈도우별 수익률
    for r in results:
        if not r["window_details"].empty:
            plot_window_returns(r["window_details"], r["strategy_name"])

    # 성과 히트맵
    plot_metrics_heatmap(summary_df, suffix=f"router_{args.oos}")

    # 레짐별 비교
    all_window_details = [(r["strategy_name"], r["window_details"]) for r in results]
    plot_regime_comparison(all_window_details)

    # 전략 비교 차트
    _plot_strategy_comparison(results, benchmarks)

    # 국면 상세 분석
    run_regime_analysis(prices, results)

    # 전략 라우터 국면 통계
    for strategy in strategies:
        if isinstance(strategy, StrategyRouterBT) and hasattr(strategy, "get_regime_stats"):
            stats = strategy.get_regime_stats()
            if stats:
                logger.info("\n  [전략 라우터 국면 분포]")
                for regime, s in stats.items():
                    regime_kr = {"bull": "상승장", "sideways": "횡보장", "bear": "하락장"}.get(regime, regime)
                    logger.info(f"    {regime_kr}: {s['일수']}일 ({s['비율']:.1%})")

    # ─── 5. 통계적 검증 ───
    if not args.skip_validation:
        logger.info("\n[5/5] 통계적 검증 중...")
        for r in results:
            if len(r["equity_curve"]) < 30:
                continue
            validation = validate_strategy(
                r["equity_curve"],
                r["window_details"],
                r["strategy_name"],
            )
            r["validation"] = validation

            # 검증 차트
            plot_validation_chart(validation, r["strategy_name"])
    else:
        logger.info("\n[5/5] 통계적 검증 생략 (--skip-validation)")

    # ─── 최종 결론 ───
    logger.info("\n" + "=" * 60)
    logger.info("  최종 결론")
    logger.info("=" * 60)

    # 전략 라우터 vs 거래량돌파 단독 비교
    router_metrics = None
    volume_metrics = None
    bb_rsi_metrics = None

    for r in results:
        if "전략라우터" in r["strategy_name"]:
            router_metrics = r["metrics"]
        elif "거래량돌파" in r["strategy_name"]:
            volume_metrics = r["metrics"]
        elif "BB+RSI" in r["strategy_name"]:
            bb_rsi_metrics = r["metrics"]

    if router_metrics and volume_metrics:
        ret_diff = router_metrics["누적수익률"] - volume_metrics["누적수익률"]
        mdd_diff = router_metrics["MDD"] - volume_metrics["MDD"]
        sharpe_diff = router_metrics["샤프비율"] - volume_metrics["샤프비율"]

        logger.info(f"\n  전략 라우터 vs 거래량돌파 단독:")
        logger.info(f"    수익률 차이: {ret_diff:+.2%}{'p (라우터 우위)' if ret_diff > 0 else 'p (거래량돌파 우위)'}")
        logger.info(f"    MDD 차이: {mdd_diff:+.2%}{'(라우터 우위)' if mdd_diff > 0 else '(거래량돌파 우위)'}")
        logger.info(f"    샤프 차이: {sharpe_diff:+.2f}")

    if router_metrics and bb_rsi_metrics:
        ret_diff = router_metrics["누적수익률"] - bb_rsi_metrics["누적수익률"]
        logger.info(f"\n  전략 라우터 vs BB+RSI 단독:")
        logger.info(f"    수익률 차이: {ret_diff:+.2%}")

    # 검증 결과 요약
    for r in results:
        if "validation" in r:
            v = r["validation"]
            logger.info(
                f"\n  [{r['strategy_name'][:25]}] "
                f"등급: {v['overall_grade']} | {v['verdict']}"
            )

    logger.info(f"\n  차트 저장 위치: {os.path.abspath(RESULTS_DIR)}")
    logger.info(f"  완료 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
