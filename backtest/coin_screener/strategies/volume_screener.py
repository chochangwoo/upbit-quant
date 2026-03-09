"""
backtest/coin_screener/strategies/volume_screener.py - 전략 B: 거래량 급증 감지

20일 평균 거래량 대비 당일 거래량 비율이 높은 상위 K개 코인을 선별합니다.
핵심 지표: 당일 거래량 / 20일 평균 거래량
"""
from .base_screener import BaseScreener


class VolumeScreener(BaseScreener):
    """
    거래량 급증 감지 전략.
    Volume Ratio가 높은 상위 코인을 선별합니다.
    """

    def __init__(self, top_n: int = 5, vol_avg_days: int = 20):
        """
        매개변수:
            top_n       : 선별할 코인 수
            vol_avg_days: 평균 거래량 계산 기간 (기본 20일)
        """
        super().__init__(top_n=top_n)
        self.vol_avg_days = vol_avg_days

    @property
    def name(self) -> str:
        return f"거래량 급증 ({self.vol_avg_days}일)"

    def screen(self, all_data: dict, current_date) -> list:
        """
        당일 거래량 / 20일 평균 거래량 비율 기준으로 상위 코인을 선별합니다.
        """
        available = self._get_available_data(all_data, current_date)
        scores = []

        for ticker, df in available.items():
            if len(df) < self.vol_avg_days + 1:
                continue

            today_volume = df.iloc[-1]["volume"]
            avg_volume = df["volume"].iloc[-(self.vol_avg_days + 1):-1].mean()

            if avg_volume <= 0:
                continue

            volume_ratio = today_volume / avg_volume
            scores.append((ticker, volume_ratio))

        # 거래량 비율 높은 순으로 정렬
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:self.top_n]
