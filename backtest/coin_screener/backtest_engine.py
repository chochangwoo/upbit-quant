"""
backtest/coin_screener/backtest_engine.py - 코인 선별 전략 전용 백테스팅 엔진

코인 스크리너 전략을 기반으로 리밸런싱 방식의 포트폴리오 백테스팅을 수행합니다.
- 리밸런싱 시점마다 전략이 선별한 K개 코인에 균등 분배 매수
- 수수료 및 슬리피지 반영
- 미래 데이터 참조(look-ahead bias) 방지
"""
import pandas as pd
import numpy as np
from loguru import logger


class ScreenerBacktestResult:
    """
    코인 선별 전략 백테스팅 결과를 담는 클래스.
    """

    def __init__(self, strategy_name: str, equity_curve: list,
                 dates: list, trades: list, initial_capital: float,
                 risk_free_rate: float = 0.035):
        """
        매개변수:
            strategy_name  : 전략 이름
            equity_curve   : 일별 포트폴리오 평가액 리스트
            dates          : equity_curve에 대응하는 날짜 리스트
            trades         : 매매 내역 리스트
            initial_capital: 초기 자본금
            risk_free_rate : 무위험이자율 (연 3.5%)
        """
        self.strategy_name = strategy_name
        self.equity_curve = equity_curve
        self.dates = dates
        self.trades = trades
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate

    def total_return(self) -> float:
        """총 수익률 (%)"""
        if not self.equity_curve:
            return 0.0
        return (self.equity_curve[-1] - self.initial_capital) / self.initial_capital * 100

    def mdd(self) -> float:
        """최대 낙폭 MDD (%)"""
        if not self.equity_curve:
            return 0.0
        values = pd.Series(self.equity_curve)
        peak = values.cummax()
        drawdown = (values - peak) / peak * 100
        return float(drawdown.min())

    def sharpe_ratio(self) -> float:
        """샤프 비율 (연환산, 무위험이자율 반영)"""
        if len(self.equity_curve) < 2:
            return 0.0
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        # 일간 무위험이자율
        daily_rf = self.risk_free_rate / 365
        excess_returns = returns - daily_rf
        return float(excess_returns.mean() / excess_returns.std() * (365 ** 0.5))

    def win_rate(self) -> float:
        """승률 (%): 매도 시 수익인 비율"""
        sell_trades = [t for t in self.trades if t.get("type") == "sell"]
        if not sell_trades:
            return 0.0
        wins = sum(1 for t in sell_trades if t.get("profit", 0) > 0)
        return wins / len(sell_trades) * 100

    def total_trades_count(self) -> int:
        """총 거래 횟수"""
        return len(self.trades)

    def summary(self) -> dict:
        """모든 성능 지표를 딕셔너리로 반환합니다."""
        return {
            "strategy_name": self.strategy_name,
            "total_return": self.total_return(),
            "mdd": self.mdd(),
            "sharpe_ratio": self.sharpe_ratio(),
            "win_rate": self.win_rate(),
            "total_trades": self.total_trades_count(),
        }


class ScreenerBacktestEngine:
    """
    코인 선별 전략 전용 백테스팅 엔진.
    리밸런싱 방식으로 포트폴리오를 운영합니다.
    """

    def __init__(self, screener, all_data: dict,
                 initial_capital: float = 1_000_000,
                 rebalance_days: int = 3,
                 fee_rate: float = 0.0005,
                 slippage: float = 0.001):
        """
        매개변수:
            screener       : 스크리너 전략 객체 (BaseScreener 상속)
            all_data       : {ticker: DataFrame} 전체 코인 데이터
            initial_capital: 초기 자본금 (기본 1,000,000원)
            rebalance_days : 리밸런싱 주기 (기본 3일)
            fee_rate       : 편도 수수료율 (기본 0.05%)
            slippage       : 슬리피지 (기본 0.1%)
        """
        self.screener = screener
        self.all_data = all_data
        self.initial_capital = initial_capital
        self.rebalance_days = rebalance_days
        self.fee_rate = fee_rate
        self.slippage = slippage

    def _get_common_dates(self) -> pd.DatetimeIndex:
        """
        과반수 이상의 코인에 존재하는 날짜 인덱스를 반환합니다.
        모든 코인에 공통인 날짜만 사용하면 데이터가 너무 적어질 수 있으므로,
        전체 코인의 50% 이상이 가진 날짜를 사용합니다.
        """
        from collections import Counter
        date_counter = Counter()
        for df in self.all_data.values():
            for dt in df.index:
                date_counter[dt] += 1

        threshold = len(self.all_data) * 0.5
        common_dates = [dt for dt, cnt in date_counter.items() if cnt >= threshold]
        return pd.DatetimeIndex(sorted(common_dates))

    def run(self) -> ScreenerBacktestResult:
        """
        백테스팅을 실행합니다.

        로직:
        1. 전체 코인의 공통 날짜를 기준으로 순회
        2. 리밸런싱 주기마다 스크리너로 코인 선별
        3. 기존 보유 전량 매도 → 선별된 코인에 균등 분배 매수
        4. 매일 포트폴리오 평가액 기록
        """
        logger.info(f"백테스팅 시작: {self.screener.name}")

        # 공통 날짜 인덱스 구하기
        all_dates = self._get_common_dates()
        if len(all_dates) == 0:
            logger.error("공통 날짜가 없어 백테스팅 불가")
            return ScreenerBacktestResult(
                self.screener.name, [], [], [], self.initial_capital
            )

        # 최소 시작 인덱스 (지표 계산에 필요한 워밍업 기간)
        warmup = 30
        if len(all_dates) <= warmup:
            logger.error("데이터가 부족하여 백테스팅 불가")
            return ScreenerBacktestResult(
                self.screener.name, [], [], [], self.initial_capital
            )

        cash = self.initial_capital
        holdings = {}  # {ticker: {"qty": float, "buy_price": float}}
        equity_curve = []
        dates_list = []
        trades = []
        days_since_rebalance = self.rebalance_days  # 첫날 바로 리밸런싱

        for i in range(warmup, len(all_dates)):
            current_date = all_dates[i]
            days_since_rebalance += 1

            # ── 리밸런싱 시점 ──
            if days_since_rebalance >= self.rebalance_days:
                days_since_rebalance = 0

                # 1. 기존 보유 전량 매도
                for ticker, info in holdings.items():
                    if ticker not in self.all_data:
                        continue
                    df = self.all_data[ticker]
                    if current_date not in df.index:
                        continue

                    sell_price = df.loc[current_date, "close"]
                    sell_amount = info["qty"] * sell_price
                    # 수수료 + 슬리피지 차감
                    sell_amount *= (1 - self.fee_rate - self.slippage)

                    profit = sell_amount - (info["qty"] * info["buy_price"])
                    trades.append({
                        "date": str(current_date.date()),
                        "type": "sell",
                        "ticker": ticker,
                        "price": sell_price,
                        "amount": sell_amount,
                        "profit": profit,
                    })
                    cash += sell_amount

                holdings = {}

                # 2. 스크리너로 코인 선별
                selected = self.screener.screen(self.all_data, current_date)

                if selected:
                    # 3. 선별된 코인에 균등 분배 매수
                    per_coin_budget = cash / len(selected)

                    for ticker, score in selected:
                        if ticker not in self.all_data:
                            continue
                        df = self.all_data[ticker]
                        if current_date not in df.index:
                            continue

                        buy_price = df.loc[current_date, "close"]
                        # 수수료 + 슬리피지 차감
                        effective_budget = per_coin_budget * (1 - self.fee_rate - self.slippage)
                        qty = effective_budget / buy_price

                        holdings[ticker] = {
                            "qty": qty,
                            "buy_price": buy_price,
                        }
                        trades.append({
                            "date": str(current_date.date()),
                            "type": "buy",
                            "ticker": ticker,
                            "price": buy_price,
                            "amount": per_coin_budget,
                            "score": score,
                        })

                    cash -= per_coin_budget * len([
                        t for t, _ in selected
                        if t in self.all_data and current_date in self.all_data[t].index
                    ])
                    cash = max(cash, 0)

            # ── 포트폴리오 평가 ──
            portfolio_value = cash
            for ticker, info in holdings.items():
                if ticker not in self.all_data:
                    continue
                df = self.all_data[ticker]
                if current_date in df.index:
                    portfolio_value += info["qty"] * df.loc[current_date, "close"]

            equity_curve.append(portfolio_value)
            dates_list.append(current_date)

        # 기간 종료 시 잔여 포지션 청산
        if holdings and len(all_dates) > 0:
            last_date = all_dates[-1]
            for ticker, info in holdings.items():
                if ticker not in self.all_data:
                    continue
                df = self.all_data[ticker]
                if last_date in df.index:
                    sell_price = df.loc[last_date, "close"]
                    sell_amount = info["qty"] * sell_price * (1 - self.fee_rate - self.slippage)
                    profit = sell_amount - (info["qty"] * info["buy_price"])
                    trades.append({
                        "date": str(last_date.date()),
                        "type": "sell",
                        "ticker": ticker,
                        "price": sell_price,
                        "amount": sell_amount,
                        "profit": profit,
                        "signal": "기간종료",
                    })

        logger.info(f"백테스팅 완료: {self.screener.name} | 거래 {len(trades)}건")

        return ScreenerBacktestResult(
            strategy_name=self.screener.name,
            equity_curve=equity_curve,
            dates=dates_list,
            trades=trades,
            initial_capital=self.initial_capital,
        )
