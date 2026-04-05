"""
backtest/sharpe_optimizer.py - 샤프 비율 극대화 전략 탐색

기존 전략 틀(상승/횡보/하락)에 국한하지 않고,
1,500일 실데이터에서 샤프 비율을 최대화하는 전략을 체계적으로 탐색합니다.

탐색 전략:
  1. 변동성 타겟팅 (Volatility Targeting) — 변동성 높으면 포지션 축소
  2. 듀얼 모멘텀 (절대+상대) — 오를 때만, 가장 많이 오르는 것만
  3. 추세 필터 + 역변동성 비중 — 추세 있을 때만, 안정적인 코인 위주
  4. ATR 트레일링 스탑 — 수익은 끝까지, 손실은 빠르게
  5. 리스크 온/오프 바이너리 — 다중 지표 합산 점수로 투자/현금 결정
  6. 모멘텀 + 변동성 콤보 — 모멘텀 상위 + 변동성 하위 교집합
  7. 적응형 리밸런싱 — 변동성에 따라 리밸런싱 주기 자동 조절
  8. 최적 조합 탐색 — 위 전략들의 요소를 조합

실행: python -m backtest.sharpe_optimizer
"""

import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO")

from backtest.data_collector import collect_ohlcv_full


# ═══════════════════════════════════════════════
# 공통 도구
# ═══════════════════════════════════════════════

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_adx(high, low, close, period=14):
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0)
    tr = calc_atr(high, low, close, period) * period  # ATR * period ≈ TR sum
    atr = calc_atr(high, low, close, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.rolling(period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def evaluate(equity):
    """에쿼티 시리즈에서 핵심 지표 계산"""
    if len(equity) < 30:
        return {"샤프": -99, "총수익": 0, "CAGR": 0, "MDD": 0, "칼마": 0, "승률": 0}
    ret = equity.pct_change().dropna()
    days = (equity.index[-1] - equity.index[0]).days
    total = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (365 / max(days, 1)) - 1) * 100
    vol = ret.std() * np.sqrt(365) * 100
    sharpe = cagr / vol if vol > 0 else 0
    peak = equity.cummax()
    mdd = ((equity - peak) / peak).min() * 100
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    win_rate = (ret > 0).mean() * 100
    return {"샤프": round(sharpe, 3), "총수익": round(total, 1), "CAGR": round(cagr, 1),
            "MDD": round(mdd, 1), "칼마": round(calmar, 2), "승률": round(win_rate, 1),
            "변동성": round(vol, 1)}


class Simulator:
    """간결한 포트폴리오 시뮬레이터"""
    def __init__(self, capital=10_000_000, cost=0.001):
        self.capital = capital
        self.cost = cost  # 편도 수수료+슬리피지

    def run(self, prices, weight_fn, **kwargs):
        """
        weight_fn(prices, date, **kwargs) → {coin: weight} or {} (현금)
        """
        cash = self.capital
        holdings = {}
        equity_list = []
        dates = prices.index[60:]

        rebal_days = kwargs.get("rebal_days", 3)
        days_since = rebal_days

        for date in dates:
            days_since += 1

            if days_since >= rebal_days:
                days_since = 0
                new_weights = weight_fn(prices, date, **kwargs)

                # 기존 매도
                for coin, info in holdings.items():
                    if coin in prices.columns:
                        p = prices.loc[date, coin]
                        if pd.notna(p) and p > 0:
                            cash += info["qty"] * p * (1 - self.cost)
                holdings = {}

                # 매수
                if new_weights:
                    invest = cash * 0.95
                    per_coin = invest / len(new_weights)
                    for coin, w in new_weights.items():
                        if coin in prices.columns:
                            p = prices.loc[date, coin]
                            if pd.notna(p) and p > 0:
                                amt = per_coin * w / sum(new_weights.values()) if sum(new_weights.values()) > 0 else per_coin
                                qty = amt * (1 - self.cost) / p
                                holdings[coin] = {"qty": qty, "buy_price": p}
                                cash -= amt

            # 평가
            val = cash
            for coin, info in holdings.items():
                if coin in prices.columns:
                    p = prices.loc[date, coin]
                    if pd.notna(p):
                        val += info["qty"] * p
            equity_list.append({"date": date, "equity": val})

        eq = pd.DataFrame(equity_list).set_index("date")["equity"]
        return eq


# ═══════════════════════════════════════════════
# 전략 1: 변동성 타겟팅 (Volatility Targeting)
# ═══════════════════════════════════════════════

def strategy_vol_target(prices, date, target_vol=0.15, lookback_mom=14,
                         lookback_vol=20, top_k=5, **kw):
    """
    목표 변동성에 맞춰 포지션 크기를 자동 조절.
    변동성이 높으면 적게 투자, 낮으면 많이 투자.
    """
    available = prices.loc[:date].dropna(axis=1, how="any")
    if len(available) < lookback_vol + 10:
        return {}

    returns = available.pct_change()
    vol = returns.tail(lookback_vol).std() * np.sqrt(365)
    mom = available.iloc[-1] / available.iloc[-lookback_mom] - 1

    # 양의 모멘텀 + 변동성 기반 비중
    scores = {}
    for coin in available.columns:
        m = mom[coin] if coin in mom.index else 0
        v = vol[coin] if coin in vol.index else 1
        if pd.isna(m) or pd.isna(v) or v <= 0 or m <= 0:
            continue
        # 변동성 역수 × 모멘텀 = 안정적이면서 오르는 코인 선호
        vol_scale = min(target_vol / v, 2.0)  # 최대 2배 레버리지 제한
        scores[coin] = m * vol_scale

    if not scores:
        return {}
    sorted_c = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    total = sum(s for _, s in sorted_c)
    if total <= 0:
        return {}
    return {c: s / total for c, s in sorted_c}


# ═══════════════════════════════════════════════
# 전략 2: 듀얼 모멘텀 (절대 + 상대)
# ═══════════════════════════════════════════════

def strategy_dual_momentum(prices, date, abs_lookback=50, rel_lookback=14,
                            top_k=5, **kw):
    """
    절대 모멘텀: N일 수익률 > 0이어야 투자 대상
    상대 모멘텀: 그 중 가장 많이 오른 K개 선택
    """
    available = prices.loc[:date].dropna(axis=1, how="any")
    if len(available) < abs_lookback + 5:
        return {}

    # 절대 모멘텀 필터: 장기(50일) 수익률 > 0
    abs_mom = available.iloc[-1] / available.iloc[-abs_lookback] - 1
    positive_coins = [c for c in available.columns if abs_mom.get(c, -1) > 0]

    if not positive_coins:
        return {}  # 전부 하락 → 현금

    # 상대 모멘텀: 단기(14일) 수익률 상위 K개
    rel_mom = available[positive_coins].iloc[-1] / available[positive_coins].iloc[-rel_lookback] - 1
    top = rel_mom.nlargest(min(top_k, len(rel_mom)))
    top = top[top > 0]

    if top.empty:
        return {}

    weight = 1.0 / len(top)
    return {c: weight for c in top.index}


# ═══════════════════════════════════════════════
# 전략 3: 추세필터 + 역변동성 비중
# ═══════════════════════════════════════════════

def strategy_trend_invvol(prices, date, sma_period=50, vol_lookback=20,
                           top_k=7, **kw):
    """
    추세 필터: SMA 위에 있는 코인만 투자 대상
    비중: 변동성의 역수 (안정적인 코인에 더 투자)
    """
    available = prices.loc[:date].dropna(axis=1, how="any")
    if len(available) < sma_period + 10:
        return {}

    sma = available.tail(sma_period).mean()
    current = available.iloc[-1]
    above_sma = [c for c in available.columns if current[c] > sma[c]]

    if not above_sma:
        return {}

    vol = available[above_sma].pct_change().tail(vol_lookback).std()
    vol = vol[vol > 0].dropna()
    if vol.empty:
        return {}

    inv_vol = 1.0 / vol
    top = inv_vol.nlargest(min(top_k, len(inv_vol)))
    total = top.sum()
    return {c: v / total for c, v in top.items()}


# ═══════════════════════════════════════════════
# 전략 4: ATR 트레일링 스탑 모멘텀
# ═══════════════════════════════════════════════

def strategy_atr_trailing(prices, date, mom_lookback=14, top_k=5, **kw):
    """
    모멘텀 상위 코인 매수 + ATR 기반 트레일링 스탑.
    (시뮬레이터가 리밸런싱 방식이므로, ATR 필터로 위험 코인 제외)
    """
    highs = kw.get("highs")
    lows = kw.get("lows")
    available = prices.loc[:date].dropna(axis=1, how="any")
    if len(available) < 30:
        return {}

    scores = {}
    for coin in available.columns:
        close = available[coin]
        mom = close.iloc[-1] / close.iloc[-mom_lookback] - 1
        if mom <= 0:
            continue

        # ATR 기반 변동성 필터
        if highs is not None and lows is not None and coin in highs.columns and coin in lows.columns:
            h = highs[coin].loc[:date].dropna()
            l = lows[coin].loc[:date].dropna()
            c = close
            common = h.index.intersection(l.index).intersection(c.index)
            if len(common) < 20:
                continue
            atr = calc_atr(h.loc[common], l.loc[common], c.loc[common]).iloc[-1]
            atr_pct = atr / close.iloc[-1] if close.iloc[-1] > 0 else 1
        else:
            atr_pct = close.pct_change().tail(14).std()

        if pd.isna(atr_pct) or atr_pct <= 0:
            continue

        # 현재가가 최근 고점 대비 2×ATR 이내 (트레일링 스탑 통과)
        recent_high = close.tail(20).max()
        if close.iloc[-1] < recent_high - 2 * atr_pct * close.iloc[-1]:
            continue  # 트레일링 스탑에 걸린 코인 제외

        scores[coin] = mom / atr_pct  # 모멘텀/변동성 = 효율

    if not scores:
        return {}
    sorted_c = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    weight = 1.0 / len(sorted_c)
    return {c: weight for c, _ in sorted_c}


# ═══════════════════════════════════════════════
# 전략 5: 리스크 온/오프 바이너리
# ═══════════════════════════════════════════════

def strategy_risk_onoff(prices, date, top_k=5, **kw):
    """
    다중 지표 합산 점수로 시장 전체의 투자/현금 결정.
    리스크 온: 모멘텀 상위 K개 균등 투자
    리스크 오프: 100% 현금
    """
    highs = kw.get("highs")
    lows = kw.get("lows")

    btc = prices["KRW-BTC"].loc[:date].dropna() if "KRW-BTC" in prices.columns else None
    if btc is None or len(btc) < 60:
        return {}

    score = 0

    # 1. BTC 50일 SMA 위? (+1)
    sma50 = btc.tail(50).mean()
    if btc.iloc[-1] > sma50:
        score += 1

    # 2. BTC 20일 모멘텀 > 0? (+1)
    mom20 = btc.iloc[-1] / btc.iloc[-20] - 1
    if mom20 > 0:
        score += 1

    # 3. BTC RSI > 40? (+1)
    rsi = calc_rsi(btc)
    if pd.notna(rsi.iloc[-1]) and rsi.iloc[-1] > 40:
        score += 1

    # 4. ADX 기반 상승 추세? (+1)
    if highs is not None and lows is not None:
        bh = highs["KRW-BTC"].loc[:date].dropna() if "KRW-BTC" in highs.columns else None
        bl = lows["KRW-BTC"].loc[:date].dropna() if "KRW-BTC" in lows.columns else None
        if bh is not None and bl is not None:
            common = btc.index.intersection(bh.index).intersection(bl.index)
            if len(common) > 42:
                adx, pdi, mdi = calc_adx(bh.loc[common], bl.loc[common], btc.loc[common])
                if pd.notna(adx.iloc[-1]) and pd.notna(pdi.iloc[-1]):
                    if adx.iloc[-1] > 20 and pdi.iloc[-1] > mdi.iloc[-1]:
                        score += 1

    # 5. BTC 200일 SMA 위? (+1)
    if len(btc) >= 200:
        sma200 = btc.tail(200).mean()
        if btc.iloc[-1] > sma200:
            score += 1

    # 리스크 온: 3점 이상 (5점 만점)
    if score < 3:
        return {}  # 리스크 오프 → 현금

    # 모멘텀 상위 K개
    available = prices.loc[:date].dropna(axis=1, how="any")
    if len(available) < 20:
        return {}
    mom = available.iloc[-1] / available.iloc[-14] - 1
    top = mom.nlargest(top_k)
    top = top[top > 0]
    if top.empty:
        return {}
    weight = 1.0 / len(top)
    return {c: weight for c in top.index}


# ═══════════════════════════════════════════════
# 전략 6: 모멘텀 + 저변동성 콤보
# ═══════════════════════════════════════════════

def strategy_mom_lowvol(prices, date, mom_lookback=14, vol_lookback=20,
                         top_k=5, **kw):
    """
    모멘텀 상위 50% + 변동성 하위 50%의 교집합에서 투자.
    "안정적으로 오르는 코인"만 선별.
    """
    available = prices.loc[:date].dropna(axis=1, how="any")
    if len(available) < max(mom_lookback, vol_lookback) + 10 or available.shape[1] < 4:
        return {}

    mom = available.iloc[-1] / available.iloc[-mom_lookback] - 1
    vol = available.pct_change().tail(vol_lookback).std()

    n = len(available.columns)
    mom_top = set(mom.nlargest(max(n // 2, 3)).index)
    vol_low = set(vol.nsmallest(max(n // 2, 3)).index)
    combo = mom_top & vol_low

    if not combo:
        # 폴백: 모멘텀 양수 중 변동성 최소
        positive = mom[mom > 0]
        if positive.empty:
            return {}
        combo_vol = vol.reindex(positive.index).dropna()
        if combo_vol.empty:
            return {}
        combo = set(combo_vol.nsmallest(min(top_k, len(combo_vol))).index)

    selected = list(combo)[:top_k]
    weight = 1.0 / len(selected)
    return {c: weight for c in selected}


# ═══════════════════════════════════════════════
# 전략 7: 적응형 리밸런싱
# ═══════════════════════════════════════════════

def strategy_adaptive_rebal(prices, date, base_rebal=5, **kw):
    """
    변동성에 따라 리밸런싱 주기를 자동 조절.
    변동성 높으면 자주 리밸런싱 (빠른 대응), 낮으면 덜 자주 (비용 절감).
    여기서는 비중 계산만 — 리밸런싱 주기는 외부에서 조절.
    """
    return strategy_dual_momentum(prices, date, abs_lookback=50, rel_lookback=20, top_k=5)


# ═══════════════════════════════════════════════
# 전략 8: 거래량돌파 + 리스크오프 결합
# ═══════════════════════════════════════════════

def strategy_vol_breakout_riskoff(prices, date, top_k=5, **kw):
    """기존 거래량돌파 + 리스크 온/오프 필터 결합"""
    highs = kw.get("highs")
    lows = kw.get("lows")
    volumes = kw.get("volumes")

    # 리스크 체크 (strategy_risk_onoff의 점수 계산)
    btc = prices["KRW-BTC"].loc[:date].dropna() if "KRW-BTC" in prices.columns else None
    if btc is None or len(btc) < 60:
        return {}

    score = 0
    sma50 = btc.tail(50).mean()
    if btc.iloc[-1] > sma50: score += 1
    mom20 = btc.iloc[-1] / btc.iloc[-20] - 1
    if mom20 > 0: score += 1
    rsi = calc_rsi(btc)
    if pd.notna(rsi.iloc[-1]) and rsi.iloc[-1] > 40: score += 1
    if len(btc) >= 200:
        if btc.iloc[-1] > btc.tail(200).mean(): score += 1

    if score < 2:
        return {}  # 리스크 오프

    # 거래량돌파 로직
    if volumes is None:
        return strategy_dual_momentum(prices, date, top_k=top_k)

    available = prices.loc[:date].dropna(axis=1, how="any")
    scores = {}
    for coin in available.columns:
        close = available[coin]
        vol = volumes[coin].loc[:date].dropna() if coin in volumes.columns else None
        if vol is None or len(close) < 25 or len(vol) < 25:
            continue
        recent_vol = vol.tail(4).mean()
        avg_vol = vol.tail(20).mean()
        if avg_vol <= 0: continue
        ratio = recent_vol / avg_vol
        mom = close.iloc[-1] / close.iloc[-4] - 1
        if ratio >= 1.26 and mom > 0:
            scores[coin] = ratio * (1 + mom)

    if not scores:
        # 폴백: 모멘텀
        for coin in available.columns:
            close = available[coin]
            if len(close) < 10: continue
            m = close.iloc[-1] / close.iloc[-4] - 1
            if m > 0: scores[coin] = m

    if not scores:
        return {}
    sorted_c = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    w = 1.0 / len(sorted_c)
    return {c: w for c, _ in sorted_c}


# ═══════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════

def main():
    logger.info("=" * 70)
    logger.info("  샤프 비율 극대화 전략 탐색")
    logger.info("=" * 70)

    # 데이터 로드
    logger.info("\n[데이터] 1500일 OHLCV 로드 중...")
    data = collect_ohlcv_full(days=1500, force=False)
    prices = data["prices"]
    highs = data["highs"]
    lows = data["lows"]
    volumes = data["volumes"]
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()} ({len(prices)}일)")

    sim = Simulator(capital=10_000_000, cost=0.001)

    # ─── 전략 목록 ───
    strategies = [
        # (이름, weight_fn, kwargs)
        ("1.변동성타겟(vol15%,mom14,K5)", strategy_vol_target,
         {"rebal_days": 3, "target_vol": 0.15, "lookback_mom": 14, "lookback_vol": 20, "top_k": 5}),
        ("1b.변동성타겟(vol10%,mom20,K5)", strategy_vol_target,
         {"rebal_days": 3, "target_vol": 0.10, "lookback_mom": 20, "lookback_vol": 20, "top_k": 5}),
        ("2.듀얼모멘텀(abs50,rel14,K5)", strategy_dual_momentum,
         {"rebal_days": 3, "abs_lookback": 50, "rel_lookback": 14, "top_k": 5}),
        ("2b.듀얼모멘텀(abs30,rel7,K3)", strategy_dual_momentum,
         {"rebal_days": 3, "abs_lookback": 30, "rel_lookback": 7, "top_k": 3}),
        ("2c.듀얼모멘텀(abs50,rel14,K5,7일)", strategy_dual_momentum,
         {"rebal_days": 7, "abs_lookback": 50, "rel_lookback": 14, "top_k": 5}),
        ("3.추세필터+역변동성(K7)", strategy_trend_invvol,
         {"rebal_days": 3, "sma_period": 50, "vol_lookback": 20, "top_k": 7}),
        ("3b.추세필터+역변동성(K5,7일)", strategy_trend_invvol,
         {"rebal_days": 7, "sma_period": 50, "vol_lookback": 20, "top_k": 5}),
        ("4.ATR트레일링(mom14,K5)", strategy_atr_trailing,
         {"rebal_days": 3, "mom_lookback": 14, "top_k": 5, "highs": highs, "lows": lows}),
        ("5.리스크온오프(K5,3일)", strategy_risk_onoff,
         {"rebal_days": 3, "top_k": 5, "highs": highs, "lows": lows}),
        ("5b.리스크온오프(K5,7일)", strategy_risk_onoff,
         {"rebal_days": 7, "top_k": 5, "highs": highs, "lows": lows}),
        ("5c.리스크온오프(K3,3일)", strategy_risk_onoff,
         {"rebal_days": 3, "top_k": 3, "highs": highs, "lows": lows}),
        ("6.모멘텀+저변동성(K5)", strategy_mom_lowvol,
         {"rebal_days": 3, "mom_lookback": 14, "vol_lookback": 20, "top_k": 5}),
        ("6b.모멘텀+저변동성(K3,7일)", strategy_mom_lowvol,
         {"rebal_days": 7, "mom_lookback": 14, "vol_lookback": 20, "top_k": 3}),
        ("7.적응형리밸런싱(5일)", strategy_adaptive_rebal,
         {"rebal_days": 5}),
        ("8.거래량돌파+리스크오프", strategy_vol_breakout_riskoff,
         {"rebal_days": 3, "top_k": 5, "highs": highs, "lows": lows, "volumes": volumes}),
        ("8b.거래량돌파+리스크오프(7일)", strategy_vol_breakout_riskoff,
         {"rebal_days": 7, "top_k": 5, "highs": highs, "lows": lows, "volumes": volumes}),
    ]

    # ─── 실행 ───
    logger.info(f"\n[실행] {len(strategies)}개 전략 백테스트 중...\n")
    results = []

    for name, fn, kwargs in strategies:
        eq = sim.run(prices, fn, **kwargs)
        metrics = evaluate(eq)
        metrics["name"] = name
        results.append(metrics)

    # ─── 벤치마크 ───
    # BTC 바이앤홀드
    btc_eq = prices["KRW-BTC"].dropna().iloc[60:]
    btc_eq = btc_eq / btc_eq.iloc[0] * 10_000_000
    btc_metrics = evaluate(btc_eq)
    btc_metrics["name"] = "BTC 바이앤홀드"
    results.append(btc_metrics)

    # 현금
    results.append({"name": "현금보유", "샤프": 0, "총수익": 0, "CAGR": 0,
                     "MDD": 0, "칼마": 0, "승률": 0, "변동성": 0})

    # ─── 결과: 샤프 순 정렬 ───
    results.sort(key=lambda x: x["샤프"], reverse=True)

    logger.info("=" * 110)
    logger.info(f"{'순위':>3s} {'전략':<35s} | {'샤프':>6s} | {'총수익':>8s} | {'CAGR':>7s} | {'MDD':>8s} | {'칼마':>6s} | {'변동성':>6s} | {'승률':>5s}")
    logger.info("-" * 110)

    for i, r in enumerate(results, 1):
        marker = " ***" if i <= 3 else ""
        logger.info(
            f"  {i:>2d} {r['name']:<35s} | "
            f"{r['샤프']:>6.3f} | "
            f"{r['총수익']:>+7.1f}% | "
            f"{r['CAGR']:>+6.1f}% | "
            f"{r['MDD']:>+7.1f}% | "
            f"{r['칼마']:>6.2f} | "
            f"{r.get('변동성', 0):>5.1f}% | "
            f"{r['승률']:>4.1f}%{marker}"
        )

    # ─── 상위 3 전략 분석 ───
    logger.info("\n" + "=" * 70)
    logger.info("  상위 3 전략 상세 분석")
    logger.info("=" * 70)

    top3 = [r for r in results if r["샤프"] > 0][:3]
    for r in top3:
        logger.info(f"\n  [{r['name']}]")
        logger.info(f"    샤프: {r['샤프']:.3f} | 총수익: {r['총수익']:+.1f}% | CAGR: {r['CAGR']:+.1f}%")
        logger.info(f"    MDD: {r['MDD']:.1f}% | 칼마: {r['칼마']:.2f} | 변동성: {r.get('변동성', 0):.1f}%")

    logger.info("\n" + "=" * 70)
    logger.info("  완료")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
