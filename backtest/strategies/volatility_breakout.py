"""
backtest/strategies/volatility_breakout.py - 변동성 돌파 전략 (백테스팅용)

전략 설명:
  - 매수: 당일 시가 + (전일 고가 - 전일 저가) × K 를 당일 고가가 넘으면 체결
  - 매도: 당일 종가에 전량 청산 (1일 보유)
  - 수수료: 매수/매도 각각 fee_rate 적용
"""
import pandas as pd


class VolatilityBreakoutStrategy:
    """
    변동성 돌파 전략 백테스팅 클래스.

    사용 예시:
        strategy = VolatilityBreakoutStrategy(k=0.5)
        trades, portfolio_values, dates = strategy.run(df, 1_000_000, 0.0005)
    """

    def __init__(self, k: float = 0.5):
        """
        매개변수:
            k: 변동성 비율 (0.3~0.7 권장, 기본값 0.5)
               낮을수록 목표가가 낮아져 매매 횟수가 늘어나고 위험도 올라감
        """
        self.k = k

    def run(self, df: pd.DataFrame, initial_capital: float, fee_rate: float) -> tuple:
        """
        과거 일봉 데이터로 전략을 시뮬레이션합니다.

        매개변수:
            df             : 일봉 OHLCV 데이터 (pyupbit.get_ohlcv 결과물)
            initial_capital: 초기 투자금 (원)
            fee_rate       : 거래 수수료율 (예: 0.0005 = 0.05%)
        반환값:
            (trades, portfolio_values, dates) 튜플
            - trades          : 매매 내역 리스트 (buy/sell 각각)
            - portfolio_values: 날짜별 포트폴리오 평가액 리스트
            - dates           : portfolio_values에 대응하는 날짜 리스트
        """
        cash = initial_capital  # 현재 보유 현금
        trades = []             # 매매 내역
        portfolio_values = []   # 날짜별 평가액
        dates = []              # 날짜 리스트

        # 첫째 날은 전일 데이터가 없으므로 둘째 날부터 시작
        for i in range(1, len(df)):
            today     = df.iloc[i]
            yesterday = df.iloc[i - 1]
            date_str  = str(df.index[i].date())

            # 목표가 = 당일 시가 + (전일 고가 - 전일 저가) × K
            target = today["open"] + (yesterday["high"] - yesterday["low"]) * self.k

            # 매수 조건: 당일 고가가 목표가를 돌파했을 때
            if today["high"] >= target:
                buy_price = target

                # 매수 수량 계산 (수수료 차감 후)
                qty = (cash / buy_price) * (1 - fee_rate)
                buy_amount = cash  # 전액 투자

                # 당일 종가에 전량 매도
                sell_price  = today["close"]
                sell_amount = qty * sell_price * (1 - fee_rate)

                # 해당 거래의 손익
                profit = sell_amount - buy_amount

                trades.append({
                    "date"    : date_str,
                    "type"    : "buy",
                    "price"   : buy_price,
                    "quantity": qty,
                    "amount"  : buy_amount,
                })
                trades.append({
                    "date"    : date_str,
                    "type"    : "sell",
                    "price"   : sell_price,
                    "quantity": qty,
                    "amount"  : sell_amount,
                    "profit"  : profit,
                })

                cash = sell_amount  # 매도 후 현금 업데이트

            # 오늘 날짜의 포트폴리오 가치 기록 (매매 없으면 현금 그대로)
            portfolio_values.append(cash)
            dates.append(df.index[i])

        return trades, portfolio_values, dates
