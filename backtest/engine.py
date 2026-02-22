"""
backtest/engine.py - 백테스팅 핵심 엔진

과거 데이터를 기반으로 전략을 시뮬레이션하고
성능 지표를 계산합니다.

사용 예시:
    from backtest.engine import BacktestEngine
    from backtest.strategies.volatility_breakout import VolatilityBreakoutStrategy

    engine = BacktestEngine(
        strategy=VolatilityBreakoutStrategy(k=0.5),
        ticker="KRW-BTC",
        start_date="2023-01-01",
        end_date="2024-12-31",
    )
    result = engine.run()
"""
import os
import time
import yaml
import pandas as pd
import numpy as np
import pyupbit
from loguru import logger


# ─────────────────────────────────────────
# 설정 로드
# ─────────────────────────────────────────

def load_backtest_config() -> dict:
    """config/settings.yaml에서 백테스팅 설정을 읽어옵니다."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("backtest", {})


# ─────────────────────────────────────────
# 데이터 수집
# ─────────────────────────────────────────

def fetch_ohlcv(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    업비트 API에서 일봉 데이터를 날짜 범위에 맞게 가져옵니다.

    업비트 API는 한 번에 최대 200일치만 반환하므로,
    날짜 범위가 길면 여러 번 나눠서 자동으로 가져옵니다.

    매개변수:
        ticker    : 코인 티커 (예: "KRW-BTC")
        start_date: 시작일 문자열 (예: "2023-01-01")
        end_date  : 종료일 문자열 (예: "2024-12-31")
    반환값:
        날짜 인덱스의 OHLCV DataFrame, 실패 시 None
    """
    logger.info(f"[{ticker}] 과거 데이터 수집 중: {start_date} ~ {end_date}")

    start_dt = pd.Timestamp(start_date)
    # to 파라미터는 그 날짜 이전 데이터를 반환하므로 하루 더 추가
    to_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1)

    all_dfs = []

    while True:
        try:
            df = pyupbit.get_ohlcv(
                ticker,
                interval="day",
                count=200,
                to=to_dt.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            logger.error(f"API 호출 실패: {e}")
            break

        if df is None or df.empty:
            break

        all_dfs.append(df)

        # 가져온 데이터의 가장 오래된 날짜
        earliest = pd.Timestamp(df.index[0])

        # 시작일보다 앞선 데이터까지 가져왔으면 완료
        if earliest <= start_dt:
            break

        # 다음 요청은 현재 가장 오래된 날짜 이전부터
        to_dt = earliest
        time.sleep(0.2)  # API 호출 제한 방지 (초당 10회 이하)

    if not all_dfs:
        logger.error(f"[{ticker}] 데이터를 가져올 수 없습니다.")
        return None

    # 여러 번 나눠 가져온 데이터를 하나로 합치기
    combined = pd.concat(all_dfs)
    combined = combined[~combined.index.duplicated(keep="first")]  # 중복 날짜 제거
    combined.sort_index(inplace=True)

    # 요청한 날짜 범위로 자르기
    combined = combined.loc[start_date:end_date]

    logger.info(f"[{ticker}] 데이터 수집 완료: {len(combined)}일치")
    return combined


# ─────────────────────────────────────────
# 백테스팅 결과 클래스
# ─────────────────────────────────────────

class BacktestResult:
    """
    백테스팅 실행 후 결과를 담는 클래스.
    성능 지표 계산과 콘솔 출력을 담당합니다.
    """

    def __init__(self, trades: list, portfolio_values: list,
                 dates: list, config: dict, strategy_name: str, ticker: str):
        """
        매개변수:
            trades          : 매매 내역 리스트
            portfolio_values: 날짜별 포트폴리오 평가액 리스트
            dates           : portfolio_values에 대응하는 날짜 리스트
            config          : 백테스팅 설정 딕셔너리
            strategy_name   : 전략 이름 (리포트 출력용)
            ticker          : 코인 티커 (리포트 출력용)
        """
        self.trades = trades
        self.portfolio_values = portfolio_values
        self.dates = dates
        self.initial_capital = config.get("initial_capital", 1_000_000)
        self.fee_rate = config.get("fee_rate", 0.0005)
        self.strategy_name = strategy_name
        self.ticker = ticker

    def cumulative_return(self) -> float:
        """
        누적 수익률을 계산합니다.
        공식: (최종 자산 - 초기 자산) / 초기 자산 × 100
        """
        if not self.portfolio_values:
            return 0.0
        return (self.portfolio_values[-1] - self.initial_capital) / self.initial_capital * 100

    def mdd(self) -> float:
        """
        MDD(최대 낙폭)를 계산합니다.
        고점 대비 최대 하락폭 — 클수록 위험한 전략입니다.
        """
        if not self.portfolio_values:
            return 0.0
        values = pd.Series(self.portfolio_values)
        peak = values.cummax()                       # 누적 고점
        drawdown = (values - peak) / peak * 100      # 고점 대비 낙폭
        return float(drawdown.min())                 # 가장 큰 낙폭

    def win_rate(self) -> float:
        """
        승률을 계산합니다.
        공식: 수익이 난 매도 횟수 / 전체 매도 횟수 × 100
        """
        sell_trades = [t for t in self.trades if t.get("type") == "sell"]
        if not sell_trades:
            return 0.0
        wins = sum(1 for t in sell_trades if t.get("profit", 0) > 0)
        return wins / len(sell_trades) * 100

    def sharpe_ratio(self) -> float:
        """
        샤프 지수를 계산합니다.
        공식: 일평균 수익률 / 수익률 표준편차 × sqrt(252)
        → 값이 높을수록 위험 대비 수익이 좋은 전략입니다.
        → 1.0 이상이면 양호, 2.0 이상이면 우수.
        """
        if len(self.portfolio_values) < 2:
            return 0.0
        returns = pd.Series(self.portfolio_values).pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        # 연율화 (1년 = 252 거래일 기준)
        return float(returns.mean() / returns.std() * (252 ** 0.5))

    def total_trades(self) -> int:
        """총 매매 횟수 (매수 + 매도 합계)를 반환합니다."""
        return len(self.trades)

    def avg_hold_days(self) -> float:
        """
        평균 보유 기간을 계산합니다.
        매수일부터 매도일까지의 평균 일수입니다.
        """
        buys  = [t for t in self.trades if t["type"] == "buy"]
        sells = [t for t in self.trades if t["type"] == "sell"]
        if not buys or not sells:
            return 0.0

        hold_days = []
        for buy, sell in zip(buys, sells):
            b = pd.Timestamp(buy["date"])
            s = pd.Timestamp(sell["date"])
            hold_days.append(max((s - b).days, 1))  # 당일 매도도 최소 1일로 계산

        return sum(hold_days) / len(hold_days)

    def summary(self) -> dict:
        """모든 성능 지표를 딕셔너리로 반환합니다."""
        return {
            "strategy_name"    : self.strategy_name,
            "ticker"           : self.ticker,
            "cumulative_return": self.cumulative_return(),
            "mdd"              : self.mdd(),
            "win_rate"         : self.win_rate(),
            "sharpe_ratio"     : self.sharpe_ratio(),
            "total_trades"     : self.total_trades(),
            "avg_hold_days"    : self.avg_hold_days(),
        }

    def print_summary(self):
        """성능 지표를 콘솔에 보기 좋게 출력합니다."""
        s = self.summary()
        print("\n" + "=" * 45)
        print(f"  백테스팅 결과: {s['strategy_name']} | {s['ticker']}")
        print("=" * 45)
        print(f"  누적 수익률  : {s['cumulative_return']:+.2f}%")
        print(f"  최대 낙폭    : {s['mdd']:.2f}%")
        print(f"  승률         : {s['win_rate']:.1f}%")
        print(f"  샤프 지수    : {s['sharpe_ratio']:.2f}")
        print(f"  총 거래 횟수 : {s['total_trades']}건")
        print(f"  평균 보유일  : {s['avg_hold_days']:.1f}일")
        print("=" * 45 + "\n")


# ─────────────────────────────────────────
# 백테스팅 엔진
# ─────────────────────────────────────────

class BacktestEngine:
    """
    백테스팅 엔진 메인 클래스.
    전략 객체와 기간을 받아 시뮬레이션을 실행합니다.
    """

    def __init__(self, strategy, ticker: str,
                 start_date: str = None, end_date: str = None):
        """
        매개변수:
            strategy  : 전략 객체 (backtest/strategies/ 안의 클래스 인스턴스)
            ticker    : 코인 티커 (예: "KRW-BTC")
            start_date: 백테스팅 시작일 (None이면 settings.yaml 값 사용)
            end_date  : 백테스팅 종료일 (None이면 settings.yaml 값 사용)
        """
        self.config = load_backtest_config()
        self.strategy = strategy
        self.ticker = ticker
        self.start_date = start_date or self.config.get("start_date", "2023-01-01")
        self.end_date   = end_date   or self.config.get("end_date",   "2024-12-31")
        self.initial_capital = self.config.get("initial_capital", 1_000_000)
        self.fee_rate        = self.config.get("fee_rate", 0.0005)

    def run(self) -> BacktestResult:
        """
        백테스팅을 실행하고 결과(BacktestResult)를 반환합니다.
        내부적으로 데이터 수집 → 전략 실행 → 결과 생성 순서로 동작합니다.
        """
        # 1단계: 과거 데이터 수집
        df = fetch_ohlcv(self.ticker, self.start_date, self.end_date)
        if df is None or df.empty:
            logger.error("데이터 로드 실패로 백테스팅을 중단합니다.")
            return None

        # 2단계: 전략 실행 (각 전략 클래스의 run() 메서드에 위임)
        strategy_name = self.strategy.__class__.__name__
        logger.info(f"전략 시뮬레이션 시작: {strategy_name}")
        trades, portfolio_values, dates = self.strategy.run(
            df=df,
            initial_capital=self.initial_capital,
            fee_rate=self.fee_rate,
        )

        # 3단계: 결과 객체 생성
        result = BacktestResult(
            trades=trades,
            portfolio_values=portfolio_values,
            dates=dates,
            config=self.config,
            strategy_name=strategy_name,
            ticker=self.ticker,
        )
        result.print_summary()
        return result
