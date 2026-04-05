"""
backtest/run_sideways_comparison.py - 횡보장 대응 전략 비교 백테스트

비교 대상 3가지:
  - Baseline: 현재 운영 전략 (ADX ≤ 25 → 거래량돌파, vol=1.26, 4일고가, top_k=5)
  - 선택 1  : 횡보장 파라미터 완화 (vol=1.1, 2일고가, top_k=3)
  - 선택 2  : ADX < 15 극횡보 구간에서 현금보유 추가

실행 방법:
  python -m backtest.run_sideways_comparison
  python -m backtest.run_sideways_comparison --strategy baseline
  python -m backtest.run_sideways_comparison --strategy selection_1
  python -m backtest.run_sideways_comparison --strategy selection_2
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

# ADX 계산 함수 (실거래 코드 그대로 사용)
from src.strategies.strategy_router import calc_adx

# 기존 백테스트 인프라 재사용
from backtest.data_collector import DATA_DIR, COINS
from backtest.metrics import (
    calc_all_metrics,
    calc_cumulative_return,
    calc_annual_return,
    calc_mdd,
    calc_sharpe_ratio,
    calc_daily_win_rate,
)

# ─────────────────────────────────────────────
# 전략 정의
# ─────────────────────────────────────────────

STRATEGIES = {
    "baseline": {
        "설명": "현재 운영 전략 (변경 없음)",
        "adx_sideways_threshold": 25,
        "adx_extreme_threshold": None,
        "vol_ratio": 1.26,
        "price_lookback": 4,
        "top_k": 5,
    },
    "selection_1": {
        "설명": "횡보장 파라미터 완화",
        "adx_sideways_threshold": 25,
        "adx_extreme_threshold": None,
        "vol_ratio": 1.1,
        "price_lookback": 2,
        "top_k": 3,
    },
    "selection_2": {
        "설명": "ADX 극저구간 현금보유 추가",
        "adx_sideways_threshold": 25,
        "adx_extreme_threshold": 15,
        "vol_ratio": 1.26,
        "price_lookback": 4,
        "top_k": 5,
    },
}

# 백테스트 설정
INITIAL_CAPITAL = 2_000_000
COMMISSION = 0.0005
CONFIRMATION_DAYS = 2
ADX_PERIOD = 14
REBALANCE_DAYS = 3

# 결과 저장 경로
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_data() -> dict:
    """CSV 파일에서 OHLCV 데이터를 로드합니다."""
    files = {
        "prices": "prices_full.csv",
        "highs": "highs.csv",
        "lows": "lows.csv",
        "opens": "opens.csv",
        "volumes": "volumes_full.csv",
    }
    data = {}
    for key, fname in files.items():
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            logger.error(f"데이터 파일 없음: {path}")
            logger.info("먼저 데이터를 수집하세요: python -m backtest.data_collector")
            sys.exit(1)
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        data[key] = df
        logger.info(f"  {key}: {df.shape[0]}일 x {df.shape[1]}코인 로드 ({fname})")
    return data


# ─────────────────────────────────────────────
# ADX 기반 국면 판단 (일별)
# ─────────────────────────────────────────────

def calc_daily_regimes(highs: pd.DataFrame, lows: pd.DataFrame,
                       closes: pd.DataFrame, adx_period: int = 14) -> pd.DataFrame:
    """
    BTC 기준으로 매일의 ADX/+DI/-DI 및 국면을 계산합니다.

    반환값:
        DataFrame (인덱스: 날짜, 컬럼: adx, plus_di, minus_di, raw_regime, regime)
        - raw_regime: 확인 대기 전 즉시 판단
        - regime: confirmation_days 적용 후 최종 국면
    """
    btc_col = "KRW-BTC"
    if btc_col not in closes.columns:
        logger.error("BTC 데이터가 없습니다")
        sys.exit(1)

    high = highs[btc_col].dropna()
    low = lows[btc_col].dropna()
    close = closes[btc_col].dropna()

    # 공통 인덱스
    common_idx = high.index.intersection(low.index).intersection(close.index)
    high = high.loc[common_idx]
    low = low.loc[common_idx]
    close = close.loc[common_idx]

    # ADX 전체 시리즈 계산 (calc_adx는 마지막 값만 반환하므로 직접 계산)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    atr = tr.ewm(alpha=1 / adx_period, min_periods=adx_period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1 / adx_period, min_periods=adx_period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1 / adx_period, min_periods=adx_period).mean()

    plus_di = 100 * plus_dm_smooth / atr
    minus_di = 100 * minus_dm_smooth / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / adx_period, min_periods=adx_period).mean()

    # raw 국면 판단
    regime_df = pd.DataFrame({
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    })
    regime_df = regime_df.dropna()

    # 즉시 국면 판단
    conditions = [
        (regime_df["adx"] > 25) & (regime_df["plus_di"] > regime_df["minus_di"]),
        (regime_df["adx"] > 25) & (regime_df["minus_di"] > regime_df["plus_di"]),
    ]
    choices = ["bull", "bear"]
    regime_df["raw_regime"] = np.select(conditions, choices, default="sideways")

    # confirmation_days 적용 (2일 연속 동일 국면 시 전환)
    confirmed = []
    current = "sideways"
    pending = None
    pending_count = 0

    for _, row in regime_df.iterrows():
        detected = row["raw_regime"]
        if detected != current:
            if detected == pending:
                pending_count += 1
                if pending_count >= CONFIRMATION_DAYS:
                    current = detected
                    pending = None
                    pending_count = 0
            else:
                pending = detected
                pending_count = 1
        else:
            pending = None
            pending_count = 0
        confirmed.append(current)

    regime_df["regime"] = confirmed

    return regime_df


# ─────────────────────────────────────────────
# 거래량돌파 신호 생성
# ─────────────────────────────────────────────

def calc_volume_breakout_weights(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    date: pd.Timestamp,
    vol_ratio: float,
    price_lookback: int,
    top_k: int,
) -> pd.Series:
    """
    거래량돌파 신호를 기반으로 포트폴리오 비중을 계산합니다.
    shift(1) 적용: 전일까지의 데이터만 사용 (룩어헤드 바이어스 방지).
    """
    # 전일까지 데이터만 사용
    p = prices.loc[:date].iloc[:-1] if date in prices.index else prices.loc[:date]
    v = volumes.loc[:date].iloc[:-1] if date in volumes.index else volumes.loc[:date]

    if len(p) < 30 or len(v) < 30:
        return pd.Series(dtype=float)

    scores = {}
    for coin in COINS:
        if coin not in p.columns or coin not in v.columns:
            continue

        coin_v = v[coin].dropna()
        coin_p = p[coin].dropna()
        if len(coin_v) < 25 or len(coin_p) < price_lookback:
            continue

        # 거래량 비율: 최근 5일 평균 / 이전 20일 평균
        avg_5 = coin_v.tail(5).mean()
        avg_20 = coin_v.iloc[-25:-5].mean()
        if avg_20 <= 0:
            continue
        ratio = avg_5 / avg_20

        # 가격 모멘텀: N일 전 대비 변화율
        price_change = coin_p.iloc[-1] / coin_p.iloc[-price_lookback] - 1

        # 거래량돌파 조건: 거래량 급증 + 양의 모멘텀
        if ratio >= vol_ratio and price_change > 0:
            scores[coin] = ratio * (1 + price_change)

    # 돌파 조건 미충족 시 모멘텀 상위 K개 (폴백)
    if not scores:
        for coin in COINS:
            if coin not in p.columns or coin not in v.columns:
                continue
            coin_v = v[coin].dropna()
            coin_p = p[coin].dropna()
            if len(coin_v) < 25 or len(coin_p) < price_lookback:
                continue
            avg_5 = coin_v.tail(5).mean()
            avg_20 = coin_v.iloc[-25:-5].mean()
            if avg_20 > 0:
                price_change = coin_p.iloc[-1] / coin_p.iloc[-price_lookback] - 1
                if price_change > 0:
                    scores[coin] = avg_5 / avg_20

    if not scores:
        return pd.Series(dtype=float)

    score_series = pd.Series(scores)
    selected = score_series.nlargest(min(top_k, len(score_series)))
    return pd.Series(1.0 / len(selected), index=selected.index)


# ─────────────────────────────────────────────
# 일별 시뮬레이션 엔진
# ─────────────────────────────────────────────

def run_simulation(
    strategy_name: str,
    config: dict,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    regime_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> dict:
    """
    하나의 전략에 대해 일별 포트폴리오 시뮬레이션을 실행합니다.

    반환값:
        dict: equity_curve, trades, regime_trades, regime_pnl
    """
    adx_extreme = config.get("adx_extreme_threshold")

    # 날짜 범위 필터
    dates = prices.index[
        (prices.index >= pd.Timestamp(start_date)) &
        (prices.index <= pd.Timestamp(end_date))
    ]
    # regime_df와 교집합
    dates = dates.intersection(regime_df.index)
    if len(dates) == 0:
        logger.error(f"[{strategy_name}] 유효한 거래일이 없습니다")
        return {}

    logger.info(f"[{strategy_name}] 시뮬레이션 시작: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)}일)")

    # 상태 변수
    capital = float(INITIAL_CAPITAL)
    holdings = {}  # {coin: quantity}
    equity_curve = []
    current_weights = pd.Series(dtype=float)
    days_since_rebal = REBALANCE_DAYS  # 첫날 바로 리밸런싱

    # 추적 변수
    total_trades = 0
    winning_trades = 0
    regime_trades = {"bull": 0, "sideways": 0, "extreme_sideways": 0, "bear": 0}
    regime_pnl = {"bull": 0.0, "sideways": 0.0, "extreme_sideways": 0.0, "bear": 0.0}

    prev_portfolio_value = float(INITIAL_CAPITAL)

    for i, date in enumerate(dates):
        # 현재 국면 확인
        regime = regime_df.loc[date, "regime"]
        adx_val = regime_df.loc[date, "adx"]

        # 극횡보 판단
        is_extreme_sideways = (
            regime == "sideways" and
            adx_extreme is not None and
            adx_val < adx_extreme
        )

        # 현재 포트폴리오 평가
        portfolio_value = capital
        for coin, qty in holdings.items():
            if coin in prices.columns and date in prices.index:
                p = prices.loc[date, coin]
                if pd.notna(p):
                    portfolio_value += qty * p

        # 일별 손익 추적 (국면별)
        daily_pnl = portfolio_value - prev_portfolio_value
        if is_extreme_sideways:
            regime_pnl["extreme_sideways"] += daily_pnl
        elif regime == "sideways":
            regime_pnl["sideways"] += daily_pnl
        elif regime == "bull":
            regime_pnl["bull"] += daily_pnl
        elif regime == "bear":
            regime_pnl["bear"] += daily_pnl

        prev_portfolio_value = portfolio_value

        # 리밸런싱 판단
        should_rebal = days_since_rebal >= REBALANCE_DAYS

        if should_rebal:
            target_weights = pd.Series(dtype=float)

            if regime == "bear":
                # 하락장: 전량 현금보유
                target_weights = pd.Series(dtype=float)
            elif is_extreme_sideways:
                # 극횡보 (selection_2만 해당): 현금보유
                target_weights = pd.Series(dtype=float)
            else:
                # 상승장 / 일반 횡보장: 거래량돌파 실행
                target_weights = calc_volume_breakout_weights(
                    prices, volumes, date,
                    vol_ratio=config["vol_ratio"],
                    price_lookback=config["price_lookback"],
                    top_k=config["top_k"],
                )

            # 리밸런싱 실행
            new_holdings, new_capital, n_trades = _execute_rebalance(
                target_weights, holdings, capital, prices, date
            )

            if n_trades > 0:
                total_trades += n_trades
                # 국면별 거래수 추적
                if is_extreme_sideways:
                    regime_trades["extreme_sideways"] += n_trades
                elif regime == "sideways":
                    regime_trades["sideways"] += n_trades
                elif regime == "bull":
                    regime_trades["bull"] += n_trades
                elif regime == "bear":
                    regime_trades["bear"] += n_trades

            holdings = new_holdings
            capital = new_capital
            current_weights = target_weights
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

    # 승률 계산 (일별 양수 수익 비율)
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


def _execute_rebalance(
    target_weights: pd.Series,
    holdings: dict,
    capital: float,
    prices: pd.DataFrame,
    date: pd.Timestamp,
) -> tuple:
    """
    목표 비중에 맞게 포트폴리오를 리밸런싱합니다.
    반환값: (new_holdings, new_capital, trade_count)
    """
    # 현재 포트폴리오 총 가치
    total_value = capital
    for coin, qty in holdings.items():
        if coin in prices.columns and date in prices.index:
            p = prices.loc[date, coin]
            if pd.notna(p):
                total_value += qty * p

    trade_count = 0
    new_holdings = {}
    new_capital = total_value  # 일단 전부 현금화 가정

    # 매도: 기존 보유 → 현금화 (수수료 차감)
    for coin, qty in holdings.items():
        if qty > 0 and coin in prices.columns and date in prices.index:
            p = prices.loc[date, coin]
            if pd.notna(p) and p > 0:
                sell_value = qty * p
                fee = sell_value * COMMISSION
                # 매도 수수료는 total_value에서 차감
                new_capital = new_capital  # 이미 total_value에 포함
                trade_count += 1

    # 수수료 반영: 매도 턴오버
    sell_turnover = sum(
        qty * prices.loc[date, coin]
        for coin, qty in holdings.items()
        if coin in prices.columns and date in prices.index and pd.notna(prices.loc[date, coin])
    ) if holdings else 0
    new_capital -= sell_turnover * COMMISSION

    # 매수: 목표 비중만큼 투자
    if len(target_weights) > 0:
        invest_amount = new_capital * 0.95  # 최대 투자 비율

        for coin, weight in target_weights.items():
            if coin in prices.columns and date in prices.index:
                p = prices.loc[date, coin]
                if pd.notna(p) and p > 0:
                    buy_amount = invest_amount * weight
                    fee = buy_amount * COMMISSION
                    actual_buy = buy_amount - fee
                    qty = actual_buy / p
                    new_holdings[coin] = qty
                    new_capital -= buy_amount
                    trade_count += 1

    return new_holdings, new_capital, trade_count


# ─────────────────────────────────────────────
# 결과 출력
# ─────────────────────────────────────────────

def print_comparison(results: dict, regime_df: pd.DataFrame,
                     start_date: str, end_date: str):
    """3개 전략 비교 결과를 콘솔에 출력합니다."""

    total_days = len(regime_df.loc[start_date:end_date])
    strategy_names = {"baseline": "Baseline", "selection_1": "선택 1", "selection_2": "선택 2"}

    print()
    print("═" * 60)
    print("  횡보장 대응 전략 비교 백테스트")
    print(f"  기간: {start_date} ~ {end_date} ({total_days}일)")
    print(f"  대상: {len(COINS)}개 코인 | 초기 자본: {INITIAL_CAPITAL:,}원")
    print("═" * 60)

    # 전략별 성과 요약
    print("\n[전략별 성과 요약]")
    print(f"{'─' * 60}")
    header = f"{'지표':<14}"
    for key in ["baseline", "selection_1", "selection_2"]:
        header += f" │ {strategy_names[key]:>10}"
    print(header)
    print(f"{'─' * 60}")

    metrics_rows = []
    for key in ["baseline", "selection_1", "selection_2"]:
        r = results[key]
        eq = r["equity_curve"]
        m = calc_all_metrics(eq)
        metrics_rows.append(m)

    rows = [
        ("누적 수익률", [f"+{m['누적수익률']*100:.1f}%" if m['누적수익률'] >= 0 else f"{m['누적수익률']*100:.1f}%" for m in metrics_rows]),
        ("CAGR", [f"+{m['연환산수익률']*100:.1f}%" if m['연환산수익률'] >= 0 else f"{m['연환산수익률']*100:.1f}%" for m in metrics_rows]),
        ("MDD", [f"{m['MDD']*100:.1f}%" for m in metrics_rows]),
        ("샤프 지수", [f"{m['샤프비율']:.2f}" for m in metrics_rows]),
        ("승률", [f"{r['win_rate']*100:.1f}%" for r in [results[k] for k in ["baseline", "selection_1", "selection_2"]]]),
        ("총 거래수", [f"{r['total_trades']}건" for r in [results[k] for k in ["baseline", "selection_1", "selection_2"]]]),
        ("최종 자산", [f"{r['equity_curve'].iloc[-1]:,.0f}" for r in [results[k] for k in ["baseline", "selection_1", "selection_2"]]]),
    ]

    for label, values in rows:
        line = f"{label:<14}"
        for v in values:
            line += f" │ {v:>10}"
        print(line)
    print(f"{'─' * 60}")

    # 국면별 거래 빈도
    print("\n[국면별 거래 빈도]")
    print(f"{'─' * 60}")
    header = f"{'국면':<14}"
    for key in ["baseline", "selection_1", "selection_2"]:
        header += f" │ {strategy_names[key]:>10}"
    print(header)
    print(f"{'─' * 60}")

    for regime_key, regime_label in [("bull", "상승장 거래"), ("sideways", "횡보장 거래"),
                                      ("extreme_sideways", "극횡보 거래"), ("bear", "하락장 거래")]:
        line = f"{regime_label:<14}"
        for key in ["baseline", "selection_1", "selection_2"]:
            rt = results[key]["regime_trades"]
            val = rt.get(regime_key, 0)
            if regime_key == "extreme_sideways" and key == "selection_2" and val == 0:
                line += f" │ {'0건(현금)':>10}"
            else:
                line += f" │ {f'{val}건':>10}"
        print(line)
    print(f"{'─' * 60}")

    # 국면별 수익 기여도
    print("\n[국면별 수익 기여도]")
    print(f"{'─' * 60}")
    header = f"{'국면':<14}"
    for key in ["baseline", "selection_1", "selection_2"]:
        header += f" │ {strategy_names[key]:>10}"
    print(header)
    print(f"{'─' * 60}")

    for regime_key, regime_label in [("bull", "상승장"), ("sideways", "횡보장"),
                                      ("extreme_sideways", "극횡보"), ("bear", "하락장")]:
        line = f"{regime_label:<14}"
        for key in ["baseline", "selection_1", "selection_2"]:
            pnl = results[key]["regime_pnl"].get(regime_key, 0)
            pnl_pct = pnl / INITIAL_CAPITAL * 100
            if regime_key == "extreme_sideways" and key == "selection_2":
                line += f" │ {'0%(현금)':>10}"
            elif pnl_pct >= 0:
                line += f" │ {f'+{pnl_pct:.1f}%':>10}"
            else:
                line += f" │ {f'{pnl_pct:.1f}%':>10}"
        print(line)
    print(f"{'─' * 60}")

    # 극횡보 비율
    regime_in_range = regime_df.loc[start_date:end_date]
    total = len(regime_in_range)
    extreme_days = ((regime_in_range["regime"] == "sideways") & (regime_in_range["adx"] < 15)).sum()
    sideways_days = (regime_in_range["regime"] == "sideways").sum()
    bull_days = (regime_in_range["regime"] == "bull").sum()
    bear_days = (regime_in_range["regime"] == "bear").sum()

    print(f"\n[국면 분포]")
    print(f"  상승장: {bull_days}일 ({bull_days/total*100:.1f}%)")
    print(f"  횡보장: {sideways_days}일 ({sideways_days/total*100:.1f}%)")
    print(f"    ├ 일반 횡보 (15≤ADX≤25): {sideways_days - extreme_days}일 ({(sideways_days-extreme_days)/total*100:.1f}%)")
    print(f"    └ 극횡보 (ADX<15): {extreme_days}일 ({extreme_days/total*100:.1f}%)")
    print(f"  하락장: {bear_days}일 ({bear_days/total*100:.1f}%)")

    # 결론
    print("\n[결론]")
    best_return = max(results.items(), key=lambda x: x[1]["equity_curve"].iloc[-1])
    best_sharpe = max(results.items(), key=lambda x: calc_sharpe_ratio(x[1]["equity_curve"]))
    print(f"  전체 기간 최우수: {strategy_names[best_return[0]]} (수익률 기준)")
    print(f"  샤프 기준 최우수: {strategy_names[best_sharpe[0]]}")


def print_recent_comparison(results: dict, regime_df: pd.DataFrame,
                            recent_start: str, recent_end: str):
    """최근 1년 성과를 별도로 출력합니다."""
    strategy_names = {"baseline": "Baseline", "selection_1": "선택 1", "selection_2": "선택 2"}

    print(f"\n[최근 구간 성과 ({recent_start} ~ {recent_end})]")
    print(f"{'─' * 60}")
    header = f"{'지표':<14}"
    for key in ["baseline", "selection_1", "selection_2"]:
        header += f" │ {strategy_names[key]:>10}"
    print(header)
    print(f"{'─' * 60}")

    for key in ["baseline", "selection_1", "selection_2"]:
        eq = results[key]["equity_curve"]
        # 최근 구간만 슬라이싱
        recent_eq = eq.loc[recent_start:recent_end]
        if len(recent_eq) < 2:
            continue

    metrics_rows = []
    for key in ["baseline", "selection_1", "selection_2"]:
        eq = results[key]["equity_curve"]
        recent_eq = eq.loc[recent_start:recent_end]
        if len(recent_eq) >= 2:
            m = calc_all_metrics(recent_eq)
        else:
            m = {"누적수익률": 0, "MDD": 0, "샤프비율": 0}
        metrics_rows.append(m)

    rows = [
        ("누적 수익률", [f"+{m['누적수익률']*100:.1f}%" if m['누적수익률'] >= 0 else f"{m['누적수익률']*100:.1f}%" for m in metrics_rows]),
        ("MDD", [f"{m['MDD']*100:.1f}%" for m in metrics_rows]),
        ("샤프 지수", [f"{m['샤프비율']:.2f}" for m in metrics_rows]),
    ]

    for label, values in rows:
        line = f"{label:<14}"
        for v in values:
            line += f" │ {v:>10}"
        print(line)
    print(f"{'─' * 60}")


# ─────────────────────────────────────────────
# CSV / 차트 저장
# ─────────────────────────────────────────────

def save_csv(results: dict, regime_df: pd.DataFrame):
    """일별 자산곡선 + 국면 정보를 CSV로 저장합니다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    path = os.path.join(RESULTS_DIR, f"sideways_comparison_{today}.csv")

    df = pd.DataFrame({
        "baseline_value": results["baseline"]["equity_curve"],
        "selection1_value": results["selection_1"]["equity_curve"],
        "selection2_value": results["selection_2"]["equity_curve"],
    })

    # 국면/ADX 정보 병합
    df = df.join(regime_df[["adx", "regime"]], how="left")
    df.index.name = "date"
    df.to_csv(path)
    logger.info(f"CSV 저장: {path}")
    return path


def save_chart(results: dict, regime_df: pd.DataFrame,
               start_date: str, end_date: str):
    """3개 전략 자산곡선 + 국면 배경색 차트를 저장합니다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    path = os.path.join(RESULTS_DIR, f"sideways_comparison_{today}.png")

    fig, ax = plt.subplots(figsize=(16, 8))

    # 국면 배경색
    regime_colors = {
        "bull": "#d4edda",       # 연녹색
        "sideways": "#fff3cd",   # 연노랑
        "bear": "#f8d7da",       # 연빨강
    }
    regime_in_range = regime_df.loc[start_date:end_date]
    prev_regime = None
    block_start = None

    for date, row in regime_in_range.iterrows():
        r = row["regime"]
        adx_val = row["adx"]
        # 극횡보 구분
        display_regime = r
        if r == "sideways" and adx_val < 15:
            display_regime = "extreme_sideways"

        if display_regime != prev_regime:
            if prev_regime is not None and block_start is not None:
                color = regime_colors.get(prev_regime, "#e2e3e5")
                if prev_regime == "extreme_sideways":
                    color = "#e2e3e5"  # 연회색
                ax.axvspan(block_start, date, alpha=0.3, color=color, linewidth=0)
            block_start = date
            prev_regime = display_regime

    # 마지막 블록
    if prev_regime is not None and block_start is not None:
        color = regime_colors.get(prev_regime, "#e2e3e5")
        if prev_regime == "extreme_sideways":
            color = "#e2e3e5"
        ax.axvspan(block_start, regime_in_range.index[-1], alpha=0.3, color=color, linewidth=0)

    # 자산곡선
    strategy_labels = {
        "baseline": "Baseline (현재)",
        "selection_1": "선택 1 (파라미터 완화)",
        "selection_2": "선택 2 (극횡보 현금)",
    }
    colors_line = {"baseline": "#1f77b4", "selection_1": "#ff7f0e", "selection_2": "#2ca02c"}

    for key in ["baseline", "selection_1", "selection_2"]:
        eq = results[key]["equity_curve"]
        final_ret = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
        label = f"{strategy_labels[key]} ({final_ret:+.1f}%)"
        ax.plot(eq.index, eq.values, label=label, color=colors_line[key], linewidth=1.5)

    ax.set_title("횡보장 대응 전략 비교 백테스트", fontsize=14, pad=15)
    ax.set_xlabel("날짜")
    ax.set_ylabel("자산 (원)")
    ax.legend(loc="upper left", fontsize=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)
    ax.grid(True, alpha=0.3)

    # 범례: 국면 배경색 설명
    from matplotlib.patches import Patch
    legend_patches = [
        Patch(facecolor="#d4edda", alpha=0.5, label="상승장"),
        Patch(facecolor="#fff3cd", alpha=0.5, label="횡보장 (15≤ADX≤25)"),
        Patch(facecolor="#e2e3e5", alpha=0.5, label="극횡보 (ADX<15)"),
        Patch(facecolor="#f8d7da", alpha=0.5, label="하락장"),
    ]
    ax.legend(handles=ax.get_legend_handles_labels()[1] and ax.lines,
              labels=[l.get_label() for l in ax.lines],
              loc="upper left", fontsize=10)
    fig.legend(handles=legend_patches, loc="lower center", ncol=4, fontsize=9,
               bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"차트 저장: {path}")
    return path


# ─────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="횡보장 대응 전략 비교 백테스트")
    parser.add_argument("--strategy", type=str, default=None,
                        choices=["baseline", "selection_1", "selection_2"],
                        help="특정 전략만 실행 (생략 시 전체 비교)")
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("횡보장 대응 전략 비교 백테스트 시작")
    logger.info("=" * 50)

    # 1. 데이터 로드
    logger.info("[1/4] 데이터 로드 중...")
    data = load_data()
    prices = data["prices"]
    volumes = data["volumes"]
    highs = data["highs"]
    lows = data["lows"]

    # 데이터 기간 확인
    data_start = prices.index.min()
    data_end = prices.index.max()
    logger.info(f"  데이터 범위: {data_start.date()} ~ {data_end.date()}")

    # 백테스트 기간 설정 (데이터 범위 내에서 자동 조정)
    bt_start = max(pd.Timestamp("2022-01-01"), data_start + pd.Timedelta(days=90))
    bt_end = min(pd.Timestamp("2024-12-31"), data_end)
    recent_start = max(pd.Timestamp("2024-01-01"), bt_start)
    recent_end = bt_end

    logger.info(f"  백테스트 기간: {bt_start.date()} ~ {bt_end.date()}")

    # 2. ADX 국면 계산
    logger.info("[2/4] ADX 국면 계산 중...")
    regime_df = calc_daily_regimes(highs, lows, prices, ADX_PERIOD)
    logger.info(f"  국면 데이터: {len(regime_df)}일")

    # 국면 분포 미리보기
    regime_in_range = regime_df.loc[str(bt_start):str(bt_end)]
    for r in ["bull", "sideways", "bear"]:
        cnt = (regime_in_range["regime"] == r).sum()
        logger.info(f"  {r}: {cnt}일 ({cnt/len(regime_in_range)*100:.1f}%)")

    # 3. 전략별 시뮬레이션 실행
    logger.info("[3/4] 전략별 시뮬레이션 실행 중...")
    strategies_to_run = (
        {args.strategy: STRATEGIES[args.strategy]} if args.strategy
        else STRATEGIES
    )

    results = {}
    for name, config in strategies_to_run.items():
        logger.info(f"\n  ▶ {name}: {config['설명']}")
        result = run_simulation(
            strategy_name=name,
            config=config,
            prices=prices,
            volumes=volumes,
            regime_df=regime_df,
            start_date=str(bt_start.date()),
            end_date=str(bt_end.date()),
        )
        if result:
            results[name] = result
            eq = result["equity_curve"]
            ret = (eq.iloc[-1] / eq.iloc[0] - 1) * 100
            logger.info(f"    수익률: {ret:+.1f}%, 거래수: {result['total_trades']}건")

    if not results:
        logger.error("실행된 전략이 없습니다")
        return

    # 4. 결과 출력 및 저장
    logger.info("[4/4] 결과 출력 및 저장 중...")

    if len(results) == 3:
        # 전체 비교 출력
        print_comparison(results, regime_df, str(bt_start.date()), str(bt_end.date()))
        print_recent_comparison(results, regime_df, str(recent_start.date()), str(recent_end.date()))

        # CSV 저장
        csv_path = save_csv(results, regime_df)

        # 차트 저장
        chart_path = save_chart(results, regime_df, str(bt_start.date()), str(bt_end.date()))

        print(f"\n  CSV: {csv_path}")
        print(f"  차트: {chart_path}")
    else:
        # 단일 전략 결과
        for name, result in results.items():
            eq = result["equity_curve"]
            m = calc_all_metrics(eq)
            print(f"\n[{name}] {STRATEGIES[name]['설명']}")
            print(f"  누적 수익률: {m['누적수익률']*100:+.1f}%")
            print(f"  CAGR: {m['연환산수익률']*100:+.1f}%")
            print(f"  MDD: {m['MDD']*100:.1f}%")
            print(f"  샤프비율: {m['샤프비율']:.2f}")
            print(f"  총 거래수: {result['total_trades']}건")


if __name__ == "__main__":
    main()
