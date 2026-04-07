"""
backtest/regime/sideways_filter.py - 횡보장 일별 마스크 생성 모듈

기존 ADX 단일 기준(run_sideways_comparison.calc_daily_regimes) 대비
세 가지 지표를 합성하여 더 보수적인 횡보 구간을 식별합니다.

판별 로직 (BTC 기준):
  1. ADX < adx_trend_threshold (추세 강도 약함)
  2. BB-width(20) 가 직전 lookback 분위 하위 bbw_quantile 이하
     (변동성 수축 — squeeze 직전 상태)
  3. 20봉 (high.max - low.min) < ATR(14) * range_atr_mult
     (가격 박스권 폭이 평균 변동성 대비 좁음)

→ ADX 약세 AND (BB-width 수축 OR 박스권 폭 좁음) → True (횡보)
"""

import numpy as np
import pandas as pd


def _calc_adx_series(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.DataFrame:
    """
    Wilder ADX/+DI/-DI 시리즈를 계산합니다.

    run_sideways_comparison.calc_daily_regimes 의 ADX 계산 블록과
    동일한 공식 — 중복 제거 목적으로 함수화했습니다.

    반환값:
        DataFrame[adx, plus_di, minus_di] (NaN 행 제거 전 원본)
    """
    common_idx = high.index.intersection(low.index).intersection(close.index)
    high = high.loc[common_idx]
    low = low.loc[common_idx]
    close = close.loc[common_idx]

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

    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1 / period, min_periods=period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1 / period, min_periods=period).mean()

    plus_di = 100 * plus_dm_smooth / atr
    minus_di = 100 * minus_dm_smooth / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    return pd.DataFrame({"adx": adx, "plus_di": plus_di, "minus_di": minus_di})


def _calc_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Wilder ATR (단순화 — EWM 평균 사용)."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def build_sideways_mask(
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    btc_col: str = "KRW-BTC",
    adx_period: int = 14,
    adx_trend_threshold: float = 25.0,
    bb_period: int = 20,
    bbw_lookback: int = 252,
    bbw_quantile: float = 0.20,
    range_window: int = 20,
    atr_period: int = 14,
    range_atr_mult: float = 1.5,
) -> pd.Series:
    """
    BTC 일봉 OHLC를 기반으로 일자별 sideways 여부(bool) 시리즈를 만듭니다.

    매개변수:
        highs/lows/closes : 코인×일자 OHLC DataFrame
        btc_col           : 기준 코인 컬럼명
        adx_period        : ADX 계산 기간
        adx_trend_threshold : ADX 미만이면 약추세
        bb_period         : 볼린저 밴드 이동평균 기간
        bbw_lookback      : BB-width 분위수 계산 윈도우
        bbw_quantile      : 하위 분위 임계값 (0.20 = 하위 20%)
        range_window      : (high.max - low.min) 박스 폭 계산 봉수
        atr_period        : ATR 계산 기간
        range_atr_mult    : 박스 폭 기준 (range < ATR * mult)

    반환값:
        bool Series (인덱스: 날짜) — True 면 횡보장
    """
    if btc_col not in closes.columns:
        raise ValueError(f"기준 코인 {btc_col} 이 closes 에 없습니다")

    high = highs[btc_col].dropna()
    low = lows[btc_col].dropna()
    close = closes[btc_col].dropna()

    # 1) ADX 약추세 마스크
    adx_df = _calc_adx_series(high, low, close, period=adx_period)
    adx_low = adx_df["adx"] < adx_trend_threshold

    # 2) BB-width 수축 마스크
    mid = close.rolling(bb_period).mean()
    std = close.rolling(bb_period).std()
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std
    bbw = (upper - lower) / mid
    bbw_threshold = bbw.rolling(bbw_lookback, min_periods=bb_period * 2).quantile(
        bbw_quantile
    )
    bbw_low = bbw <= bbw_threshold

    # 3) 박스권 폭 마스크
    box_range = high.rolling(range_window).max() - low.rolling(range_window).min()
    atr = _calc_atr(high, low, close, period=atr_period)
    range_low = box_range < (atr * range_atr_mult)

    # 합성: ADX 약 AND (BB 수축 OR 박스 좁음)
    common = adx_low.index.intersection(bbw_low.index).intersection(range_low.index)
    mask = adx_low.loc[common] & (bbw_low.loc[common] | range_low.loc[common])
    mask = mask.fillna(False).astype(bool)
    mask.name = "sideways"
    return mask
