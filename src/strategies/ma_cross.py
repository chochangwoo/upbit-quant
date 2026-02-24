"""
이동평균 크로스 전략 (실거래용)

전략 원리:
- 골든크로스: 단기 MA(5일)가 장기 MA(20일)를 위로 돌파 → 매수
- 데드크로스: 단기 MA(5일)가 장기 MA(20일)를 아래로 돌파 → 매도
- 일봉 데이터 기반으로 신호를 감지합니다.
"""
from loguru import logger
from src.api.upbit_client import get_ohlcv
from src.strategies.base import BaseStrategy


class MACrossStrategy(BaseStrategy):
    """이동평균 크로스 실거래 전략 클래스."""

    def __init__(self, short_window: int = 5, long_window: int = 20):
        """
        매개변수:
            short_window: 단기 이동평균 기간 (기본 5일)
            long_window : 장기 이동평균 기간 (기본 20일)
        """
        if short_window >= long_window:
            raise ValueError("short_window는 long_window보다 작아야 합니다.")
        self.short_window = short_window
        self.long_window  = long_window

    def get_strategy_name(self) -> str:
        return "ma_cross"

    def get_ma_values(self, ticker: str) -> dict | None:
        """
        최신 MA 값과 이전 MA 값을 계산하여 반환합니다.

        반환값:
            {
              "ma_short"     : 현재 단기 MA,
              "ma_long"      : 현재 장기 MA,
              "ma_short_prev": 전일 단기 MA,
              "ma_long_prev" : 전일 장기 MA,
              "current_price": 현재가 (최신 종가),
            }
        """
        # 장기 MA 계산에 필요한 기간 + 이전값 비교용 여유분 포함
        count = self.long_window + 5
        df = get_ohlcv(ticker, interval="day", count=count)

        if df is None or len(df) < self.long_window + 2:
            logger.error(f"[{ticker}] MA 계산에 필요한 데이터가 부족합니다.")
            return None

        closes       = df["close"]
        short_series = closes.rolling(self.short_window).mean()
        long_series  = closes.rolling(self.long_window).mean()

        return {
            "ma_short"     : short_series.iloc[-1],
            "ma_long"      : long_series.iloc[-1],
            "ma_short_prev": short_series.iloc[-2],
            "ma_long_prev" : long_series.iloc[-2],
            "current_price": closes.iloc[-1],
        }

    def check_signal(self, ticker: str) -> tuple[str | None, dict]:
        """
        골든크로스/데드크로스 신호를 확인합니다.

        반환값:
            ('buy', info)   → 골든크로스 감지
            ('sell', info)  → 데드크로스 감지
            (None, info)    → 신호 없음
        """
        values = self.get_ma_values(ticker)
        if values is None:
            return None, {}

        ma5_prev  = values["ma_short_prev"]
        ma20_prev = values["ma_long_prev"]
        ma5_curr  = values["ma_short"]
        ma20_curr = values["ma_long"]

        info = {
            "ma5"          : ma5_curr,
            "ma20"         : ma20_curr,
            "current_price": values["current_price"],
        }

        # 골든크로스: MA5가 MA20을 위로 돌파 → 매수
        if ma5_prev <= ma20_prev and ma5_curr > ma20_curr:
            logger.info(
                f"[{ticker}] 골든크로스 감지! "
                f"MA{self.short_window}: {ma5_curr:,.0f} / MA{self.long_window}: {ma20_curr:,.0f}"
            )
            info["signal"] = "golden_cross"
            return "buy", info

        # 데드크로스: MA5가 MA20을 아래로 돌파 → 매도
        if ma5_prev >= ma20_prev and ma5_curr < ma20_curr:
            logger.info(
                f"[{ticker}] 데드크로스 감지! "
                f"MA{self.short_window}: {ma5_curr:,.0f} / MA{self.long_window}: {ma20_curr:,.0f}"
            )
            info["signal"] = "dead_cross"
            return "sell", info

        # 신호 없음
        logger.debug(
            f"[{ticker}] 신호 없음. "
            f"MA{self.short_window}: {ma5_curr:,.0f} / MA{self.long_window}: {ma20_curr:,.0f}"
        )
        return None, info
