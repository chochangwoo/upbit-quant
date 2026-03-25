"""
src/strategies/risk_manager.py - 실거래 리스크 관리 모듈

실투자 시 자금을 보호하기 위한 리스크 관리 규칙:
  1. 최대 투자 비율: 전체 자산 대비 투자 한도
  2. 코인당 최대 비중: 단일 코인 집중 방지
  3. MDD 한도: 누적 손실이 한도 초과 시 전량 매도
  4. 손절 라인: 코인별 손실이 한도 초과 시 해당 코인 매도
  5. 최소 거래 금액: 업비트 최소 주문 금액 (5,000원)
"""

import os
import json
from datetime import datetime
from loguru import logger

from src.api.upbit_client import get_balance_krw, get_balance_coin, get_current_price


# 리스크 관리 기본 설정
DEFAULT_RISK_CONFIG = {
    "max_invest_ratio": 0.95,       # 최대 투자 비율 (전체 자산의 95%)
    "max_coin_weight": 0.30,        # 코인당 최대 비중 (30%)
    "mdd_limit": -0.15,             # MDD 한도 (-15% 초과 시 전량 매도)
    "stop_loss_per_coin": -0.10,    # 코인별 손절선 (-10%)
    "min_order_krw": 5000,          # 최소 주문 금액 (원)
    "cool_down_hours": 1,           # 손절 후 재진입 대기 시간
}

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "risk_state.json")


class RiskManager:
    """
    실거래 리스크 관리자

    사용법:
        rm = RiskManager()
        orders = rm.calc_orders(target_weights, live_trading=False)
        if rm.check_mdd():
            # 전량 매도 실행
    """

    def __init__(self, config: dict = None):
        self.config = {**DEFAULT_RISK_CONFIG, **(config or {})}
        self.peak_value = 0
        self.entry_prices = {}  # {코인: 매수평균가}
        self.stop_triggered = {}  # {코인: 손절 발동 시간}
        self._load_state()

    def _load_state(self):
        """이전 상태 복원"""
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                self.peak_value = state.get("peak_value", 0)
                self.entry_prices = state.get("entry_prices", {})
                self.stop_triggered = {
                    k: datetime.fromisoformat(v)
                    for k, v in state.get("stop_triggered", {}).items()
                }
        except Exception:
            pass

    def _save_state(self):
        """상태 저장"""
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            state = {
                "peak_value": self.peak_value,
                "entry_prices": self.entry_prices,
                "stop_triggered": {
                    k: v.isoformat() for k, v in self.stop_triggered.items()
                },
            }
            with open(STATE_FILE, "w") as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"[리스크] 상태 저장 실패: {e}")

    def get_total_value(self, coins: list) -> float:
        """현재 총 자산 가치를 계산합니다 (원화 + 코인 평가액)."""
        total = get_balance_krw()
        for coin in coins:
            volume = get_balance_coin(coin)
            if volume and volume > 0:
                price = get_current_price(coin)
                if price:
                    total += volume * price
        return total

    def check_mdd(self, coins: list) -> dict:
        """
        MDD 한도 초과 여부를 확인합니다.

        반환값:
            {
                "total_value": 현재 총 자산,
                "peak_value": 최고점,
                "current_mdd": 현재 MDD,
                "mdd_breached": 한도 초과 여부,
            }
        """
        total = self.get_total_value(coins)

        if total > self.peak_value:
            self.peak_value = total

        current_mdd = 0
        if self.peak_value > 0:
            current_mdd = (total - self.peak_value) / self.peak_value

        breached = current_mdd < self.config["mdd_limit"]

        if breached:
            logger.warning(
                f"[리스크] MDD 한도 초과! "
                f"현재 MDD: {current_mdd:.1%} (한도: {self.config['mdd_limit']:.1%})"
            )

        self._save_state()

        return {
            "total_value": total,
            "peak_value": self.peak_value,
            "current_mdd": current_mdd,
            "mdd_breached": breached,
        }

    def check_stop_loss(self, coins: list) -> list:
        """
        코인별 손절선 초과 여부를 확인합니다.

        반환값:
            손절 필요한 코인 리스트 [(코인, 현재가, 매수가, 손실률)]
        """
        stop_list = []
        now = datetime.now()

        for coin in coins:
            entry = self.entry_prices.get(coin)
            if not entry:
                continue

            current = get_current_price(coin)
            if not current:
                continue

            loss = (current - entry) / entry
            limit = self.config["stop_loss_per_coin"]

            if loss < limit:
                # 쿨다운 체크
                last_stop = self.stop_triggered.get(coin)
                cool_hours = self.config["cool_down_hours"]
                if last_stop and (now - last_stop).total_seconds() < cool_hours * 3600:
                    continue

                stop_list.append((coin, current, entry, loss))
                self.stop_triggered[coin] = now
                logger.warning(
                    f"[손절] {coin} 손절선 돌파! "
                    f"매수가: {entry:,.0f} → 현재: {current:,.0f} ({loss:.1%})"
                )

        self._save_state()
        return stop_list

    def calc_orders(self, target_weights: dict, coins: list) -> dict:
        """
        목표 비중과 현재 보유량의 차이를 계산하여 주문 리스트를 생성합니다.

        매개변수:
            target_weights: {코인: 목표비중} (합계 ≤ 1.0)
            coins         : 전체 대상 코인 리스트
        반환값:
            {
                "buy_orders" : [(코인, 금액)],     # 매수할 코인과 금액
                "sell_orders": [(코인, 수량)],     # 매도할 코인과 수량
                "total_value": 총 자산,
                "invest_amount": 투자 가능 금액,
            }
        """
        total_value = self.get_total_value(coins)
        max_invest = total_value * self.config["max_invest_ratio"]
        max_per_coin = total_value * self.config["max_coin_weight"]
        min_order = self.config["min_order_krw"]

        buy_orders = []
        sell_orders = []

        # 현재 보유 현황
        current_holdings = {}
        for coin in coins:
            volume = get_balance_coin(coin)
            price = get_current_price(coin)
            if volume and volume > 0 and price:
                current_holdings[coin] = {
                    "volume": volume,
                    "value": volume * price,
                    "price": price,
                }

        current_invested = sum(h["value"] for h in current_holdings.values())

        # 1. 매도 주문: 목표에 없는 코인 또는 비중 초과 코인
        for coin, holding in current_holdings.items():
            target_w = target_weights.get(coin, 0)
            target_value = max_invest * target_w

            if target_w == 0:
                # 전량 매도
                sell_orders.append((coin, holding["volume"]))
            elif holding["value"] > target_value * 1.1:
                # 비중 축소 (10% 이상 초과 시)
                excess_value = holding["value"] - target_value
                sell_volume = excess_value / holding["price"]
                if excess_value > min_order:
                    sell_orders.append((coin, sell_volume))

        # 2. 매수 주문: 목표 비중보다 부족한 코인
        krw_balance = get_balance_krw()
        # 매도 실행 후 확보될 원화 추정
        sell_proceeds = sum(
            current_holdings.get(c, {}).get("value", 0)
            for c, _ in sell_orders
            if target_weights.get(c, 0) == 0
        )
        available_krw = krw_balance + sell_proceeds

        for coin, target_w in target_weights.items():
            if target_w <= 0:
                continue

            target_value = min(max_invest * target_w, max_per_coin)
            current_value = current_holdings.get(coin, {}).get("value", 0)
            needed = target_value - current_value

            if needed > min_order and needed <= available_krw:
                buy_orders.append((coin, needed))
                available_krw -= needed

        return {
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "total_value": total_value,
            "invest_amount": max_invest,
            "krw_available": krw_balance,
        }

    def update_entry_price(self, coin: str, price: float):
        """매수 평균가를 업데이트합니다."""
        self.entry_prices[coin] = price
        self._save_state()

    def remove_entry_price(self, coin: str):
        """매도 후 매수가 기록을 제거합니다."""
        self.entry_prices.pop(coin, None)
        self._save_state()

    def get_status(self, coins: list) -> dict:
        """현재 리스크 상태를 반환합니다."""
        mdd_info = self.check_mdd(coins)
        return {
            "total_value": mdd_info["total_value"],
            "peak_value": mdd_info["peak_value"],
            "current_mdd": mdd_info["current_mdd"],
            "mdd_limit": self.config["mdd_limit"],
            "mdd_breached": mdd_info["mdd_breached"],
            "max_invest_ratio": self.config["max_invest_ratio"],
            "max_coin_weight": self.config["max_coin_weight"],
            "stop_loss": self.config["stop_loss_per_coin"],
            "tracked_coins": len(self.entry_prices),
        }
