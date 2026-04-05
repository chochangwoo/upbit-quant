"""
src/strategies/bb_rsi_mean_reversion.py - BB+RSI 평균회귀 전략

횡보장에서 볼린저밴드 하단 + RSI 과매도 시 매수,
볼린저밴드 상단 + RSI 과매수 시 매도하는 평균회귀 전략.

백테스트 근거 (300일, 13개 코인):
  - BB+RSI 평균 수익률: +2.14% (횡보장 구간만)
  - 거래량돌파 평균 수익률: -2.08% (횡보장 구간만)
  - BB+RSI 우위: 8/13 코인
  - BB+RSI 평균 MDD: -1.2% vs 거래량돌파 MDD: -7.0%

매수 조건 (모두 충족):
  1. 현재 시장 국면이 sideways
  2. 현재가 <= 볼린저밴드 하단
  3. RSI(14) < 30 (과매도)
  4. (선택) 이전 캔들 BB 하단 아래 → 현재 캔들 BB 하단 위 복귀

매도 조건 (하나라도 충족):
  1. BB 상단 터치 + RSI > 70 → 전량 매도
  2. 현재가 >= BB 중간선 AND 수익률 > 1% → 보수적 익절
  3. 수익률 <= -3% → 손절
  4. 수익률 >= +5% → 익절
  5. 시장 국면이 sideways가 아닌 것으로 전환 → 즉시 청산
"""

import time
import pandas as pd
from loguru import logger

from src.api.upbit_client import get_ohlcv, get_current_price, get_avg_buy_price
from src.strategies.base import BaseStrategy


# 대상 코인 13종
TARGET_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """볼린저밴드 상단/중간/하단 계산"""
    df = df.copy()
    df['bb_mid'] = df['close'].rolling(period).mean()
    df['bb_std'] = df['close'].rolling(period).std()
    df['bb_upper'] = df['bb_mid'] + std_dev * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - std_dev * df['bb_std']
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid'] * 100
    return df


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI 계산"""
    df = df.copy()
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df


class BBRSIMeanReversion(BaseStrategy):
    """
    BB+RSI 평균회귀 전략

    횡보장에서 볼린저밴드 + RSI 조합으로 과매도 매수, 과매수 매도.
    StrategyRouter에 의해 횡보장 감지 시 자동 활성화됩니다.
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
        position_size: float = 0.95,
        relaxed_mode: bool = False,
        relaxed_rsi_oversold: int = 35,
        relaxed_bb_std: float = 1.5,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.position_size = position_size

        # 완화 모드 적용
        if relaxed_mode:
            self.rsi_oversold = relaxed_rsi_oversold
            self.bb_std = relaxed_bb_std
            logger.info(f"[BB+RSI] 완화 모드 적용: RSI<{self.rsi_oversold}, BB std={self.bb_std}")

        self.coins = TARGET_COINS

        # 코인별 보유 상태 추적 (매수가 기록)
        self.positions = {}  # {ticker: entry_price}

        logger.info(
            f"[BB+RSI] 초기화 완료 | BB({self.bb_period}, {self.bb_std}) | "
            f"RSI({self.rsi_period}) | 과매도<{self.rsi_oversold} | 과매수>{self.rsi_overbought} | "
            f"손절: {self.stop_loss_pct}% | 익절: {self.take_profit_pct}%"
        )

    def get_strategy_name(self) -> str:
        return "bb_rsi_mean_reversion"

    def _calc_indicators(self, ticker: str) -> dict | None:
        """코인의 BB+RSI 지표를 계산합니다."""
        try:
            count = max(self.bb_period, self.rsi_period) + 10
            df = get_ohlcv(ticker, interval="day", count=count)
            if df is None or len(df) < self.bb_period:
                return None

            df = calculate_bollinger_bands(df, self.bb_period, self.bb_std)
            df = calculate_rsi(df, self.rsi_period)

            current = df.iloc[-1]
            prev = df.iloc[-2]

            return {
                "current_price": current['close'],
                "bb_upper": current['bb_upper'],
                "bb_mid": current['bb_mid'],
                "bb_lower": current['bb_lower'],
                "bb_width": current['bb_width'],
                "rsi": current['rsi'],
                "prev_close": prev['close'],
                "prev_bb_lower": prev['bb_lower'],
            }
        except Exception as e:
            logger.error(f"[BB+RSI] {ticker} 지표 계산 오류: {e}")
            return None

    def check_buy_signal(self, ticker: str, indicators: dict) -> bool:
        """매수 조건 확인 (모두 충족 시 True)"""
        price = indicators["current_price"]
        bb_lower = indicators["bb_lower"]
        rsi = indicators["rsi"]

        # 조건 1: 현재가 <= BB 하단
        if price > bb_lower:
            return False

        # 조건 2: RSI < 과매도 기준
        if rsi >= self.rsi_oversold:
            return False

        # 조건 3 (선택): 이전 캔들에서 BB 하단 아래 → 현재 BB 하단 근처로 복귀
        prev_close = indicators["prev_close"]
        prev_bb_lower = indicators["prev_bb_lower"]
        bb_bounce = prev_close <= prev_bb_lower and price >= bb_lower * 0.99

        logger.info(
            f"[BB+RSI] {ticker} 매수 신호! | "
            f"가격: {price:,.0f} <= BB하단: {bb_lower:,.0f} | "
            f"RSI: {rsi:.1f} < {self.rsi_oversold} | "
            f"BB 반등: {bb_bounce}"
        )
        return True

    def check_sell_signal(self, ticker: str, indicators: dict, entry_price: float) -> tuple[bool, str]:
        """
        매도 조건 확인 (하나라도 충족 시 True)

        반환값: (매도 여부, 매도 사유)
        """
        price = indicators["current_price"]
        bb_upper = indicators["bb_upper"]
        bb_mid = indicators["bb_mid"]
        rsi = indicators["rsi"]

        # 수익률 계산 (수수료 0.05% 반영)
        fee = 0.0005
        pnl_pct = (price / entry_price - 1) * 100 - (fee * 2 * 100)

        # 조건 1: BB 상단 터치 + RSI > 70 (과매수)
        if price >= bb_upper and rsi > self.rsi_overbought:
            return True, "bb_upper_rsi"

        # 조건 2: BB 중간선 도달 + 수익 1% 이상 → 보수적 익절
        if price >= bb_mid and pnl_pct > 1.0:
            return True, "bb_mid"

        # 조건 3: 손절
        if pnl_pct <= self.stop_loss_pct:
            return True, "stop_loss"

        # 조건 4: 익절
        if pnl_pct >= self.take_profit_pct:
            return True, "take_profit"

        return False, ""

    def check_signal(self, ticker: str = None) -> tuple[str | None, dict]:
        """
        전체 코인 대상 BB+RSI 매매 신호를 확인합니다.

        StrategyRouter에서 호출됩니다.
        ticker가 None이면 전체 코인 스캔, 지정되면 해당 코인만 확인.

        반환값:
            ('buy', info)  → 매수 신호
            ('sell', info) → 매도 신호
            (None, info)   → 대기
        """
        buy_signals = []
        sell_signals = []

        coins_to_check = [ticker] if ticker else self.coins

        for coin in coins_to_check:
            try:
                indicators = self._calc_indicators(coin)
                if indicators is None:
                    continue

                # 이미 보유 중인 코인 → 매도 조건 확인
                if coin in self.positions:
                    entry_price = self.positions[coin]
                    should_sell, reason = self.check_sell_signal(coin, indicators, entry_price)
                    if should_sell:
                        price = indicators["current_price"]
                        fee = 0.0005
                        pnl_pct = (price / entry_price - 1) * 100 - (fee * 2 * 100)

                        sell_signals.append({
                            "ticker": coin,
                            "price": price,
                            "entry_price": entry_price,
                            "pnl_pct": pnl_pct,
                            "sell_reason": reason,
                            "bb_upper": indicators["bb_upper"],
                            "bb_mid": indicators["bb_mid"],
                            "bb_lower": indicators["bb_lower"],
                            "rsi": indicators["rsi"],
                            "bb_width": indicators["bb_width"],
                        })

                        logger.info(
                            f"[BB+RSI] {coin} 매도 신호 | 사유: {reason} | "
                            f"수익률: {pnl_pct:+.2f}% | RSI: {indicators['rsi']:.1f}"
                        )
                else:
                    # 보유하지 않은 코인 → 매수 조건 확인
                    if self.check_buy_signal(coin, indicators):
                        buy_signals.append({
                            "ticker": coin,
                            "price": indicators["current_price"],
                            "bb_upper": indicators["bb_upper"],
                            "bb_mid": indicators["bb_mid"],
                            "bb_lower": indicators["bb_lower"],
                            "rsi": indicators["rsi"],
                            "bb_width": indicators["bb_width"],
                        })

                time.sleep(0.1)  # API 레이트 리밋

            except Exception as e:
                logger.error(f"[BB+RSI] {coin} 처리 오류: {e}")
                continue

        # 매도 우선
        if sell_signals:
            return "sell", {"signals": sell_signals, "type": "bb_rsi_sell"}

        if buy_signals:
            return "buy", {"signals": buy_signals, "type": "bb_rsi_buy"}

        return None, {"type": "bb_rsi_wait", "positions": len(self.positions)}

    def add_position(self, ticker: str, entry_price: float):
        """보유 포지션 추가 (매수 체결 후 호출)"""
        self.positions[ticker] = entry_price
        logger.info(f"[BB+RSI] 포지션 추가: {ticker} @ {entry_price:,.0f}원")

    def remove_position(self, ticker: str):
        """보유 포지션 제거 (매도 체결 후 호출)"""
        if ticker in self.positions:
            del self.positions[ticker]
            logger.info(f"[BB+RSI] 포지션 제거: {ticker}")

    def clear_all_positions(self):
        """전체 포지션 초기화 (국면 전환 시 호출)"""
        count = len(self.positions)
        self.positions.clear()
        logger.info(f"[BB+RSI] 전체 포지션 초기화 ({count}개)")

    def get_positions(self) -> dict:
        """현재 보유 포지션 반환"""
        return self.positions.copy()


if __name__ == "__main__":
    """단독 실행 테스트"""
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    logger.remove()
    logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="DEBUG")

    strategy = BBRSIMeanReversion()
    logger.info("=== BB+RSI 평균회귀 전략 단독 테스트 ===")

    for coin in TARGET_COINS[:3]:  # 테스트용 3개 코인만
        indicators = strategy._calc_indicators(coin)
        if indicators:
            logger.info(
                f"{coin} | 가격: {indicators['current_price']:,.0f} | "
                f"BB상단: {indicators['bb_upper']:,.0f} | BB중간: {indicators['bb_mid']:,.0f} | "
                f"BB하단: {indicators['bb_lower']:,.0f} | RSI: {indicators['rsi']:.1f} | "
                f"BB폭: {indicators['bb_width']:.2f}%"
            )
            is_buy = strategy.check_buy_signal(coin, indicators)
            logger.info(f"  → 매수 신호: {is_buy}")
        time.sleep(0.2)

    signal, info = strategy.check_signal()
    logger.info(f"\n전체 스캔 결과: signal={signal}, info={info}")
