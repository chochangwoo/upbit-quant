"""
backtest/strategies/_helpers.py - 전략 공통 헬퍼 함수

여러 전략에서 공통으로 사용하는 유틸리티 함수입니다.
"""

import pandas as pd


def volume_filter(volumes: pd.DataFrame, date, columns, quantile: float = 0.2):
    """
    거래량 하위 quantile% 코인을 제외합니다.

    유동성이 너무 낮은 코인은 실제 매매 시 슬리피지가 크므로 제외합니다.

    매개변수:
        volumes : 거래량 데이터
        date    : 기준 날짜
        columns : 대상 코인 컬럼
        quantile: 제외 기준 (기본 하위 20%)
    반환값:
        필터링된 코인 인덱스
    """
    if volumes is None or volumes.empty:
        return columns
    vol_window = min(7, len(volumes.loc[:date]))
    recent_vol = volumes.loc[:date].tail(vol_window).mean()
    recent_vol = recent_vol.reindex(columns).dropna()
    if len(recent_vol) > 2:
        threshold = recent_vol.quantile(quantile)
        return recent_vol[recent_vol >= threshold].index
    return columns


def inverse_volatility_weights(daily_returns: pd.DataFrame, lookback: int) -> pd.Series:
    """
    역변동성 비중을 계산합니다.

    변동성이 낮은 코인일수록 높은 비중을 부여합니다.

    매개변수:
        daily_returns: 일별 수익률 DataFrame
        lookback     : 변동성 계산 기간
    반환값:
        코인별 비중 Series (합계 = 1.0)
    """
    if len(daily_returns) < lookback:
        return pd.Series(dtype=float)
    vol = daily_returns.tail(lookback).std()
    vol = vol[vol > 0]
    if len(vol) == 0:
        return pd.Series(dtype=float)
    inv_vol = 1.0 / vol
    return inv_vol / inv_vol.sum()
