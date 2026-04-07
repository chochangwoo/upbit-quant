"""
backtest/strategies/keltner_squeeze.py - 켈트너 스퀴즈 전략 (백테스트용)

TTM Squeeze 단순판:
  - 볼린저 밴드(20, 2σ) 가 켈트너 채널(EMA20 ± 1.5*ATR20) 안에 들어오면 Squeeze ON
  - Squeeze 가 OFF 로 풀리는 첫 봉의 모멘텀 부호가 양(+)이면 롱 진입
  - 손절 -3% / 익절 +5% / 동시 보유 top_k 종목

BBRSIMeanReversionBT 와 동일한 인터페이스(get_weights / reset)를 따릅니다.
백테스트 전용 — 라이브 라우터에는 연결되지 않습니다.
"""

import numpy as np
import pandas as pd


class KeltnerSqueezeBT:
    """
    매개변수:
        ema_period      : Keltner 중심선 EMA 기간
        atr_period      : Keltner 폭 산정용 ATR 기간
        atr_mult        : Keltner 폭 = ATR × mult
        bb_period       : 볼린저 밴드 이동평균 기간
        bb_std          : 볼린저 밴드 표준편차 배수
        momentum_window : Squeeze OFF 첫 봉의 모멘텀 측정 봉수
        stop_loss_pct   : 손절 % (음수)
        take_profit_pct : 익절 %
        top_k           : 동시 보유 상한
    """

    def __init__(
        self,
        ema_period: int = 20,
        atr_period: int = 20,
        atr_mult: float = 1.5,
        bb_period: int = 20,
        bb_std: float = 2.0,
        momentum_window: int = 12,
        stop_loss_pct: float = -3.0,
        take_profit_pct: float = 5.0,
        top_k: int = 3,
    ):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.momentum_window = momentum_window
        self.stop_loss_pct = stop_loss_pct / 100
        self.take_profit_pct = take_profit_pct / 100
        self.top_k = top_k
        self.name = f"KeltnerSqueeze(EMA{ema_period}_ATR{atr_period}x{atr_mult})"

        # 보유 상태 + 직전 squeeze ON 여부 추적
        self._positions: dict[str, float] = {}
        self._prev_squeeze_on: dict[str, bool] = {}

    # ──────────────────────────────────────
    # 지표 계산
    # ──────────────────────────────────────
    def _calc_bb(self, close: pd.Series):
        if len(close) < self.bb_period:
            return None, None
        mid = close.tail(self.bb_period).mean()
        std = close.tail(self.bb_period).std()
        return mid - self.bb_std * std, mid + self.bb_std * std

    def _calc_keltner(self, high: pd.Series, low: pd.Series, close: pd.Series):
        if len(close) < max(self.ema_period, self.atr_period) + 1:
            return None, None
        ema = close.ewm(span=self.ema_period, adjust=False).mean().iloc[-1]
        tr = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / self.atr_period, min_periods=self.atr_period).mean().iloc[-1]
        if pd.isna(atr):
            return None, None
        return ema - self.atr_mult * atr, ema + self.atr_mult * atr

    def _momentum(self, close: pd.Series) -> float:
        if len(close) < self.momentum_window + 1:
            return 0.0
        return float(close.iloc[-1] / close.iloc[-self.momentum_window - 1] - 1)

    # ──────────────────────────────────────
    # 메인 진입점 (BBRSI 와 동일 시그니처)
    # ──────────────────────────────────────
    def get_weights(
        self,
        prices: pd.DataFrame,
        volumes: pd.DataFrame,
        date: pd.Timestamp,
        lookback_prices: pd.DataFrame,
        highs: pd.DataFrame | None = None,
        lows: pd.DataFrame | None = None,
    ) -> pd.Series:
        available = lookback_prices.dropna(axis=1, how="any")
        min_data = max(self.bb_period, self.ema_period, self.atr_period) + self.momentum_window + 5
        if available.shape[1] == 0 or len(available) < min_data:
            return pd.Series(dtype=float)

        candidates: dict[str, float] = {}
        sells: list[str] = []

        for coin in available.columns:
            close = available[coin]
            current = float(close.iloc[-1])

            # 켈트너 채널이 필요 — high/low 가 없으면 close 로 폴백
            if highs is not None and lows is not None and coin in highs.columns and coin in lows.columns:
                h = highs[coin].loc[: close.index[-1]].tail(len(close))
                l = lows[coin].loc[: close.index[-1]].tail(len(close))
            else:
                h = close
                l = close

            bb_lo, bb_up = self._calc_bb(close)
            kc_lo, kc_up = self._calc_keltner(h, l, close)
            if bb_lo is None or kc_lo is None:
                continue

            squeeze_on = (bb_lo > kc_lo) and (bb_up < kc_up)
            prev_on = self._prev_squeeze_on.get(coin, False)
            self._prev_squeeze_on[coin] = squeeze_on

            # 보유 중 → 청산 조건
            if coin in self._positions:
                entry = self._positions[coin]
                pnl = current / entry - 1
                if pnl <= self.stop_loss_pct or pnl >= self.take_profit_pct:
                    sells.append(coin)
                continue

            # 신규 진입: squeeze ON → OFF 전환 + 양의 모멘텀
            if prev_on and not squeeze_on:
                mom = self._momentum(close)
                if mom > 0:
                    candidates[coin] = mom

        for coin in sells:
            self._positions.pop(coin, None)

        slots = self.top_k - len(self._positions)
        if slots > 0 and candidates:
            for coin, _ in sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:slots]:
                self._positions[coin] = float(available[coin].iloc[-1])

        if not self._positions:
            return pd.Series(dtype=float)
        w = 1.0 / len(self._positions)
        return pd.Series(w, index=list(self._positions.keys()))

    def reset(self):
        self._positions.clear()
        self._prev_squeeze_on.clear()
