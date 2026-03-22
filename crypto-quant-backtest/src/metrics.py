"""
백테스트 성과 지표 계산 모듈

- 누적/연환산 수익률, 변동성
- 샤프 비율, 소르티노 비율
- MDD, 칼마 비율
- 승률 등
"""

import numpy as np
import pandas as pd


def calc_cumulative_return(equity_curve: pd.Series) -> float:
    """누적 수익률"""
    if len(equity_curve) < 2:
        return 0.0
    return equity_curve.iloc[-1] / equity_curve.iloc[0] - 1


def calc_annual_return(equity_curve: pd.Series) -> float:
    """연환산 수익률 (CAGR)"""
    if len(equity_curve) < 2:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0]
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    if days <= 0:
        return 0.0
    return total_return ** (365.0 / days) - 1


def calc_annual_volatility(equity_curve: pd.Series) -> float:
    """연환산 변동성"""
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) < 2:
        return 0.0
    return daily_returns.std() * np.sqrt(365)


def calc_sharpe_ratio(equity_curve: pd.Series, risk_free: float = 0.0) -> float:
    """샤프 비율 (무위험수익률 0%)"""
    ann_ret = calc_annual_return(equity_curve)
    ann_vol = calc_annual_volatility(equity_curve)
    if ann_vol == 0:
        return 0.0
    return (ann_ret - risk_free) / ann_vol


def calc_sortino_ratio(equity_curve: pd.Series, risk_free: float = 0.0) -> float:
    """소르티노 비율 (하방 변동성만 사용)"""
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
    """최대 낙폭 (MDD) - 음수로 반환"""
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return drawdown.min()


def calc_calmar_ratio(equity_curve: pd.Series) -> float:
    """칼마 비율 (연수익률 / |MDD|)"""
    ann_ret = calc_annual_return(equity_curve)
    mdd = calc_mdd(equity_curve)
    if mdd == 0:
        return 0.0
    return ann_ret / abs(mdd)


def calc_daily_win_rate(equity_curve: pd.Series) -> float:
    """일별 승률"""
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) == 0:
        return 0.0
    return (daily_returns > 0).mean()


def calc_all_metrics(equity_curve: pd.Series) -> dict:
    """전체 성과 지표를 한번에 계산"""
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
    """단일 윈도우(OOS)에 대한 지표 계산"""
    return {
        "수익률": calc_cumulative_return(equity_curve),
        "샤프비율": calc_sharpe_ratio(equity_curve),
        "MDD": calc_mdd(equity_curve),
    }


def classify_regime(btc_prices: pd.Series, date: pd.Timestamp, lookback: int = 30) -> str:
    """
    BTC 가격 기준으로 시장 레짐을 분류한다.
    - BTC 30일 수익률 > +10%: 불장
    - BTC 30일 수익률 < -10%: 하락장
    - 그 외: 횡보
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
