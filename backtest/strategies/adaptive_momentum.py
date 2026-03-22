"""
backtest/strategies/adaptive_momentum.py - 적응형 모멘텀 전략

전략 설명:
  - BTC의 20일 변동성을 기준으로 모멘텀 룩백 기간을 자동 조절합니다.
  - 변동성 높으면 (>4%): 짧은 룩백 (빠른 반응)
  - 변동성 낮으면 (<2%): 긴 룩백 (안정적 추세)
  - 그 사이: 선형 보간

원리:
  "시장 상황에 맞게 전략을 자동으로 조절"
  변동성이 클 때는 빠르게 반응하고, 안정적일 때는 장기 추세를 따릅니다.
"""

import pandas as pd

from ._helpers import volume_filter


class AdaptiveMomentum:
    """
    적응형 모멘텀 전략

    매개변수:
        short_lb: 최소 룩백 기간 (변동성 높을 때, 기본 5일)
        long_lb : 최대 룩백 기간 (변동성 낮을 때, 기본 30일)
        top_k   : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, short_lb: int = 5, long_lb: int = 30, top_k: int = 5):
        self.short_lb = short_lb
        self.long_lb = long_lb
        self.top_k = top_k
        self.name = f"적응형모멘텀(S{short_lb}_L{long_lb}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.long_lb:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0 or len(available) < self.long_lb:
            return pd.Series(dtype=float)

        # BTC 변동성으로 적응형 룩백 결정
        btc_col = "KRW-BTC"
        if btc_col in available.columns:
            btc_vol = available[btc_col].pct_change().tail(20).std()
            if btc_vol > 0.04:
                lookback = self.short_lb
            elif btc_vol < 0.02:
                lookback = self.long_lb
            else:
                # 선형 보간
                ratio = (btc_vol - 0.02) / 0.02
                lookback = int(self.long_lb - ratio * (self.long_lb - self.short_lb))
        else:
            lookback = (self.short_lb + self.long_lb) // 2

        lookback = max(self.short_lb, min(lookback, len(available) - 1))

        returns = available.iloc[-1] / available.iloc[-lookback] - 1
        returns = returns.dropna()
        if len(returns) == 0:
            return pd.Series(dtype=float)

        selected = returns.nlargest(min(self.top_k, len(returns)))
        return pd.Series(1.0 / len(selected), index=selected.index)
