"""
backtest/run_dynamic_topk.py - 동적 top_k 전략 백테스트

이전 비교 백테스트(run_sideways_comparison.py) 인사이트 검증:
  - 상승장: top_k=5, vol=1.26, 4일고가 (Baseline 파라미터)
  - 횡보장: top_k=3, vol=1.1, 2일고가 (선택 1 파라미터)
  - 하락장: 현금보유

비교 대상 (3-way):
  - Baseline   : 전 국면 동일 (vol=1.26, 4일, top_k=5)
  - 선택 1      : 전 국면 동일 (vol=1.1, 2일, top_k=3)
  - 동적 top_k  : 국면별 파라미터 분리 적용 (신규)

실행:
  python -m backtest.run_dynamic_topk
"""

import argparse
import io
import os
import sys
from datetime import datetime

# Windows cp949 인코딩 문제 해결
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

# Windows 한글 폰트 설정
for font_name in ["Malgun Gothic", "NanumGothic", "AppleGothic"]:
    if any(font_name in f.name for f in fm.fontManager.ttflist):
        plt.rcParams["font.family"] = font_name
        plt.rcParams["axes.unicode_minus"] = False
        break

import numpy as np
import pandas as pd
from loguru import logger

# 기존 인프라 재사용
from backtest.data_collector import DATA_DIR, COINS
from backtest.metrics import calc_all_metrics, calc_sharpe_ratio
from backtest.run_sideways_comparison import (
    load_data,
    calc_daily_regimes,
    calc_volume_breakout_weights,
    _execute_rebalance,
    INITIAL_CAPITAL,
    COMMISSION,
    CONFIRMATION_DAYS,
    ADX_PERIOD,
    REBALANCE_DAYS,
    RESULTS_DIR,
)

# ──────────────────────────────────��──────────
# 전략 정의 (국면별 파라미터)
# ─────────────────────────────────────────────

STRATEGIES = {
    "baseline": {
        "설명": "현재 운영 전략 (전 국면 동일)",
        "bull":     {"vol_ratio": 1.26, "price_lookback": 4, "top_k": 5},
        "sideways": {"vol_ratio": 1.26, "price_lookback": 4, "top_k": 5},
        "bear": "cash",
    },
    "selection_1": {
        "설명": "파라미터 완화 (전 국면 동일)",
        "bull":     {"vol_ratio": 1.1, "price_lookback": 2, "top_k": 3},
        "sideways": {"vol_ratio": 1.1, "price_lookback": 2, "top_k": 3},
        "bear": "cash",
    },
    "dynamic_topk": {
        "설명": "국면별 파라미터 분리 (신규)",
        "bull":     {"vol_ratio": 1.26, "price_lookback": 4, "top_k": 5},
        "sideways": {"vol_ratio": 1.1,  "price_lookback": 2, "top_k": 3},
        "bear": "cash",
    },
}

# 백테스트 기간 (이전 백테스트와 동일)
BACKTEST_START = "2022-05-19"
BACKTEST_END = "2024-12-31"
RECENT_START = "2024-01-01"
RECENT_END = "2024-12-31"


# ─────────────────────────────────────────────
# 국면별 파라미터 시뮬레이션 엔진
# ─────────────────────────────────────────────

def run_simulation_dynamic(
    strategy_name: str,
    config: dict,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    regime_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> dict:
    """
    국면별로 다른 파라미터를 적용하는 일별 포트폴리오 시뮬레이션.

    config 형식:
        {"bull": {"vol_ratio": ..., "price_lookback": ..., "top_k": ...},
         "sideways": {"vol_ratio": ..., ...},
         "bear": "cash"}
    """
    bull_params = config["bull"]
    sideways_params = config["sideways"]

    # 날짜 범위 필터
    dates = prices.index[
        (prices.index >= pd.Timestamp(start_date)) &
        (prices.index <= pd.Timestamp(end_date))
    ]
    dates = dates.intersection(regime_df.index)
    if len(dates) == 0:
        logger.error(f"[{strategy_name}] 유효한 거래일이 없습니다")
        return {}

    logger.info(f"[{strategy_name}] 시뮬레이션: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)}일)")

    # 상태 변수
    capital = float(INITIAL_CAPITAL)
    holdings = {}
    equity_curve = []
    days_since_rebal = REBALANCE_DAYS  # 첫날 바로 리밸런싱

    # 추적 변수
    total_trades = 0
    regime_trades = {"bull": 0, "sideways": 0, "bear": 0}
    regime_pnl = {"bull": 0.0, "sideways": 0.0, "bear": 0.0}
    prev_portfolio_value = float(INITIAL_CAPITAL)

    for date in dates:
        regime = regime_df.loc[date, "regime"]

        # 현재 포트폴리오 평가
        portfolio_value = capital
        for coin, qty in holdings.items():
            if coin in prices.columns and date in prices.index:
                p = prices.loc[date, coin]
                if pd.notna(p):
                    portfolio_value += qty * p

        # 일별 손익 추적 (국면별)
        daily_pnl = portfolio_value - prev_portfolio_value
        regime_pnl[regime] += daily_pnl
        prev_portfolio_value = portfolio_value

        # 리밸런싱 판단
        if days_since_rebal >= REBALANCE_DAYS:
            target_weights = pd.Series(dtype=float)

            if regime == "bear":
                # 하락장: 현금보유
                target_weights = pd.Series(dtype=float)
            elif regime == "bull":
                # 상승장: bull 파라미터 적용
                target_weights = calc_volume_breakout_weights(
                    prices, volumes, date,
                    vol_ratio=bull_params["vol_ratio"],
                    price_lookback=bull_params["price_lookback"],
                    top_k=bull_params["top_k"],
                )
            else:
                # 횡보장: sideways 파라미터 적용
                target_weights = calc_volume_breakout_weights(
                    prices, volumes, date,
                    vol_ratio=sideways_params["vol_ratio"],
                    price_lookback=sideways_params["price_lookback"],
                    top_k=sideways_params["top_k"],
                )

            # 리밸런싱 실행
            new_holdings, new_capital, n_trades = _execute_rebalance(
                target_weights, holdings, capital, prices, date
            )

            if n_trades > 0:
                total_trades += n_trades
                regime_trades[regime] += n_trades

            holdings = new_holdings
            capital = new_capital
            days_since_rebal = 0
        else:
            days_since_rebal += 1

        # 포트폴리오 가치 재계산 (리밸런싱 후)
        portfolio_value = capital
        for coin, qty in holdings.items():
            if coin in prices.columns and date in prices.index:
                p = prices.loc[date, coin]
                if pd.notna(p):
                    portfolio_value += qty * p

        equity_curve.append({"date": date, "value": portfolio_value})

    # 결과 정리
    eq = pd.DataFrame(equity_curve).set_index("date")["value"]
    daily_returns = eq.pct_change().dropna()
    win_days = (daily_returns > 0).sum()
    total_days = len(daily_returns)

    return {
        "equity_curve": eq,
        "total_trades": total_trades,
        "regime_trades": regime_trades,
        "regime_pnl": regime_pnl,
        "win_rate": win_days / total_days if total_days > 0 else 0,
    }


# ─────────────────────────────────────────────
# 결과 출력
# ─────────────────────────────────────────────

def print_results(results: dict, regime_df: pd.DataFrame):
    """전체 비교 결과를 콘솔에 출력합니다."""

    regime_in_range = regime_df.loc[BACKTEST_START:BACKTEST_END]
    total_days = len(regime_in_range)
    names = {"baseline": "Baseline", "selection_1": "선택 1", "dynamic_topk": "동적 top_k"}
    keys = ["baseline", "selection_1", "dynamic_topk"]

    print()
    print("=" * 64)
    print("  동적 top_k 전략 백테스트")
    print(f"  기간: {BACKTEST_START} ~ {BACKTEST_END} ({total_days}일)")
    print(f"  초기 자본: {INITIAL_CAPITAL:,}원")
    print("=" * 64)

    # ── 전체 기간 성과 ──
    print("\n[전략별 성과 -- 전체 기간]")
    print("-" * 64)
    header = f"{'지표':<14}"
    for k in keys:
        header += f" | {names[k]:>12}"
    print(header)
    print("-" * 64)

    metrics_list = []
    for k in keys:
        eq = results[k]["equity_curve"]
        m = calc_all_metrics(eq)
        m["win_rate"] = results[k]["win_rate"]
        m["total_trades"] = results[k]["total_trades"]
        m["final_value"] = eq.iloc[-1]
        metrics_list.append(m)

    def fmt_pct(v):
        return f"+{v*100:.1f}%" if v >= 0 else f"{v*100:.1f}%"

    rows = [
        ("누적 수익률", [fmt_pct(m["누적수익률"]) for m in metrics_list]),
        ("CAGR", [fmt_pct(m["연환산수익률"]) for m in metrics_list]),
        ("MDD", [f"{m['MDD']*100:.1f}%" for m in metrics_list]),
        ("샤프 지수", [f"{m['샤프비율']:.2f}" for m in metrics_list]),
        ("승률", [f"{m['win_rate']*100:.1f}%" for m in metrics_list]),
        ("총 거래수", [f"{m['total_trades']}건" for m in metrics_list]),
        ("최종 자산", [f"{m['final_value']:,.0f}" for m in metrics_list]),
    ]

    for label, values in rows:
        line = f"{label:<14}"
        for v in values:
            line += f" | {v:>12}"
        print(line)
    print("-" * 64)

    # ── 동적 top_k 파라미터 현황 ──
    print("\n[국면별 파라미터 적용 현황 -- 동적 top_k]")
    print("-" * 50)
    print(f"{'국면':<10} | {'vol_ratio':>10} | {'price_look':>10} | {'top_k':>6}")
    print("-" * 50)
    dtk = STRATEGIES["dynamic_topk"]
    for regime_key, regime_label in [("bull", "상승장"), ("sideways", "횡보장"), ("bear", "하락장")]:
        params = dtk[regime_key]
        if params == "cash":
            print(f"{regime_label:<10} | {'현금보유':>10} | {'-':>10} | {'-':>6}")
        else:
            print(f"{regime_label:<10} | {params['vol_ratio']:>10} | {str(params['price_lookback'])+'일':>10} | {str(params['top_k'])+'개':>6}")
    print("-" * 50)

    # ── 국면 분포 ──
    print("\n[국면별 기간 비율]")
    for r, label in [("bull", "상승장"), ("sideways", "횡보장"), ("bear", "하락장")]:
        cnt = (regime_in_range["regime"] == r).sum()
        print(f"  {label}: {cnt}일 ({cnt/total_days*100:.1f}%)")

    # ── 국면별 거래 빈도 ──
    print("\n[국면별 거래 빈도]")
    print("-" * 64)
    header = f"{'국면':<14}"
    for k in keys:
        header += f" | {names[k]:>12}"
    print(header)
    print("-" * 64)
    for regime_key, regime_label in [("bull", "상승장"), ("sideways", "횡보장"), ("bear", "하락장")]:
        line = f"{regime_label:<14}"
        for k in keys:
            rt = results[k]["regime_trades"]
            val = rt.get(regime_key, 0)
            line += f" | {f'{val}건':>12}"
        print(line)
    print("-" * 64)

    # ── 국면별 수익 기여도 ──
    print("\n[국면별 수익 기여도]")
    print("-" * 64)
    header = f"{'국면':<14}"
    for k in keys:
        header += f" | {names[k]:>12}"
    print(header)
    print("-" * 64)
    for regime_key, regime_label in [("bull", "상승장"), ("sideways", "횡보장"), ("bear", "하락장")]:
        line = f"{regime_label:<14}"
        for k in keys:
            pnl = results[k]["regime_pnl"].get(regime_key, 0)
            pnl_pct = pnl / INITIAL_CAPITAL * 100
            if regime_key == "bear":
                line += f" | {'0%(현금)':>12}"
            elif pnl_pct >= 0:
                line += f" | {f'+{pnl_pct:.1f}%':>12}"
            else:
                line += f" | {f'{pnl_pct:.1f}%':>12}"
        print(line)
    print("-" * 64)

    # ── 가설 검증 ──
    print("\n[가설 검증]")
    # 1. 상승장 top_k=5 vs top_k=3
    bull_baseline = results["baseline"]["regime_pnl"]["bull"] / INITIAL_CAPITAL * 100
    bull_sel1 = results["selection_1"]["regime_pnl"]["bull"] / INITIAL_CAPITAL * 100
    bull_dynamic = results["dynamic_topk"]["regime_pnl"]["bull"] / INITIAL_CAPITAL * 100
    print(f"  1) 상승장에서 top_k=5 vs top_k=3:")
    print(f"     Baseline(top_k=5): {bull_baseline:+.1f}%")
    print(f"     선택 1(top_k=3):   {bull_sel1:+.1f}%")
    print(f"     동적(top_k=5):     {bull_dynamic:+.1f}%")
    if bull_baseline > bull_sel1:
        print(f"     -> top_k=5가 상승장에서 {bull_baseline - bull_sel1:.1f}%p 우위 (가설 지지)")
    else:
        print(f"     -> top_k=3이 상승장에서 {bull_sel1 - bull_baseline:.1f}%p 우위 (가설 기각)")

    # 2. 횡보장 파라미터 완화
    sw_baseline = results["baseline"]["regime_pnl"]["sideways"] / INITIAL_CAPITAL * 100
    sw_sel1 = results["selection_1"]["regime_pnl"]["sideways"] / INITIAL_CAPITAL * 100
    sw_dynamic = results["dynamic_topk"]["regime_pnl"]["sideways"] / INITIAL_CAPITAL * 100
    print(f"\n  2) 횡보장에서 파라미터 완화 효과:")
    print(f"     Baseline(현재):       {sw_baseline:+.1f}%")
    print(f"     선택 1(완화):          {sw_sel1:+.1f}%")
    print(f"     동적(완화 적용):       {sw_dynamic:+.1f}%")
    if sw_sel1 > sw_baseline:
        print(f"     -> 파라미터 완화가 횡보장에서 {sw_sel1 - sw_baseline:.1f}%p 개선 (가설 지지)")
    else:
        print(f"     -> 파라미터 완화가 오히려 {sw_baseline - sw_sel1:.1f}%p 악화 (가설 기각)")

    # ── 최근 1년 성과 ──
    print(f"\n[최근 1년 성과 -- {RECENT_START} ~ {RECENT_END}]")
    print("-" * 64)
    header = f"{'지표':<14}"
    for k in keys:
        header += f" | {names[k]:>12}"
    print(header)
    print("-" * 64)

    recent_metrics = []
    for k in keys:
        eq = results[k]["equity_curve"]
        recent_eq = eq.loc[RECENT_START:RECENT_END]
        if len(recent_eq) >= 2:
            m = calc_all_metrics(recent_eq)
        else:
            m = {"누적수익률": 0, "MDD": 0, "샤프비율": 0}
        recent_metrics.append(m)

    recent_rows = [
        ("누적 수익률", [fmt_pct(m["누적수익률"]) for m in recent_metrics]),
        ("MDD", [f"{m['MDD']*100:.1f}%" for m in recent_metrics]),
        ("샤프 지수", [f"{m['샤프비율']:.2f}" for m in recent_metrics]),
    ]

    for label, values in recent_rows:
        line = f"{label:<14}"
        for v in values:
            line += f" | {v:>12}"
        print(line)
    print("-" * 64)

    # ── 결론 ──
    print("\n[결론]")
    best_return = max(keys, key=lambda k: results[k]["equity_curve"].iloc[-1])
    best_sharpe = max(keys, key=lambda k: calc_sharpe_ratio(results[k]["equity_curve"]))
    best_recent = max(keys, key=lambda k: (
        calc_all_metrics(results[k]["equity_curve"].loc[RECENT_START:RECENT_END])["누적수익률"]
        if len(results[k]["equity_curve"].loc[RECENT_START:RECENT_END]) >= 2 else -999
    ))
    print(f"  전체 기간 최우수: {names[best_return]}")
    print(f"  샤프 기준 최우수: {names[best_sharpe]}")
    print(f"  최근 1년 최우수:  {names[best_recent]}")

    # 동적 top_k 평가
    dtk_ret = metrics_list[2]["누적수익률"]
    bl_ret = metrics_list[0]["누적수익률"]
    s1_ret = metrics_list[1]["누적수익률"]
    print(f"\n  동적 top_k 평가:")
    print(f"    vs Baseline: {(dtk_ret - bl_ret)*100:+.1f}%p")
    print(f"    vs 선택 1:   {(dtk_ret - s1_ret)*100:+.1f}%p")

    if dtk_ret > bl_ret and dtk_ret > s1_ret:
        print(f"    -> 동적 top_k가 양쪽 모두 상회. 실거래 적용 권장.")
    elif dtk_ret > bl_ret:
        print(f"    -> Baseline 대비 개선, 선택 1 대비는 미달.")
    elif dtk_ret > s1_ret:
        print(f"    -> 선택 1 대비 개선, Baseline 대비는 미달.")
    else:
        print(f"    -> 양쪽 모두 하회. 추가 최적화 필요.")


# ─────────────────────────────────────────────
# 차트 저장
# ─────────────────────────────────────────────

def save_chart(results: dict, regime_df: pd.DataFrame):
    """3개 전략 자산곡선 + 국면 배경색 차트를 저장합니다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    path = os.path.join(RESULTS_DIR, f"dynamic_topk_{today}.png")

    fig, ax = plt.subplots(figsize=(16, 8))

    # 국면 배경색
    regime_colors = {"bull": "#d4edda", "sideways": "#fff3cd", "bear": "#f8d7da"}
    regime_in_range = regime_df.loc[BACKTEST_START:BACKTEST_END]
    prev_regime = None
    block_start = None

    for date, row in regime_in_range.iterrows():
        r = row["regime"]
        if r != prev_regime:
            if prev_regime is not None and block_start is not None:
                ax.axvspan(block_start, date, alpha=0.3,
                          color=regime_colors.get(prev_regime, "#e2e3e5"), linewidth=0)
            block_start = date
            prev_regime = r
    if prev_regime is not None and block_start is not None:
        ax.axvspan(block_start, regime_in_range.index[-1], alpha=0.3,
                  color=regime_colors.get(prev_regime, "#e2e3e5"), linewidth=0)

    # 자산곡선
    labels = {
        "baseline": "Baseline (전 국면 동일)",
        "selection_1": "선택 1 (파라미터 완화)",
        "dynamic_topk": "동적 top_k (국면별 분리)",
    }
    colors_line = {"baseline": "#1f77b4", "selection_1": "#ff7f0e", "dynamic_topk": "#2ca02c"}
    linewidths = {"baseline": 1.2, "selection_1": 1.2, "dynamic_topk": 2.5}

    for key in ["baseline", "selection_1", "dynamic_topk"]:
        eq = results[key]["equity_curve"]
        final_ret = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
        label = f"{labels[key]} ({final_ret:+.1f}%)"
        ax.plot(eq.index, eq.values, label=label,
                color=colors_line[key], linewidth=linewidths[key],
                linestyle="-" if key == "dynamic_topk" else "--")

    # 초기 자본선
    ax.axhline(y=INITIAL_CAPITAL, color="gray", linestyle=":", alpha=0.5, label=f"초기 자본 ({INITIAL_CAPITAL:,}원)")

    ax.set_title("동적 top_k 전략 백테스트 (국면별 파라미터 분리)", fontsize=14, pad=15)
    ax.set_xlabel("날짜")
    ax.set_ylabel("자산 (원)")
    ax.legend(loc="upper left", fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)
    ax.grid(True, alpha=0.3)

    # 국면 범례
    from matplotlib.patches import Patch
    legend_patches = [
        Patch(facecolor="#d4edda", alpha=0.5, label="상승장"),
        Patch(facecolor="#fff3cd", alpha=0.5, label="횡보장"),
        Patch(facecolor="#f8d7da", alpha=0.5, label="하락장"),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"차트 저장: {path}")
    return path


def save_csv(results: dict, regime_df: pd.DataFrame):
    """일별 자산곡선 + 국면 정보를 CSV로 저장합니다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    path = os.path.join(RESULTS_DIR, f"dynamic_topk_{today}.csv")

    df = pd.DataFrame({
        "baseline_value": results["baseline"]["equity_curve"],
        "selection1_value": results["selection_1"]["equity_curve"],
        "dynamic_topk_value": results["dynamic_topk"]["equity_curve"],
    })
    df = df.join(regime_df[["adx", "regime"]], how="left")
    df.index.name = "date"
    df.to_csv(path)
    logger.info(f"CSV 저장: {path}")
    return path


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────

def main():
    logger.info("=" * 50)
    logger.info("동적 top_k 전략 백테스트 시작")
    logger.info("=" * 50)

    # 1. 데이터 로드
    logger.info("[1/4] 데이터 로드 중...")
    data = load_data()
    prices = data["prices"]
    volumes = data["volumes"]
    highs = data["highs"]
    lows = data["lows"]

    # 2. ADX 국면 계산
    logger.info("[2/4] ADX 국면 계산 중...")
    regime_df = calc_daily_regimes(highs, lows, prices, ADX_PERIOD)

    regime_in_range = regime_df.loc[BACKTEST_START:BACKTEST_END]
    total = len(regime_in_range)
    for r in ["bull", "sideways", "bear"]:
        cnt = (regime_in_range["regime"] == r).sum()
        logger.info(f"  {r}: {cnt}일 ({cnt/total*100:.1f}%)")

    # 3. 전략별 시뮬레이션 실행
    logger.info("[3/4] 전략별 시뮬레이션 실행 중...")
    results = {}
    for name, config in STRATEGIES.items():
        logger.info(f"\n  >> {name}: {config['설명']}")
        result = run_simulation_dynamic(
            strategy_name=name,
            config=config,
            prices=prices,
            volumes=volumes,
            regime_df=regime_df,
            start_date=BACKTEST_START,
            end_date=BACKTEST_END,
        )
        if result:
            results[name] = result
            eq = result["equity_curve"]
            ret = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
            logger.info(f"    수익률: {ret:+.1f}%, 거래수: {result['total_trades']}건")

    if len(results) != 3:
        logger.error("일부 전략 실행 실패")
        return

    # 4. 결과 출력 및 저장
    logger.info("[4/4] 결과 출력 및 저장 중...")
    print_results(results, regime_df)

    csv_path = save_csv(results, regime_df)
    chart_path = save_chart(results, regime_df)

    print(f"\n  CSV: {csv_path}")
    print(f"  차트: {chart_path}")


if __name__ == "__main__":
    main()
