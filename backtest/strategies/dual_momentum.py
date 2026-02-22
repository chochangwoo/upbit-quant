"""
backtest/strategies/dual_momentum.py - 듀얼 모멘텀 전략 (백테스팅용)

게리 안토나치(Gary Antonacci)가 고안한 전략입니다.

전략 설명:
  - 절대 모멘텀: 최근 N일 수익률이 0(무위험 수익률)보다 높으면 보유
  - 절대 모멘텀 미충족: 현금 보유 (하락장 방어)
  - 포지션 변경은 매일 종가 기준으로 확인
  - 매매 신호 발생 시 다음날 시가에 체결 (현실 반영)
"""
import pandas as pd


class DualMomentumStrategy:
    """
    듀얼 모멘텀 전략 백테스팅 클래스.

    사용 예시:
        strategy = DualMomentumStrategy(lookback_days=12)
        trades, portfolio_values, dates = strategy.run(df, 1_000_000, 0.0005)
    """

    def __init__(self, lookback_days: int = 12, risk_free_rate: float = 0.0):
        """
        매개변수:
            lookback_days  : 모멘텀 계산 기간 (일), 기본 12일
            risk_free_rate : 무위험 수익률 기준 (기본 0%)
                             이 값보다 모멘텀이 낮으면 현금 보유
        """
        self.lookback_days  = lookback_days
        self.risk_free_rate = risk_free_rate

    def run(self, df: pd.DataFrame, initial_capital: float, fee_rate: float) -> tuple:
        """
        과거 데이터로 듀얼 모멘텀 전략을 시뮬레이션합니다.

        매개변수:
            df             : 일봉 OHLCV 데이터
            initial_capital: 초기 투자금 (원)
            fee_rate       : 거래 수수료율
        반환값:
            (trades, portfolio_values, dates) 튜플
        """
        cash     = initial_capital  # 현재 보유 현금
        coin_qty = 0.0              # 현재 보유 코인 수량
        trades   = []
        portfolio_values = []
        dates    = []

        # N일 모멘텀 (N일 전 종가 대비 현재 종가 수익률)
        momentum = df["close"].pct_change(self.lookback_days)

        # 매매 신호: 당일 종가 기준으로 계산 후 다음날 시가에 체결
        # → lookback_days + 1 일째부터 시작
        for i in range(self.lookback_days + 1, len(df)):
            today    = df.iloc[i]
            prev_mom = momentum.iloc[i - 1]  # 어제 종가 기준 모멘텀으로 오늘 거래 결정
            date_str = str(df.index[i].date())

            # ── 매수 신호: 모멘텀 > 무위험 수익률 + 코인 미보유
            if prev_mom > self.risk_free_rate and coin_qty == 0 and cash > 0:
                buy_price = today["open"]   # 당일 시가에 매수 (현실 반영)
                coin_qty  = (cash / buy_price) * (1 - fee_rate)
                trades.append({
                    "date"    : date_str,
                    "type"    : "buy",
                    "price"   : buy_price,
                    "quantity": coin_qty,
                    "amount"  : cash,
                })
                cash = 0.0

            # ── 매도 신호: 모멘텀 ≤ 무위험 수익률 + 코인 보유 중
            elif prev_mom <= self.risk_free_rate and coin_qty > 0:
                sell_price  = today["open"]  # 당일 시가에 매도
                sell_amount = coin_qty * sell_price * (1 - fee_rate)

                # 직전 매수 금액 찾기
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
                })
                cash     = sell_amount
                coin_qty = 0.0

            # 당일 포트폴리오 평가액 = 현금 + 보유 코인 × 당일 종가
            portfolio_values.append(cash + coin_qty * today["close"])
            dates.append(df.index[i])

        # 기간 종료 시 코인 보유 중이면 마지막 종가에 강제 청산
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
