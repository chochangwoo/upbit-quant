"""
backtest/coin_screener/strategies/mean_reversion_screener.py - 전략 C: 평균회귀

RSI(14) 기준으로 과매도 상태인 코인을 선별합니다.
RSI가 낮을수록 우선순위가 높습니다 (역추세 전략).
핵심 지표: RSI(14) — 낮을수록 우선순위 높음
"""
import pandas as pd
from .base_screener import BaseScreener


class MeanReversionScreener(BaseScreener):
    """
    평균회귀 전략.
    RSI가 가장 낮은(과매도) 상위 코인을 선별합니다.
    """

    def __init__(self, top_n: int = 5, rsi_period: int = 14):
        """
        매개변수:
            top_n     : 선별할 코인 수
            rsi_period: RSI 계산 기간 (기본 14일)
        """
        super().__init__(top_n=top_n)
        self.rsi_period = rsi_period

    @property
    def name(self) -> str:
        return f"평균회귀 RSI({self.rsi_period})"

    def _calc_rsi(self, closes: pd.Series) -> float:
        """
        RSI(Relative Strength Index)를 계산합니다.

        매개변수:
            closes: 종가 시리즈
        반환값:
            RSI 값 (0~100), 계산 불가 시 50.0 반환
        """
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.rolling(self.rsi_period).mean().iloc[-1]
        avg_loss = loss.rolling(self.rsi_period).mean().iloc[-1]

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def screen(self, all_data: dict, current_date) -> list:
        """
        RSI가 가장 낮은 코인을 선별합니다 (과매도 → 반등 기대).
        """
        available = self._get_available_data(all_data, current_date)
        scores = []

        for ticker, df in available.items():
            if len(df) < self.rsi_period + 2:
                continue

            rsi = self._calc_rsi(df["close"])
            # RSI가 낮을수록 점수가 높음 (score = -RSI로 정렬)
            scores.append((ticker, rsi))

        # RSI 낮은 순으로 정렬 (과매도 우선)
        scores.sort(key=lambda x: x[1])
        return scores[:self.top_n]
