"""
backtest/metrics.py - 백테스트 성과 지표 계산 모듈

8가지 성과 지표를 계산합니다:
  1. 누적 수익률
  2. 연환산 수익률 (CAGR)
  3. 연환산 변동성
  4. 샤프 비율
  5. 소르티노 비율 (하방 위험만 고려)
  6. MDD (최대 낙폭)
  7. 칼마 비율 (수익/위험 비율)
  8. 일별 승률

추가로 BTC 30일 수익률 기준 시장 레짐(불장/횡보/하락장) 분류 기능을 제공합니다.
"""

import numpy as np
import pandas as pd


def calc_cumulative_return(equity_curve: pd.Series) -> float:
    """누적 수익률: (최종값 / 초기값) - 1"""
    if len(equity_curve) < 2:
        return 0.0
    return equity_curve.iloc[-1] / equity_curve.iloc[0] - 1


def calc_annual_return(equity_curve: pd.Series) -> float:
    """연환산 수익률 (CAGR): 복리 기준 연평균 수익률"""
    if len(equity_curve) < 2:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    if days <= 0:
        return 0.0
    return total_return ** (365.0 / days) - 1


def calc_annual_volatility(equity_curve: pd.Series) -> float:
    """연환산 변동성: 일별 수익률 표준편차 x sqrt(365)"""
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) < 2:
        return 0.0
    return daily_returns.std() * np.sqrt(365)


def calc_sharpe_ratio(equity_curve: pd.Series, risk_free: float = 0.0) -> float:
    """
    샤프 비율: 위험 대비 수익성
    1.0 이상 양호, 2.0 이상 우수
    """
    ann_ret = calc_annual_return(equity_curve)
    ann_vol = calc_annual_volatility(equity_curve)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - risk_free) / ann_vol


def calc_sortino_ratio(equity_curve: pd.Series, risk_free: float = 0.0) -> float:
    """
    소르티노 비율: 하방 변동성만 사용 (하락 위험 대비 수익성)
    샤프 비율보다 더 공정한 평가 — 상승 변동성은 좋은 것이므로 제외
    """
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) < 2:
        return 0.0
    downside = daily_returns[daily_returns < 0]
    if len(downside) == 0:
        return float("inf")
    downside_std = downside.std() * np.sqrt(365)
    if downside_std == 0:
        return 0.0
    ann_ret = calc_annual_return(equity_curve)
    return (ann_ret - risk_free) / downside_std


def calc_mdd(equity_curve: pd.Series) -> float:
    """MDD (최대 낙폭): 고점 대비 최대 하락폭 (음수로 반환)"""
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return drawdown.min()


def calc_calmar_ratio(equity_curve: pd.Series) -> float:
    """칼마 비율: 연수익률 / |MDD| — 리스크 대비 수익 효율"""
    ann_ret = calc_annual_return(equity_curve)
    mdd = calc_mdd(equity_curve)
    if mdd == 0:
        return 0.0
    return ann_ret / abs(mdd)


def calc_daily_win_rate(equity_curve: pd.Series) -> float:
    """일별 승률: 수익이 난 날의 비율"""
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) == 0:
        return 0.0
    return (daily_returns > 0).mean()


def calc_all_metrics(equity_curve: pd.Series) -> dict:
    """전체 8가지 성과 지표를 한 번에 계산하여 딕셔너리로 반환합니다."""
    return {
        "누적수익률": calc_cumulative_return(equity_curve),
        "연환산수익률": calc_annual_return(equity_curve),
        "연환산변동성": calc_annual_volatility(equity_curve),
        "샤프비율": calc_sharpe_ratio(equity_curve),
        "소르티노비율": calc_sortino_ratio(equity_curve),
        "MDD": calc_mdd(equity_curve),
        "칼마비율": calc_calmar_ratio(equity_curve),
        "일별승률": calc_daily_win_rate(equity_curve),
    }


def calc_window_metrics(equity_curve: pd.Series) -> dict:
    """단일 윈도우(OOS)에 대한 간단 지표 계산"""
    return {
        "수익률": calc_cumulative_return(equity_curve),
        "샤프비율": calc_sharpe_ratio(equity_curve),
        "MDD": calc_mdd(equity_curve),
    }


def classify_regime(btc_prices: pd.Series, date: pd.Timestamp, lookback: int = 30) -> str:
    """
    BTC 가격 기준으로 시장 레짐을 분류합니다.

    분류 기준 (BTC 30일 수익률):
      - +10% 이상: 불장 (강한 상승)
      - -10% 이하: 하락장 (강한 하락)
      - 그 사이: 횡보 (방향성 불명확)

    매개변수:
        btc_prices: BTC 가격 Series
        date      : 기준 날짜
        lookback  : 수익률 계산 기간 (기본 30일)
    반환값:
        "불장", "하락장", "횡보" 중 하나
    """
    btc_data = btc_prices.loc[:date].dropna()
    if len(btc_data) < lookback:
        return "횡보"

    ret_30d = btc_data.iloc[-1] / btc_data.iloc[-lookback] - 1
    if ret_30d > 0.10:
        return "불장"
    elif ret_30d < -0.10:
        return "하락장"
    else:
        return "횡보"
