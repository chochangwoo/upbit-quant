"""
backtest/strategies/ma_cross_rotation.py - 이동평균 크로스 로테이션 전략

전략 설명:
  - 단기 MA > 장기 MA인 코인만 선택 (골든크로스 상태)
  - 선택된 코인 중 (단기MA/장기MA - 1) 비율이 높은 상위 K개 투자
  - 역변동성 가중으로 비중 배분

원리:
  "골든크로스 상태이면서 추세 강도가 큰 코인에 집중 투자"
  이동평균 기반의 추세추종 + 위험 관리를 결합합니다.
"""

import pandas as pd

from ._helpers import volume_filter, inverse_volatility_weights


class MACrossRotation:
    """
    이동평균 크로스 로테이션 전략

    매개변수:
        short_ma: 단기 이동평균 기간 (기본 5일)
        long_ma : 장기 이동평균 기간 (기본 20일)
        top_k   : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, short_ma: int = 5, long_ma: int = 20, top_k: int = 5):
        self.short_ma = short_ma
        self.long_ma = long_ma
        self.top_k = top_k
        self.name = f"MA크로스(S{short_ma}_L{long_ma}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.long_ma:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0:
            return pd.Series(dtype=float)

        scores = {}
        for coin in available.columns:
            short_avg = available[coin].tail(self.short_ma).mean()
            long_avg = available[coin].tail(self.long_ma).mean()
            if long_avg > 0 and short_avg > long_avg:
                scores[coin] = short_avg / long_avg - 1

        if not scores:
            # 골든크로스 코인 없으면 비율 상위 K개
            for coin in available.columns:
                short_avg = available[coin].tail(self.short_ma).mean()
                long_avg = available[coin].tail(self.long_ma).mean()
                if long_avg > 0:
                    scores[coin] = short_avg / long_avg - 1

        if not scores:
            return pd.Series(dtype=float)

        score_series = pd.Series(scores)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))

        # 역변동성 가중
        daily_returns = available[selected.index].pct_change().dropna()
        weights = inverse_volatility_weights(daily_returns, min(20, len(daily_returns)))
        if len(weights) == 0:
            return pd.Series(1.0 / len(selected), index=selected.index)
        return weights
