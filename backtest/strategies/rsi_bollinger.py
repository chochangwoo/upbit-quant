"""
backtest/strategies/rsi_bollinger.py - RSI + 볼린저밴드 복합 전략 (백테스팅용)

전략 설명:
  두 지표가 동시에 신호를 줄 때만 매매해 신뢰도를 높입니다.

  [매수 조건] RSI < oversold(30) AND 종가 < 볼린저밴드 하단
    → 가격이 과도하게 떨어진 상황 → 반등 기대

  [매도 조건] RSI > overbought(70) OR 종가 > 볼린저밴드 상단
    → 가격이 과도하게 오른 상황 → 차익 실현
"""
import pandas as pd
import numpy as np


class RSIBollingerStrategy:
    """
    RSI + 볼린저밴드 복합 전략 백테스팅 클래스.
    """

    def __init__(
        self,
        rsi_period   : int   = 14,
        rsi_oversold : float = 30.0,
        rsi_overbought: float = 70.0,
        bb_period    : int   = 20,
        bb_std       : float = 2.0,
    ):
        """
        매개변수:
            rsi_period    : RSI 계산 기간 (기본 14일)
            rsi_oversold  : RSI 과매도 기준 (기본 30 → 이 이하면 매수 신호)
            rsi_overbought: RSI 과매수 기준 (기본 70 → 이 이상이면 매도 신호)
            bb_period     : 볼린저밴드 이동평균 기간 (기본 20일)
            bb_std        : 볼린저밴드 표준편차 배수 (기본 2.0)
        """
        self.rsi_period    = rsi_period
        self.rsi_oversold  = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_period = bb_period
        self.bb_std    = bb_std

    def _calculate_rsi(self, prices: pd.Series) -> pd.Series:
        """
        RSI(상대강도지수)를 계산합니다.
        0~100 사이 값. 30 이하 = 과매도, 70 이상 = 과매수.

        매개변수:
            prices: 종가 Series
        반환값:
            날짜별 RSI Series
        """
        delta = prices.diff()                            # 전일 대비 가격 변화
        gain  = delta.clip(lower=0)                      # 상승분만 추출
        loss  = (-delta).clip(lower=0)                   # 하락분만 추출 (양수로 변환)

        # 지수이동평균(EWM)으로 평균 상승/하락폭 계산
        avg_gain = gain.ewm(com=self.rsi_period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, adjust=False).mean()

        # 0으로 나누는 경우 방어
        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)  # 계산 불가 구간은 중립(50)으로 처리

    def _calculate_bollinger(self, prices: pd.Series) -> tuple:
        """
        볼린저밴드 상단/중단/하단을 계산합니다.

        매개변수:
            prices: 종가 Series
        반환값:
            (upper, middle, lower) 튜플 — 각각 상단/중간/하단 밴드 Series
        """
        middle = prices.rolling(self.bb_period).mean()       # 중간선 (단순이동평균)
        std    = prices.rolling(self.bb_period).std()        # 표준편차
        upper  = middle + self.bb_std * std                  # 상단 밴드
        lower  = middle - self.bb_std * std                  # 하단 밴드
        return upper, middle, lower

    def run(self, df: pd.DataFrame, initial_capital: float, fee_rate: float) -> tuple:
        """
        과거 데이터로 RSI + 볼린저밴드 전략을 시뮬레이션합니다.

        매개변수:
            df             : 일봉 OHLCV 데이터
            initial_capital: 초기 투자금 (원)
            fee_rate       : 거래 수수료율
        반환값:
            (trades, portfolio_values, dates) 튜플
        """
        cash     = initial_capital
        coin_qty = 0.0
        trades   = []
        portfolio_values = []
        dates    = []

        prices              = df["close"]
        rsi                 = self._calculate_rsi(prices)
        upper, middle, lower = self._calculate_bollinger(prices)

        # 지표 계산에 필요한 최소 기간 이후부터 시작
        start_i = max(self.rsi_period, self.bb_period) + 1

        for i in range(start_i, len(df)):
            today    = df.iloc[i]
            date_str = str(df.index[i].date())

            rsi_val   = rsi.iloc[i]
            lower_val = lower.iloc[i]
            upper_val = upper.iloc[i]
            close     = today["close"]

            # ── 매수 조건: RSI 과매도 AND 종가가 볼린저밴드 하단 이하
            if rsi_val < self.rsi_oversold and close <= lower_val and coin_qty == 0 and cash > 0:
                buy_price = today["close"]  # 당일 종가에 체결
                coin_qty  = (cash / buy_price) * (1 - fee_rate)
                trades.append({
                    "date"    : date_str,
                    "type"    : "buy",
                    "price"   : buy_price,
                    "quantity": coin_qty,
                    "amount"  : cash,
                    "rsi"     : round(rsi_val, 2),
                })
                cash = 0.0

            # ── 매도 조건: RSI 과매수 OR 종가가 볼린저밴드 상단 이상
            elif coin_qty > 0 and (rsi_val > self.rsi_overbought or close >= upper_val):
                sell_price  = today["close"]
                sell_amount = coin_qty * sell_price * (1 - fee_rate)

                last_buy = next(
                    (t for t in reversed(trades) if t["type"] == "buy"), None
                )
                profit = sell_amount - (last_buy["amount"] if last_buy else initial_capital)

                trades.append({
                    "date"    : date_str,
                    "type"    : "sell",
                    "price"   : sell_price,
                    "quantity": coin_qty,
                    "amount"  : sell_amount,
                    "profit"  : profit,
                    "rsi"     : round(rsi_val, 2),
                })
                cash     = sell_amount
                coin_qty = 0.0

            portfolio_values.append(cash + coin_qty * today["close"])
            dates.append(df.index[i])

        # 기간 종료 시 강제 청산
        if coin_qty > 0:
            last_close  = df.iloc[-1]["close"]
            sell_amount = coin_qty * last_close * (1 - fee_rate)
            last_buy    = next(
                (t for t in reversed(trades) if t["type"] == "buy"), None
            )
            trades.append({
                "date"    : str(df.index[-1].date()),
                "type"    : "sell",
                "price"   : last_close,
                "quantity": coin_qty,
                "amount"  : sell_amount,
                "profit"  : sell_amount - (last_buy["amount"] if last_buy else 0),
            })

        return trades, portfolio_values, dates
