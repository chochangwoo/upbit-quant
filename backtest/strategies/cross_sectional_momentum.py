"""
backtest/strategies/cross_sectional_momentum.py - 크로스섹셔널 모멘텀 전략

전략 설명:
  - 최근 N일 수익률 기준으로 코인들의 순위를 매기고
  - 상위 K개 코인에 동일비중으로 투자합니다.
  - 거래량 필터: 최근 7일 평균 거래량 하위 20% 코인은 제외합니다.

원리:
  "최근에 많이 오른 코인은 당분간 더 오를 가능성이 높다" (모멘텀 효과)
  단, 거래량이 너무 적은 코인은 유동성 위험이 있으므로 제외합니다.
"""

import pandas as pd

from ._helpers import volume_filter


class CrossSectionalMomentum:
    """
    크로스섹셔널 모멘텀 전략

    매개변수:
        lookback: 모멘텀 계산 기간 (기본 14일)
        top_k   : 투자할 상위 코인 수 (기본 5개)
    """

    def __init__(self, lookback: int = 14, top_k: int = 5):
        self.lookback = lookback
        self.top_k = top_k
        self.name = f"모멘텀(L{lookback}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """
        주어진 날짜 기준 포트폴리오 비중을 계산합니다.

        매개변수:
            prices         : 전체 가격 데이터
            volumes        : 전체 거래량 데이터
            date           : 리밸런싱 날짜
            lookback_prices: 학습 윈도우 가격 데이터
        반환값:
            코인별 비중 Series (합계 = 1.0)
        """
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.lookback:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0 or len(available) < self.lookback:
            return pd.Series(dtype=float)

        # 모멘텀 스코어: 최근 N일 수익률
        returns = available.iloc[-1] / available.iloc[-self.lookback] - 1
        returns = returns.dropna()

        if len(returns) == 0:
            return pd.Series(dtype=float)

        # 상위 K개 선택, 동일비중
        top_coins = returns.nlargest(min(self.top_k, len(returns)))
        weights = pd.Series(1.0 / len(top_coins), index=top_coins.index)
        return weights
