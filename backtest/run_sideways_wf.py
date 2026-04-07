"""
backtest/run_sideways_wf.py - 횡보장 한정 walk-forward 전략 비교 러너

기존 run_sideways_comparison.py 의 데이터 로더 / 거래량돌파 신호 함수를 재사용하면서,
횡보 구간(sideways_filter.build_sideways_mask) 한정으로 다음 3가지 전략을 walk-forward 비교합니다:

  - baseline : 기존 거래량돌파 (vol_ratio 1.26, 4일고가, top_k 5)
  - bb_rsi   : BB+RSI 평균회귀 (BBRSIMeanReversionBT)
  - keltner  : 켈트너 스퀴즈 (KeltnerSqueezeBT)

비-횡보일은 전부 현금 보유 (자본 그대로 이월).

실행:
  python -m backtest.run_sideways_wf
  python -m backtest.run_sideways_wf --strategies baseline,bb_rsi --train 180 --test 60

본 PR 은 백테스트 검증 전용 — 실거래(src/) 코드는 변경하지 않습니다.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from datetime import datetime

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger

from backtest.data_collector import COINS
from backtest.regime.sideways_filter import build_sideways_mask
from backtest.run_sideways_comparison import (
    INITIAL_CAPITAL,
    COMMISSION,
    REBALANCE_DAYS,
    load_data,
    calc_volume_breakout_weights,
    calc_daily_regimes,
    _execute_rebalance,
)

# 모듈 레벨 캐시 (baseline_live 가 라우터 v2 의 ADX 국면 결과를 공유)
_REGIME_CACHE: dict = {}
from backtest.strategies.bb_rsi_mean_reversion import BBRSIMeanReversionBT
from backtest.strategies.keltner_squeeze import KeltnerSqueezeBT
from backtest.strategies.grid_trading import GridTradingBT
from backtest.walk_forward import run_walk_forward

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# ─────────────────────────────────────────────
# 전략 어댑터: 일별 weights 함수 통일
# ─────────────────────────────────────────────


def _adapter_baseline():
    """거래량돌파 단독 (국면 무관, 항상 진입) — 라이브보다 공격적."""

    def fn(prices, volumes, highs, lows, date):
        return calc_volume_breakout_weights(
            prices, volumes, date,
            vol_ratio=1.26, price_lookback=4, top_k=5,
        )

    return fn, "baseline_volume_breakout"


def _is_cash(date, *, use_sma200=False, use_mom30=False, mom30_threshold=-0.03):
    """
    공용 하락 필터. ADX bear 는 항상 켜져 있고, 옵션으로 SMA200/모멘텀 추가.
    True = 현금 보유, False = 거래.
    """
    regime_df = _REGIME_CACHE.get("regime_df")
    if regime_df is None or date not in regime_df.index:
        return True  # 판정 불가 → 보수적
    if regime_df.loc[date, "regime"] == "bear":
        return True
    if use_sma200:
        sma_ser = _REGIME_CACHE.get("btc_sma200")
        btc_ser = _REGIME_CACHE.get("btc_close")
        if sma_ser is not None and date in sma_ser.index:
            sma = sma_ser.loc[date]
            close = btc_ser.loc[date]
            if pd.notna(sma) and close < sma:
                return True
    if use_mom30:
        mom_ser = _REGIME_CACHE.get("btc_mom30")
        if mom_ser is not None and date in mom_ser.index:
            mom = mom_ser.loc[date]
            if pd.notna(mom) and mom < mom30_threshold:
                return True
    return False


def _make_baseline_adapter(*, use_sma200=False, use_mom30=False):
    def fn(prices, volumes, highs, lows, date):
        if _is_cash(date, use_sma200=use_sma200, use_mom30=use_mom30):
            return pd.Series(dtype=float)
        return calc_volume_breakout_weights(
            prices, volumes, date,
            vol_ratio=1.26, price_lookback=4, top_k=5,
        )
    return fn


def _adapter_baseline_live():
    """라이브 라우터 v2 동등: ADX bear 만."""
    return _make_baseline_adapter(), "baseline_live_router_v2"


def _adapter_bb_rsi():
    strat = BBRSIMeanReversionBT(top_k=3)

    def fn(prices, volumes, highs, lows, date):
        lookback = prices.loc[:date]
        return strat.get_weights(prices, volumes, date, lookback)

    return fn, "bb_rsi_mean_reversion", strat


def _adapter_keltner():
    strat = KeltnerSqueezeBT(top_k=3)

    def fn(prices, volumes, highs, lows, date):
        lookback = prices.loc[:date]
        return strat.get_weights(prices, volumes, date, lookback, highs=highs, lows=lows)

    return fn, "keltner_squeeze", strat


def build_strategy(name: str):
    """
    이름→(kind, payload) 반환.
      kind="weights" : payload=(weights_fn, reset_fn)  → simulate() 사용
      kind="custom"  : payload=simulate_fn(prices, volumes, highs, lows, mask, dates, capital)
                       → 자체 시뮬레이터 사용 (그리드 등 주문 기반 전략)
    """
    if name == "baseline":
        fn, _ = _adapter_baseline()
        return "weights", (fn, lambda: None)
    if name == "baseline_live":
        fn, _ = _adapter_baseline_live()
        return "weights", (fn, lambda: None)
    if name == "baseline_v_sma200":
        fn = _make_baseline_adapter(use_sma200=True)
        return "weights", (fn, lambda: None)
    if name == "baseline_v_mom30":
        fn = _make_baseline_adapter(use_mom30=True)
        return "weights", (fn, lambda: None)
    if name == "baseline_v_combo":
        fn = _make_baseline_adapter(use_sma200=True, use_mom30=True)
        return "weights", (fn, lambda: None)
    if name == "bb_rsi":
        fn, _, strat = _adapter_bb_rsi()
        return "weights", (fn, strat.reset)
    if name == "keltner":
        fn, _, strat = _adapter_keltner()
        return "weights", (fn, strat.reset)
    if name == "grid":
        strat = GridTradingBT()

        def custom_sim(prices, volumes, highs, lows, mask, dates, capital):
            return strat.simulate(
                prices, highs, lows, dates, initial_capital=capital, mask=mask
            )

        return "custom", custom_sim
    raise ValueError(f"unknown strategy: {name}")


# ─────────────────────────────────────────────
# 시뮬레이션 (sideways 마스크 적용)
# ─────────────────────────────────────────────


def simulate(
    weights_fn,
    reset_fn,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    sideways_mask: pd.Series,
    dates: pd.DatetimeIndex,
) -> dict:
    """주어진 dates 구간만 시뮬레이션. 횡보 아닌 날은 현금 보유."""
    reset_fn()

    capital = float(INITIAL_CAPITAL)
    holdings: dict[str, float] = {}
    equity_curve = []
    days_since_rebal = REBALANCE_DAYS
    total_trades = 0

    for date in dates:
        is_sideways = bool(sideways_mask.get(date, False))

        # 리밸런싱 판단
        if days_since_rebal >= REBALANCE_DAYS:
            if is_sideways:
                target = weights_fn(prices, volumes, highs, lows, date)
            else:
                target = pd.Series(dtype=float)  # 현금 보유

            new_holdings, new_capital, n_trades = _execute_rebalance(
                target, holdings, capital, prices, date
            )
            holdings = new_holdings
            capital = new_capital
            total_trades += n_trades
            days_since_rebal = 0
        else:
            days_since_rebal += 1

        # 평가
        portfolio_value = capital
        for coin, qty in holdings.items():
            if coin in prices.columns and date in prices.index:
                p = prices.loc[date, coin]
                if pd.notna(p):
                    portfolio_value += qty * p
        equity_curve.append({"date": date, "value": portfolio_value})

    eq = pd.DataFrame(equity_curve).set_index("date")["value"]
    return {"equity": eq, "trades": total_trades}


# ─────────────────────────────────────────────
# 출력
# ─────────────────────────────────────────────


def print_results(per_strategy: dict[str, dict]):
    print()
    print("=" * 72)
    print("  횡보장 walk-forward 비교 결과")
    print("=" * 72)
    for name, wf in per_strategy.items():
        s = wf.get("summary", {})
        if not s:
            print(f"\n[{name}] (실행된 fold 없음)")
            continue
        print(f"\n[{name}] folds={s['n_folds']}, 총거래={s['총거래수']}")
        print(
            f"  평균수익률 {s['평균수익률']*100:+.2f}%  "
            f"평균샤프 {s['평균샤프']:.2f}  "
            f"σ샤프 {s['샤프표준편차']:.2f}  "
            f"평균MDD {s['평균MDD']*100:.1f}%"
        )
        print(f"  fold 별:")
        print(f"    {'test_start':<12} {'test_end':<12} {'수익률':>10} {'샤프':>8} {'MDD':>8} {'PF':>8} {'거래':>6}")
        for f in wf["folds"]:
            pf = f["프로핏팩터"]
            pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
            print(
                f"    {f['test_start']:<12} {f['test_end']:<12} "
                f"{f['수익률']*100:+9.2f}% {f['샤프비율']:7.2f} "
                f"{f['MDD']*100:7.1f}% {pf_str:>8} {f['거래수']:>6}"
            )


def save_csv(per_strategy: dict[str, dict]) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"sideways_wf_{today}.csv")
    rows = []
    for name, wf in per_strategy.items():
        for f in wf.get("folds", []):
            row = {"strategy": name, **f}
            if row["프로핏팩터"] == float("inf"):
                row["프로핏팩터"] = np.nan
            rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def save_chart(per_strategy: dict[str, dict]) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"sideways_wf_{today}.png")

    names = list(per_strategy.keys())
    avg_sharpe = [per_strategy[n]["summary"].get("평균샤프", 0) for n in names]
    avg_ret = [per_strategy[n]["summary"].get("평균수익률", 0) * 100 for n in names]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].bar(names, avg_sharpe, color="#1f77b4")
    axes[0].set_title("OOS 평균 Sharpe")
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[1].bar(names, avg_ret, color="#2ca02c")
    axes[1].set_title("OOS fold 평균 수익률 (%)")
    axes[1].axhline(0, color="black", linewidth=0.5)
    for ax in axes:
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="횡보 한정 walk-forward 비교")
    parser.add_argument("--strategies", type=str, default="baseline,bb_rsi,keltner")
    parser.add_argument("--train", type=int, default=180)
    parser.add_argument("--test", type=int, default=60)
    parser.add_argument("--step", type=int, default=None, help="기본=test (비겹침)")
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument(
        "--mask",
        type=str,
        default="sideways",
        choices=["sideways", "none"],
        help="sideways: 횡보 마스크 적용 / none: 전 구간 (마스크 비활성)",
    )
    args = parser.parse_args()

    logger.info("데이터 로드 중...")
    data = load_data()
    prices = data["prices"]
    volumes = data["volumes"]
    highs = data["highs"]
    lows = data["lows"]

    bt_start = pd.Timestamp(args.start) if args.start else prices.index.min() + pd.Timedelta(days=90)
    bt_end = pd.Timestamp(args.end) if args.end else prices.index.max()
    logger.info(f"기간: {bt_start.date()} ~ {bt_end.date()}")

    # baseline_live 와 변형들이 사용할 BTC 지표 사전 계산
    logger.info("ADX 국면(라우터 v2) + BTC SMA200 / mom30 계산 중...")
    _REGIME_CACHE["regime_df"] = calc_daily_regimes(highs, lows, prices, adx_period=14)
    btc_close = prices["KRW-BTC"]
    _REGIME_CACHE["btc_close"] = btc_close
    _REGIME_CACHE["btc_sma200"] = btc_close.rolling(200).mean()
    _REGIME_CACHE["btc_mom30"] = btc_close / btc_close.shift(30) - 1

    if args.mask == "sideways":
        logger.info("횡보장 마스크 생성 중...")
        mask = build_sideways_mask(highs, lows, prices)
        sideways_days = int(mask.sum())
        total_days = int(mask.size)
        logger.info(
            f"  횡보일 {sideways_days}/{total_days} ({sideways_days/total_days*100:.1f}%)"
        )
        dates = prices.index[(prices.index >= bt_start) & (prices.index <= bt_end)]
        dates = dates.intersection(mask.index)
    else:
        logger.info("마스크 비활성 (전 구간)")
        mask = pd.Series(True, index=prices.index)
        dates = prices.index[(prices.index >= bt_start) & (prices.index <= bt_end)]

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    per_strategy: dict[str, dict] = {}

    for name in strategies:
        logger.info(f"▶ {name} walk-forward 실행")
        kind, payload = build_strategy(name)

        if kind == "weights":
            weights_fn, reset_fn = payload

            def run_fn(train_idx, test_idx, _wfn=weights_fn, _rfn=reset_fn):
                return simulate(
                    _wfn, _rfn, prices, volumes, highs, lows, mask, test_idx
                )
        else:
            custom_sim = payload

            def run_fn(train_idx, test_idx, _sim=custom_sim):
                return _sim(
                    prices, volumes, highs, lows, mask, test_idx, INITIAL_CAPITAL
                )

        wf = run_walk_forward(
            dates,
            run_fn,
            train_days=args.train,
            test_days=args.test,
            step_days=args.step,
        )
        per_strategy[name] = wf
        s = wf.get("summary", {})
        if s:
            logger.info(
                f"  folds={s['n_folds']}  평균샤프={s['평균샤프']:.2f}  "
                f"평균수익률={s['평균수익률']*100:+.2f}%"
            )

    print_results(per_strategy)
    csv_path = save_csv(per_strategy)
    chart_path = save_chart(per_strategy)
    print(f"\nCSV : {csv_path}")
    print(f"차트: {chart_path}")


if __name__ == "__main__":
    main()
