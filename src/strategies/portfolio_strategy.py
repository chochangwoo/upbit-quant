"""
src/strategies/portfolio_strategy.py - 멀티코인 포트폴리오 실거래 전략

백테스트에서 검증된 전략(Optuna 최적, ML, 룰 기반)을
실거래에 적용하기 위한 포트폴리오 매매 전략입니다.

핵심 차이점 (기존 MA Cross vs 포트폴리오):
  - 단일 코인(BTC) → 최대 13개 코인 동시 보유
  - 골든/데드 크로스 이벤트 → 정기 리밸런싱 (목표 비중 조정)
  - 전량 매수/매도 → 비중 기반 점진적 조정
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

from src.api.upbit_client import get_ohlcv, get_current_price
from src.strategies.base import BaseStrategy


class PortfolioStrategy(BaseStrategy):
    """
    포트폴리오 기반 실거래 전략

    백테스트 전략의 get_weights()를 실거래 check_signal()로 변환합니다.
    """

    def __init__(
        self,
        strategy_type: str = "momentum",
        top_k: int = 5,
        rebalance_days: int = 3,
        lookback: int = 14,
        coins: list = None,
        risk_config: dict = None,
    ):
        """
        매개변수:
            strategy_type  : 전략 유형 ("momentum", "ml", "optimized")
            top_k          : 보유할 최대 코인 수
            rebalance_days : 리밸런싱 주기 (일)
            lookback       : 모멘텀 계산 기간 (일)
            coins          : 대상 코인 리스트
            risk_config    : 리스크 관리 설정
        """
        self.strategy_type = strategy_type
        self.top_k = top_k
        self.rebalance_days = rebalance_days
        self.lookback = lookback
        self.coins = coins or [
            "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
            "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
            "KRW-NEAR", "KRW-UNI", "KRW-POL",
        ]
        self.risk_config = risk_config or {}

        # 상태 관리
        self.current_weights = {}
        self.last_rebalance_date = None
        self.ml_model = None

    def get_strategy_name(self) -> str:
        return f"portfolio_{self.strategy_type}"

    def _collect_prices(self, days: int = 60) -> pd.DataFrame:
        """실시간 가격 데이터를 수집합니다."""
        import time
        prices = {}
        for coin in self.coins:
            df = get_ohlcv(coin, interval="day", count=days)
            if df is not None and not df.empty:
                prices[coin] = df["close"]
            time.sleep(0.15)

        if not prices:
            return pd.DataFrame()

        return pd.DataFrame(prices)

    def _calc_momentum_weights(self, prices: pd.DataFrame) -> dict:
        """모멘텀 기반 비중 계산"""
        if len(prices) < self.lookback:
            return {}

        # N일 수익률 계산
        returns = prices.iloc[-1] / prices.iloc[-self.lookback] - 1
        returns = returns.dropna()

        if len(returns) == 0:
            return {}

        # 상위 K개 코인 선택
        top = returns.nlargest(min(self.top_k, len(returns)))

        # 양의 수익률만 (하락 중인 코인은 제외)
        top = top[top > 0]
        if len(top) == 0:
            return {}

        # 균등 비중
        weight = 1.0 / len(top)
        return {coin: weight for coin in top.index}

    def _calc_rsi_weights(self, prices: pd.DataFrame) -> dict:
        """RSI 기반 비중 계산 (과매도 코인 매수)"""
        if len(prices) < 15:
            return {}

        weights = {}
        for coin in prices.columns:
            close = prices[coin].dropna()
            if len(close) < 15:
                continue
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rs = gain.iloc[-1] / max(loss.iloc[-1], 1e-10)
            rsi = 100 - (100 / (1 + rs))

            if rsi < 35:  # 과매도
                weights[coin] = (35 - rsi) / 35  # RSI 낮을수록 높은 비중

        if not weights:
            return {}

        # 상위 K개만
        sorted_coins = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        top = dict(sorted_coins[:self.top_k])

        # 비중 정규화
        total = sum(top.values())
        return {coin: w / total for coin, w in top.items()}

    def _calc_combined_weights(self, prices: pd.DataFrame) -> dict:
        """복합 전략 비중 계산 (모멘텀 50% + 저변동성 30% + 거래량 20%)"""
        if len(prices) < 30:
            return {}

        scores = {}
        for coin in prices.columns:
            close = prices[coin].dropna()
            if len(close) < 30:
                continue

            # 모멘텀 스코어 (14일 수익률 순위)
            mom = close.iloc[-1] / close.iloc[-14] - 1

            # 저변동성 스코어 (낮을수록 좋음 → 역수)
            vol = close.pct_change().tail(20).std()
            inv_vol = 1.0 / max(vol, 1e-10)

            scores[coin] = {
                "momentum": mom,
                "inv_volatility": inv_vol,
            }

        if not scores:
            return {}

        df = pd.DataFrame(scores).T

        # 순위 기반 정규화 (0~1)
        for col in df.columns:
            df[col] = df[col].rank(pct=True)

        # 복합 점수
        df["score"] = df["momentum"] * 0.5 + df["inv_volatility"] * 0.5

        # 상위 K개
        top = df.nlargest(min(self.top_k, len(df)), "score")

        # 양의 모멘텀만
        original_scores = pd.DataFrame(scores).T
        top = top[original_scores.loc[top.index, "momentum"] > 0]

        if len(top) == 0:
            return {}

        weight = 1.0 / len(top)
        return {coin: weight for coin in top.index}

    def _calc_ml_weights(self, prices: pd.DataFrame) -> dict:
        """ML 모델 기반 비중 계산"""
        try:
            from backtest.ml.feature_engineer import build_coin_features

            coin_proba = {}
            for coin in prices.columns:
                features = build_coin_features(
                    prices, pd.DataFrame(), coin, alt_data=None
                )
                if features.empty:
                    continue

                latest = features.iloc[[-1]]

                if self.ml_model is None:
                    continue

                # ML 예측
                x = latest[self.ml_model["feature_cols"]]
                x = x.fillna(0).replace([np.inf, -np.inf], 0)
                x_scaled = self.ml_model["scaler"].transform(x)
                proba = self.ml_model["model"].predict(x_scaled)[0]
                coin_proba[coin] = proba

            if not coin_proba:
                return {}

            # 상위 K개 (50% 초과만)
            sorted_coins = sorted(coin_proba.items(), key=lambda x: x[1], reverse=True)
            top = [(c, p) for c, p in sorted_coins[:self.top_k] if p > 0.5]

            if not top:
                return {}

            # 확률 가중 비중
            total_excess = sum(p - 0.5 for _, p in top)
            if total_excess <= 0:
                return {}

            return {coin: (proba - 0.5) / total_excess for coin, proba in top}

        except Exception as e:
            logger.error(f"[ML] 비중 계산 실패: {e}")
            return {}

    def calc_target_weights(self) -> dict:
        """
        현재 시장 데이터를 기반으로 목표 포트폴리오 비중을 계산합니다.

        반환값:
            {코인: 비중} 딕셔너리 (합계 = 1.0) 또는 빈 딕셔너리
        """
        prices = self._collect_prices(days=max(60, self.lookback + 10))
        if prices.empty:
            return {}

        if self.strategy_type == "momentum":
            return self._calc_momentum_weights(prices)
        elif self.strategy_type == "rsi":
            return self._calc_rsi_weights(prices)
        elif self.strategy_type == "combined":
            return self._calc_combined_weights(prices)
        elif self.strategy_type == "ml":
            return self._calc_ml_weights(prices)
        else:
            return self._calc_momentum_weights(prices)

    def check_signal(self, ticker: str = None) -> tuple:
        """
        리밸런싱 필요 여부를 확인하고 매매 신호를 반환합니다.

        기존 인터페이스 호환:
          - ('rebalance', info) → 리밸런싱 필요
          - (None, info)        → 아직 리밸런싱 시점 아님

        info에 target_weights가 포함되어 호출자가 매매를 실행합니다.
        """
        today = datetime.now().date()

        # 리밸런싱 주기 확인
        if self.last_rebalance_date is not None:
            days_since = (today - self.last_rebalance_date).days
            if days_since < self.rebalance_days:
                return None, {"reason": f"리밸런싱 대기 ({days_since}/{self.rebalance_days}일)"}

        # 목표 비중 계산
        target_weights = self.calc_target_weights()

        info = {
            "strategy": self.strategy_type,
            "target_weights": target_weights,
            "current_weights": self.current_weights,
            "coins_count": len(target_weights),
        }

        if not target_weights:
            info["reason"] = "유효한 매매 신호 없음"
            return None, info

        # 리밸런싱 신호 발생
        self.last_rebalance_date = today
        self.current_weights = target_weights
        return "rebalance", info
