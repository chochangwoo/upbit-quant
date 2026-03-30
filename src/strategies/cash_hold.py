"""
src/strategies/cash_hold.py - 하락장 방어 전략

하락장에서 현금 비중을 최대화하여 자산을 보전하는 방어 전략.
- 기존 보유 포지션이 있다면 전량 매도
- 신규 매수 금지
- 텔레그램으로 하락장 방어 모드 알림
"""

from loguru import logger
from src.strategies.base import BaseStrategy


class CashHoldStrategy(BaseStrategy):
    """
    하락장 방어 전략 - 현금 비중 최대화

    하락장 감지 시 StrategyRouter에 의해 자동 활성화됩니다.
    모든 보유 코인을 매도하고 신규 매수를 금지합니다.
    """

    def __init__(self):
        self._notified = False  # 방어 모드 진입 알림 중복 방지
        logger.info("[CashHold] 하락장 방어 전략 초기화")

    def get_strategy_name(self) -> str:
        return "cash_hold"

    def check_signal(self, ticker: str = None) -> tuple[str | None, dict]:
        """
        하락장에서는 항상 매도 또는 대기 신호만 반환합니다.

        반환값:
            ('emergency_sell', info) → 보유 포지션 전량 매도 (최초 1회)
            (None, info)            → 현금 보유 유지
        """
        if not self._notified:
            self._notified = True
            logger.warning("[CashHold] 하락장 방어 모드 활성화 - 전량 현금 전환")
            return "emergency_sell", {
                "regime": "bear",
                "target_weights": {},
                "reason": "하락장 감지 - 전량 현금 전환",
            }

        return None, {
            "regime": "bear",
            "reason": "하락장 현금 보유 중",
        }

    def reset(self):
        """국면 전환 시 상태 초기화"""
        self._notified = False
        logger.info("[CashHold] 방어 전략 상태 초기화")


if __name__ == "__main__":
    """단독 실행 테스트"""
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    logger.remove()
    logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="DEBUG")

    strategy = CashHoldStrategy()
    logger.info("=== 하락장 방어 전략 단독 테스트 ===")

    # 첫 번째 호출: emergency_sell
    signal, info = strategy.check_signal()
    logger.info(f"1차 호출: signal={signal}, reason={info.get('reason')}")

    # 두 번째 호출: 현금 보유 유지
    signal, info = strategy.check_signal()
    logger.info(f"2차 호출: signal={signal}, reason={info.get('reason')}")

    # 리셋 후 다시 호출
    strategy.reset()
    signal, info = strategy.check_signal()
    logger.info(f"리셋 후: signal={signal}, reason={info.get('reason')}")
