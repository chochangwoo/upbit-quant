"""
src/strategies/adaptive_volume_strategy.py - 적응형 거래량돌파 실거래 전략

백테스트 결과 최적 전략:
  - 상승장/횡보장: 거래량돌파 전략 (lookback=4, ratio=1.26, top_k=5)
  - 하락장: 전량 현금 보유

국면 감지:
  - SMA50 + 20일 모멘텀 기반 자동 분류
  - Bull : 가격 > SMA50 AND 20일 수익률 > +10%
  - Bear : 가격 < SMA50 AND 20일 수익률 < -10%
  - Sideways: 그 외

성과 (800일 백테스트):
  - 샤프 1.79, 수익률 +490%, MDD -49.5%
"""

import time
import numpy as np
import pandas as pd
from datetime import datetime, date
from loguru import logger

from src.api.upbit_client import get_ohlcv, get_current_price
from src.strategies.base import BaseStrategy
from src.database.supabase_client import save_strategy_state, load_strategy_state


# 대상 코인 13종
TARGET_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]


class AdaptiveVolumeStrategy(BaseStrategy):
    """
    적응형 거래량돌파 실거래 전략

    국면에 따라 자동 전환:
      - 상승장/횡보장 → 거래량 돌파 상위 5개 코인 매수
      - 하락장 → 전량 현금 (매도)
    """

    def __init__(
        self,
        price_lookback: int = 4,
        vol_ratio: float = 1.26,
        top_k: int = 5,
        rebalance_days: int = 3,
        sma_window: int = 50,
        momentum_window: int = 20,
        bull_threshold: float = 0.10,
        bear_threshold: float = -0.10,
    ):
        self.price_lookback = price_lookback
        self.vol_ratio = vol_ratio
        self.top_k = top_k
        self.rebalance_days = rebalance_days
        self.sma_window = sma_window
        self.momentum_window = momentum_window
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold

        self.coins = TARGET_COINS
        self.current_regime = None
        self.current_weights = {}

        # DB에서 마지막 리밸런싱 날짜 복원 (컨테이너 재시작 대응)
        self.last_rebalance_date = self._load_last_rebalance_date()
        if self.last_rebalance_date:
            logger.info(f"[상태복원] 마지막 리밸런싱: {self.last_rebalance_date}")

    def get_strategy_name(self) -> str:
        return "adaptive_volume"

    def _load_last_rebalance_date(self) -> date | None:
        """DB에서 마지막 리밸런싱 날짜를 복원합니다."""
        try:
            value = load_strategy_state("adaptive_volume", "last_rebalance_date")
            if value:
                return datetime.strptime(value, "%Y-%m-%d").date()
        except Exception as e:
            logger.warning(f"[상태복원] 리밸런싱 날짜 로드 실패: {e}")
        return None

    def _save_last_rebalance_date(self, d: date):
        """리밸런싱 날짜를 DB에 저장합니다."""
        save_strategy_state("adaptive_volume", "last_rebalance_date", d.isoformat())

    def _detect_regime(self) -> str:
        """BTC 가격 기반 시장 국면을 감지합니다."""
        df = get_ohlcv("KRW-BTC", interval="day", count=self.sma_window + 10)
        if df is None or len(df) < self.sma_window:
            logger.warning("[국면] BTC 데이터 부족, sideways로 판단")
            return "sideways"

        close = df["close"]
        sma = close.rolling(self.sma_window).mean().iloc[-1]
        current_price = close.iloc[-1]
        momentum = current_price / close.iloc[-self.momentum_window] - 1

        if current_price > sma and momentum > self.bull_threshold:
            regime = "bull"
        elif current_price < sma and momentum < self.bear_threshold:
            regime = "bear"
        else:
            regime = "sideways"

        if regime != self.current_regime:
            logger.info(
                f"[국면전환] {self.current_regime or '초기'} → {regime} | "
                f"BTC: {current_price:,.0f}원 | SMA{self.sma_window}: {sma:,.0f}원 | "
                f"모멘텀: {momentum:+.1%}"
            )

        self.current_regime = regime
        return regime

    def _calc_volume_breakout_weights(self) -> dict:
        """거래량 돌파 기반 상위 K개 코인 비중을 계산합니다."""
        scores = {}

        for coin in self.coins:
            try:
                df = get_ohlcv(coin, interval="day", count=max(25, self.price_lookback + 20))
                if df is None or len(df) < 20:
                    continue

                close = df["close"]
                volume = df["value"]  # 거래대금

                # 거래량 돌파: 최근 거래량 / 20일 평균 거래량
                recent_vol = volume.tail(self.price_lookback).mean()
                avg_vol = volume.tail(20).mean()

                if avg_vol <= 0:
                    continue

                vol_ratio = recent_vol / avg_vol

                # 가격 모멘텀 (price_lookback일 수익률)
                price_momentum = close.iloc[-1] / close.iloc[-self.price_lookback] - 1

                # 거래량 비율이 기준 초과 AND 양의 모멘텀
                if vol_ratio >= self.vol_ratio and price_momentum > 0:
                    scores[coin] = vol_ratio * (1 + price_momentum)

                time.sleep(0.1)

            except Exception as e:
                logger.debug(f"[거래량돌파] {coin} 스킵: {e}")
                continue

        if not scores:
            # 돌파 신호 없으면 모멘텀 상위 코인
            return self._fallback_momentum_weights()

        # 상위 K개 선택
        sorted_coins = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top = dict(sorted_coins[:self.top_k])

        # 균등 비중
        weight = 1.0 / len(top)
        return {coin: weight for coin in top}

    def _fallback_momentum_weights(self) -> dict:
        """거래량 돌파 신호가 없을 때 모멘텀 기반 대체."""
        momentums = {}
        for coin in self.coins:
            try:
                df = get_ohlcv(coin, interval="day", count=15)
                if df is None or len(df) < 10:
                    continue
                mom = df["close"].iloc[-1] / df["close"].iloc[-self.price_lookback] - 1
                if mom > 0:
                    momentums[coin] = mom
                time.sleep(0.1)
            except Exception:
                continue

        if not momentums:
            return {}

        sorted_coins = sorted(momentums.items(), key=lambda x: x[1], reverse=True)
        top = dict(sorted_coins[:self.top_k])
        weight = 1.0 / len(top)
        return {coin: weight for coin in top}

    def check_signal(self, ticker: str = None) -> tuple:
        """
        리밸런싱 신호를 확인합니다.

        반환값:
            ('rebalance', info) → 리밸런싱 실행
            ('emergency_sell', info) → 하락장 전환, 전량 매도
            (None, info) → 대기
        """
        today = datetime.now().date()

        # 국면 감지 (매번 실행)
        regime = self._detect_regime()

        # 하락장 전환 감지 → 즉시 전량 매도
        if regime == "bear" and self.current_weights:
            logger.warning("[하락장] 전량 현금 전환!")
            self.current_weights = {}
            return "emergency_sell", {
                "regime": regime,
                "target_weights": {},
                "reason": "하락장 감지 → 전량 현금 전환",
            }

        # 하락장 중 → 현금 유지
        if regime == "bear":
            return None, {
                "regime": regime,
                "reason": "하락장 현금 유지 중",
            }

        # 리밸런싱 주기 확인
        if self.last_rebalance_date is not None:
            days_since = (today - self.last_rebalance_date).days
            if days_since < self.rebalance_days:
                return None, {
                    "regime": regime,
                    "reason": f"리밸런싱 대기 ({days_since}/{self.rebalance_days}일)",
                }

        # 거래량 돌파 비중 계산
        target_weights = self._calc_volume_breakout_weights()

        if not target_weights:
            return None, {
                "regime": regime,
                "reason": "유효한 매수 신호 없음",
            }

        self.last_rebalance_date = today
        self._save_last_rebalance_date(today)
        self.current_weights = target_weights

        return "rebalance", {
            "regime": regime,
            "target_weights": target_weights,
            "current_weights": self.current_weights,
            "coins_count": len(target_weights),
        }
