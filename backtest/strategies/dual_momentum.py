"""
backtest/strategies/dual_momentum.py - 듀얼 모멘텀 전략

전략 설명:
  - 장기 모멘텀(60일)으로 상승 추세인 코인만 필터링
  - 단기 모멘텀(7~14일)으로 그 중 순위를 매김
  - 장기 상승 + 단기 강세인 코인 상위 K개에 동일비중 투자

원리:
  "큰 추세가 상승인 코인 중에서 최근 모멘텀이 강한 것을 선택"
  장기 필터로 하락장 코인을 걸러내고, 단기로 타이밍을 잡습니다.
"""

import pandas as pd

from ._helpers import volume_filter


class DualMomentum:
    """
    듀얼 모멘텀 전략

    매개변수:
        short_lookback: 단기 모멘텀 기간 (기본 7일)
        long_lookback : 장기 모멘텀 기간 (기본 60일)
        top_k         : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, short_lookback: int = 7, long_lookback: int = 60, top_k: int = 5):
        self.short_lookback = short_lookback
        self.long_lookback = long_lookback
        self.top_k = top_k
        self.name = f"듀얼모멘텀(S{short_lookback}_L{long_lookback}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.long_lookback:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0 or len(available) < self.long_lookback:
            return pd.Series(dtype=float)

        # 장기 모멘텀 필터: > 0 (상승 추세)
        long_mom = available.iloc[-1] / available.iloc[-self.long_lookback] - 1
        uptrend = long_mom[long_mom > 0].index

        if len(uptrend) == 0:
            # 상승 추세 코인이 없으면 장기 모멘텀 상위 절반
            uptrend = long_mom.nlargest(max(1, len(long_mom) // 2)).index

        # 단기 모멘텀으로 순위
        short_mom = available[uptrend].iloc[-1] / available[uptrend].iloc[-self.short_lookback] - 1
        short_mom = short_mom.dropna()
        if len(short_mom) == 0:
            return pd.Series(dtype=float)

        selected = short_mom.nlargest(min(self.top_k, len(short_mom)))
        return pd.Series(1.0 / len(selected), index=selected.index)
