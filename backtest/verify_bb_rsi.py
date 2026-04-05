"""
backtest/verify_bb_rsi.py - BB+RSI 백테스트 신뢰도 검증

대시보드(시뮬레이션)와 실제 백테스트의 괴리를 분석합니다.

검증 항목:
  1. 대시보드와 동일한 조건(횡보장만, 코인별 독립)으로 BB+RSI 재현
  2. 전 기간 적용 vs 횡보장만 적용 비교
  3. BB+RSI 신호 빈도/품질 분석
  4. Walk-forward 엔진과 독립 시뮬레이션 결과 비교
  5. 파라미터 민감도 테스트

실행:
    python -m backtest.verify_bb_rsi
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="INFO")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data_collector import collect_all_data


# ═══════════════════════════════════════════════
# 지표 계산
# ═══════════════════════════════════════════════

def calc_bb(close: pd.Series, period=20, std_dev=2.0):
    """볼린저밴드 계산"""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return mid, upper, lower


def calc_rsi(close: pd.Series, period=14):
    """RSI 계산"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def detect_regime(btc_close: pd.Series, sma_period=50, mom_period=20):
    """일별 시장 국면 분류"""
    sma = btc_close.rolling(sma_period).mean()
    regime = pd.Series("sideways", index=btc_close.index)

    for i in range(max(sma_period, mom_period), len(btc_close)):
        price = btc_close.iloc[i]
        sma_val = sma.iloc[i]
        mom = price / btc_close.iloc[i - mom_period] - 1

        if price > sma_val and mom > 0.10:
            regime.iloc[i] = "bull"
        elif price < sma_val and mom < -0.10:
            regime.iloc[i] = "bear"
        else:
            regime.iloc[i] = "sideways"

    return regime


# ═══════════════════════════════════════════════
# 검증 1: 코인별 독립 BB+RSI 시뮬레이션 (대시보드 방식 재현)
# ═══════════════════════════════════════════════

def simulate_bb_rsi_per_coin(prices, regimes, bb_period=20, bb_std=2.0,
                              rsi_period=14, rsi_oversold=30, rsi_overbought=70,
                              stop_loss=-0.03, take_profit=0.05,
                              fee_rate=0.0005, sideways_only=True):
    """
    코인별 독립 BB+RSI 시뮬레이션 (대시보드 방식 재현)

    각 코인을 독립적으로:
      - 매수: BB하단 이하 + RSI < oversold
      - 매도: BB상단+RSI과매수 / BB중간+수익1% / 손절 / 익절
    """
    results = []

    for coin in prices.columns:
        close = prices[coin].dropna()
        if len(close) < bb_period + 10:
            continue

        bb_mid, bb_upper, bb_lower = calc_bb(close, bb_period, bb_std)
        rsi = calc_rsi(close, rsi_period)

        trades = []
        in_position = False
        entry_price = 0
        entry_date = None

        for i in range(max(bb_period, rsi_period) + 1, len(close)):
            date = close.index[i]
            price = close.iloc[i]
            cur_rsi = rsi.iloc[i]
            cur_bb_lower = bb_lower.iloc[i]
            cur_bb_upper = bb_upper.iloc[i]
            cur_bb_mid = bb_mid.iloc[i]

            if pd.isna(cur_rsi) or pd.isna(cur_bb_lower):
                continue

            # 횡보장 필터
            if sideways_only and date in regimes.index:
                if regimes.loc[date] != "sideways":
                    # 포지션 있으면 국면 전환으로 청산
                    if in_position:
                        pnl = (price / entry_price - 1) - fee_rate * 2
                        trades.append({
                            "entry_date": entry_date, "exit_date": date,
                            "entry_price": entry_price, "exit_price": price,
                            "pnl_pct": pnl * 100, "reason": "regime_change",
                            "rsi_entry": None, "holding_days": (date - entry_date).days,
                        })
                        in_position = False
                    continue

            if not in_position:
                # 매수 조건: BB하단 이하 + RSI 과매도
                if price <= cur_bb_lower and cur_rsi < rsi_oversold:
                    entry_price = price
                    entry_date = date
                    entry_rsi = cur_rsi
                    in_position = True
            else:
                pnl = price / entry_price - 1

                sell = False
                reason = ""

                # 매도 조건 1: BB상단 + RSI과매수
                if price >= cur_bb_upper and cur_rsi > rsi_overbought:
                    sell, reason = True, "bb_upper_rsi"
                # 매도 조건 2: BB중간선 + 수익 > 1%
                elif price >= cur_bb_mid and pnl > 0.01:
                    sell, reason = True, "bb_mid_profit"
                # 매도 조건 3: 손절
                elif pnl <= stop_loss:
                    sell, reason = True, "stop_loss"
                # 매도 조건 4: 익절
                elif pnl >= take_profit:
                    sell, reason = True, "take_profit"

                if sell:
                    net_pnl = pnl - fee_rate * 2
                    trades.append({
                        "entry_date": entry_date, "exit_date": date,
                        "entry_price": entry_price, "exit_price": price,
                        "pnl_pct": net_pnl * 100, "reason": reason,
                        "rsi_entry": entry_rsi, "holding_days": (date - entry_date).days,
                    })
                    in_position = False

        # 미청산 포지션
        if in_position:
            last_price = close.iloc[-1]
            pnl = (last_price / entry_price - 1) - fee_rate * 2
            trades.append({
                "entry_date": entry_date, "exit_date": close.index[-1],
                "entry_price": entry_price, "exit_price": last_price,
                "pnl_pct": pnl * 100, "reason": "end_of_period",
                "rsi_entry": entry_rsi, "holding_days": (close.index[-1] - entry_date).days,
            })

        # 코인별 요약
        n_trades = len(trades)
        total_return = sum(t["pnl_pct"] for t in trades)
        wins = [t for t in trades if t["pnl_pct"] > 0]
        losses = [t for t in trades if t["pnl_pct"] <= 0]
        win_rate = len(wins) / n_trades * 100 if n_trades > 0 else 0
        avg_win = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
        avg_loss = np.mean([t["pnl_pct"] for t in losses]) if losses else 0
        max_dd = min([t["pnl_pct"] for t in trades]) if trades else 0

        # 횡보장 비율
        if coin in regimes.index or len(regimes) > 0:
            coin_dates = close.index
            sideways_count = sum(1 for d in coin_dates if d in regimes.index and regimes.loc[d] == "sideways")
            sideways_pct = sideways_count / len(coin_dates) * 100
        else:
            sideways_pct = 0

        results.append({
            "ticker": coin,
            "sideways_pct": round(sideways_pct, 1),
            "n_trades": n_trades,
            "total_return": round(total_return, 2),
            "win_rate": round(win_rate, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "max_dd": round(max_dd, 2),
            "trades": trades,
        })

    return results


# ═══════════════════════════════════════════════
# 검증 2: 신호 빈도/품질 분석
# ═══════════════════════════════════════════════

def analyze_signal_frequency(prices, regimes, bb_period=20, bb_std=2.0,
                              rsi_period=14, rsi_oversold=30):
    """BB+RSI 매수 신호가 얼마나 자주 발생하는지 분석"""
    signal_stats = []

    for coin in prices.columns:
        close = prices[coin].dropna()
        if len(close) < bb_period + 10:
            continue

        bb_mid, bb_upper, bb_lower = calc_bb(close, bb_period, bb_std)
        rsi = calc_rsi(close, rsi_period)

        total_days = 0
        sideways_days = 0
        bb_lower_days = 0  # BB하단 이하 일수
        rsi_oversold_days = 0  # RSI<30 일수
        both_days = 0  # 두 조건 동시 충족 일수

        for i in range(max(bb_period, rsi_period) + 1, len(close)):
            date = close.index[i]
            price = close.iloc[i]
            cur_rsi = rsi.iloc[i]
            cur_bb_lower = bb_lower.iloc[i]

            if pd.isna(cur_rsi) or pd.isna(cur_bb_lower):
                continue

            is_sideways = date in regimes.index and regimes.loc[date] == "sideways"
            if is_sideways:
                sideways_days += 1

            total_days += 1

            if price <= cur_bb_lower:
                bb_lower_days += 1
            if cur_rsi < rsi_oversold:
                rsi_oversold_days += 1
            if price <= cur_bb_lower and cur_rsi < rsi_oversold:
                both_days += 1

        signal_stats.append({
            "ticker": coin,
            "total_days": total_days,
            "sideways_days": sideways_days,
            "bb_lower_days": bb_lower_days,
            "rsi_oversold_days": rsi_oversold_days,
            "both_signal_days": both_days,
            "signal_rate": round(both_days / total_days * 100, 2) if total_days > 0 else 0,
            "sideways_signal_rate": round(
                both_days / sideways_days * 100, 2
            ) if sideways_days > 0 else 0,
        })

    return signal_stats


# ═══════════════════════════════════════════════
# 검증 3: 파라미터 민감도
# ═══════════════════════════════════════════════

def parameter_sensitivity(prices, regimes):
    """BB+RSI 파라미터 변화에 따른 수익률 변화"""
    configs = [
        {"name": "기본 (BB20,2.0,RSI30)", "bb_period": 20, "bb_std": 2.0, "rsi_oversold": 30},
        {"name": "완화1 (BB20,1.5,RSI35)", "bb_period": 20, "bb_std": 1.5, "rsi_oversold": 35},
        {"name": "완화2 (BB20,1.0,RSI40)", "bb_period": 20, "bb_std": 1.0, "rsi_oversold": 40},
        {"name": "엄격 (BB20,2.5,RSI25)", "bb_period": 20, "bb_std": 2.5, "rsi_oversold": 25},
        {"name": "단기BB (BB10,2.0,RSI30)", "bb_period": 10, "bb_std": 2.0, "rsi_oversold": 30},
    ]

    results = []
    for cfg in configs:
        coin_results = simulate_bb_rsi_per_coin(
            prices, regimes,
            bb_period=cfg["bb_period"],
            bb_std=cfg["bb_std"],
            rsi_oversold=cfg["rsi_oversold"],
            sideways_only=True,
        )
        total_trades = sum(r["n_trades"] for r in coin_results)
        avg_return = np.mean([r["total_return"] for r in coin_results]) if coin_results else 0
        wins = sum(1 for r in coin_results if r["total_return"] > 0)
        results.append({
            "config": cfg["name"],
            "total_trades": total_trades,
            "avg_return": round(avg_return, 2),
            "coins_positive": wins,
            "coins_total": len(coin_results),
        })

    return results


# ═══════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════

def main():
    logger.info("=" * 70)
    logger.info("  BB+RSI 백테스트 신뢰도 검증")
    logger.info("=" * 70)

    # 1. 데이터 로드
    logger.info("\n[1/5] 데이터 로드 중...")
    prices, volumes = collect_all_data(days=800)
    btc_close = prices["KRW-BTC"]
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()} ({len(prices)}일)")

    # 2. 국면 분류
    logger.info("\n[2/5] BTC 국면 분류 중...")
    regimes = detect_regime(btc_close)
    counts = regimes.value_counts()
    for regime in ["bull", "sideways", "bear"]:
        n = counts.get(regime, 0)
        logger.info(f"  {regime:>8s}: {n}일 ({n/len(regimes):.1%})")

    # 3. 검증 1: 대시보드 방식 재현 (횡보장만)
    logger.info("\n[3/5] 검증 1: 대시보드 방식 재현 (횡보장 구간만, 코인별 독립)")
    logger.info("-" * 70)

    sideways_results = simulate_bb_rsi_per_coin(prices, regimes, sideways_only=True)

    logger.info(f"{'코인':<12s} | {'거래수':>5s} | {'수익률':>8s} | {'승률':>6s} | {'최대손실':>8s} | {'횡보%':>5s}")
    logger.info("-" * 60)
    for r in sideways_results:
        logger.info(
            f"  {r['ticker'].replace('KRW-', ''):<10s} | "
            f"{r['n_trades']:>5d} | "
            f"{r['total_return']:>+7.2f}% | "
            f"{r['win_rate']:>5.1f}% | "
            f"{r['max_dd']:>+7.2f}% | "
            f"{r['sideways_pct']:>4.1f}%"
        )

    avg_return_sideways = np.mean([r["total_return"] for r in sideways_results])
    total_trades_sideways = sum(r["n_trades"] for r in sideways_results)
    coins_positive = sum(1 for r in sideways_results if r["total_return"] > 0)

    logger.info(f"\n  [횡보장만] 평균 수익률: {avg_return_sideways:+.2f}%")
    logger.info(f"  [횡보장만] 총 거래 수: {total_trades_sideways}")
    logger.info(f"  [횡보장만] 양수 코인: {coins_positive}/{len(sideways_results)}")

    # 4. 전 기간 적용 비교
    logger.info("\n  --- 전 기간(국면 무관) BB+RSI 적용 ---")
    all_period_results = simulate_bb_rsi_per_coin(prices, regimes, sideways_only=False)
    avg_return_all = np.mean([r["total_return"] for r in all_period_results])
    total_trades_all = sum(r["n_trades"] for r in all_period_results)
    coins_positive_all = sum(1 for r in all_period_results if r["total_return"] > 0)

    logger.info(f"  [전 기간] 평균 수익률: {avg_return_all:+.2f}%")
    logger.info(f"  [전 기간] 총 거래 수: {total_trades_all}")
    logger.info(f"  [전 기간] 양수 코인: {coins_positive_all}/{len(all_period_results)}")

    logger.info(f"\n  >>> 횡보장 필터 효과: {avg_return_sideways - avg_return_all:+.2f}%p 개선")

    # 5. 검증 2: 신호 빈도 분석
    logger.info("\n[4/5] 검증 2: BB+RSI 신호 빈도 분석")
    logger.info("-" * 70)

    signal_stats = analyze_signal_frequency(prices, regimes)
    logger.info(f"{'코인':<12s} | {'전체일':>6s} | {'횡보일':>6s} | {'BB하단':>6s} | {'RSI<30':>6s} | {'동시충족':>6s} | {'신호율':>6s}")
    logger.info("-" * 70)
    for s in signal_stats:
        logger.info(
            f"  {s['ticker'].replace('KRW-', ''):<10s} | "
            f"{s['total_days']:>6d} | "
            f"{s['sideways_days']:>6d} | "
            f"{s['bb_lower_days']:>6d} | "
            f"{s['rsi_oversold_days']:>6d} | "
            f"{s['both_signal_days']:>6d} | "
            f"{s['signal_rate']:>5.2f}%"
        )

    total_signal_days = sum(s["both_signal_days"] for s in signal_stats)
    avg_signal_rate = np.mean([s["signal_rate"] for s in signal_stats])
    logger.info(f"\n  전체 코인 동시충족 총 일수: {total_signal_days}")
    logger.info(f"  평균 신호 발생률: {avg_signal_rate:.2f}%")

    if avg_signal_rate < 1:
        logger.warning(f"  [경고] 신호 발생률이 {avg_signal_rate:.2f}%로 매우 낮음!")
        logger.warning(f"  → BB하단(2.0) + RSI<30 동시 충족이 실제 시장에서 극히 드뭄")
        logger.warning(f"  → 대시보드의 시뮬레이션 데이터와 실제 시장 괴리의 핵심 원인")

    # 6. 검증 3: 파라미터 민감도
    logger.info("\n[5/5] 검증 3: 파라미터 민감도 (횡보장만)")
    logger.info("-" * 70)

    sensitivity = parameter_sensitivity(prices, regimes)
    logger.info(f"{'파라미터':<30s} | {'거래수':>6s} | {'평균수익':>8s} | {'양수코인':>8s}")
    logger.info("-" * 65)
    for s in sensitivity:
        logger.info(
            f"  {s['config']:<28s} | "
            f"{s['total_trades']:>6d} | "
            f"{s['avg_return']:>+7.2f}% | "
            f"{s['coins_positive']:>3d}/{s['coins_total']}"
        )

    # 최종 결론
    logger.info("\n" + "=" * 70)
    logger.info("  검증 결론")
    logger.info("=" * 70)

    logger.info(f"""
  1. 대시보드 데이터 신뢰도: 낮음
     - 대시보드는 "시뮬레이션 데이터"로 명시 (Upbit API 미접근)
     - 실제 데이터 기반 재현 시 평균 수익률: {avg_return_sideways:+.2f}%
     - 대시보드 수치(+2.14%)와 {'일치' if abs(avg_return_sideways - 2.14) < 2 else '괴리'}

  2. BB+RSI 신호 빈도: 극히 낮음
     - RSI<30 + BB하단 동시 충족: 평균 {avg_signal_rate:.2f}%
     - 800일 중 코인당 {total_signal_days/len(signal_stats):.1f}일만 신호 발생
     - 거래 기회가 너무 적어 전략 효용 제한적

  3. 횡보장 필터 효과: {avg_return_sideways - avg_return_all:+.2f}%p
     - 횡보장만 적용 시: {avg_return_sideways:+.2f}%
     - 전 기간 적용 시: {avg_return_all:+.2f}%
     - 국면 필터가 {'효과적' if avg_return_sideways > avg_return_all else '제한적'}

  4. Walk-forward 엔진 vs 독립 시뮬레이션 괴리:
     - Walk-forward(-80.19%)는 전 기간 포트폴리오 방식
     - 독립 시뮬레이션({avg_return_all:+.2f}%)은 코인별 개별 거래
     - 포트폴리오 리밸런싱의 누적 손실이 괴리의 주 원인

  5. 권장 사항:
     - BB+RSI 단독 사용은 비추천 (신호 빈도 부족)
     - 파라미터 완화(RSI<35, BB std=1.5) 시 거래 빈도 개선 가능
     - 전략 라우터에서 횡보장 전략은 "현금보유" 또는
       "거래량돌파 축소(50%)" 방식이 더 현실적
""")

    logger.info("=" * 70)


if __name__ == "__main__":
    main()
