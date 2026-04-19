"""
backtest/strategies/low_vol_rebalance.py - 저변동성 리밸런싱 전략

전략 설명:
  - 횡보장에서 변동성이 낮은 코인 위주로 포트폴리오를 구성합니다.
  - 역변동성 가중(inverse volatility weighting)으로 비중을 배분합니다.
  - 변동성이 낮은 코인 = 횡보장에서 안정적 수익 기대
  - 리밸런싱 시 드리프트 보정으로 소폭 수익을 지속 포착합니다.

원리:
  "횡보장에서 저변동성 코인은 큰 손실 없이 안정적인 수익을 제공한다"
  고변동성 코인은 횡보장에서 위아래로 크게 흔들려 손실 위험이 큼
"""

import numpy as np
import pandas as pd

from ._helpers import volume_filter


class LowVolRebalance:
    """
    저변동성 리밸런싱 전략

    매개변수:
        vol_lookback: 변동성 계산 기간 (기본 20일)
        top_k       : 투자할 코인 수 (기본 5개)
        min_return   : 최소 모멘텀 필터 (기본 -0.05, 극단적 하락 제외)
    """

    def __init__(self, vol_lookback: int = 20, top_k: int = 5,
                 min_return: float = -0.05):
        self.vol_lookback = vol_lookback
        self.top_k = top_k
        self.min_return = min_return
        self.name = f"저변동성(V{vol_lookback}_K{top_k}_MR{min_return})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.vol_lookback + 5:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]

        # 일별 수익률 계산
        returns = available.pct_change().dropna()
        if len(returns) < self.vol_lookback:
            return pd.Series(dtype=float)

        recent_returns = returns.tail(self.vol_lookback)

        # 변동성 계산
        volatilities = recent_returns.std()
        volatilities = volatilities[volatilities > 0]

        if len(volatilities) == 0:
            return pd.Series(dtype=float)

        # 최소 모멘텀 필터: 극단적 하락 코인 제외
        period_return = available.iloc[-1] / available.iloc[-self.vol_lookback] - 1
        valid_coins_list = []
        for coin in volatilities.index:
            if coin in period_return.index and period_return[coin] >= self.min_return:
                valid_coins_list.append(coin)

        if not valid_coins_list:
            # 필터 후 남은 코인이 없으면 변동성 가장 낮은 K개 선택
            valid_coins_list = volatilities.nsmallest(self.top_k).index.tolist()

        volatilities = volatilities.reindex(valid_coins_list).dropna()
        if len(volatilities) == 0:
            return pd.Series(dtype=float)

        # 저변동성 상위 K개 선택
        low_vol = volatilities.nsmallest(min(self.top_k, len(volatilities)))

        # 역변동성 가중
        inv_vol = 1.0 / low_vol
        weights = inv_vol / inv_vol.sum()
        return weights
