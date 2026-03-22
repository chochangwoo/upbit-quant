"""
backtest/strategies/momentum_reversal.py - 모멘텀 반전 전략

전략 설명:
  - 중기(30일) 모멘텀이 양수인 코인 중에서
  - 단기(5일) 하락 후 최근 2일 반등이 시작된 코인을 매수합니다.
  - 조건: 30일 수익률 > 0, 5일 수익률 < 0, 2일 수익률 > 0

원리:
  "큰 추세는 상승인데 일시적으로 하락한 코인 = 매수 기회"
  추세 추종과 역추세를 결합하여 좋은 진입점을 찾습니다.
"""

import pandas as pd

from ._helpers import volume_filter


class MomentumReversal:
    """
    모멘텀 반전 전략

    매개변수:
        mid_lookback  : 중기 모멘텀 기간 (기본 30일)
        short_lookback: 단기 하락 확인 기간 (기본 5일)
        top_k         : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, mid_lookback: int = 30, short_lookback: int = 5, top_k: int = 5):
        self.mid_lookback = mid_lookback
        self.short_lookback = short_lookback
        self.top_k = top_k
        self.name = f"반전(M{mid_lookback}_S{short_lookback}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.mid_lookback:
            return pd.Series(dtype=float)

        valid_coins = volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0:
            return pd.Series(dtype=float)

        scores = {}
        for coin in available.columns:
            p = available[coin]
            mid_ret = p.iloc[-1] / p.iloc[-self.mid_lookback] - 1
            short_ret = p.iloc[-1] / p.iloc[-self.short_lookback] - 1
            bounce_ret = p.iloc[-1] / p.iloc[-2] - 1 if len(p) >= 2 else 0

            # 이상적 조건: 중기 상승 + 단기 하락 + 반등
            if mid_ret > 0 and short_ret < 0 and bounce_ret > 0:
                scores[coin] = bounce_ret  # 반등 강도
            elif mid_ret > 0 and short_ret < -0.05:
                # 중기 상승 + 단기 급락 (반등 아직 안 해도 매수 기회)
                scores[coin] = -short_ret * 0.5

        if not scores:
            # 조건 충족 없으면 중기 모멘텀 상위 K개 (단기 하락 우선)
            for coin in available.columns:
                p = available[coin]
                mid_ret = p.iloc[-1] / p.iloc[-self.mid_lookback] - 1
                short_ret = p.iloc[-1] / p.iloc[-self.short_lookback] - 1
                if mid_ret > 0:
                    scores[coin] = mid_ret - short_ret

        if not scores:
            return pd.Series(dtype=float)

        score_series = pd.Series(scores)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))
        return pd.Series(1.0 / len(selected), index=selected.index)
