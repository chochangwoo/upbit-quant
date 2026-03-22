"""
backtest/strategies/rsi_mean_reversion.py - RSI 역추세 전략

전략 설명:
  - 각 코인의 RSI(상대강도지수)를 계산합니다.
  - RSI가 threshold 이하인 과매도 코인을 매수합니다.
  - 과매도 상태에서 반등을 노리는 역추세(Mean Reversion) 전략입니다.

원리:
  "급격히 하락한 코인은 반등할 가능성이 높다"
  RSI가 낮을수록 과매도 상태 -> 반등 기대치가 높음
"""

import pandas as pd

from ._helpers import volume_filter


class RSIMeanReversion:
    """
    RSI 역추세 전략

    매개변수:
        rsi_period: RSI 계산 기간 (기본 14일)
        threshold : RSI 과매도 기준 (기본 40 이하면 매수 후보)
        top_k     : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, rsi_period: int = 14, threshold: int = 40, top_k: int = 5):
        self.rsi_period = rsi_period
        self.threshold = threshold
        self.top_k = top_k
        self.name = f"RSI역추세(P{rsi_period}_T{threshold}_K{top_k})"

    def _calc_rsi(self, series: pd.Series) -> float:
        """단일 코인의 RSI를 계산합니다."""
        delta = series.diff().dropna()
        if len(delta) < self.rsi_period:
            return 50.0
        gain = delta.where(delta > 0, 0.0).tail(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).tail(self.rsi_period).mean()
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.rsi_period + 1:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]

        # 각 코인의 RSI 계산
        rsi_values = {}
        for coin in available.columns:
            rsi = self._calc_rsi(available[coin])
            if rsi < self.threshold:
                rsi_values[coin] = rsi

        if not rsi_values:
            # 과매도 코인이 없으면 RSI가 가장 낮은 K개 선택
            for coin in available.columns:
                rsi_values[coin] = self._calc_rsi(available[coin])

        rsi_series = pd.Series(rsi_values)
        # RSI 낮은 순서로 K개 선택 (과매도 = 반등 기대)
        selected = rsi_series.nsmallest(min(self.top_k, len(rsi_series)))
        return pd.Series(1.0 / len(selected), index=selected.index)
