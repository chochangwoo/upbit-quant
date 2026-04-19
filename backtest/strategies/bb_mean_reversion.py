"""
backtest/strategies/bb_mean_reversion.py - 볼린저밴드 평균회귀 전략

전략 설명:
  - 각 코인의 볼린저밴드(20일, 2σ)를 계산합니다.
  - %B 지표(현재가가 밴드 내 어디 위치하는지)로 과매도 판단합니다.
  - %B가 낮을수록(하단밴드 근처) 높은 비중을 부여합니다.
  - 횡보장에서 가격이 밴드 내에서 진동하는 특성을 활용합니다.

원리:
  "횡보장에서 가격은 볼린저밴드 상하단 사이를 오가며 평균으로 회귀한다"
  하단밴드 근처에서 매수하면 중간밴드(평균)까지의 반등으로 수익 기대
"""

import numpy as np
import pandas as pd

from ._helpers import volume_filter


class BBMeanReversion:
    """
    볼린저밴드 평균회귀 전략

    매개변수:
        bb_period : 볼린저밴드 기간 (기본 20일)
        bb_std    : 표준편차 배수 (기본 2.0)
        pct_b_threshold: %B 매수 기준 (기본 0.2 이하면 과매도)
        top_k     : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, bb_period: int = 20, bb_std: float = 2.0,
                 pct_b_threshold: float = 0.2, top_k: int = 5):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.pct_b_threshold = pct_b_threshold
        self.top_k = top_k
        self.name = f"BB평균회귀(P{bb_period}_S{bb_std}_B{pct_b_threshold}_K{top_k})"

    def _calc_pct_b(self, series: pd.Series) -> float:
        """
        %B 지표를 계산합니다.
        %B = (현재가 - 하단밴드) / (상단밴드 - 하단밴드)
        0 이하 = 하단밴드 아래 (극도 과매도)
        0~0.2 = 하단밴드 근처 (과매도)
        0.5 = 중간밴드 (평균)
        1.0 이상 = 상단밴드 위 (과매수)
        """
        if len(series) < self.bb_period:
            return 0.5

        recent = series.tail(self.bb_period)
        middle = recent.mean()
        std = recent.std()

        if std == 0:
            return 0.5

        upper = middle + self.bb_std * std
        lower = middle - self.bb_std * std
        band_width = upper - lower

        if band_width == 0:
            return 0.5

        current_price = series.iloc[-1]
        return (current_price - lower) / band_width

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.bb_period + 5:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]

        # 각 코인의 %B 계산
        pct_b_values = {}
        for coin in available.columns:
            pct_b = self._calc_pct_b(available[coin])
            if pct_b < self.pct_b_threshold:
                # 과매도 코인: %B가 낮을수록 높은 점수
                pct_b_values[coin] = 1.0 - pct_b

        if not pct_b_values:
            # 과매도 코인이 없으면 %B가 가장 낮은 K개 선택
            for coin in available.columns:
                pct_b = self._calc_pct_b(available[coin])
                pct_b_values[coin] = 1.0 - pct_b

        score_series = pd.Series(pct_b_values)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))

        # 점수 비례 비중 (과매도일수록 더 높은 비중)
        total = selected.sum()
        if total <= 0:
            return pd.Series(1.0 / len(selected), index=selected.index)
        return selected / total
