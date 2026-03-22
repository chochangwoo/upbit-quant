"""
backtest/strategies/volume_breakout.py - 거래량 브레이크아웃 전략

전략 설명:
  - 최근 5일 평균 거래량이 이전 20일 대비 급증한 코인을 찾습니다.
  - 동시에 가격도 상승 중인 코인만 선택합니다.
  - 거래량 급증 + 가격 상승 = 새로운 추세 시작 신호

원리:
  "거래량이 급증하면서 가격이 오르면 큰 추세가 시작되는 신호"
  단순 가격 상승보다 거래량이 뒷받침되는 상승이 더 신뢰할 수 있습니다.
"""

import pandas as pd


class VolumeBreakout:
    """
    거래량 브레이크아웃 전략

    매개변수:
        price_lookback: 가격 상승 확인 기간 (기본 5일)
        vol_ratio     : 거래량 급증 기준 배수 (기본 1.5배)
        top_k         : 투자할 코인 수 (기본 5개)
    """

    def __init__(self, price_lookback: int = 5, vol_ratio: float = 1.5, top_k: int = 5):
        self.price_lookback = price_lookback
        self.vol_ratio = vol_ratio
        self.top_k = top_k
        self.name = f"거래량돌파(P{price_lookback}_R{vol_ratio}_K{top_k})"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < 30:
            return pd.Series(dtype=float)
        if volumes is None or volumes.empty:
            return pd.Series(dtype=float)

        vol_data = volumes.loc[:date]
        scores = {}

        for coin in available.columns:
            if coin not in vol_data.columns:
                continue
            v = vol_data[coin].dropna()
            if len(v) < 25:
                continue

            avg_5 = v.tail(5).mean()
            avg_20 = v.iloc[-25:-5].mean()
            if avg_20 <= 0:
                continue

            ratio = avg_5 / avg_20

            # 가격 상승 확인
            p = available[coin]
            if len(p) < self.price_lookback:
                continue
            price_change = p.iloc[-1] / p.iloc[-self.price_lookback] - 1

            if ratio >= self.vol_ratio and price_change > 0:
                scores[coin] = ratio

        if not scores:
            # 조건 충족 코인이 없으면 거래량 비율 상위 K개 (가격 상승만 필터)
            for coin in available.columns:
                if coin not in vol_data.columns:
                    continue
                v = vol_data[coin].dropna()
                if len(v) < 25:
                    continue
                avg_5 = v.tail(5).mean()
                avg_20 = v.iloc[-25:-5].mean()
                if avg_20 > 0:
                    p = available[coin]
                    price_change = p.iloc[-1] / p.iloc[-self.price_lookback] - 1
                    if price_change > 0:
                        scores[coin] = avg_5 / avg_20

        if not scores:
            return pd.Series(dtype=float)

        score_series = pd.Series(scores)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))
        return pd.Series(1.0 / len(selected), index=selected.index)
