"""
backtest/run_baseline_sensitivity.py - baseline_v_combo 민감도 분석

SMA 기간 × mom30 임계값 격자를 walk-forward 로 돌려
하락감지 필터 파라미터에 대한 결과 안정성을 확인합니다.

격자:
  sma_period      : 150, 200, 250
  mom30_threshold : -0.03, -0.05, -0.07
→ 총 9개 조합 + baseline_live (필터 없음) 비교

실행:
  python -m backtest.run_baseline_sensitivity
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from loguru import logger

from backtest.run_sideways_comparison import (
    INITIAL_CAPITAL,
    load_data,
    calc_volume_breakout_weights,
    calc_daily_regimes,
)
from backtest.run_sideways_wf import simulate
from backtest.walk_forward import run_walk_forward

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def make_combo_adapter(regime_df, btc_close, sma_period, mom_window, mom_threshold):
    """주어진 파라미터로 combo 필터 어댑터를 생성."""
    sma = btc_close.rolling(sma_period).mean()
    mom = btc_close / btc_close.shift(mom_window) - 1

    def fn(prices, volumes, highs, lows, date):
        if date not in regime_df.index:
            return pd.Series(dtype=float)
        if regime_df.loc[date, "regime"] == "bear":
            return pd.Series(dtype=float)
        if date in sma.index:
            sma_val = sma.loc[date]
            if pd.notna(sma_val) and btc_close.loc[date] < sma_val:
                return pd.Series(dtype=float)
        if date in mom.index:
            mom_val = mom.loc[date]
            if pd.notna(mom_val) and mom_val < mom_threshold:
                return pd.Series(dtype=float)
        return calc_volume_breakout_weights(
            prices, volumes, date, vol_ratio=1.26, price_lookback=4, top_k=5
        )

    return fn


def make_baseline_live_adapter(regime_df):
    """필터 없음 (ADX bear 만)."""
    def fn(prices, volumes, highs, lows, date):
        if date not in regime_df.index:
            return pd.Series(dtype=float)
        if regime_df.loc[date, "regime"] == "bear":
            return pd.Series(dtype=float)
        return calc_volume_breakout_weights(
            prices, volumes, date, vol_ratio=1.26, price_lookback=4, top_k=5
        )
    return fn


def main():
    logger.info("데이터 로드 중...")
    data = load_data()
    prices, volumes = data["prices"], data["volumes"]
    highs, lows = data["highs"], data["lows"]

    bt_start = prices.index.min() + pd.Timedelta(days=90)
    bt_end = prices.index.max()
    dates = prices.index[(prices.index >= bt_start) & (prices.index <= bt_end)]

    logger.info("ADX 국면 계산 중...")
    regime_df = calc_daily_regimes(highs, lows, prices, adx_period=14)
    btc_close = prices["KRW-BTC"]

    sma_periods = [150, 200, 250]
    mom_thresholds = [-0.03, -0.05, -0.07]
    mom_window = 30

    rows = []

    # baseline_live (필터 없음) 기준점
    logger.info("▶ baseline_live (no filter)")
    fn = make_baseline_live_adapter(regime_df)
    wf = run_walk_forward(
        dates,
        lambda tr, te, _f=fn: simulate(_f, lambda: None, prices, volumes, highs, lows,
                                        pd.Series(True, index=prices.index), te),
        train_days=120, test_days=60,
    )
    s = wf["summary"]
    worst = min(f["수익률"] for f in wf["folds"])
    rows.append({
        "label": "baseline_live", "sma": "-", "mom": "-",
        "평균수익률": s["평균수익률"], "평균MDD": s["평균MDD"],
        "평균샤프": s["평균샤프"], "worst": worst, "거래수": s["총거래수"],
    })

    for sma_p in sma_periods:
        for mom_t in mom_thresholds:
            label = f"sma{sma_p}_mom{int(mom_t*100)}"
            logger.info(f"▶ {label}")
            fn = make_combo_adapter(regime_df, btc_close, sma_p, mom_window, mom_t)
            wf = run_walk_forward(
                dates,
                lambda tr, te, _f=fn: simulate(_f, lambda: None, prices, volumes, highs, lows,
                                                pd.Series(True, index=prices.index), te),
                train_days=120, test_days=60,
            )
            s = wf["summary"]
            worst = min(f["수익률"] for f in wf["folds"])
            rows.append({
                "label": label, "sma": sma_p, "mom": f"{int(mom_t*100)}%",
                "평균수익률": s["평균수익률"], "평균MDD": s["평균MDD"],
                "평균샤프": s["평균샤프"], "worst": worst, "거래수": s["총거래수"],
            })

    df = pd.DataFrame(rows)

    print()
    print("=" * 84)
    print("  baseline_v_combo 민감도 분석 (train 120 / test 60, 21 fold)")
    print("=" * 84)
    print(f"{'label':<20} {'SMA':>5} {'MOM':>6} {'평균수익':>10} {'평균MDD':>9} {'worst':>9} {'거래':>7}")
    for _, r in df.iterrows():
        print(
            f"{r['label']:<20} {str(r['sma']):>5} {str(r['mom']):>6} "
            f"{r['평균수익률']*100:+9.2f}% {r['평균MDD']*100:8.1f}% "
            f"{r['worst']*100:+8.1f}% {r['거래수']:>7}"
        )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(RESULTS_DIR, f"baseline_sensitivity_{today}.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nCSV: {csv_path}")


if __name__ == "__main__":
    main()
