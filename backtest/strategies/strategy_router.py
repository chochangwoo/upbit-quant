"""
backtest/strategies/strategy_router.py - 국면별 전략 자동 스위칭 (백테스트용)

시장 국면(상승/횡보/하락)을 자동 감지하여 전략을 전환합니다.

국면 판단 기준 (BTC 기준):
  - 상승장(Bull) : 가격 > SMA50 AND 20일 모멘텀 > +10%
  - 하락장(Bear) : 가격 < SMA50 AND 20일 모멘텀 < -10%
  - 횡보장(Sideways): 그 외

전략 매핑:
  - 상승장 → 거래량돌파 (VolumeBreakout)
  - ��보장 → BB+RSI 평균회귀 (BBRSIMeanReversionBT)
  - 하락장 → 현금보유 (CashHoldBT)
"""

import pandas as pd
import numpy as np

from .volume_breakout import VolumeBreakout
from .bb_rsi_mean_reversion import BBRSIMeanReversionBT
from .cash_hold import CashHoldBT


class StrategyRouterBT:
    """
    국면별 전략 자동 스위칭 백테스트 전략

    매개변수:
        sma_period         : 국면 판단용 SMA 기간 (기본 50)
        momentum_period    : 모멘텀 계산 기간 (기본 20)
        bull_threshold     : 상승장 모멘텀 임계값 (��본 0.10 = 10%)
        bear_threshold     : 하락장 모멘텀 임계값 (기본 -0.10 = -10%)
        confirmation_days  : 국면 전환 확인 대기일 (기본 2)

        vol_price_lookback : 거래량돌파 가격 확인 기간 (기본 4)
        vol_ratio          : 거래량돌파 기준 배수 (기본 1.26)
        vol_top_k          : 거래량돌파 선택 코인 수 (기본 5)

        bb_period          : BB 이동평균 기간 (기본 20)
        bb_std             : BB 표준편차 배수 (기본 2.0)
        rsi_period         : RSI 계산 기간 (기본 14)
        rsi_oversold       : RSI 과매도 (기본 30)
        rsi_overbought     : RSI 과매수 (기본 70)
        bb_stop_loss       : BB+RSI 손절 % (기본 -3.0)
        bb_take_profit     : BB+RSI 익절 % (기본 5.0)
        bb_top_k           : BB+RSI 동시보유 코인 수 (기본 5)
    """

    def __init__(
        self,
        # 국면 감지
        sma_period: int = 50,
        momentum_period: int = 20,
        bull_threshold: float = 0.10,
        bear_threshold: float = -0.10,
        confirmation_days: int = 2,
        # 상승장 전략 (거래량돌파)
        vol_price_lookback: int = 4,
        vol_ratio: float = 1.26,
        vol_top_k: int = 5,
        # 횡보장 전략 (BB+RSI)
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
        bb_stop_loss: float = -3.0,
        bb_take_profit: float = 5.0,
        bb_top_k: int = 5,
    ):
        self.sma_period = sma_period
        self.momentum_period = momentum_period
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold
        self.confirmation_days = confirmation_days

        # 하위 전략 인스턴스
        self.strategies = {
            "bull": VolumeBreakout(
                price_lookback=vol_price_lookback,
                vol_ratio=vol_ratio,
                top_k=vol_top_k,
            ),
            "sideways": BBRSIMeanReversionBT(
                bb_period=bb_period,
                bb_std=bb_std,
                rsi_period=rsi_period,
                rsi_oversold=rsi_oversold,
                rsi_overbought=rsi_overbought,
                stop_loss_pct=bb_stop_loss,
                take_profit_pct=bb_take_profit,
                top_k=bb_top_k,
            ),
            "bear": CashHoldBT(),
        }

        self.name = "전략라우터(상승=거래량돌파, 횡보=BB+RSI, 하락=현금)"

        # 국면 상태
        self._current_regime = None
        self._pending_regime = None
        self._pending_count = 0  # 연속 감지 일수

        # 통계 추적
        self.regime_log = []  # [(date, regime)]

    def _detect_regime(self, btc_prices: pd.Series, date: pd.Timestamp) -> str:
        """BTC 가격 기반 시장 국면 ��단"""
        btc_data = btc_prices.loc[:date].dropna()
        if len(btc_data) < self.sma_period:
            return "sideways"

        current_price = btc_data.iloc[-1]
        sma = btc_data.tail(self.sma_period).mean()

        if len(btc_data) < self.momentum_period:
            return "sideways"

        momentum = current_price / btc_data.iloc[-self.momentum_period] - 1

        if current_price > sma and momentum > self.bull_threshold:
            return "bull"
        elif current_price < sma and momentum < self.bear_threshold:
            return "bear"
        else:
            return "sideways"

    def _update_regime(self, detected: str) -> bool:
        """국면 전환 확인 로직 (confirmation_days 대기)"""
        if self._current_regime is None:
            self._current_regime = detected
            return True

        if detected == self._current_regime:
            self._pending_regime = None
            self._pending_count = 0
            return False

        if self._pending_regime == detected:
            self._pending_count += 1
            if self._pending_count >= self.confirmation_days:
                # 국면 전환 확정
                self._current_regime = detected
                self._pending_regime = None
                self._pending_count = 0
                # BB+RSI 포지션 초기화 (국면 전환 시)
                self.strategies["sideways"].reset()
                return True
        else:
            self._pending_regime = detected
            self._pending_count = 1

        return False

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """국면을 판단하고 해당 전략의 비중을 반환합니다."""

        # BTC 가격으로 국면 감지
        if "KRW-BTC" in prices.columns:
            detected = self._detect_regime(prices["KRW-BTC"], date)
        else:
            detected = "sideways"

        self._update_regime(detected)
        self.regime_log.append((date, self._current_regime))

        # 현재 국면의 전략 실행
        strategy = self.strategies[self._current_regime]
        return strategy.get_weights(prices, volumes, date, lookback_prices)

    def get_regime_stats(self) -> dict:
        """백테스트 완료 후 국면별 통계 반환"""
        if not self.regime_log:
            return {}

        df = pd.DataFrame(self.regime_log, columns=["date", "regime"])
        stats = {}
        total = len(df)
        for regime in ["bull", "sideways", "bear"]:
            count = (df["regime"] == regime).sum()
            stats[regime] = {
                "일수": count,
                "비율": count / total if total > 0 else 0,
            }
        return stats

    def reset(self):
        """백테스트 간 상태 초기화"""
        self._current_regime = None
        self._pending_regime = None
        self._pending_count = 0
        self.regime_log.clear()
        self.strategies["sideways"].reset()
