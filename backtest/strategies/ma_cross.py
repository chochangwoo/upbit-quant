"""
backtest/strategies/ma_cross.py - 이동평균 크로스 전략 (백테스팅용)

전략 설명:
  단기 이동평균선이 장기 이동평균선을 위/아래로 교차할 때 매매합니다.

  [골든크로스 → 매수]
    단기MA(5일)가 장기MA(20일)를 아래→위로 돌파
    → 상승 추세 시작 신호

  [데드크로스 → 매도]
    단기MA(5일)가 장기MA(20일)를 위→아래로 돌파
    → 하락 추세 시작 신호
"""
import pandas as pd


class MACrossStrategy:
    """
    이동평균 크로스 전략 백테스팅 클래스.
    """

    def __init__(self, short_ma: int = 5, long_ma: int = 20):
        """
        매개변수:
            short_ma: 단기 이동평균 기간 (기본 5일)
            long_ma : 장기 이동평균 기간 (기본 20일)
        """
        if short_ma >= long_ma:
            raise ValueError("short_ma는 long_ma보다 작아야 합니다.")
        self.short_ma = short_ma
        self.long_ma  = long_ma

    def run(self, df: pd.DataFrame, initial_capital: float, fee_rate: float) -> tuple:
        """
        과거 데이터로 이동평균 크로스 전략을 시뮬레이션합니다.

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

        closes = df["close"]

        # 단기/장기 이동평균 계산
        short_series = closes.rolling(self.short_ma).mean()  # 단기 이동평균
        long_series  = closes.rolling(self.long_ma).mean()   # 장기 이동평균

        # 단기가 장기 위에 있으면 1, 아니면 0
        position = (short_series > long_series).astype(int)
        # diff()로 교차 신호 감지: +1=골든크로스, -1=데드크로스
        signal = position.diff()

        # 장기 이동평균 계산에 필요한 기간 이후부터 시작
        for i in range(self.long_ma + 1, len(df)):
            today    = df.iloc[i]
            date_str = str(df.index[i].date())
            sig      = signal.iloc[i]

            # ── 골든크로스 → 매수
            if sig == 1 and coin_qty == 0 and cash > 0:
                buy_price = today["open"]  # 다음날 시가에 체결
                coin_qty  = (cash / buy_price) * (1 - fee_rate)
                trades.append({
                    "date"    : date_str,
                    "type"    : "buy",
                    "price"   : buy_price,
                    "quantity": coin_qty,
                    "amount"  : cash,
                    "signal"  : "골든크로스",
                })
                cash = 0.0

            # ── 데드크로스 → 매도
            elif sig == -1 and coin_qty > 0:
                sell_price  = today["open"]  # 다음날 시가에 체결
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
                    "signal"  : "데드크로스",
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
                "signal"  : "기간종료",
            })

        return trades, portfolio_values, dates
