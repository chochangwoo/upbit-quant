"""
backtest/sideways_comparison.py - 횡보장 개선 전략 4종 비교 백테스트

횡보장에서의 손실을 줄이기 위한 4가지 접근법을 비교합니다:
  1. 횡보장 투자비중 50% (현금 50% 유지)
  2. 횡보장 거래량 돌파 기준 강화 (vol_ratio 1.26 → 2.0)
  3. 횡보장 매수 금지 (상승장에서만 매수)
  4. 횡보장 손절선 강화 (-5%)

+ 기준선: 현재 방식 (횡보장에서도 동일하게 매수)

실행:
    python -m backtest.sideways_comparison
"""

import numpy as np
import pandas as pd
from loguru import logger

from backtest.coin_screener.strategies.base_screener import BaseScreener
from backtest.coin_screener.backtest_engine import ScreenerBacktestResult
from backtest.coin_screener.data_collector import DataCollector
from backtest.regime.detector import classify_indicator


TARGET_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]


# ═══════════════════════════════════════════════
# 공통 유틸
# ═══════════════════════════════════════════════

def _volume_breakout_scores(available, price_lookback=4, vol_ratio_threshold=1.26):
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


def _momentum_scores(available, lookback=4):
    """모멘텀 기준 스코어를 반환합니다."""
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


def _get_available_data(all_data, current_date):
    """look-ahead bias 방지를 위해 current_date까지만 잘라서 반환."""
    available = {}
    for ticker, df in all_data.items():
        sliced = df.loc[:current_date]
        if len(sliced) > 0:
            available[ticker] = sliced
    return available


def _detect_regime_at(btc_data, current_date, sma_window=50, momentum_window=20):
    """특정 날짜의 BTC 국면을 판단합니다."""
    sliced = btc_data.loc[:current_date]
    if len(sliced) < sma_window + 5:
        return "sideways"
    close = sliced["close"]
    sma = close.rolling(sma_window).mean().iloc[-1]
    mom = close.iloc[-1] / close.iloc[-momentum_window] - 1
    if close.iloc[-1] > sma and mom > 0.10:
        return "bull"
    elif close.iloc[-1] < sma and mom < -0.10:
        return "bear"
    return "sideways"


# ═══════════════════════════════════════════════
# 국면 인식 백테스트 엔진
# ═══════════════════════════════════════════════

class RegimeAwareEngine:
    """
    국면별로 다른 행동을 취하는 백테스트 엔진.

    매개변수:
        strategy_config: {
            "name": 전략 이름,
            "bull_action": "buy",           # 상승장 행동
            "sideways_action": "buy" | "half" | "strict" | "cash",
            "bear_action": "cash",          # 하락장 행동
            "sideways_vol_threshold": 2.0,  # strict 모드일 때 거래량 기준
            "stop_loss": None | -0.05,      # 손절선 (None이면 없음)
        }
    """

    def __init__(self, strategy_config: dict, all_data: dict, btc_data,
                 initial_capital=1_000_000, rebalance_days=3,
                 fee_rate=0.0005, slippage=0.001, top_n=5):
        self.config = strategy_config
        self.all_data = all_data
        self.btc_data = btc_data
        self.initial_capital = initial_capital
        self.rebalance_days = rebalance_days
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.top_n = top_n

    def _get_common_dates(self):
        from collections import Counter
        date_counter = Counter()
        for df in self.all_data.values():
            for dt in df.index:
                date_counter[dt] += 1
        threshold = len(self.all_data) * 0.5
        common_dates = [dt for dt, cnt in date_counter.items() if cnt >= threshold]
        return pd.DatetimeIndex(sorted(common_dates))

    def run(self) -> ScreenerBacktestResult:
        all_dates = self._get_common_dates()
        warmup = 60

        if len(all_dates) <= warmup:
            return ScreenerBacktestResult(self.config["name"], [], [], [], self.initial_capital)

        cash = self.initial_capital
        holdings = {}  # {ticker: {"qty", "buy_price"}}
        equity_curve = []
        dates_list = []
        trades = []
        days_since_rebalance = self.rebalance_days

        for i in range(warmup, len(all_dates)):
            current_date = all_dates[i]
            days_since_rebalance += 1

            # 손절 체크
            stop_loss = self.config.get("stop_loss")
            if stop_loss and holdings:
                stopped = []
                for ticker, info in list(holdings.items()):
                    if ticker not in self.all_data:
                        continue
                    df = self.all_data[ticker]
                    if current_date not in df.index:
                        continue
                    cur_price = df.loc[current_date, "close"]
                    pnl_rate = cur_price / info["buy_price"] - 1
                    if pnl_rate <= stop_loss:
                        sell_amount = info["qty"] * cur_price * (1 - self.fee_rate - self.slippage)
                        profit = sell_amount - (info["qty"] * info["buy_price"])
                        trades.append({
                            "date": str(current_date.date()), "type": "sell",
                            "ticker": ticker, "price": cur_price,
                            "amount": sell_amount, "profit": profit,
                            "signal": "stop_loss",
                        })
                        cash += sell_amount
                        stopped.append(ticker)
                for t in stopped:
                    del holdings[t]

            # 리밸런싱 시점
            if days_since_rebalance >= self.rebalance_days:
                days_since_rebalance = 0
                regime = _detect_regime_at(self.btc_data, current_date)
                available = _get_available_data(self.all_data, current_date)

                # 국면별 행동 결정
                action = self.config.get(f"{regime}_action", "buy")

                # 기존 보유 매도
                if action == "cash" or action in ("buy", "half", "strict"):
                    for ticker, info in holdings.items():
                        if ticker not in self.all_data:
                            continue
                        df = self.all_data[ticker]
                        if current_date not in df.index:
                            continue
                        sell_price = df.loc[current_date, "close"]
                        sell_amount = info["qty"] * sell_price * (1 - self.fee_rate - self.slippage)
                        profit = sell_amount - (info["qty"] * info["buy_price"])
                        trades.append({
                            "date": str(current_date.date()), "type": "sell",
                            "ticker": ticker, "price": sell_price,
                            "amount": sell_amount, "profit": profit,
                        })
                        cash += sell_amount
                    holdings = {}

                if action == "cash":
                    # 현금 보유, 매수 안 함
                    pass

                elif action == "buy":
                    # 일반 매수 (거래량 돌파 우선, fallback 모멘텀)
                    scores = _volume_breakout_scores(available)
                    if not scores:
                        scores = _momentum_scores(available)
                    selected = scores[:self.top_n]
                    cash = self._buy_coins(selected, cash, current_date, holdings, trades, invest_ratio=1.0)

                elif action == "half":
                    # 50% 투자, 50% 현금
                    scores = _volume_breakout_scores(available)
                    if not scores:
                        scores = _momentum_scores(available)
                    selected = scores[:self.top_n]
                    cash = self._buy_coins(selected, cash, current_date, holdings, trades, invest_ratio=0.5)

                elif action == "strict":
                    # 엄격한 거래량 기준 (vol_ratio 2.0)
                    threshold = self.config.get("sideways_vol_threshold", 2.0)
                    scores = _volume_breakout_scores(available, vol_ratio_threshold=threshold)
                    if scores:
                        selected = scores[:self.top_n]
                        cash = self._buy_coins(selected, cash, current_date, holdings, trades, invest_ratio=1.0)
                    # 신호 없으면 현금 유지

            # 포트폴리오 평가
            portfolio_value = cash
            for ticker, info in holdings.items():
                if ticker not in self.all_data:
                    continue
                df = self.all_data[ticker]
                if current_date in df.index:
                    portfolio_value += info["qty"] * df.loc[current_date, "close"]

            equity_curve.append(portfolio_value)
            dates_list.append(current_date)

        # 기간 종료 청산
        if holdings and len(all_dates) > 0:
            last_date = all_dates[-1]
            for ticker, info in holdings.items():
                if ticker not in self.all_data:
                    continue
                df = self.all_data[ticker]
                if last_date in df.index:
                    sell_price = df.loc[last_date, "close"]
                    sell_amount = info["qty"] * sell_price * (1 - self.fee_rate - self.slippage)
                    trades.append({
                        "date": str(last_date.date()), "type": "sell",
                        "ticker": ticker, "price": sell_price,
                        "amount": sell_amount,
                        "profit": sell_amount - (info["qty"] * info["buy_price"]),
                    })

        return ScreenerBacktestResult(
            self.config["name"], equity_curve, dates_list, trades, self.initial_capital
        )

    def _buy_coins(self, selected, cash, current_date, holdings, trades, invest_ratio=1.0):
        """선별된 코인에 균등 분배 매수. invest_ratio로 투자 비중 조절."""
        if not selected:
            return cash
        invest_cash = cash * invest_ratio
        per_coin = invest_cash / len(selected)

        for ticker, score in selected:
            if ticker not in self.all_data:
                continue
            df = self.all_data[ticker]
            if current_date not in df.index:
                continue
            buy_price = df.loc[current_date, "close"]
            effective = per_coin * (1 - self.fee_rate - self.slippage)
            qty = effective / buy_price
            holdings[ticker] = {"qty": qty, "buy_price": buy_price}
            trades.append({
                "date": str(current_date.date()), "type": "buy",
                "ticker": ticker, "price": buy_price,
                "amount": per_coin, "score": score,
            })
            cash -= per_coin

        return max(cash, 0)


# ═══════════════════════════════════════════════
# 국면별 성과 분리
# ═══════════════════════════════════════════════

def split_by_regime(result, regimes):
    if not result.dates or not result.equity_curve:
        return {}

    equity_df = pd.DataFrame({"date": result.dates, "equity": result.equity_curve})
    equity_df["date"] = pd.to_datetime(equity_df["date"])
    equity_df = equity_df.set_index("date")
    equity_df["return"] = equity_df["equity"].pct_change()

    output = {"overall": result.summary()}

    for regime_name in ["bull", "sideways", "bear"]:
        regime_dates = regimes[regimes == regime_name].index
        mask = equity_df.index.isin(regime_dates)
        regime_returns = equity_df.loc[mask, "return"].dropna()

        if len(regime_returns) < 5:
            output[regime_name] = {"days": 0, "cumulative_return": 0, "mdd": 0, "sharpe": 0}
            continue

        cum_return = (1 + regime_returns).prod() - 1
        regime_equity = equity_df.loc[mask, "equity"]
        peak = regime_equity.cummax()
        dd = (regime_equity - peak) / peak
        mdd = float(dd.min()) * 100

        daily_rf = 0.035 / 365
        excess = regime_returns - daily_rf
        sharpe = float(excess.mean() / excess.std() * (365 ** 0.5)) if excess.std() > 0 else 0

        output[regime_name] = {
            "days": len(regime_returns),
            "cumulative_return": round(cum_return * 100, 2),
            "mdd": round(mdd, 2),
            "sharpe": round(sharpe, 2),
        }

    return output


# ═══════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════

def run_comparison():
    print("=" * 70)
    print("  횡보장 개선 전략 4종 + 기준선 비교 백테스트")
    print("=" * 70)

    # 1. 데이터 수집
    print("\n[1/4] 데이터 수집 중...")
    collector = DataCollector()
    all_data = collector.collect_all(days=830)
    filtered = {k: v for k, v in all_data.items() if k in TARGET_COINS}
    print(f"  대상 코인: {len(filtered)}개")

    btc_data = filtered.get("KRW-BTC")
    if btc_data is None or len(filtered) < 5:
        print("데이터 부족")
        return

    # 2. 국면 분류
    print("\n[2/4] BTC 국면 분류 중...")
    regimes = classify_indicator(btc_data)
    counts = regimes.value_counts()
    total = len(regimes)
    print(f"  전체: {total}일")
    for r in ["bull", "sideways", "bear"]:
        n = counts.get(r, 0)
        print(f"  {r:>8s}: {n}일 ({n/total:.1%})")

    # 3. 전략 정의
    strategies = [
        {
            "name": "0. 기준선 (현재방식)",
            "bull_action": "buy",
            "sideways_action": "buy",
            "bear_action": "cash",
            "stop_loss": None,
        },
        {
            "name": "1. 횡보 50% 투자",
            "bull_action": "buy",
            "sideways_action": "half",
            "bear_action": "cash",
            "stop_loss": None,
        },
        {
            "name": "2. 횡보 엄격기준(2.0)",
            "bull_action": "buy",
            "sideways_action": "strict",
            "bear_action": "cash",
            "sideways_vol_threshold": 2.0,
            "stop_loss": None,
        },
        {
            "name": "3. 횡보 매수금지",
            "bull_action": "buy",
            "sideways_action": "cash",
            "bear_action": "cash",
            "stop_loss": None,
        },
        {
            "name": "4. 횡보 손절-5%",
            "bull_action": "buy",
            "sideways_action": "buy",
            "bear_action": "cash",
            "stop_loss": -0.05,
        },
    ]

    # 4. 백테스팅
    print("\n[3/4] 백테스팅 실행 중...")
    results = []
    for config in strategies:
        engine = RegimeAwareEngine(
            strategy_config=config,
            all_data=filtered,
            btc_data=btc_data,
            initial_capital=1_000_000,
            rebalance_days=3,
            top_n=5,
        )
        result = engine.run()
        metrics = split_by_regime(result, regimes)
        results.append((result, metrics, config))
        print(f"  [완료] {config['name']}")

    # 5. 결과 출력
    print("\n[4/4] 결과 비교")
    print("=" * 70)

    # 전체
    print(f"\n{'[전체 기간]':<28s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'거래':>6s}")
    print("-" * 70)
    for result, metrics, _ in results:
        s = metrics["overall"]
        print(
            f"  {result.strategy_name:<26s} | "
            f"{s['total_return']:>+7.1f}% | "
            f"{s['mdd']:>7.1f}% | "
            f"{s['sharpe_ratio']:>6.2f} | "
            f"{s['total_trades']:>5d}"
        )

    # 상승장
    print(f"\n{'[상승장 Bull]':<28s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'일수':>6s}")
    print("-" * 70)
    for result, metrics, _ in results:
        s = metrics.get("bull", {})
        if s.get("days", 0) > 0:
            print(
                f"  {result.strategy_name:<26s} | "
                f"{s['cumulative_return']:>+7.1f}% | "
                f"{s['mdd']:>7.1f}% | "
                f"{s['sharpe']:>6.2f} | "
                f"{s['days']:>5d}"
            )

    # 횡보장
    print(f"\n{'[횡보장 Sideways]':<28s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'일수':>6s}")
    print("-" * 70)
    for result, metrics, _ in results:
        s = metrics.get("sideways", {})
        if s.get("days", 0) > 0:
            print(
                f"  {result.strategy_name:<26s} | "
                f"{s['cumulative_return']:>+7.1f}% | "
                f"{s['mdd']:>7.1f}% | "
                f"{s['sharpe']:>6.2f} | "
                f"{s['days']:>5d}"
            )

    # 하락장
    print(f"\n{'[하락장 Bear]':<28s} | {'수익률':>8s} | {'MDD':>8s} | {'샤프':>6s} | {'일수':>6s}")
    print("-" * 70)
    for result, metrics, _ in results:
        s = metrics.get("bear", {})
        if s.get("days", 0) > 0:
            print(
                f"  {result.strategy_name:<26s} | "
                f"{s['cumulative_return']:>+7.1f}% | "
                f"{s['mdd']:>7.1f}% | "
                f"{s['sharpe']:>6.2f} | "
                f"{s['days']:>5d}"
            )

    print("\n" + "=" * 70)
    print("완료!")
    return results


if __name__ == "__main__":
    run_comparison()
