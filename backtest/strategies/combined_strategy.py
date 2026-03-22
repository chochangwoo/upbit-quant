"""
backtest/strategies/combined_strategy.py - 통합 전략 (모멘텀 + 변동성 + 거래량)

전략 설명:
  3가지 신호를 조합하여 투자 대상과 비중을 결정합니다.

  Step 1: 모멘텀 스코어 — 최근 N일 수익률로 코인 순위 매기기
  Step 2: 거래량 변화 — 7일 평균 / 30일 평균 비교 (급등/급감 포착)
  Step 3: 복합 스코어 — 모멘텀순위 × (1 + 거래량변화 × 0.3) 합성
  Step 4: 상위 K개 코인에 역변동성 가중 투자

원리:
  "상승 추세 + 거래량 뒷받침 + 위험 관리"를 동시에 고려하는 정교한 전략
"""

import pandas as pd

from ._helpers import inverse_volatility_weights


class CombinedStrategy:
    """
    통합 전략: 모멘텀 + 변동성 가중 + 거래량 시그널

    매개변수:
        mom_lookback: 모멘텀 계산 기간 (기본 14일)
        vol_lookback: 변동성 계산 기간 (기본 20일)
        top_k       : 투자할 상위 코인 수 (기본 5개)
    """

    def __init__(self, mom_lookback: int = 14, vol_lookback: int = 20, top_k: int = 5):
        self.mom_lookback = mom_lookback
        self.vol_lookback = vol_lookback
        self.top_k = top_k
        self.name = f"통합(M{mom_lookback}_V{vol_lookback}_K{top_k})"

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
        if available.shape[1] == 0 or len(available) < max(self.mom_lookback, self.vol_lookback):
            return pd.Series(dtype=float)

        coins = available.columns

        # Step 1: 모멘텀 스코어
        momentum = available.iloc[-1] / available.iloc[-self.mom_lookback] - 1
        momentum = momentum.dropna()
        if len(momentum) == 0:
            return pd.Series(dtype=float)

        # 모멘텀 순위 (높을수록 좋음)
        mom_rank = momentum.rank(ascending=True)

        # Step 2: 거래량 변화 시그널
        vol_change = pd.Series(0.0, index=coins)
        if volumes is not None and not volumes.empty:
            vol_data = volumes.loc[:date]
            for coin in coins:
                if coin in vol_data.columns:
                    v = vol_data[coin].dropna()
                    if len(v) >= 30:
                        avg_7 = v.tail(7).mean()
                        avg_30 = v.tail(30).mean()
                        if avg_30 > 0:
                            vol_change[coin] = avg_7 / avg_30 - 1

        # Step 3: 복합 스코어 합성
        common = mom_rank.index.intersection(vol_change.index)
        composite = mom_rank[common] * (1 + vol_change[common] * 0.3)

        # 상위 K개 선택
        top_coins = composite.nlargest(min(self.top_k, len(composite))).index

        # Step 4: 선택된 코인에 역변동성 가중
        daily_returns = available[top_coins].pct_change().dropna()
        weights = inverse_volatility_weights(daily_returns, self.vol_lookback)
        if len(weights) == 0:
            return pd.Series(1.0 / len(top_coins), index=top_coins)
        return weights
