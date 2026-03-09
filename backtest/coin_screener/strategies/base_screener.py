"""
backtest/coin_screener/strategies/base_screener.py - 스크리너 추상 클래스

모든 코인 선별 전략이 상속해야 하는 기본 클래스입니다.
"""
from abc import ABC, abstractmethod
import pandas as pd


class BaseScreener(ABC):
    """
    코인 선별 전략의 추상 기본 클래스.
    모든 스크리너는 이 클래스를 상속하고 screen() 메서드를 구현해야 합니다.
    """

    def __init__(self, top_n: int = 5):
        """
        매개변수:
            top_n: 선별할 코인 수 (기본 5개)
        """
        self.top_n = top_n

    @property
    @abstractmethod
    def name(self) -> str:
        """전략 이름을 반환합니다."""
        pass

    @abstractmethod
    def screen(self, all_data: dict, current_date) -> list:
        """
        특정 날짜 시점에서 상위 코인을 선별합니다.

        매개변수:
            all_data     : {ticker: DataFrame} 전체 코인 데이터
            current_date : 현재 날짜 (look-ahead bias 방지를 위해 이 날짜까지만 사용)
        반환값:
            [(ticker, score), ...] 선별된 코인과 점수 리스트 (상위 top_n개)
        """
        pass

    def _get_available_data(self, all_data: dict, current_date) -> dict:
        """
        look-ahead bias 방지를 위해 current_date까지의 데이터만 잘라서 반환합니다.

        매개변수:
            all_data     : 전체 데이터
            current_date : 현재 날짜
        반환값:
            {ticker: DataFrame} current_date까지만 포함된 데이터
        """
        available = {}
        for ticker, df in all_data.items():
            sliced = df.loc[:current_date]
            if len(sliced) > 0:
                available[ticker] = sliced
        return available
