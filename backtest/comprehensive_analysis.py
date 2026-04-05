"""
backtest/comprehensive_analysis.py - 전략 가이드 보충을 위한 종합 실데이터 분석

원본 문서에서 시뮬레이션/미검증이었던 항목을 실제 Upbit 데이터로 검증합니다.

분석 항목:
  1. EMA 9/34 vs MA 5/20 크로스오버 비교
  2. ADX 기반 국면 판단 vs 현행 SMA50+모멘텀 비교
  3. ADX+ATR 4분류 국면 감지 및 분포
  4. BB+RSI 파라미터별 횡보장 성과 (국면별 분리)
  5. 전략 스위칭 비용 정량 분석
  6. 각 전략의 국면별 실제 성과 매트릭스
  7. 신호 빈도 및 거래 품질 분석
  8. Choppiness Index / BB Width 국면 판단 정확도

실행: python -m backtest.comprehensive_analysis
"""

import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO")

from backtest.data_collector import collect_all_data


# ═══════════════════════════════════════════════
# 지표 계산 함수들
# ═══════════════════════════════════════════════

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_sma(series, period):
    return series.rolling(period).mean()

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_bb(close, period=20, std_dev=2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    width = (upper - lower) / mid * 100
    return mid, upper, lower, width

def calc_atr(high, low, close, period=14):
    """ATR 계산 (high/low 없으면 close로 근사)"""
    if high is not None and low is not None:
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    else:
        tr = close.diff().abs()
    return tr.rolling(period).mean()

def calc_adx(close, period=14):
    """ADX 근사 계산 (close만 사용 - 일봉 데이터 한계)"""
    diff = close.diff()
    plus_dm = diff.where(diff > 0, 0)
    minus_dm = (-diff).where(diff < 0, 0)

    atr = close.diff().abs().rolling(period).mean()
    atr = atr.replace(0, np.nan)

    plus_di = 100 * plus_dm.rolling(period).mean() / atr
    minus_di = 100 * minus_dm.rolling(period).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(period).mean()
    return adx, plus_di, minus_di

def calc_choppiness(close, period=14):
    """Choppiness Index 근사 계산"""
    atr_sum = close.diff().abs().rolling(period).sum()
    high_low_range = close.rolling(period).max() - close.rolling(period).min()
    high_low_range = high_low_range.replace(0, np.nan)
    ci = 100 * np.log10(atr_sum / high_low_range) / np.log10(period)
    return ci


# ═══════════════════════════════════════════════
# 국면 분류 함수들
# ═══════════════════════════════════════════════

def regime_sma_momentum(btc_close, sma_period=50, mom_period=20):
    """현행 방식: SMA50 + 20일 모멘텀"""
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

def regime_adx_based(btc_close, adx_period=14):
    """ADX 기반 국면 분류"""
    adx, plus_di, minus_di = calc_adx(btc_close, adx_period)
    regime = pd.Series("sideways", index=btc_close.index)
    for i in range(adx_period * 3, len(btc_close)):
        a = adx.iloc[i]
        if pd.isna(a):
            continue
        if a > 25:
            if plus_di.iloc[i] > minus_di.iloc[i]:
                regime.iloc[i] = "bull"
            else:
                regime.iloc[i] = "bear"
        else:
            regime.iloc[i] = "sideways"
    return regime

def regime_adx_atr_4class(btc_close, adx_period=14, atr_period=14):
    """ADX+ATR 4분류 (문서 권장 업그레이드)"""
    adx, plus_di, minus_di = calc_adx(btc_close, adx_period)
    atr = btc_close.diff().abs().rolling(atr_period).mean()
    atr_avg = atr.rolling(42).mean()
    _, _, _, bb_width = calc_bb(btc_close)
    bb_width_avg = bb_width.rolling(42).mean()

    regime = pd.Series("ranging", index=btc_close.index)
    for i in range(60, len(btc_close)):
        a = adx.iloc[i]
        atr_ratio = atr.iloc[i] / atr_avg.iloc[i] if atr_avg.iloc[i] > 0 else 1
        bw = bb_width.iloc[i]
        bw_avg = bb_width_avg.iloc[i]

        if pd.isna(a) or pd.isna(atr_ratio) or pd.isna(bw) or pd.isna(bw_avg):
            continue

        if a > 20 and atr_ratio > 0.8:
            regime.iloc[i] = "trending"
        elif a < 25 and bw < bw_avg * 0.8 and atr_ratio < 0.9:
            regime.iloc[i] = "quiet"
        elif bw > bw_avg * 1.5 or atr_ratio > 1.2:
            regime.iloc[i] = "volatile"
        else:
            regime.iloc[i] = "ranging"
    return regime


# ═══════════════════════════════════════════════
# 분석 1: EMA 9/34 vs MA 5/20
# ═══════════════════════════════════════════════

def analyze_crossover_strategies(prices):
    """EMA 9/34 vs MA 5/20 크로스오버 비교"""
    results = []
    for coin in prices.columns:
        close = prices[coin].dropna()
        if len(close) < 50:
            continue

        for name, fast_fn, slow_fn, fast_p, slow_p in [
            ("MA 5/20", calc_sma, calc_sma, 5, 20),
            ("EMA 9/34", calc_ema, calc_ema, 9, 34),
            ("EMA 12/26", calc_ema, calc_ema, 12, 26),
        ]:
            fast = fast_fn(close, fast_p)
            slow = slow_fn(close, slow_p)

            trades = []
            in_position = False
            entry_price = 0

            for i in range(slow_p + 1, len(close)):
                if pd.isna(fast.iloc[i]) or pd.isna(slow.iloc[i]):
                    continue

                # 골든크로스
                if not in_position and fast.iloc[i] > slow.iloc[i] and fast.iloc[i-1] <= slow.iloc[i-1]:
                    entry_price = close.iloc[i]
                    in_position = True
                # 데드크로스
                elif in_position and fast.iloc[i] < slow.iloc[i] and fast.iloc[i-1] >= slow.iloc[i-1]:
                    exit_price = close.iloc[i]
                    pnl = (exit_price / entry_price - 1) * 100 - 0.1  # 수수료
                    trades.append(pnl)
                    in_position = False

            if trades:
                results.append({
                    "strategy": name,
                    "coin": coin.replace("KRW-", ""),
                    "trades": len(trades),
                    "avg_return": round(np.mean(trades), 2),
                    "win_rate": round(sum(1 for t in trades if t > 0) / len(trades) * 100, 1),
                    "total_return": round(sum(trades), 2),
                })

    return pd.DataFrame(results)


# ═══════════════════════════════════════════════
# 분석 2: 국면 판단 방식 비교
# ═══════════════════════════════════════════════

def compare_regime_methods(btc_close):
    """세 가지 국면 판단 방식의 분포 비교"""
    r1 = regime_sma_momentum(btc_close)
    r2 = regime_adx_based(btc_close)
    r4 = regime_adx_atr_4class(btc_close)

    methods = {
        "SMA50+모멘텀 (현행)": r1,
        "ADX 기반": r2,
        "ADX+ATR 4분류": r4,
    }

    results = {}
    for name, regime in methods.items():
        counts = regime.value_counts()
        total = len(regime)
        dist = {}
        for r in counts.index:
            dist[r] = {"일수": int(counts[r]), "비율": round(counts[r] / total * 100, 1)}
        results[name] = dist

    return results, methods


# ═══════════════════════════════════════════════
# 분석 3: 전략별 국면별 실제 성과
# ═══════════════════════════════════════════════

def analyze_strategy_by_regime(prices, regimes, strategy_fn, strategy_name):
    """특정 전략을 국면별로 분리하여 성과 측정"""
    results = {}
    for regime_name in regimes.unique():
        regime_dates = regimes[regimes == regime_name].index
        trades = []

        for coin in prices.columns:
            close = prices[coin].dropna()
            coin_trades = strategy_fn(close, regime_dates)
            trades.extend(coin_trades)

        if trades:
            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            results[regime_name] = {
                "거래수": len(trades),
                "평균수익": round(np.mean(trades), 2),
                "승률": round(len(wins) / len(trades) * 100, 1),
                "총수익": round(sum(trades), 2),
                "평균손실": round(np.mean(losses), 2) if losses else 0,
                "평균이익": round(np.mean(wins), 2) if wins else 0,
            }
        else:
            results[regime_name] = {"거래수": 0}

    return results


def bb_rsi_trades_fn(close, valid_dates, bb_period=20, bb_std=2.0, rsi_oversold=30):
    """BB+RSI 거래 시뮬레이션 (특정 날짜에서만)"""
    if len(close) < bb_period + 5:
        return []
    bb_mid, bb_upper, bb_lower, _ = calc_bb(close, bb_period, bb_std)
    rsi = calc_rsi(close)
    trades = []
    in_pos = False
    entry_p = 0

    for i in range(bb_period + 1, len(close)):
        date = close.index[i]
        if date not in valid_dates:
            if in_pos:
                pnl = (close.iloc[i] / entry_p - 1) * 100 - 0.1
                trades.append(pnl)
                in_pos = False
            continue

        price = close.iloc[i]
        r = rsi.iloc[i]
        if pd.isna(r) or pd.isna(bb_lower.iloc[i]):
            continue

        if not in_pos:
            if price <= bb_lower.iloc[i] and r < rsi_oversold:
                entry_p = price
                in_pos = True
        else:
            pnl_raw = price / entry_p - 1
            if (price >= bb_upper.iloc[i] and r > 70) or \
               (price >= bb_mid.iloc[i] and pnl_raw > 0.01) or \
               pnl_raw <= -0.03 or pnl_raw >= 0.05:
                pnl = pnl_raw * 100 - 0.1
                trades.append(pnl)
                in_pos = False

    if in_pos:
        pnl = (close.iloc[-1] / entry_p - 1) * 100 - 0.1
        trades.append(pnl)
    return trades


def volume_breakout_trades_fn(close, valid_dates, lookback=4):
    """거래량돌파 거래 시뮬레이션"""
    if len(close) < 25:
        return []
    trades = []
    mom = close.pct_change(lookback)
    in_pos = False
    entry_p = 0
    hold_days = 0

    for i in range(25, len(close)):
        date = close.index[i]
        if date not in valid_dates:
            if in_pos:
                pnl = (close.iloc[i] / entry_p - 1) * 100 - 0.1
                trades.append(pnl)
                in_pos = False
            continue

        if not in_pos:
            if mom.iloc[i] > 0:
                entry_p = close.iloc[i]
                in_pos = True
                hold_days = 0
        else:
            hold_days += 1
            if hold_days >= 3:  # 3일 리밸런싱
                pnl = (close.iloc[i] / entry_p - 1) * 100 - 0.1
                trades.append(pnl)
                in_pos = False
    return trades


# ═══════════════════════════════════════════════
# 분석 4: 전략 스위칭 비용 분석
# ═══════════════════════════════════════════════

def analyze_switching_cost(regimes, fee_per_switch=0.1):
    """국면 전환 횟수와 비용 분석"""
    switches = []
    prev = None
    for date, regime in regimes.items():
        if prev is not None and regime != prev:
            switches.append({"date": date, "from": prev, "to": regime})
        prev = regime

    total_switches = len(switches)
    total_cost_pct = total_switches * fee_per_switch  # 전환마다 약 0.1% 비용
    days = len(regimes)

    return {
        "총_전환횟수": total_switches,
        "연간_전환횟수": round(total_switches / days * 365, 1),
        "전환_비용_총합": round(total_cost_pct, 2),
        "연간_전환_비용": round(total_cost_pct / days * 365, 2),
        "평균_국면_유지일": round(days / max(total_switches, 1), 1),
        "전환_이력": switches[:20],  # 최근 20개만
    }


# ═══════════════════════════════════════════════
# 분석 5: Choppiness Index 정확도
# ═══════════════════════════════════════════════

def analyze_choppiness_accuracy(btc_close, actual_regimes):
    """Choppiness Index의 국면 판단 정확도"""
    ci = calc_choppiness(btc_close)
    results = {"high_choppy": {}, "low_choppy": {}, "mid": {}}

    for i in range(60, len(btc_close)):
        date = btc_close.index[i]
        c = ci.iloc[i]
        if pd.isna(c) or date not in actual_regimes.index:
            continue

        actual = actual_regimes.loc[date]
        if c > 61.8:
            bucket = "high_choppy"
        elif c < 38.2:
            bucket = "low_choppy"
        else:
            bucket = "mid"

        results[bucket][actual] = results[bucket].get(actual, 0) + 1

    return results


# ═══════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════

def main():
    logger.info("=" * 70)
    logger.info("  전략 가이드 보충 종합 분석")
    logger.info("=" * 70)

    # 데이터 로드
    logger.info("\n[데이터] 로드 중...")
    prices, volumes = collect_all_data(days=800)
    btc = prices["KRW-BTC"]
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()} ({len(prices)}일)")

    # ─── 분석 1: EMA vs MA 크로스오버 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 1: EMA 9/34 vs MA 5/20 크로스오버")
    logger.info("=" * 70)

    cross_df = analyze_crossover_strategies(prices)
    if not cross_df.empty:
        summary = cross_df.groupby("strategy").agg({
            "trades": "sum",
            "avg_return": "mean",
            "win_rate": "mean",
            "total_return": "sum",
        }).round(2)

        for name, row in summary.iterrows():
            logger.info(
                f"  {name:<12s} | 총거래: {row['trades']:>4.0f} | "
                f"평균수익: {row['avg_return']:>+6.2f}% | "
                f"승률: {row['win_rate']:>5.1f}% | "
                f"총수익: {row['total_return']:>+8.1f}%"
            )

    # ─── 분석 2: 국면 판단 비교 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 2: 국면 판단 방식 비교")
    logger.info("=" * 70)

    regime_results, regime_methods = compare_regime_methods(btc)
    for method_name, dist in regime_results.items():
        logger.info(f"\n  [{method_name}]")
        for regime, stats in sorted(dist.items()):
            logger.info(f"    {regime:<12s}: {stats['일수']:>4d}일 ({stats['비율']:>5.1f}%)")

    # ─── 분석 3: 전환 비용 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 3: 전략 스위칭 비용 분석")
    logger.info("=" * 70)

    for method_name, regimes in regime_methods.items():
        cost = analyze_switching_cost(regimes)
        logger.info(
            f"\n  [{method_name}]\n"
            f"    총 전환: {cost['총_전환횟수']}회 | 연간: {cost['연간_전환횟수']}회\n"
            f"    전환 비용 총합: {cost['전환_비용_총합']}% | 연간: {cost['연간_전환_비용']}%\n"
            f"    평균 국면 유지: {cost['평균_국면_유지일']}일"
        )

    # ─── 분석 4: 전략별 국면별 성과 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 4: 전략별 국면별 실제 성과 (SMA50+모멘텀 기준)")
    logger.info("=" * 70)

    regimes_current = regime_sma_momentum(btc)

    # BB+RSI 국면별
    bb_results = {}
    for regime_name in ["bull", "sideways", "bear"]:
        regime_dates = regimes_current[regimes_current == regime_name].index
        all_trades = []
        for coin in prices.columns:
            close = prices[coin].dropna()
            trades = bb_rsi_trades_fn(close, regime_dates)
            all_trades.extend(trades)
        if all_trades:
            wins = [t for t in all_trades if t > 0]
            bb_results[regime_name] = {
                "거래수": len(all_trades), "평균수익": round(np.mean(all_trades), 2),
                "승률": round(len(wins) / len(all_trades) * 100, 1),
                "총수익": round(sum(all_trades), 2),
            }
        else:
            bb_results[regime_name] = {"거래수": 0, "평균수익": 0, "승률": 0, "총수익": 0}

    logger.info("\n  [BB+RSI 평균회귀]")
    for regime, stats in bb_results.items():
        regime_kr = {"bull": "상승장", "sideways": "횡보장", "bear": "하락장"}.get(regime, regime)
        logger.info(
            f"    {regime_kr:<6s}: 거래 {stats['거래수']:>3d}회 | "
            f"평균 {stats['평균수익']:>+6.2f}% | 승률 {stats['승률']:>5.1f}% | "
            f"총 {stats['총수익']:>+8.2f}%"
        )

    # 거래량돌파 국면별
    vol_results = {}
    for regime_name in ["bull", "sideways", "bear"]:
        regime_dates = regimes_current[regimes_current == regime_name].index
        all_trades = []
        for coin in prices.columns:
            close = prices[coin].dropna()
            trades = volume_breakout_trades_fn(close, regime_dates)
            all_trades.extend(trades)
        if all_trades:
            wins = [t for t in all_trades if t > 0]
            vol_results[regime_name] = {
                "거래수": len(all_trades), "평균수익": round(np.mean(all_trades), 2),
                "승률": round(len(wins) / len(all_trades) * 100, 1),
                "총수익": round(sum(all_trades), 2),
            }
        else:
            vol_results[regime_name] = {"거래수": 0, "평균수익": 0, "승률": 0, "총수익": 0}

    logger.info("\n  [거래량돌파]")
    for regime, stats in vol_results.items():
        regime_kr = {"bull": "상승장", "sideways": "횡보장", "bear": "하락장"}.get(regime, regime)
        logger.info(
            f"    {regime_kr:<6s}: 거래 {stats['거래수']:>3d}회 | "
            f"평균 {stats['평균수익']:>+6.2f}% | 승률 {stats['승률']:>5.1f}% | "
            f"총 {stats['총수익']:>+8.2f}%"
        )

    # ─── 분석 5: Choppiness Index 정확도 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 5: Choppiness Index 국면 판단 정확도")
    logger.info("=" * 70)

    # 실제 국면: 30일 수익률 기준
    actual_regime = pd.Series("sideways", index=btc.index)
    for i in range(30, len(btc)):
        ret = btc.iloc[i] / btc.iloc[i-30] - 1
        if ret > 0.10:
            actual_regime.iloc[i] = "bull"
        elif ret < -0.10:
            actual_regime.iloc[i] = "bear"

    ci_results = analyze_choppiness_accuracy(btc, actual_regime)
    for ci_zone, regime_counts in ci_results.items():
        total = sum(regime_counts.values()) if regime_counts else 0
        zone_name = {"high_choppy": "CI > 61.8 (횡보 예측)", "low_choppy": "CI < 38.2 (추세 예측)", "mid": "38.2~61.8 (중간)"}.get(ci_zone)
        logger.info(f"\n  [{zone_name}] ({total}일)")
        for regime, count in sorted(regime_counts.items()):
            regime_kr = {"bull": "상승장", "sideways": "횡보장", "bear": "하락장"}.get(regime, regime)
            pct = count / total * 100 if total > 0 else 0
            logger.info(f"    {regime_kr}: {count}일 ({pct:.1f}%)")

    # ─── 분석 6: BB+RSI 파라미터별 횡보장 성과 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 6: BB+RSI 파라미터별 횡보장 성과")
    logger.info("=" * 70)

    sideways_dates = regimes_current[regimes_current == "sideways"].index
    param_configs = [
        ("기본 BB20/2.0/RSI30", 20, 2.0, 30),
        ("완화 BB20/1.5/RSI35", 20, 1.5, 35),
        ("강화 BB20/2.0/RSI40", 20, 2.0, 40),
        ("엄격 BB20/2.5/RSI25", 20, 2.5, 25),
        ("단기 BB10/2.0/RSI30", 10, 2.0, 30),
        ("장기 BB30/2.0/RSI30", 30, 2.0, 30),
    ]

    for name, bb_p, bb_s, rsi_t in param_configs:
        all_trades = []
        for coin in prices.columns:
            close = prices[coin].dropna()
            trades = bb_rsi_trades_fn(close, sideways_dates, bb_period=bb_p, bb_std=bb_s, rsi_oversold=rsi_t)
            all_trades.extend(trades)
        if all_trades:
            wins = [t for t in all_trades if t > 0]
            logger.info(
                f"  {name:<25s} | 거래: {len(all_trades):>4d} | "
                f"평균: {np.mean(all_trades):>+6.2f}% | "
                f"승률: {len(wins)/len(all_trades)*100:>5.1f}% | "
                f"총: {sum(all_trades):>+8.1f}%"
            )
        else:
            logger.info(f"  {name:<25s} | 거래: 없음")

    # ─── 분석 7: ADX+ATR 4분류 기반 전략 성과 ───
    logger.info("\n" + "=" * 70)
    logger.info("  분석 7: ADX+ATR 4분류 기반 BB+RSI 성과")
    logger.info("=" * 70)

    regime_4class = regime_adx_atr_4class(btc)
    for regime_name in ["trending", "ranging", "volatile", "quiet"]:
        regime_dates = regime_4class[regime_4class == regime_name].index
        all_trades = []
        for coin in prices.columns:
            close = prices[coin].dropna()
            trades = bb_rsi_trades_fn(close, regime_dates)
            all_trades.extend(trades)
        regime_kr = {"trending": "추세", "ranging": "레인지", "volatile": "고변동", "quiet": "저변동"}.get(regime_name)
        n_days = len(regime_dates)
        if all_trades:
            wins = [t for t in all_trades if t > 0]
            logger.info(
                f"  {regime_kr:<6s} ({n_days:>3d}일) | 거래: {len(all_trades):>3d} | "
                f"평균: {np.mean(all_trades):>+6.2f}% | "
                f"승률: {len(wins)/len(all_trades)*100:>5.1f}%"
            )
        else:
            logger.info(f"  {regime_kr:<6s} ({n_days:>3d}일) | 거래: 없음")

    # ─── 최종 요약 ───
    logger.info("\n" + "=" * 70)
    logger.info("  종합 분석 결과 요약")
    logger.info("=" * 70)
    logger.info("""
  [데이터 기반 핵심 발견]

  1. 크로스오버: MA 5/20, EMA 9/34, EMA 12/26 실제 비교 완료
  2. 국면 판단: 현행(SMA50) vs ADX vs ADX+ATR 분포/비용 비교 완료
  3. BB+RSI: 6가지 파라미터, 3가지 국면, 4분류 국면 성과 완료
  4. 전략 스위칭: 전환 횟수/비용 정량화 완료
  5. Choppiness Index: 횡보 예측 정확도 검증 완료
""")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
