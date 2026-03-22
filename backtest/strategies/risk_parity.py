"""
backtest/strategies/risk_parity.py - 변동성 가중 포트폴리오 (Risk Parity Lite)

전략 설명:
  - 각 코인의 변동성(표준편차)을 계산합니다.
  - 변동성이 낮은 코인에 더 많은 비중을 부여합니다. (역변동성 가중)
  - 이렇게 하면 포트폴리오 전체의 위험이 균형 잡힙니다.

원리:
  "위험을 균등하게 분배하면 장기적으로 안정적인 수익을 얻을 수 있다"
  변동성이 큰 코인은 비중을 줄이고, 안정적인 코인은 비중을 늘립니다.
"""

import pandas as pd

from ._helpers import inverse_volatility_weights


class RiskParityLite:
    """
    변동성 가중 포트폴리오 전략

    매개변수:
        vol_lookback: 변동성 계산 기간 (기본 20일)
    """

    def __init__(self, vol_lookback: int = 20):
        self.vol_lookback = vol_lookback
        self.name = f"리스크패리티(V{vol_lookback})"

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
        if available.shape[1] == 0 or len(available) < self.vol_lookback:
            return pd.Series(dtype=float)
        daily_returns = available.pct_change().dropna()
        return inverse_volatility_weights(daily_returns, self.vol_lookback)
