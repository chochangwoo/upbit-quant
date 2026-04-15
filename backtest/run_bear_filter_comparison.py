"""
backtest/run_bear_filter_comparison.py - bear 필터 변형 비교 백테스트

현재 라이브(v3)에서 BTC < SMA200 필터 때문에
ADX 상승장임에도 하락장(현금보유) 판정되는 문제를 검증합니다.

비교 대상 6종:
  1. v2_adx_only     : ADX bear만 (SMA/mom 필터 없음)
  2. v3_sma200_mom30 : 현재 배포본 (ADX bear + SMA200 + mom30<-3%)
  3. v3_sma150_mom30 : SMA 기간 축소 (150일)
  4. v3_sma100_mom30 : SMA 기간 축소 (100일)
  5. v3_sma200_adx_override : SMA200 사용하되, ADX가 상승 추세이면 bear 필터 무시
  6. naked           : 필터 없음 (거래량돌파 단독, 벤치마크)

실행:
  python -m backtest.run_bear_filter_comparison
  python -m backtest.run_bear_filter_comparison --train 120 --test 60
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

import pandas as pd
from loguru import logger

from backtest.run_sideways_comparison import load_data, calc_daily_regimes
from backtest.walk_forward import run_walk_forward
from backtest.metrics import (
    calc_cumulative_return,
    calc_sharpe_ratio,
    calc_mdd,
    calc_daily_win_rate,
    calc_profit_factor,
    calc_annual_return,
    calc_annual_volatility,
    calc_sortino_ratio,
)

import backtest.run_sideways_wf as wf_mod
from backtest.run_sideways_comparison import (
    INITIAL_CAPITAL,
    COMMISSION,
    REBALANCE_DAYS,
    calc_volume_breakout_weights,
    _execute_rebalance,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


# ─────────────────────────────────────────────
# bear 필터 변형 어댑터
# ─────────────────────────────────────────────

def _is_cash_custom(
    date,
    *,
    use_sma: bool = False,
    sma_key: str = "btc_sma200",
    use_mom30: bool = False,
    mom30_threshold: float = -0.03,
    adx_bull_override: bool = False,
):
    """
    커스텀 하락 필터.
    adx_bull_override=True: ADX가 bull이면 SMA/mom 필터를 무시합니다.
    """
    regime_df = wf_mod._REGIME_CACHE.get("regime_df")
    if regime_df is None or date not in regime_df.index:
        return True

    adx_regime = regime_df.loc[date, "regime"]

    # ADX bear → 항상 현금
    if adx_regime == "bear":
        return True

    # ADX bull override: ADX가 bull이면 SMA/mom 필터 무시
    if adx_bull_override and adx_regime == "bull":
        return False

    # SMA 필터
    if use_sma:
        sma_ser = wf_mod._REGIME_CACHE.get(sma_key)
        btc_ser = wf_mod._REGIME_CACHE.get("btc_close")
        if sma_ser is not None and date in sma_ser.index:
            sma = sma_ser.loc[date]
            close = btc_ser.loc[date]
            if pd.notna(sma) and close < sma:
                return True

    # 모멘텀 필터
    if use_mom30:
        mom_ser = wf_mod._REGIME_CACHE.get("btc_mom30")
        if mom_ser is not None and date in mom_ser.index:
            mom = mom_ser.loc[date]
            if pd.notna(mom) and mom < mom30_threshold:
                return True

    return False


def _make_adapter(*, use_sma=False, sma_key="btc_sma200", use_mom30=False, adx_bull_override=False):
    """bear 필터 변형 어댑터를 생성합니다."""
    def fn(prices, volumes, highs, lows, date):
        if _is_cash_custom(
            date,
            use_sma=use_sma,
            sma_key=sma_key,
            use_mom30=use_mom30,
            adx_bull_override=adx_bull_override,
        ):
            return pd.Series(dtype=float)
        return calc_volume_breakout_weights(
            prices, volumes, date,
            vol_ratio=1.1, price_lookback=2, top_k=3,
        )
    return fn


# 전략 정의
STRATEGIES = {
    "v2_adx_only": {
        "설명": "ADX bear만 (SMA/mom 필터 없음)",
        "adapter_kwargs": {"use_sma": False, "use_mom30": False},
    },
    "v3_sma200_mom30": {
        "설명": "현재 배포본 (SMA200 + mom30)",
        "adapter_kwargs": {"use_sma": True, "sma_key": "btc_sma200", "use_mom30": True},
    },
    "v3_sma150_mom30": {
        "설명": "SMA150 + mom30",
        "adapter_kwargs": {"use_sma": True, "sma_key": "btc_sma150", "use_mom30": True},
    },
    "v3_sma100_mom30": {
        "설명": "SMA100 + mom30",
        "adapter_kwargs": {"use_sma": True, "sma_key": "btc_sma100", "use_mom30": True},
    },
    "v3_sma200_adx_override": {
        "설명": "SMA200 사용하되 ADX bull이면 무시",
        "adapter_kwargs": {"use_sma": True, "sma_key": "btc_sma200", "use_mom30": True, "adx_bull_override": True},
    },
    "naked": {
        "설명": "필터 없음 (거래량돌파 단독)",
        "adapter_kwargs": None,  # 특수 처리
    },
}


def _build_naked_adapter():
    """필터 없이 항상 거래량돌파 실행."""
    def fn(prices, volumes, highs, lows, date):
        return calc_volume_breakout_weights(
            prices, volumes, date,
            vol_ratio=1.1, price_lookback=2, top_k=3,
        )
    return fn


# ─────────────────────────────────────────────
# 지표 계산/포맷 헬퍼
# ─────────────────────────────────────────────

def _summarize(eq: pd.Series, trades: int) -> dict:
    return {
        "수익률": calc_cumulative_return(eq),
        "연환산": calc_annual_return(eq),
        "샤프비율": calc_sharpe_ratio(eq),
        "MDD": calc_mdd(eq),
        "일별승률": calc_daily_win_rate(eq),
        "프로핏팩터": calc_profit_factor(eq),
        "거래수": trades,
    }


def _fmt_metrics(m: dict) -> str:
    pf = m["프로핏팩터"]
    pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
    return (
        f"수익률 {m['수익률']*100:+8.2f}% | "
        f"연환산 {m['연환산']*100:+7.2f}% | "
        f"샤프 {m['샤프비율']:6.2f} | "
        f"MDD {m['MDD']*100:7.2f}% | "
        f"승률 {m['일별승률']*100:5.1f}% | "
        f"PF {pf_str:>6} | "
        f"거래 {m['거래수']:>4}"
    )


# ─────────────────────────────────────────────
# 시뮬레이션 (run_sideways_wf.simulate 재사용)
# ─────────────────────────────────────────────

def _run_simulate(weights_fn, dates, prices, volumes, highs, lows, mask):
    return wf_mod.simulate(weights_fn, lambda: None, prices, volumes, highs, lows, mask, dates)


# ─────────────────────────────────────────────
# 백테스트 1: 전체 구간
# ─────────────────────────────────────────────

def run_overall(prices, volumes, highs, lows, mask_all, dates) -> dict:
    print()
    print("=" * 88)
    print("  [1/3] 전체 구간 단일 백테스트")
    print(f"        기간: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)}일)")
    print("=" * 88)

    out = {}
    for label, cfg in STRATEGIES.items():
        if cfg["adapter_kwargs"] is None:
            fn = _build_naked_adapter()
        else:
            fn = _make_adapter(**cfg["adapter_kwargs"])

        result = _run_simulate(fn, dates, prices, volumes, highs, lows, mask_all)
        eq = result["equity"]
        if eq.empty or len(eq) < 2:
            print(f"  {label:<26} (데이터 부족)")
            continue
        m = _summarize(eq, int(result["trades"]))
        out[label] = m
        print(f"  {label:<26} {_fmt_metrics(m)}")
        print(f"  {'':26} -> {cfg['설명']}")
    return out


# ─────────────────────────────────────────────
# 백테스트 2: bear 필터 발동 일수 분석
# ─────────────────────────────────────────────

def run_filter_analysis(dates, prices) -> dict:
    print()
    print("=" * 88)
    print("  [2/3] bear 필터 발동 일수 분석")
    print("=" * 88)

    btc_close = wf_mod._REGIME_CACHE["btc_close"]
    regime_df = wf_mod._REGIME_CACHE["regime_df"]

    analysis = {}
    for sma_label, sma_key, period in [
        ("SMA100", "btc_sma100", 100),
        ("SMA150", "btc_sma150", 150),
        ("SMA200", "btc_sma200", 200),
    ]:
        sma_ser = wf_mod._REGIME_CACHE[sma_key]
        below_sma = 0
        adx_bull_but_below = 0
        total = 0
        for d in dates:
            if d not in sma_ser.index or pd.isna(sma_ser.loc[d]):
                continue
            total += 1
            if btc_close.loc[d] < sma_ser.loc[d]:
                below_sma += 1
                if d in regime_df.index and regime_df.loc[d, "regime"] == "bull":
                    adx_bull_but_below += 1

        analysis[sma_label] = {
            "total": total,
            "below": below_sma,
            "pct": below_sma / total * 100 if total > 0 else 0,
            "adx_bull_conflict": adx_bull_but_below,
        }
        print(
            f"  {sma_label}: BTC 하회 {below_sma}일/{total}일 ({below_sma/total*100:.1f}%) | "
            f"ADX bull인데 SMA 하회: {adx_bull_but_below}일"
        )

    # mom30 분석
    mom_ser = wf_mod._REGIME_CACHE["btc_mom30"]
    mom_below = sum(1 for d in dates if d in mom_ser.index and pd.notna(mom_ser.loc[d]) and mom_ser.loc[d] < -0.03)
    print(f"  mom30<-3%: {mom_below}일/{len(dates)}일 ({mom_below/len(dates)*100:.1f}%)")

    # ADX 국면 분포
    regime_aligned = regime_df["regime"].reindex(dates).dropna()
    counts = regime_aligned.value_counts().to_dict()
    total = len(regime_aligned)
    print(
        f"\n  ADX 국면 분포: "
        f"bull {counts.get('bull', 0)}일({counts.get('bull', 0)/total*100:.1f}%) | "
        f"sideways {counts.get('sideways', 0)}일({counts.get('sideways', 0)/total*100:.1f}%) | "
        f"bear {counts.get('bear', 0)}일({counts.get('bear', 0)/total*100:.1f}%)"
    )

    return analysis


# ─────────────────────────────────────────────
# 백테스트 3: Walk-forward K-fold
# ─────────────────────────────────────────────

def run_kfold(prices, volumes, highs, lows, mask_all, dates, train_days, test_days) -> dict:
    print()
    print("=" * 88)
    print(f"  [3/3] Walk-forward K-fold (train={train_days} / test={test_days})")
    print("=" * 88)

    out = {}
    for label, cfg in STRATEGIES.items():
        if cfg["adapter_kwargs"] is None:
            fn = _build_naked_adapter()
        else:
            fn = _make_adapter(**cfg["adapter_kwargs"])

        def run_fn(_train, _test, _wfn=fn):
            return wf_mod.simulate(_wfn, lambda: None, prices, volumes, highs, lows, mask_all, _test)

        wf = run_walk_forward(dates, run_fn, train_days=train_days, test_days=test_days)
        s = wf.get("summary") or {}
        out[label] = wf
        if not s:
            print(f"  {label:<26} (fold 없음)")
            continue
        print(
            f"\n  [{label}] {cfg['설명']}"
            f"\n    folds={s['n_folds']}  총거래={s['총거래수']}"
            f"\n    수익률  mean {s['평균수익률']*100:+.2f}%  median {s['중앙수익률']*100:+.2f}%"
            f"\n    샤프    mean {s['평균샤프']:.2f}  median {s['중앙샤프']:.2f}  "
            f"trimmed {s['trimmed샤프']:.2f}  σ {s['샤프표준편차']:.2f}"
            f"\n    MDD     mean {s['평균MDD']*100:.2f}%  median {s['중앙MDD']*100:.2f}%"
        )
        print(f"    {'test_start':<12}{'test_end':<12}{'수익률':>10}{'샤프':>8}{'MDD':>9}{'PF':>8}{'거래':>6}")
        for f in wf["folds"]:
            pf = f["프로핏팩터"]
            pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
            print(
                f"    {f['test_start']:<12}{f['test_end']:<12}"
                f"{f['수익률']*100:+9.2f}%{f['샤프비율']:7.2f}"
                f"{f['MDD']*100:7.1f}% {pf_str:>7} {f['거래수']:>5}"
            )
    return out


# ─────────────────────────────────────────────
# CSV 저장
# ─────────────────────────────────────────────

def save_csv(overall, kfold) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    rows = []
    for label, m in overall.items():
        rows.append({"section": "overall", "strategy": label, "설명": STRATEGIES[label]["설명"], **m})
    for label, wf in kfold.items():
        for f in wf.get("folds", []):
            rows.append({"section": "kfold", "strategy": label, "설명": STRATEGIES[label]["설명"], **f})

    path = os.path.join(RESULTS_DIR, f"bear_filter_comparison_{stamp}.csv")
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    return path


# ─────────────────────────────────────────────
# 최종 요약
# ─────────────────────────────────────────────

def print_recommendation(overall: dict, kfold: dict):
    print()
    print("=" * 88)
    print("  최종 비교 요약")
    print("=" * 88)

    # 전체 구간 기준 정렬 (샤프 기준)
    ranked = sorted(overall.items(), key=lambda x: x[1].get("샤프비율", 0), reverse=True)
    print(f"\n  {'순위':<4} {'전략':<26} {'수익률':>10} {'샤프':>8} {'MDD':>9} {'설명'}")
    print(f"  {'─'*4} {'─'*26} {'─'*10} {'─'*8} {'─'*9} {'─'*30}")
    for i, (label, m) in enumerate(ranked, 1):
        marker = " <-- 현재" if label == "v3_sma200_mom30" else ""
        print(
            f"  {i:<4} {label:<26} "
            f"{m['수익률']*100:+9.2f}% {m['샤프비율']:7.2f} {m['MDD']*100:8.2f}% "
            f"{STRATEGIES[label]['설명']}{marker}"
        )

    # WF median 기준 (이상치에 강건한 지표)
    print(f"\n  Walk-forward 비교 (median 기준 — 이상치 방어):")
    wf_ranked = []
    for label, wf in kfold.items():
        s = wf.get("summary")
        if s:
            wf_ranked.append((label, s))
    wf_ranked.sort(key=lambda x: x[1].get("중앙샤프", 0), reverse=True)

    print(f"  {'순위':<4} {'전략':<26} {'중앙수익률':>12} {'중앙샤프':>10} {'trimmed샤프':>13} {'중앙MDD':>10}")
    print(f"  {'─'*4} {'─'*26} {'─'*12} {'─'*10} {'─'*13} {'─'*10}")
    for i, (label, s) in enumerate(wf_ranked, 1):
        marker = " <-- 현재" if label == "v3_sma200_mom30" else ""
        print(
            f"  {i:<4} {label:<26} "
            f"{s['중앙수익률']*100:+11.2f}% {s['중앙샤프']:9.2f} {s['trimmed샤프']:12.2f} {s['중앙MDD']*100:9.2f}%"
            f"{marker}"
        )


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="bear 필터 변형 비교 백테스트")
    parser.add_argument("--train", type=int, default=120, help="walk-forward train 일수 (기본 120)")
    parser.add_argument("--test", type=int, default=60, help="walk-forward test 일수 (기본 60)")
    parser.add_argument("--start", type=str, default=None, help="시작일 YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="종료일 YYYY-MM-DD")
    args = parser.parse_args()

    print("=" * 88)
    print("  bear 필터 변형 비교 백테스트")
    print("  문제: BTC < SMA200 필터가 ADX 상승장에서도 현금 강제 → 매매 기회 상실?")
    print("=" * 88)

    logger.info("데이터 로드 중...")
    data = load_data()
    prices = data["prices"]
    volumes = data["volumes"]
    highs = data["highs"]
    lows = data["lows"]

    # 백테스트 기간 설정 (SMA200 워밍업 필요)
    bt_start = pd.Timestamp(args.start) if args.start else prices.index.min() + pd.Timedelta(days=210)
    bt_end = pd.Timestamp(args.end) if args.end else prices.index.max()
    dates = prices.index[(prices.index >= bt_start) & (prices.index <= bt_end)]
    print(f"  데이터 기간 : {prices.index.min().date()} ~ {prices.index.max().date()}")
    print(f"  백테스트 기간: {bt_start.date()} ~ {bt_end.date()} ({len(dates)}일)")

    # ADX 국면 + SMA + 모멘텀 사전 계산
    logger.info("ADX 국면 + SMA(100/150/200) + mom30 사전 계산 중...")
    regime_df = calc_daily_regimes(highs, lows, prices, adx_period=14)
    btc_close = prices["KRW-BTC"]
    wf_mod._REGIME_CACHE["regime_df"] = regime_df
    wf_mod._REGIME_CACHE["btc_close"] = btc_close
    wf_mod._REGIME_CACHE["btc_sma100"] = btc_close.rolling(100).mean()
    wf_mod._REGIME_CACHE["btc_sma150"] = btc_close.rolling(150).mean()
    wf_mod._REGIME_CACHE["btc_sma200"] = btc_close.rolling(200).mean()
    wf_mod._REGIME_CACHE["btc_mom30"] = btc_close / btc_close.shift(30) - 1

    mask_all = pd.Series(True, index=prices.index)

    # 실행
    overall = run_overall(prices, volumes, highs, lows, mask_all, dates)
    run_filter_analysis(dates, prices)
    kfold = run_kfold(prices, volumes, highs, lows, mask_all, dates, args.train, args.test)

    # 저장 및 요약
    csv_path = save_csv(overall, kfold)
    print_recommendation(overall, kfold)

    print()
    print(f"  CSV 저장: {csv_path}")
    print("=" * 88)


if __name__ == "__main__":
    main()
