"""
backtest/reliable_backtest.py - 신뢰도 강화 통합 백테스트

기존 백테스트의 5가지 한계를 모두 해결합니다:
  1. OHLCV 전체 사용 (close만이 아닌 open/high/low/close)
  2. 1,500일 확장 (2022 하락장 포함)
  3. 슬리피지 반영 (수수료 + 시장가 슬리피지)
  4. 실거래 구조 반영 단일 시뮬레이터 (포트폴리오 vs 개별진입 통합)
  5. 복리 수익률 계산

실행: python -m backtest.reliable_backtest
"""

import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO")

from backtest.data_collector import collect_ohlcv_full


# ═══════════════════════════════════════════════
# 정밀 지표 계산 (OHLC 기반) — 한계 2 해결
# ═══════════════════════════════════════════════

def calc_true_range(high, low, close):
    """True Range: max(H-L, |H-prevC|, |L-prevC|)"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

def calc_atr_precise(high, low, close, period=14):
    """정밀 ATR (True Range 기반)"""
    tr = calc_true_range(high, low, close)
    return tr.rolling(period).mean()

def calc_adx_precise(high, low, close, period=14):
    """정밀 ADX (high/low 사용)"""
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    atr = calc_atr_precise(high, low, close, period)
    atr_safe = atr.replace(0, np.nan)

    plus_di = 100 * plus_dm.rolling(period).mean() / atr_safe
    minus_di = 100 * minus_dm.rolling(period).mean() / atr_safe

    di_sum = plus_di + minus_di
    di_sum = di_sum.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = dx.rolling(period).mean()

    return adx, plus_di, minus_di

def calc_choppiness_precise(high, low, close, period=14):
    """정밀 Choppiness Index (True Range 기반)"""
    tr = calc_true_range(high, low, close)
    atr_sum = tr.rolling(period).sum()
    high_range = high.rolling(period).max()
    low_range = low.rolling(period).min()
    hl_range = (high_range - low_range).replace(0, np.nan)
    ci = 100 * np.log10(atr_sum / hl_range) / np.log10(period)
    return ci

def calc_bb(close, period=20, std_dev=2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    width = (upper - lower) / mid.replace(0, np.nan) * 100
    return mid, upper, lower, width

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ═══════════════════════════════════════════════
# 정밀 국면 분류 — 한계 2 해결
# ═══════════════════════════════════════════════

def regime_sma_momentum(btc_close, sma_period=50, mom_period=20):
    """현행: SMA50 + 20일 모멘텀"""
    sma = btc_close.rolling(sma_period).mean()
    regime = pd.Series("sideways", index=btc_close.index)
    for i in range(max(sma_period, mom_period), len(btc_close)):
        price = btc_close.iloc[i]
        mom = price / btc_close.iloc[i - mom_period] - 1
        if price > sma.iloc[i] and mom > 0.10:
            regime.iloc[i] = "bull"
        elif price < sma.iloc[i] and mom < -0.10:
            regime.iloc[i] = "bear"
    return regime

def regime_adx_precise(btc_high, btc_low, btc_close, period=14):
    """정밀 ADX 기반 국면 분류 (OHLC 사용)"""
    adx, plus_di, minus_di = calc_adx_precise(btc_high, btc_low, btc_close, period)
    regime = pd.Series("sideways", index=btc_close.index)
    for i in range(period * 3, len(btc_close)):
        a = adx.iloc[i]
        if pd.isna(a):
            continue
        if a > 25:
            regime.iloc[i] = "bull" if plus_di.iloc[i] > minus_di.iloc[i] else "bear"
        else:
            regime.iloc[i] = "sideways"
    return regime

def regime_adx_atr_4class_precise(btc_high, btc_low, btc_close, adx_period=14, atr_period=14):
    """정밀 ADX+ATR 4분류 (OHLC 사용)"""
    adx, plus_di, minus_di = calc_adx_precise(btc_high, btc_low, btc_close, adx_period)
    atr = calc_atr_precise(btc_high, btc_low, btc_close, atr_period)
    atr_avg = atr.rolling(42).mean()
    _, _, _, bb_width = calc_bb(btc_close)
    bb_width_avg = bb_width.rolling(42).mean()

    regime = pd.Series("ranging", index=btc_close.index)
    for i in range(60, len(btc_close)):
        a = adx.iloc[i]
        atr_r = atr.iloc[i] / atr_avg.iloc[i] if pd.notna(atr_avg.iloc[i]) and atr_avg.iloc[i] > 0 else 1
        bw = bb_width.iloc[i]
        bw_avg = bb_width_avg.iloc[i]

        if pd.isna(a) or pd.isna(bw) or pd.isna(bw_avg):
            continue

        if a > 20 and atr_r > 0.8:
            regime.iloc[i] = "trending"
        elif a < 25 and bw < bw_avg * 0.8 and atr_r < 0.9:
            regime.iloc[i] = "quiet"
        elif bw > bw_avg * 1.5 or atr_r > 1.2:
            regime.iloc[i] = "volatile"
        else:
            regime.iloc[i] = "ranging"
    return regime


# ═══════════════════════════════════════════════
# 통합 시뮬레이터 — 한계 3, 4, 5 해결
# ═══════════════════════════════════════════════

class RealisticSimulator:
    """
    실거래 구조를 반영한 통합 백테스트 시뮬레이터.

    특징:
      - 슬리피지 반영 (수수료 + 시장가 슬리피지)
      - 복리 수익률 (자본금 기반)
      - 포트폴리오/개별진입 모두 지원
      - 국면별 분리 성과 자동 기록
    """

    def __init__(self, initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0005):
        """
        매개변수:
            initial_capital: 초기 자본금 (원, 기본 1000만원)
            fee_rate: 편도 수수료 (기본 0.05%)
            slippage: 편도 슬리피지 (기본 0.05%)
        """
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.cost_per_trade = fee_rate + slippage  # 편도 총 비용

    def run_portfolio_strategy(self, prices, volumes, regimes, strategy_fn,
                                strategy_name, rebalance_days=3, top_k=5,
                                target_regimes=None):
        """
        포트폴리오 리밸런싱 방식 시뮬레이션 (거래량돌파 등).

        매개변수:
            prices: 종가 DataFrame
            volumes: 거래대금 DataFrame
            regimes: 국면 Series
            strategy_fn: (prices, volumes, date, top_k) -> {coin: weight} 반환 함수
            strategy_name: 전략 이름
            rebalance_days: 리밸런싱 주기
            top_k: 선택 코인 수
            target_regimes: 활성 국면 리스트 (None이면 전 국면)
        """
        cash = self.initial_capital
        holdings = {}  # {coin: {"qty": float, "buy_price": float}}
        equity_log = []
        trade_log = []
        days_since = rebalance_days  # 첫날 바로 리밸런싱

        dates = prices.index[60:]  # 워밍업 60일

        for date in dates:
            days_since += 1
            current_regime = regimes.loc[date] if date in regimes.index else "sideways"

            # 국면 필터: 대상 국면이 아니면 전량 매도 후 현금
            if target_regimes and current_regime not in target_regimes:
                if holdings:
                    for coin, info in list(holdings.items()):
                        if coin in prices.columns and date in prices.index:
                            sell_price = prices.loc[date, coin]
                            if pd.notna(sell_price) and sell_price > 0:
                                proceeds = info["qty"] * sell_price * (1 - self.cost_per_trade)
                                pnl_pct = (sell_price / info["buy_price"] - 1) * 100
                                trade_log.append({
                                    "date": date, "coin": coin, "side": "sell",
                                    "price": sell_price, "amount": proceeds,
                                    "pnl_pct": pnl_pct, "regime": current_regime,
                                    "reason": "regime_exit",
                                })
                                cash += proceeds
                    holdings = {}
                equity_log.append({"date": date, "equity": cash, "regime": current_regime})
                continue

            # 리밸런싱
            if days_since >= rebalance_days:
                days_since = 0

                # 기존 보유 매도
                for coin, info in list(holdings.items()):
                    if coin in prices.columns and date in prices.index:
                        sell_price = prices.loc[date, coin]
                        if pd.notna(sell_price) and sell_price > 0:
                            proceeds = info["qty"] * sell_price * (1 - self.cost_per_trade)
                            pnl_pct = (sell_price / info["buy_price"] - 1) * 100
                            trade_log.append({
                                "date": date, "coin": coin, "side": "sell",
                                "price": sell_price, "amount": proceeds,
                                "pnl_pct": pnl_pct, "regime": current_regime,
                                "reason": "rebalance",
                            })
                            cash += proceeds
                holdings = {}

                # 새 비중 계산
                target_weights = strategy_fn(prices, volumes, date, top_k)
                if target_weights:
                    per_coin = cash * 0.95 / len(target_weights)  # 95% 투입
                    for coin, weight in target_weights.items():
                        if coin in prices.columns and date in prices.index:
                            buy_price = prices.loc[date, coin]
                            if pd.notna(buy_price) and buy_price > 0:
                                invest = per_coin * (1 - self.cost_per_trade)
                                qty = invest / buy_price
                                holdings[coin] = {"qty": qty, "buy_price": buy_price}
                                trade_log.append({
                                    "date": date, "coin": coin, "side": "buy",
                                    "price": buy_price, "amount": per_coin,
                                    "pnl_pct": 0, "regime": current_regime,
                                    "reason": "rebalance",
                                })
                                cash -= per_coin

            # 포트폴리오 평가
            portfolio_value = cash
            for coin, info in holdings.items():
                if coin in prices.columns and date in prices.index:
                    p = prices.loc[date, coin]
                    if pd.notna(p):
                        portfolio_value += info["qty"] * p

            equity_log.append({"date": date, "equity": portfolio_value, "regime": current_regime})

        # 종료 청산
        if holdings:
            last_date = dates[-1]
            for coin, info in holdings.items():
                if coin in prices.columns:
                    p = prices.loc[last_date, coin]
                    if pd.notna(p) and p > 0:
                        proceeds = info["qty"] * p * (1 - self.cost_per_trade)
                        trade_log.append({
                            "date": last_date, "coin": coin, "side": "sell",
                            "price": p, "amount": proceeds,
                            "pnl_pct": (p / info["buy_price"] - 1) * 100,
                            "regime": "end", "reason": "end",
                        })

        return self._compile_results(strategy_name, equity_log, trade_log)

    def run_signal_strategy(self, prices, highs, lows, regimes,
                             strategy_name, signal_fn, target_regimes=None,
                             max_positions=5):
        """
        개별 진입/청산 방식 시뮬레이션 (BB+RSI 등).

        매개변수:
            signal_fn: (coin, close, high, low, date_idx, positions) ->
                       ("buy"/"sell"/None, {info}) 반환 함수
            target_regimes: 활성 국면 리스트
            max_positions: 동시 보유 최대 수
        """
        cash = self.initial_capital
        positions = {}  # {coin: {"qty", "buy_price", "entry_date"}}
        equity_log = []
        trade_log = []

        dates = prices.index[60:]

        for date in dates:
            current_regime = regimes.loc[date] if date in regimes.index else "sideways"

            # 국면 필터
            if target_regimes and current_regime not in target_regimes:
                # 보유 포지션 청산
                for coin in list(positions.keys()):
                    if coin in prices.columns:
                        p = prices.loc[date, coin]
                        if pd.notna(p) and p > 0:
                            info = positions[coin]
                            proceeds = info["qty"] * p * (1 - self.cost_per_trade)
                            pnl = (p / info["buy_price"] - 1) * 100
                            trade_log.append({
                                "date": date, "coin": coin, "side": "sell",
                                "price": p, "amount": proceeds, "pnl_pct": pnl,
                                "regime": current_regime, "reason": "regime_exit",
                            })
                            cash += proceeds
                            del positions[coin]
                equity_log.append({"date": date, "equity": cash, "regime": current_regime})
                continue

            # 각 코인 신호 확인
            for coin in prices.columns:
                if coin not in prices.columns:
                    continue
                close = prices[coin]
                high = highs[coin] if coin in highs.columns else close
                low = lows[coin] if coin in lows.columns else close

                date_idx = prices.index.get_loc(date)
                if date_idx < 60:
                    continue

                signal, info = signal_fn(coin, close, high, low, date_idx, positions)

                if signal == "buy" and coin not in positions and len(positions) < max_positions:
                    buy_price = close.iloc[date_idx]
                    if pd.isna(buy_price) or buy_price <= 0:
                        continue
                    invest = min(cash * 0.95 / max(1, max_positions - len(positions)),
                                 cash * 0.3)  # 코인당 최대 30%
                    if invest < 5000:
                        continue
                    effective = invest * (1 - self.cost_per_trade)
                    qty = effective / buy_price
                    positions[coin] = {"qty": qty, "buy_price": buy_price, "entry_date": date}
                    cash -= invest
                    trade_log.append({
                        "date": date, "coin": coin, "side": "buy",
                        "price": buy_price, "amount": invest, "pnl_pct": 0,
                        "regime": current_regime, "reason": info.get("reason", "signal"),
                    })

                elif signal == "sell" and coin in positions:
                    sell_price = close.iloc[date_idx]
                    if pd.isna(sell_price) or sell_price <= 0:
                        continue
                    pos = positions[coin]
                    proceeds = pos["qty"] * sell_price * (1 - self.cost_per_trade)
                    pnl = (sell_price / pos["buy_price"] - 1) * 100
                    trade_log.append({
                        "date": date, "coin": coin, "side": "sell",
                        "price": sell_price, "amount": proceeds, "pnl_pct": pnl,
                        "regime": current_regime, "reason": info.get("reason", "signal"),
                    })
                    cash += proceeds
                    del positions[coin]

            # 평가
            portfolio_value = cash
            for coin, pos in positions.items():
                if coin in prices.columns and date in prices.index:
                    p = prices.loc[date, coin]
                    if pd.notna(p):
                        portfolio_value += pos["qty"] * p
            equity_log.append({"date": date, "equity": portfolio_value, "regime": current_regime})

        return self._compile_results(strategy_name, equity_log, trade_log)

    def _compile_results(self, name, equity_log, trade_log):
        """결과를 정리하여 반환"""
        eq_df = pd.DataFrame(equity_log)
        if eq_df.empty:
            return {"name": name, "error": "데이터 없음"}

        eq_df["date"] = pd.to_datetime(eq_df["date"])
        eq_df = eq_df.set_index("date")

        equity = eq_df["equity"]
        total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
        days = (equity.index[-1] - equity.index[0]).days
        cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (365 / max(days, 1)) - 1) * 100
        daily_ret = equity.pct_change().dropna()
        vol = daily_ret.std() * np.sqrt(365) * 100
        sharpe = (cagr / vol) if vol > 0 else 0
        peak = equity.cummax()
        mdd = ((equity - peak) / peak).min() * 100
        calmar = cagr / abs(mdd) if mdd != 0 else 0
        win_rate = (daily_ret > 0).mean() * 100

        # 거래 분석
        trades_df = pd.DataFrame(trade_log)
        sell_trades = trades_df[trades_df["side"] == "sell"] if not trades_df.empty else pd.DataFrame()
        n_trades = len(sell_trades)
        trade_win_rate = (sell_trades["pnl_pct"] > 0).mean() * 100 if n_trades > 0 else 0
        avg_trade_pnl = sell_trades["pnl_pct"].mean() if n_trades > 0 else 0

        # 국면별 분리
        regime_perf = {}
        for regime_name in eq_df["regime"].unique():
            mask = eq_df["regime"] == regime_name
            r_eq = eq_df.loc[mask, "equity"]
            if len(r_eq) < 5:
                continue
            r_ret = r_eq.pct_change().dropna()
            r_cum = (1 + r_ret).prod() - 1
            r_ann = ((1 + r_ret.mean()) ** 365 - 1) if len(r_ret) > 0 else 0
            r_trades = sell_trades[sell_trades["regime"] == regime_name] if not sell_trades.empty else pd.DataFrame()

            regime_perf[regime_name] = {
                "일수": int(mask.sum()),
                "누적수익": round(r_cum * 100, 2),
                "연환산": round(r_ann * 100, 2),
                "거래수": len(r_trades),
                "거래승률": round((r_trades["pnl_pct"] > 0).mean() * 100, 1) if len(r_trades) > 0 else 0,
                "평균거래수익": round(r_trades["pnl_pct"].mean(), 2) if len(r_trades) > 0 else 0,
            }

        return {
            "name": name,
            "총수익률": round(total_return, 2),
            "CAGR": round(cagr, 2),
            "변동성": round(vol, 2),
            "샤프": round(sharpe, 2),
            "MDD": round(mdd, 2),
            "칼마": round(calmar, 2),
            "일별승률": round(win_rate, 1),
            "총거래수": n_trades,
            "거래승률": round(trade_win_rate, 1),
            "평균거래수익": round(avg_trade_pnl, 2),
            "초기자본": self.initial_capital,
            "최종자본": round(equity.iloc[-1]),
            "기간": f"{equity.index[0].date()} ~ {equity.index[-1].date()}",
            "국면별": regime_perf,
            "equity": equity,
            "trades": trades_df,
        }


# ═══════════════════════════════════════════════
# 전략 함수들
# ═══════════════════════════════════════════════

def volume_breakout_weights(prices, volumes, date, top_k, lookback=4, vol_ratio=1.26):
    """거래량돌파 비중 계산"""
    scores = {}
    for coin in prices.columns:
        close = prices[coin].loc[:date].dropna()
        vol = volumes[coin].loc[:date].dropna() if coin in volumes.columns else None
        if vol is None or len(close) < 25 or len(vol) < 25:
            continue
        recent_vol = vol.tail(lookback).mean()
        avg_vol = vol.tail(20).mean()
        if avg_vol <= 0:
            continue
        ratio = recent_vol / avg_vol
        mom = close.iloc[-1] / close.iloc[-lookback] - 1
        if ratio >= vol_ratio and mom > 0:
            scores[coin] = ratio * (1 + mom)

    if not scores:
        # 폴백: 모멘텀 상위
        for coin in prices.columns:
            close = prices[coin].loc[:date].dropna()
            if len(close) < lookback + 5:
                continue
            mom = close.iloc[-1] / close.iloc[-lookback] - 1
            if mom > 0:
                scores[coin] = mom

    if not scores:
        return {}
    sorted_coins = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    weight = 1.0 / len(sorted_coins)
    return {c: weight for c, _ in sorted_coins}


def bb_rsi_signal_fn(coin, close, high, low, date_idx, positions,
                      bb_period=20, bb_std=2.0, rsi_period=14,
                      rsi_oversold=30, rsi_overbought=70):
    """BB+RSI 매수/매도 신호"""
    if date_idx < max(bb_period, rsi_period) + 5:
        return None, {}

    series = close.iloc[:date_idx + 1]
    price = series.iloc[-1]

    bb_mid, bb_upper, bb_lower, _ = calc_bb(series, bb_period, bb_std)
    rsi = calc_rsi(series, rsi_period)

    cur_rsi = rsi.iloc[-1]
    cur_bb_lower = bb_lower.iloc[-1]
    cur_bb_upper = bb_upper.iloc[-1]
    cur_bb_mid = bb_mid.iloc[-1]

    if pd.isna(cur_rsi) or pd.isna(cur_bb_lower):
        return None, {}

    # 보유 중 → 매도 조건
    if coin in positions:
        entry_price = positions[coin]["buy_price"]
        pnl = price / entry_price - 1

        if price >= cur_bb_upper and cur_rsi > rsi_overbought:
            return "sell", {"reason": "bb_upper_rsi"}
        if price >= cur_bb_mid and pnl > 0.01:
            return "sell", {"reason": "bb_mid_profit"}
        if pnl <= -0.03:
            return "sell", {"reason": "stop_loss"}
        if pnl >= 0.05:
            return "sell", {"reason": "take_profit"}
        return None, {}

    # 미보유 → 매수 조건
    if price <= cur_bb_lower and cur_rsi < rsi_oversold:
        return "buy", {"reason": "bb_rsi_oversold"}

    return None, {}


# ═══════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════

def main():
    logger.info("=" * 70)
    logger.info("  신뢰도 강화 통합 백테스트")
    logger.info("=" * 70)
    logger.info("  해결 한계: OHLCV 전체 | 1500일 확장 | 슬리피지 | 통합 시뮬레이터 | 복리")

    # ─── 1. OHLCV 전체 데이터 수집 (1500일) ───
    logger.info("\n[1/6] OHLCV 전체 데이터 수집 (1500일)...")
    data = collect_ohlcv_full(days=1500, force=False)
    prices = data["prices"]
    highs = data["highs"]
    lows = data["lows"]
    volumes = data["volumes"]

    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()} ({len(prices)}일)")
    logger.info(f"  코인: {len(prices.columns)}개")
    logger.info(f"  컬럼: prices(close), highs, lows, volumes(value) — OHLCV 완전")

    # BTC 시장 요약
    btc = prices["KRW-BTC"].dropna()
    logger.info(f"\n  BTC 요약: {btc.iloc[0]:,.0f}원 → {btc.iloc[-1]:,.0f}원 ({(btc.iloc[-1]/btc.iloc[0]-1)*100:+.1f}%)")
    logger.info(f"  최고가: {btc.max():,.0f}원 ({btc.idxmax().date()}) | 최저가: {btc.min():,.0f}원 ({btc.idxmin().date()})")

    # ─── 2. 정밀 국면 분류 (OHLC 기반) ───
    logger.info("\n[2/6] 정밀 국면 분류 (OHLC 기반 ADX)...")

    btc_h = highs["KRW-BTC"].dropna()
    btc_l = lows["KRW-BTC"].dropna()
    btc_c = prices["KRW-BTC"].dropna()

    # 공통 인덱스
    common_idx = btc_h.index.intersection(btc_l.index).intersection(btc_c.index)
    btc_h, btc_l, btc_c = btc_h.loc[common_idx], btc_l.loc[common_idx], btc_c.loc[common_idx]

    regime_sma = regime_sma_momentum(btc_c)
    regime_adx = regime_adx_precise(btc_h, btc_l, btc_c)
    regime_4class = regime_adx_atr_4class_precise(btc_h, btc_l, btc_c)

    for name, reg in [("SMA50+모멘텀 (현행)", regime_sma),
                       ("ADX 정밀 (OHLC)", regime_adx),
                       ("ADX+ATR 4분류 정밀", regime_4class)]:
        counts = reg.value_counts()
        total = len(reg)
        parts = " | ".join(f"{r}: {counts.get(r,0)}일({counts.get(r,0)/total*100:.1f}%)" for r in sorted(counts.index))
        logger.info(f"  [{name}] {parts}")

    # ─── 3. 전환 비용 (정밀) ───
    logger.info("\n[3/6] 전환 비용 분석 (정밀)...")
    for name, reg in [("SMA50+모멘텀", regime_sma), ("ADX 정밀", regime_adx)]:
        switches = sum(1 for i in range(1, len(reg)) if reg.iloc[i] != reg.iloc[i-1])
        days_total = len(reg)
        annual = switches / days_total * 365
        cost = switches * 0.10  # 수수료 + 슬리피지
        logger.info(f"  [{name}] 전환: {switches}회(연{annual:.0f}회) | 비용: {cost:.1f}%(연{cost/days_total*365:.1f}%) | 평균유지: {days_total/max(switches,1):.1f}일")

    # Choppiness Index 정확도 (정밀)
    logger.info("\n  [Choppiness Index 정밀 (OHLC)]")
    ci = calc_choppiness_precise(btc_h, btc_l, btc_c)
    for zone_name, cond in [("CI>61.8(횡보)", ci > 61.8), ("CI<38.2(추세)", ci < 38.2), ("38~62(중간)", (ci >= 38.2) & (ci <= 61.8))]:
        zone_dates = ci[cond].index
        if len(zone_dates) == 0:
            logger.info(f"    {zone_name}: 0일")
            continue
        actual = regime_sma.reindex(zone_dates).dropna()
        if len(actual) == 0:
            continue
        counts = actual.value_counts()
        parts = ", ".join(f"{r}:{counts.get(r,0)}" for r in sorted(counts.index))
        logger.info(f"    {zone_name}: {len(zone_dates)}일 → {parts}")

    # ─── 4. 전략 백테스트 (슬리피지 + 복리) ───
    logger.info("\n[4/6] 전략 백테스트 (슬리피지 0.05% + 수수료 0.05% = 편도 0.10%)...")
    sim = RealisticSimulator(initial_capital=10_000_000, fee_rate=0.0005, slippage=0.0005)

    results = []

    # 4-1. 거래량돌파 — 전 국면
    logger.info("\n  [거래량돌파 — 전 국면]")
    r = sim.run_portfolio_strategy(
        prices, volumes, regime_sma,
        strategy_fn=volume_breakout_weights,
        strategy_name="거래량돌파(전국면)",
        rebalance_days=3, top_k=5,
        target_regimes=None,
    )
    results.append(r)

    # 4-2. 거래량돌파 — 상승+횡보만 (하락장 현금)
    logger.info("  [거래량돌파 — 하락장 현금]")
    r = sim.run_portfolio_strategy(
        prices, volumes, regime_sma,
        strategy_fn=volume_breakout_weights,
        strategy_name="거래량돌파(하락현금/SMA)",
        rebalance_days=3, top_k=5,
        target_regimes=["bull", "sideways"],
    )
    results.append(r)

    # 4-3. 거래량돌파 — ADX 하락장 현금
    logger.info("  [거래량돌파 — ADX 하락장 현금]")
    r = sim.run_portfolio_strategy(
        prices, volumes, regime_adx,
        strategy_fn=volume_breakout_weights,
        strategy_name="거래량돌파(하락현금/ADX)",
        rebalance_days=3, top_k=5,
        target_regimes=["bull", "sideways"],
    )
    results.append(r)

    # 4-4. BB+RSI — 횡보장만 (SMA 기준)
    logger.info("  [BB+RSI — 횡보장만/SMA]")
    r = sim.run_signal_strategy(
        prices, highs, lows, regime_sma,
        strategy_name="BB+RSI(횡보만/SMA)",
        signal_fn=bb_rsi_signal_fn,
        target_regimes=["sideways"],
        max_positions=5,
    )
    results.append(r)

    # 4-5. BB+RSI — 하락장만
    logger.info("  [BB+RSI — 하락장만]")
    r = sim.run_signal_strategy(
        prices, highs, lows, regime_sma,
        strategy_name="BB+RSI(하락장만/SMA)",
        signal_fn=bb_rsi_signal_fn,
        target_regimes=["bear"],
        max_positions=5,
    )
    results.append(r)

    # 4-6. BB+RSI — 전 국면
    logger.info("  [BB+RSI — 전 국면]")
    r = sim.run_signal_strategy(
        prices, highs, lows, regime_sma,
        strategy_name="BB+RSI(전국면)",
        signal_fn=bb_rsi_signal_fn,
        target_regimes=None,
        max_positions=5,
    )
    results.append(r)

    # 4-7. 현금 보유 (벤치마크)
    logger.info("  [현금 보유]")
    results.append({
        "name": "현금보유",
        "총수익률": 0, "CAGR": 0, "변동성": 0, "샤프": 0, "MDD": 0,
        "칼마": 0, "일별승률": 0, "총거래수": 0, "거래승률": 0,
        "평균거래수익": 0, "초기자본": 10_000_000, "최종자본": 10_000_000,
        "기간": f"{prices.index[60].date()} ~ {prices.index[-1].date()}",
        "국면별": {},
    })

    # ─── 5. 결과 출력 ───
    logger.info("\n[5/6] 결과 요약")
    logger.info("=" * 100)
    logger.info(f"{'전략':<28s} | {'총수익':>8s} | {'CAGR':>7s} | {'샤프':>6s} | {'MDD':>8s} | {'칼마':>6s} | {'거래':>5s} | {'거래승률':>7s} | {'최종자본':>14s}")
    logger.info("-" * 100)

    for r in results:
        if "error" in r:
            logger.info(f"  {r['name']:<26s} | 오류: {r['error']}")
            continue
        logger.info(
            f"  {r['name']:<26s} | "
            f"{r['총수익률']:>+7.1f}% | "
            f"{r['CAGR']:>+6.1f}% | "
            f"{r['샤프']:>6.2f} | "
            f"{r['MDD']:>+7.1f}% | "
            f"{r['칼마']:>6.2f} | "
            f"{r['총거래수']:>5d} | "
            f"{r['거래승률']:>6.1f}% | "
            f"{r['최종자본']:>13,d}원"
        )

    # 국면별 상세
    logger.info("\n[6/6] 국면별 상세 성과")
    logger.info("=" * 100)

    for r in results:
        if "error" in r or not r.get("국면별"):
            continue
        logger.info(f"\n  [{r['name']}]")
        for regime, stats in sorted(r["국면별"].items()):
            regime_kr = {"bull": "상승장", "sideways": "횡보장", "bear": "하락장"}.get(regime, regime)
            logger.info(
                f"    {regime_kr:<8s}: {stats['일수']:>4d}일 | "
                f"누적: {stats['누적수익']:>+7.2f}% | "
                f"거래: {stats['거래수']:>4d}회 | "
                f"거래승률: {stats['거래승률']:>5.1f}% | "
                f"평균거래: {stats['평균거래수익']:>+6.2f}%"
            )

    # 최종 요약
    logger.info("\n" + "=" * 70)
    logger.info("  신뢰도 강화 사항 요약")
    logger.info("=" * 70)
    logger.info(f"  데이터: {len(prices)}일 OHLCV 전체 ({prices.index[0].date()} ~ {prices.index[-1].date()})")
    logger.info(f"  지표: ADX/ATR/CI 모두 high/low/close 정밀 계산")
    logger.info(f"  비용: 수수료 0.05% + 슬리피지 0.05% = 편도 0.10%")
    logger.info(f"  수익률: 자본금 1,000만원 기반 복리")
    logger.info(f"  시뮬레이터: 포트폴리오/개별진입 통합, 국면 필터 적용")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
