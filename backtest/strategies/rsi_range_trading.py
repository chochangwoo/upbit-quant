"""
backtest/strategies/rsi_range_trading.py - RSI 레인지 트레이딩 전략

전략 설명:
  - 횡보장에서 RSI가 예측 가능하게 진동하는 특성을 활용합니다.
  - RSI가 과매도 구간(기본 35 이하)인 코인에 집중 투자합니다.
  - RSI 값에 반비례하여 비중을 배분합니다 (RSI 낮을수록 더 많이 매수).
  - 기존 RSI역추세와 차이: 동일비중이 아닌 RSI 반비례 가중 + 완화된 임계값

원리:
  "횡보장에서 RSI 30 이하로 떨어진 코인은 높은 확률로 반등한다"
  추세장에서는 RSI가 한 방향으로 쏠리지만, 횡보장에서는 30~70 사이를 진동
"""

import pandas as pd

from ._helpers import volume_filter


class RSIRangeTrading:
    """
    RSI 레인지 트레이딩 전략

    매개변수:
        rsi_period    : RSI 계산 기간 (기본 14일)
        oversold      : 과매도 임계값 (기본 35)
        overbought    : 과매수 임계값 (기본 65) — 이 위의 코인은 제외
        top_k         : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, rsi_period: int = 14, oversold: int = 35,
                 overbought: int = 65, top_k: int = 5):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.top_k = top_k
        self.name = f"RSI레인지(P{rsi_period}_OS{oversold}_OB{overbought}_K{top_k})"

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
        if available.shape[1] == 0 or len(available) < self.rsi_period + 5:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]

        # 각 코인의 RSI 계산
        candidates = {}
        for coin in available.columns:
            rsi = self._calc_rsi(available[coin])
            # 과매수 코인은 제외, 과매도 코인에 집중
            if rsi < self.overbought:
                if rsi <= self.oversold:
                    # 과매도: RSI가 낮을수록 높은 점수 (반비례 가중)
                    candidates[coin] = max(1.0, self.oversold - rsi + 1)
                else:
                    # 중립 구간: 낮은 점수
                    candidates[coin] = 0.5

        if not candidates:
            # 후보가 없으면 RSI가 가장 낮은 K개
            for coin in available.columns:
                rsi = self._calc_rsi(available[coin])
                candidates[coin] = max(0.1, 100 - rsi)

        score_series = pd.Series(candidates)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))

        # 점수 비례 비중
        total = selected.sum()
        if total <= 0:
            return pd.Series(1.0 / len(selected), index=selected.index)
        return selected / total
