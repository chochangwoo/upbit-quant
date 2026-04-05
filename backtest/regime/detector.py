"""
backtest/regime/detector.py - 시장 국면 감지 모듈

3가지 방법으로 시장 국면(Bull/Bear/Sideways)을 분류합니다:

  방법 1. 규칙 기반: BTC 수동 구간 지정
  방법 2. 지표 기반: SMA + ATR 자동 분류 (권장)
  방법 3. ML 기반: K-Means 클러스터링

국면 정의:
  - Bull (상승장)  : 가격 > SMA50, 20일 수익률 > +10%
  - Bear (하락장)  : 가격 < SMA50, 20일 수익률 < -10%
  - Sideways (횡보장): ATR% 낮고, 방향성 불명확
"""

import numpy as np
import pandas as pd
from loguru import logger


# ═══════════════════════════════════════════════════════
# 방법 1: 규칙 기반 (수동 구간 지정)
# ═══════════════════════════════════════════════════════

# BTC 역사적 시장 국면 (수동 레이블링)
MANUAL_REGIMES = [
    ("2019-01-01", "2020-09-30", "sideways"),
    ("2020-10-01", "2021-11-10", "bull"),
    ("2021-11-11", "2022-12-31", "bear"),
    ("2023-01-01", "2023-09-30", "sideways"),
    ("2023-10-01", "2024-03-15", "bull"),
    ("2024-03-16", "2024-08-31", "sideways"),
    ("2024-09-01", "2024-12-31", "bull"),
    ("2025-01-01", "2025-03-31", "bear"),
    ("2025-04-01", "2025-09-30", "sideways"),
    ("2025-10-01", "2026-01-15", "bull"),
    ("2026-01-16", "2026-12-31", "bear"),
]


def classify_manual(dates: pd.DatetimeIndex) -> pd.Series:
    """
    수동 정의된 구간으로 국면을 분류합니다.

    반환값:
        pd.Series (index: dates, values: "bull"/"bear"/"sideways")
    """
    regimes = pd.Series("sideways", index=dates)

    for start, end, regime in MANUAL_REGIMES:
        start_dt = pd.Timestamp(start)
        end_dt = pd.Timestamp(end)
        mask = (dates >= start_dt) & (dates <= end_dt)
        regimes[mask] = regime

    return regimes


# ═══════════════════════════════════════════════════════
# 방법 2: 지표 기반 (SMA + ATR 자동 분류) — 권장
# ═══════════════════════════════════════════════════════

def _calc_atr(high, low, close, period=14):
    """ATR(평균진폭) 계산"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def classify_indicator(
    btc_prices: pd.DataFrame,
    sma_window: int = 50,
    atr_window: int = 14,
    momentum_window: int = 20,
    bull_threshold: float = 0.10,
    bear_threshold: float = -0.10,
    atr_pct_threshold: float = 0.03,
) -> pd.Series:
    """
    SMA + ATR + 모멘텀 기반으로 국면을 자동 분류합니다.

    분류 규칙:
      1. 모멘텀 = (현재가 / N일 전 가격) - 1
      2. SMA 위치 = 현재가 > SMA50 여부
      3. ATR% = ATR / 현재가 (변동성 수준)

      Bull : 가격 > SMA AND 모멘텀 > +bull_threshold
      Bear : 가격 < SMA AND 모멘텀 < bear_threshold
      Sideways: 그 외 (또는 ATR% < threshold)

    매개변수:
        btc_prices        : BTC OHLCV DataFrame (close 필수, high/low 선택)
        sma_window        : SMA 기간 (기본 50일)
        atr_window        : ATR 기간 (기본 14일)
        momentum_window   : 모멘텀 계산 기간 (기본 20일)
        bull_threshold    : 상승장 판단 모멘텀 기준 (+10%)
        bear_threshold    : 하락장 판단 모멘텀 기준 (-10%)
        atr_pct_threshold : 횡보 판단 ATR% 기준 (3%)
    반환값:
        pd.Series (index: dates, values: "bull"/"bear"/"sideways")
    """
    if isinstance(btc_prices, pd.Series):
        close = btc_prices
        high = close
        low = close
    elif "close" in btc_prices.columns:
        close = btc_prices["close"]
        high = btc_prices.get("high", close)
        low = btc_prices.get("low", close)
    else:
        close = btc_prices.iloc[:, 0]
        high = close
        low = close

    # 지표 계산
    sma = close.rolling(sma_window, min_periods=sma_window).mean()
    momentum = close / close.shift(momentum_window) - 1
    atr = _calc_atr(high, low, close, atr_window)
    atr_pct = atr / close

    # 국면 분류
    regimes = pd.Series("sideways", index=close.index)

    # Bull: 가격 > SMA AND 강한 상승 모멘텀
    bull_mask = (close > sma) & (momentum > bull_threshold)
    regimes[bull_mask] = "bull"

    # Bear: 가격 < SMA AND 강한 하락 모멘텀
    bear_mask = (close < sma) & (momentum < bear_threshold)
    regimes[bear_mask] = "bear"

    # 초기 NaN 구간은 sideways로 처리
    nan_mask = sma.isna() | momentum.isna()
    regimes[nan_mask] = "sideways"

    return regimes


# ═══════════════════════════════════════════════════════
# 방법 3: ML 기반 (K-Means 클러스터링)
# ═══════════════════════════════════════════════════════

def classify_kmeans(
    btc_prices: pd.Series,
    n_clusters: int = 3,
    features_window: int = 20,
) -> pd.Series:
    """
    K-Means로 수익률-변동성 공간에서 국면을 분류합니다.

    피처:
      - 20일 수익률 (모멘텀)
      - 20일 변동성 (리스크)

    클러스터를 수익률 기준으로 Bull/Sideways/Bear에 매핑합니다.

    매개변수:
        btc_prices      : BTC 종가 Series
        n_clusters      : 클러스터 수 (기본 3)
        features_window : 피처 계산 기간
    반환값:
        pd.Series (index: dates, values: "bull"/"bear"/"sideways")
    """
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        logger.warning("[국면] scikit-learn 미설치, 지표 기반으로 대체")
        return classify_indicator(btc_prices)

    # 피처 계산
    returns = btc_prices.pct_change(features_window)
    volatility = btc_prices.pct_change().rolling(features_window).std()

    features = pd.DataFrame({
        "return": returns,
        "volatility": volatility,
    }).dropna()

    if len(features) < n_clusters * 10:
        logger.warning("[국면] 데이터 부족, 지표 기반으로 대체")
        return classify_indicator(btc_prices)

    # 스케일링 + K-Means
    scaler = StandardScaler()
    X = scaler.fit_transform(features)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)

    # 클러스터를 수익률 기준으로 매핑
    cluster_returns = {}
    for c in range(n_clusters):
        mask = labels == c
        cluster_returns[c] = features["return"][mask].mean()

    sorted_clusters = sorted(cluster_returns.items(), key=lambda x: x[1])
    regime_map = {
        sorted_clusters[0][0]: "bear",
        sorted_clusters[1][0]: "sideways",
        sorted_clusters[2][0]: "bull",
    }

    regimes = pd.Series("sideways", index=btc_prices.index)
    for i, date in enumerate(features.index):
        regimes[date] = regime_map[labels[i]]

    return regimes


# ═══════════════════════════════════════════════════════
# 통합 인터페이스
# ═══════════════════════════════════════════════════════

def detect_regimes(
    btc_prices,
    method: str = "indicator",
    **kwargs,
) -> pd.Series:
    """
    시장 국면을 감지합니다.

    매개변수:
        btc_prices: BTC 가격 데이터 (Series 또는 DataFrame)
        method    : "manual", "indicator" (권장), "kmeans"
    반환값:
        pd.Series (index: dates, values: "bull"/"bear"/"sideways")
    """
    if method == "manual":
        if isinstance(btc_prices, pd.Series):
            dates = btc_prices.index
        else:
            dates = btc_prices.index
        regimes = classify_manual(dates)

    elif method == "indicator":
        regimes = classify_indicator(btc_prices, **kwargs)

    elif method == "kmeans":
        if isinstance(btc_prices, pd.DataFrame):
            prices_series = btc_prices["close"] if "close" in btc_prices.columns else btc_prices.iloc[:, 0]
        else:
            prices_series = btc_prices
        regimes = classify_kmeans(prices_series, **kwargs)

    else:
        raise ValueError(f"알 수 없는 방법: {method}")

    # 통계 출력
    counts = regimes.value_counts()
    total = len(regimes)
    logger.info(f"[국면감지] 방법: {method}")
    for regime in ["bull", "sideways", "bear"]:
        n = counts.get(regime, 0)
        logger.info(f"  {regime:>8s}: {n:>4d}일 ({n/total:>5.1%})")

    return regimes
