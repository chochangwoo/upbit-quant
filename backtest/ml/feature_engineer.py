"""
backtest/ml/feature_engineer.py - ML 피처 엔지니어링

OHLCV 가격 데이터 + 대안 데이터를 결합하여
LightGBM 학습에 사용할 피처 매트릭스를 생성합니다.

피처 카테고리:
  1. 모멘텀 피처: 다기간 수익률, 순위
  2. 기술적 지표: RSI, MACD, 볼린저밴드, ATR
  3. 거래량 피처: 거래량 비율, OBV 추세
  4. 변동성 피처: 다기간 변동성, 변동성 비율
  5. 대안 데이터: 공포탐욕, BTC 도미넌스, 펀딩비율
"""

import numpy as np
import pandas as pd
from loguru import logger


def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI(상대강도지수) 계산"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 계산 → (macd_line, signal_line, histogram)"""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _calc_bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    """볼린저밴드 → (upper, middle, lower, %B, bandwidth)"""
    middle = series.rolling(period, min_periods=period).mean()
    std = series.rolling(period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    pct_b = (series - lower) / (upper - lower)
    bandwidth = (upper - lower) / middle
    return upper, middle, lower, pct_b, bandwidth


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR(평균진폭) 계산"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def build_coin_features(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    coin: str,
    alt_data: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    단일 코인에 대한 전체 피처를 생성합니다.

    매개변수:
        prices  : 전체 가격 DataFrame
        volumes : 전체 거래량 DataFrame
        coin    : 코인 티커 (예: "KRW-BTC")
        alt_data: 대안 데이터 DataFrame (공포탐욕 + 온체인 + 펀딩비율)
    반환값:
        DataFrame (index: dates, columns: 피처들)
    """
    if coin not in prices.columns:
        return pd.DataFrame()

    close = prices[coin].dropna()
    vol = volumes[coin].dropna() if coin in volumes.columns else pd.Series(dtype=float)

    if len(close) < 60:
        return pd.DataFrame()

    features = pd.DataFrame(index=close.index)

    # ── 1. 모멘텀 피처 ──────────────────────────────
    for period in [1, 3, 5, 7, 14, 21, 30, 60]:
        features[f"ret_{period}d"] = close.pct_change(period)

    # 모멘텀 가속도 (단기 모멘텀 - 장기 모멘텀)
    features["mom_accel"] = features["ret_7d"] - features["ret_30d"]

    # 수익률 순위 (cross-sectional: 다른 코인 대비 순위)
    for period in [7, 14, 30]:
        all_returns = prices.pct_change(period)
        rank = all_returns.rank(axis=1, pct=True)
        if coin in rank.columns:
            features[f"rank_{period}d"] = rank[coin]

    # ── 2. 기술적 지표 ──────────────────────────────
    # RSI
    features["rsi_14"] = _calc_rsi(close, 14)
    features["rsi_7"] = _calc_rsi(close, 7)

    # MACD
    macd_line, signal_line, histogram = _calc_macd(close)
    features["macd"] = macd_line / close * 100  # 가격 대비 정규화
    features["macd_signal"] = signal_line / close * 100
    features["macd_hist"] = histogram / close * 100

    # 볼린저밴드
    _, _, _, pct_b, bandwidth = _calc_bollinger(close)
    features["bb_pctb"] = pct_b
    features["bb_bandwidth"] = bandwidth

    # 이동평균 대비 위치
    for ma_period in [5, 10, 20, 60]:
        ma = close.rolling(ma_period, min_periods=ma_period).mean()
        features[f"price_vs_ma{ma_period}"] = (close - ma) / ma

    # MA 크로스 신호
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    features["ma_cross_5_20"] = (ma5 > ma20).astype(int)
    features["ma_dist_5_20"] = (ma5 - ma20) / ma20

    # ── 3. 거래량 피처 ──────────────────────────────
    if len(vol) > 0:
        vol_aligned = vol.reindex(close.index)
        features["vol_ratio_5_20"] = (
            vol_aligned.rolling(5, min_periods=1).mean()
            / vol_aligned.rolling(20, min_periods=1).mean()
        )
        features["vol_change_1d"] = vol_aligned.pct_change(1)
        features["vol_change_5d"] = vol_aligned.pct_change(5)

        # OBV 추세 (On-Balance Volume)
        price_direction = np.sign(close.diff())
        obv = (vol_aligned * price_direction).cumsum()
        obv_ma = obv.rolling(20, min_periods=1).mean()
        features["obv_trend"] = np.where(obv > obv_ma, 1, -1)
    else:
        features["vol_ratio_5_20"] = 0
        features["vol_change_1d"] = 0
        features["vol_change_5d"] = 0
        features["obv_trend"] = 0

    # ── 4. 변동성 피처 ──────────────────────────────
    daily_ret = close.pct_change()
    for period in [5, 14, 30, 60]:
        features[f"volatility_{period}d"] = daily_ret.rolling(period, min_periods=period).std()

    # 변동성 비율 (단기 vs 장기) → 변동성 브레이크아웃 감지
    features["vol_ratio_5_30"] = features["volatility_5d"] / features["volatility_30d"].replace(0, np.nan)

    # 고가-저가 범위 (당일 변동폭)
    features["daily_range"] = daily_ret.abs()

    # ── 5. 대안 데이터 피처 (있을 때만) ──────────────
    if alt_data is not None and not alt_data.empty:
        alt_aligned = alt_data.reindex(features.index, method="ffill")
        for col in alt_data.columns:
            features[col] = alt_aligned[col]

    return features


def build_multi_coin_features(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    coins: list = None,
    alt_data: pd.DataFrame = None,
) -> dict:
    """
    여러 코인에 대한 피처를 생성합니다.

    반환값:
        {코인: 피처 DataFrame} 딕셔너리
    """
    if coins is None:
        coins = prices.columns.tolist()

    result = {}
    for coin in coins:
        features = build_coin_features(prices, volumes, coin, alt_data)
        if not features.empty:
            result[coin] = features
            logger.debug(f"[피처] {coin}: {features.shape[1]}개 피처, {len(features)}일")

    logger.info(f"[피처] 전체 {len(result)}개 코인 피처 생성 완료")
    return result


def build_training_dataset(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    coins: list = None,
    alt_data: pd.DataFrame = None,
    target_horizon: int = 5,
    target_type: str = "binary",
) -> tuple:
    """
    전체 코인의 피처와 타겟을 결합한 학습 데이터셋을 생성합니다.

    매개변수:
        prices         : 가격 데이터
        volumes        : 거래량 데이터
        coins          : 대상 코인 리스트
        alt_data       : 대안 데이터
        target_horizon : 미래 수익률 계산 기간 (일)
        target_type    : "binary" (상승=1/하락=0) 또는 "regression" (수익률)
    반환값:
        (X, y, meta) 튜플
        - X   : 피처 DataFrame (NaN 제거 후)
        - y   : 타겟 Series
        - meta: 메타 정보 DataFrame (date, coin)
    """
    all_features = build_multi_coin_features(prices, volumes, coins, alt_data)

    X_list, y_list, meta_list = [], [], []

    for coin, feat_df in all_features.items():
        # 미래 수익률 (타겟) 계산
        close = prices[coin]
        future_return = close.shift(-target_horizon) / close - 1

        # 피처와 타겟을 정렬
        common_idx = feat_df.index.intersection(future_return.dropna().index)
        if len(common_idx) < 30:
            continue

        X_coin = feat_df.loc[common_idx]
        y_coin = future_return.loc[common_idx]

        if target_type == "binary":
            y_coin = (y_coin > 0).astype(int)

        # 메타 정보
        meta_coin = pd.DataFrame({
            "date": common_idx,
            "coin": coin,
        }, index=common_idx)

        X_list.append(X_coin)
        y_list.append(y_coin)
        meta_list.append(meta_coin)

    if not X_list:
        return pd.DataFrame(), pd.Series(dtype=float), pd.DataFrame()

    X = pd.concat(X_list, axis=0)
    y = pd.concat(y_list, axis=0)
    meta = pd.concat(meta_list, axis=0)

    # NaN/Inf 제거
    valid_mask = X.notna().all(axis=1) & y.notna() & ~np.isinf(X).any(axis=1)
    X = X[valid_mask]
    y = y[valid_mask]
    meta = meta[valid_mask]

    logger.info(
        f"[데이터셋] 학습 데이터 생성: {X.shape[0]}행 × {X.shape[1]}열 | "
        f"타겟 비율: {y.mean():.1%} (상승)"
    )

    return X, y, meta
