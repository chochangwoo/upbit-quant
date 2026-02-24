"""
전략 추상 기본 클래스
모든 실거래 전략은 이 클래스를 상속받아 구현합니다.
"""
from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """실거래 전략 추상 클래스."""

    @abstractmethod
    def check_signal(self, ticker: str) -> tuple[str | None, dict]:
        """
        매매 신호를 확인합니다.

        반환값:
            (signal, info) 튜플
            signal: 'buy' | 'sell' | None
            info  : 전략별 부가 정보 딕셔너리 (가격, MA 값 등)
        """

    @abstractmethod
    def get_strategy_name(self) -> str:
        """전략 이름을 반환합니다."""
