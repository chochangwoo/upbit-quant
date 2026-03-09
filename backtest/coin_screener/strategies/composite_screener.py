"""
backtest/coin_screener/strategies/composite_screener.py - 전략 D: 복합 스코어링

모멘텀(50%) + 거래량(30%) + 저변동성(20%) 가중 합산으로 코인을 선별합니다.
각 지표별 순위(rank)를 매긴 뒤 가중 합산하여 종합 점수를 산출합니다.
핵심: composite_score = momentum_rank × 0.5 + volume_rank × 0.3 + volatility_rank × 0.2
"""
import numpy as np
from .base_screener import BaseScreener


class CompositeScreener(BaseScreener):
    """
    복합 스코어링 전략.
    모멘텀 + 거래량 + 저변동성을 가중 합산하여 종합 점수를 산출합니다.
    """

    def __init__(self, top_n: int = 5, momentum_days: int = 7,
                 vol_avg_days: int = 20, volatility_days: int = 20,
                 w_momentum: float = 0.5, w_volume: float = 0.3,
                 w_volatility: float = 0.2):
        """
        매개변수:
            top_n          : 선별할 코인 수
            momentum_days  : 모멘텀 계산 기간
            vol_avg_days   : 거래량 평균 기간
            volatility_days: 변동성 계산 기간
            w_momentum     : 모멘텀 가중치 (기본 0.5)
            w_volume       : 거래량 가중치 (기본 0.3)
            w_volatility   : 저변동성 가중치 (기본 0.2)
        """
        super().__init__(top_n=top_n)
        self.momentum_days = momentum_days
        self.vol_avg_days = vol_avg_days
        self.volatility_days = volatility_days
        self.w_momentum = w_momentum
        self.w_volume = w_volume
        self.w_volatility = w_volatility

    @property
    def name(self) -> str:
        return "복합 스코어링"

    def screen(self, all_data: dict, current_date) -> list:
        """
        모멘텀/거래량/변동성을 종합하여 상위 코인을 선별합니다.
        """
        available = self._get_available_data(all_data, current_date)
        min_len = max(self.momentum_days, self.vol_avg_days, self.volatility_days) + 2

        # 각 지표별 원시값 수집
        raw_data = []
        for ticker, df in available.items():
            if len(df) < min_len:
                continue

            # 모멘텀: N일 수익률
            current_price = df.iloc[-1]["close"]
            past_price = df.iloc[-(self.momentum_days + 1)]["close"]
            if past_price <= 0:
                continue
            momentum = (current_price - past_price) / past_price

            # 거래량 비율
            today_volume = df.iloc[-1]["volume"]
            avg_volume = df["volume"].iloc[-(self.vol_avg_days + 1):-1].mean()
            if avg_volume <= 0:
                continue
            volume_ratio = today_volume / avg_volume

            # 변동성: 일간 수익률의 표준편차 (낮을수록 좋음)
            returns = df["close"].iloc[-self.volatility_days:].pct_change().dropna()
            volatility = returns.std() if len(returns) > 1 else 0

            raw_data.append({
                "ticker": ticker,
                "momentum": momentum,
                "volume_ratio": volume_ratio,
                "volatility": volatility,
            })

        if not raw_data:
            return []

        n = len(raw_data)

        # 모멘텀 순위 (높을수록 좋음 → 높은 값 = 낮은 rank 번호 = 좋음)
        sorted_by_momentum = sorted(raw_data, key=lambda x: x["momentum"], reverse=True)
        for rank, item in enumerate(sorted_by_momentum):
            item["momentum_rank"] = rank + 1

        # 거래량 순위 (높을수록 좋음)
        sorted_by_volume = sorted(raw_data, key=lambda x: x["volume_ratio"], reverse=True)
        for rank, item in enumerate(sorted_by_volume):
            item["volume_rank"] = rank + 1

        # 변동성 순위 (낮을수록 좋음 → 낮은 값 = 낮은 rank 번호 = 좋음)
        sorted_by_volatility = sorted(raw_data, key=lambda x: x["volatility"])
        for rank, item in enumerate(sorted_by_volatility):
            item["volatility_rank"] = rank + 1

        # 가중 합산 점수 (낮을수록 좋음)
        for item in raw_data:
            item["composite_score"] = (
                item["momentum_rank"] * self.w_momentum
                + item["volume_rank"] * self.w_volume
                + item["volatility_rank"] * self.w_volatility
            )

        # 복합 점수 낮은 순으로 정렬 (1등에 가까울수록 좋음)
        raw_data.sort(key=lambda x: x["composite_score"])

        return [(item["ticker"], item["composite_score"]) for item in raw_data[:self.top_n]]
