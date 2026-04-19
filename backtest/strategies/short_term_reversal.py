"""
backtest/strategies/short_term_reversal.py - 단기 반전 전략

전략 설명:
  - 최근 N일간 가장 많이 하락한 코인을 매수합니다.
  - 횡보장에서 단기 과매도 후 평균회귀하는 패턴을 포착합니다.
  - 하락폭에 비례하여 비중을 배분합니다 (더 많이 떨어진 코인 = 더 높은 비중).
  - 극단적 하락(-15% 이상)은 추세 전환일 수 있으므로 제외합니다.

원리:
  "횡보장에서 단기 급락한 코인은 빠르게 원래 수준으로 돌아온다"
  추세장과 달리 횡보장에서는 하락이 지속되지 않고 반등하는 경향
"""

import pandas as pd

from ._helpers import volume_filter


class ShortTermReversal:
    """
    단기 반전 전략

    매개변수:
        lookback   : 하락 측정 기간 (기본 5일)
        max_drop   : 최대 허용 하락폭 (기본 -0.15, 이 이상 하락은 제외)
        top_k      : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, lookback: int = 5, max_drop: float = -0.15, top_k: int = 5):
        self.lookback = lookback
        self.max_drop = max_drop
        self.top_k = top_k
        self.name = f"단기반전(L{lookback}_D{max_drop}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.lookback + 5:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]

        # 최근 N일 수익률 계산
        recent_returns = {}
        for coin in available.columns:
            p = available[coin]
            if len(p) < self.lookback + 1:
                continue
            ret = p.iloc[-1] / p.iloc[-self.lookback - 1] - 1
            # 적당히 하락한 코인만 (극단적 하락은 추세 전환 가능성)
            if self.max_drop <= ret < 0:
                recent_returns[coin] = ret

        if not recent_returns:
            # 하락 코인이 없으면 수익률이 가장 낮은 K개 선택 (약간의 역추세)
            for coin in available.columns:
                p = available[coin]
                if len(p) >= self.lookback + 1:
                    ret = p.iloc[-1] / p.iloc[-self.lookback - 1] - 1
                    if ret >= self.max_drop:
                        recent_returns[coin] = ret

        if not recent_returns:
            return pd.Series(dtype=float)

        ret_series = pd.Series(recent_returns)
        # 가장 많이 하락한 코인 = 가장 높은 반등 기대
        selected = ret_series.nsmallest(min(self.top_k, len(ret_series)))

        # 하락폭 비례 비중 (더 많이 떨어진 코인에 더 높은 비중)
        scores = selected.abs()
        total = scores.sum()
        if total <= 0:
            return pd.Series(1.0 / len(selected), index=selected.index)
        return scores / total
