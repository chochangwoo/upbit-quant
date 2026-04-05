"""
backtest/strategies/bb_rsi_mean_reversion.py - BB+RSI 평균회귀 전략 (백테스트용)

횡보장에서 볼린저밴드 하단 + RSI 과매도 시 매수,
볼린저밴드 상단 + RSI 과매수 또는 BB 중간선 도달 시 매도.

매수 조건 (모두 충족):
  1. 현재가 <= BB 하단
  2. RSI(14) < 30 (과매도)

매도 조건 (하나라도 충족):
  1. BB 상단 터치 + RSI > 70
  2. 현재가 >= BB 중간선 + 수익 > 1%
  3. 수익률 <= -3% (손절)
  4. 수익률 >= +5% (익절)
"""

import pandas as pd
import numpy as np


class BBRSIMeanReversionBT:
    """
    BB+RSI 평균회귀 백테스트 전략

    매개변수:
        bb_period      : 볼린저밴드 이동평균 기간 (기본 20)
        bb_std         : 볼린저밴드 표준편차 배수 (기본 2.0)
        rsi_period     : RSI 계산 기간 (기본 14)
        rsi_oversold   : RSI 과매도 임계값 (기본 30)
        rsi_overbought : RSI 과매수 임계값 (기본 70)
        stop_loss_pct  : 손절 기준 % (기본 -3.0)
        take_profit_pct: 익절 기준 % (기본 5.0)
        top_k          : 동시 보유 최대 코인 수 (기본 5)
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
        stop_loss_pct: float = -3.0,
        take_profit_pct: float = 5.0,
        top_k: int = 5,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stop_loss_pct = stop_loss_pct / 100  # % → 비율
        self.take_profit_pct = take_profit_pct / 100
        self.top_k = top_k
        self.name = f"BB+RSI(BB{bb_period}_{bb_std}_RSI{rsi_period}_{rsi_oversold})"

        # 포지션 추적 (백테스트용)
        self._positions = {}  # {coin: entry_price}

    def _calc_rsi(self, series: pd.Series) -> float:
        """RSI 계산"""
        delta = series.diff().dropna()
        if len(delta) < self.rsi_period:
            return 50.0
        gain = delta.where(delta > 0, 0.0).tail(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).tail(self.rsi_period).mean()
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calc_bb(self, series: pd.Series) -> tuple:
        """볼린저밴드 (중간, 상단, 하단) 계산"""
        if len(series) < self.bb_period:
            return None, None, None
        mid = series.tail(self.bb_period).mean()
        std = series.tail(self.bb_period).std()
        upper = mid + self.bb_std * std
        lower = mid - self.bb_std * std
        return mid, upper, lower

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """포트폴리오 비중을 계산합니다."""
        available = lookback_prices.dropna(axis=1, how="any")
        min_data = max(self.bb_period, self.rsi_period) + 5
        if available.shape[1] == 0 or len(available) < min_data:
            return pd.Series(dtype=float)

        buy_candidates = {}
        sell_coins = []

        for coin in available.columns:
            series = available[coin]
            current_price = series.iloc[-1]

            rsi = self._calc_rsi(series)
            bb_mid, bb_upper, bb_lower = self._calc_bb(series)
            if bb_mid is None:
                continue

            # 이미 보유 중인 코인 → 매도 조건 확인
            if coin in self._positions:
                entry_price = self._positions[coin]
                pnl = current_price / entry_price - 1

                should_sell = False
                # 조건 1: BB 상단 + RSI 과매수
                if current_price >= bb_upper and rsi > self.rsi_overbought:
                    should_sell = True
                # 조건 2: BB 중간선 + 수익 > 1%
                elif current_price >= bb_mid and pnl > 0.01:
                    should_sell = True
                # 조�� 3: 손절
                elif pnl <= self.stop_loss_pct:
                    should_sell = True
                # 조건 4: 익절
                elif pnl >= self.take_profit_pct:
                    should_sell = True

                if should_sell:
                    sell_coins.append(coin)
                # 보유 유지 → 비중 유지 (아래에서 처리)
            else:
                # 매수 조건: BB 하단 이하 + RSI 과매도
                if current_price <= bb_lower and rsi < self.rsi_oversold:
                    # RSI가 낮을수록 강한 과매도 → 점수 높음
                    score = (self.rsi_oversold - rsi) + (bb_lower - current_price) / bb_lower * 100
                    buy_candidates[coin] = score

        # 매도 처리
        for coin in sell_coins:
            if coin in self._positions:
                del self._positions[coin]

        # 매수 처리 (빈 슬롯만큼)
        available_slots = self.top_k - len(self._positions)
        if available_slots > 0 and buy_candidates:
            sorted_candidates = sorted(buy_candidates.items(), key=lambda x: x[1], reverse=True)
            for coin, _ in sorted_candidates[:available_slots]:
                self._positions[coin] = available[coin].iloc[-1]

        # 현재 보유 코인 기반 비중 반환
        if not self._positions:
            return pd.Series(dtype=float)

        weight = 1.0 / len(self._positions)
        return pd.Series(weight, index=list(self._positions.keys()))

    def reset(self):
        """백테스트 간 상태 초기화"""
        self._positions.clear()
