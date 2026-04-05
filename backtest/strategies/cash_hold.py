"""
backtest/strategies/cash_hold.py - 현금 보유 전략 (백테스트용)

하락장에서 현금을 100% 보유하는 방어 전략.
비교 벤치마크용으로 사용합니다.
"""

import pandas as pd


class CashHoldBT:
    """하락장 현금 보유 전략 (백테스트용)"""

    def __init__(self):
        self.name = "현금보유(Bear)"

    def get_weights(self, prices: pd.DataFrame, volumes: pd.DataFrame,
                    date: pd.Timestamp, lookback_prices: pd.DataFrame) -> pd.Series:
        """항상 빈 비중 반환 (현금 100%)"""
        return pd.Series(dtype=float)
