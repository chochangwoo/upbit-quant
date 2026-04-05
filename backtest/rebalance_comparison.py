"""
backtest/rebalance_comparison.py - 리밸런싱 방식 3종 비교 백테스트

3가지 리밸런싱 접근법을 상승장/횡보장에서 비교합니다:
  A. 현재 방식: 거래량 돌파 신호 필수 (없으면 스킵)
  B. 기계적 3일: 무조건 리밸런싱 (신호 없으면 모멘텀 fallback)
  C. 적응형 3~7일: 신호 있으면 3일, 없으면 7일 후 강제

실행:
    python -m backtest.rebalance_comparison
"""

import numpy as np
import pandas as pd
from loguru import logger

from backtest.coin_screener.strategies.base_screener import BaseScreener
from backtest.coin_screener.backtest_engine import ScreenerBacktestEngine, ScreenerBacktestResult
from backtest.coin_screener.data_collector import DataCollector
from backtest.regime.detector import classify_indicator


# ─── 대상 코인 (실거래와 동일) ──────────────────
TARGET_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]


# ═══════════════════════════════════════════════
# 공통 유틸: 거래량 돌파 + 모멘텀 스코어 계산
# ═══════════════════════════════════════════════

def _volume_breakout_scores(available: dict, price_lookback=4, vol_ratio_threshold=1.26):
    """거래량 돌파 조건을 만족하는 코인과 스코어를 반환합니다."""
    scores = []
    for ticker, df in available.items():
        if len(df) < 25:
            continue
        close = df["close"]
        volume = df["value"] if "value" in df.columns else df["volume"]

        recent_vol = volume.tail(price_lookback).mean()
        avg_vol = volume.tail(20).mean()
        if avg_vol <= 0:
            continue

        vol_ratio = recent_vol / avg_vol
        price_mom = close.iloc[-1] / close.iloc[-price_lookback] - 1

        if vol_ratio >= vol_ratio_threshold and price_mom > 0:
            scores.append((ticker, vol_ratio * (1 + price_mom)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def _momentum_scores(available: dict, lookback=4):
    """모멘텀(가격 상승률) 기준 스코어를 반환합니다."""
    scores = []
    for ticker, df in available.items():
        if len(df) < lookback + 5:
            continue
        close = df["close"]
        mom = close.iloc[-1] / close.iloc[-lookback] - 1
        if mom > 0:
            scores.append((ticker, mom))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


# ═══════════════════════════════════════════════
# 방식 A: 현재 방식 (거래량 돌파 신호 필수)
# ═══════════════════════════════════════════════

class VolumeOnlyScreener(BaseScreener):
    """거래량 돌파 신호가 있을 때만 코인 반환. 없으면 빈 리스트 → 리밸런싱 스킵."""

    def __init__(self, top_n=5):
        super().__init__(top_n=top_n)

    @property
    def name(self) -> str:
        return "A. 현재방식 (신호필수)"

    def screen(self, all_data: dict, current_date) -> list:
        available = self._get_available_data(all_data, current_date)
        scores = _volume_breakout_scores(available)
        return scores[:self.top_n]  # 신호 없으면 빈 리스트


# ═══════════════════════════════════════════════
# 방식 B: 기계적 3일 (무조건 리밸런싱)
# ═══════════════════════════════════════════════

class MechanicalScreener(BaseScreener):
    """3일마다 무조건 리밸런싱. 거래량 돌파 우선, 없으면 모멘텀 fallback."""

    def __init__(self, top_n=5):
        super().__init__(top_n=top_n)

    @property
    def name(self) -> str:
        return "B. 기계적3일 (강제)"

    def screen(self, all_data: dict, current_date) -> list:
        available = self._get_available_data(all_data, current_date)

        # 1차: 거래량 돌파
        scores = _volume_breakout_scores(available)
        if scores:
            return scores[:self.top_n]

        # 2차: 모멘텀 fallback (항상 코인 반환)
        scores = _momentum_scores(available)
        return scores[:self.top_n]


# ═══════════════════════════════════════════════
# 방식 C: 적응형 3~7일
# ═══════════════════════════════════════════════

class AdaptiveScreener(BaseScreener):
    """
    거래량 돌파 신호 있으면 즉시 리밸런싱, 없으면 대기.
    최대 7일(리밸런싱 2회분) 대기 후 모멘텀으로 강제 리밸런싱.

    ScreenerBacktestEngine은 rebalance_days마다 screen()을 호출하므로,
    내부적으로 연속 스킵 횟수를 추적합니다.
    """

    def __init__(self, top_n=5, max_wait_cycles=2):
        """max_wait_cycles: 최대 스킵 가능 횟수 (2 = 3일*2 = 6일 대기 → 7~9일째 강제)"""
        super().__init__(top_n=top_n)
        self.max_wait_cycles = max_wait_cycles
        self.skip_count = 0

    @property
    def name(self) -> str:
        return "C. 적응형3~7일"

    def screen(self, all_data: dict, current_date) -> list:
        available = self._get_available_data(all_data, current_date)

        # 1차: 거래량 돌파
        scores = _volume_breakout_scores(available)
        if scores:
            self.skip_count = 0
            return scores[:self.top_n]

        # 대기 횟수 초과 → 모멘텀으로 강제
        self.skip_count += 1
        if self.skip_count >= self.max_wait_cycles:
            self.skip_count = 0
            scores = _momentum_scores(available)
            return scores[:self.top_n]

        # 아직 대기 → 빈 리스트 (리밸런싱 스킵)
        return []


# ═══════════════════════════════════════════════
# 국면별 성과 분리 함수
# ═══════════════════════════════════════════════

def split_by_regime(result: ScreenerBacktestResult, regimes: pd.Series) -> dict:
    """
    백테스트 결과를 국면별로 분리하여 성과를 계산합니다.

    반환값:
        {"bull": {...metrics}, "sideways": {...metrics}, "overall": {...metrics}}
    """
    if not result.dates or not result.equity_curve:
        return {}

    equity_df = pd.DataFrame({
        "date": result.dates,
        "equity": result.equity_curve,
    })
    equity_df["date"] = pd.to_datetime(equity_df["date"])
    equity_df = equity_df.set_index("date")
    equity_df["return"] = equity_df["equity"].pct_change()

    output = {"overall": result.summary()}

    for regime_name in ["bull", "sideways"]:
        regime_dates = regimes[regimes == regime_name].index
        mask = equity_df.index.isin(regime_dates)
        regime_returns = equity_df.loc[mask, "return"].dropna()

        if len(regime_returns) < 5:
            output[regime_name] = {
                "days": 0, "cumulative_return": 0, "mdd": 0,
                "sharpe": 0, "daily_avg_return": 0,
            }
            continue

        # 누적 수익률
        cum_return = (1 + regime_returns).prod() - 1

        # MDD (해당 구간만)
        regime_equity = equity_df.loc[mask, "equity"]
        peak = regime_equity.cummax()
        dd = (regime_equity - peak) / peak
        mdd = float(dd.min()) * 100

        # 샤프
        daily_rf = 0.035 / 365
        excess = regime_returns - daily_rf
        sharpe = float(excess.mean() / excess.std() * (365 ** 0.5)) if excess.std() > 0 else 0

        output[regime_name] = {
            "days": len(regime_returns),
            "cumulative_return": round(cum_return * 100, 2),
            "mdd": round(mdd, 2),
            "sharpe": round(sharpe, 2),
            "daily_avg_return": round(regime_returns.mean() * 100, 4),
        }

    return output


# ═══════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════

def run_comparison():
    """3가지 리밸런싱 방식 비교 백테스트를 실행합니다."""

    print("=" * 60)
    print("  리밸런싱 방식 3종 비교 백테스트")
    print("=" * 60)

    # 1. 데이터 수집
    print("\n[1/4] 데이터 수집 중...")
    collector = DataCollector()
    all_data = collector.collect_all(days=830)

    # TARGET_COINS만 필터링
    filtered = {k: v for k, v in all_data.items() if k in TARGET_COINS}
    print(f"  대상 코인: {len(filtered)}개 / 전체 {len(all_data)}개")

    if len(filtered) < 5:
        print("대상 코인 데이터가 부족합니다.")
        return

    # 2. BTC 국면 분류
    print("\n[2/4] BTC 국면 분류 중...")
    btc_data = filtered.get("KRW-BTC")
    if btc_data is None:
        print("BTC 데이터가 없습니다.")
        return

    regimes = classify_indicator(btc_data)

    # 국면 통계
    counts = regimes.value_counts()
    total = len(regimes)
    print(f"  전체 기간: {total}일")
    for r in ["bull", "sideways", "bear"]:
        n = counts.get(r, 0)
        print(f"  {r:>8s}: {n}일 ({n/total:.1%})")

    # 3. 백테스팅 실행
    print("\n[3/4] 백테스팅 실행 중...")
    screeners = [
        VolumeOnlyScreener(top_n=5),
        MechanicalScreener(top_n=5),
        AdaptiveScreener(top_n=5, max_wait_cycles=2),
    ]

    results = []
    for screener in screeners:
        engine = ScreenerBacktestEngine(
            screener=screener,
            all_data=filtered,
            initial_capital=1_000_000,
            rebalance_days=3,
            fee_rate=0.0005,
            slippage=0.001,
        )
        result = engine.run()
        regime_metrics = split_by_regime(result, regimes)
        results.append((result, regime_metrics))
        print(f"  [완료] {screener.name}")

    # 4. 결과 출력
    print("\n[4/4] 결과 비교")
    print("=" * 60)

    # 전체 성과
    print(f"\n{'':>24s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'거래수':>6s}")
    print("-" * 60)
    for result, metrics in results:
        s = metrics["overall"]
        print(
            f"  {result.strategy_name:<22s} | "
            f"{s['total_return']:>+7.1f}% | "
            f"{s['mdd']:>7.1f}% | "
            f"{s['sharpe_ratio']:>6.2f} | "
            f"{s['total_trades']:>5d}건"
        )

    # 상승장 성과
    print(f"\n{'[상승장 (Bull)]':>24s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'일수':>6s}")
    print("-" * 60)
    for result, metrics in results:
        s = metrics.get("bull", {})
        if s.get("days", 0) > 0:
            print(
                f"  {result.strategy_name:<22s} | "
                f"{s['cumulative_return']:>+7.1f}% | "
                f"{s['mdd']:>7.1f}% | "
                f"{s['sharpe']:>6.2f} | "
                f"{s['days']:>5d}일"
            )
        else:
            print(f"  {result.strategy_name:<22s} | {'데이터 부족':>20s}")

    # 횡보장 성과
    print(f"\n{'[횡보장 (Sideways)]':>24s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'일수':>6s}")
    print("-" * 60)
    for result, metrics in results:
        s = metrics.get("sideways", {})
        if s.get("days", 0) > 0:
            print(
                f"  {result.strategy_name:<22s} | "
                f"{s['cumulative_return']:>+7.1f}% | "
                f"{s['mdd']:>7.1f}% | "
                f"{s['sharpe']:>6.2f} | "
                f"{s['days']:>5d}일"
            )
        else:
            print(f"  {result.strategy_name:<22s} | {'데이터 부족':>20s}")

    print("\n" + "=" * 60)
    print("완료!")

    return results


if __name__ == "__main__":
    run_comparison()
