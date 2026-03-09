"""
backtest/coin_screener/strategies/momentum_screener.py - 전략 A: 모멘텀 스크리닝

최근 N일 수익률이 높은 상위 K개 코인을 선별합니다.
핵심 지표: (현재가 - N일전 종가) / N일전 종가
"""
from loguru import logger
from .base_screener import BaseScreener


class MomentumScreener(BaseScreener):
    """
    모멘텀 스크리닝 전략.
    최근 N일 수익률 상위 코인을 선별합니다.
    """

    def __init__(self, top_n: int = 5, lookback_days: int = 7):
        """
        매개변수:
            top_n        : 선별할 코인 수
            lookback_days: 모멘텀 계산 기간 (기본 7일)
        """
        super().__init__(top_n=top_n)
        self.lookback_days = lookback_days

    @property
    def name(self) -> str:
        return f"모멘텀 스크리닝 ({self.lookback_days}일)"

    def screen(self, all_data: dict, current_date) -> list:
        """
        최근 lookback_days 수익률 기준으로 상위 코인을 선별합니다.
        """
        available = self._get_available_data(all_data, current_date)
        scores = []

        for ticker, df in available.items():
            if len(df) < self.lookback_days + 1:
                continue

            current_price = df.iloc[-1]["close"]
            past_price = df.iloc[-(self.lookback_days + 1)]["close"]

            if past_price <= 0:
                continue

            momentum = (current_price - past_price) / past_price
            scores.append((ticker, momentum))

        # 수익률 높은 순으로 정렬
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:self.top_n]
