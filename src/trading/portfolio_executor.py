"""
src/trading/portfolio_executor.py - 포트폴리오 매매 실행기

포트폴리오 전략의 리밸런싱 주문을 실제로 실행합니다.

실행 순서:
  1. 리스크 체크 (MDD, 손절)
  2. 목표 비중 계산 (전략)
  3. 주문 계산 (리스크 매니저)
  4. 매도 먼저 → 매수 나중 (원화 확보)
  5. DB 기록 + 텔레그램 알림
"""

import time
from loguru import logger

from src.api.upbit_client import (
    buy_market_order,
    sell_market_order,
    get_current_price,
    get_balance_coin,
)
from src.notifications.telegram_bot import send_message, send_error_alert
from src.database.supabase_client import save_trade
from src.strategies.risk_manager import RiskManager


class PortfolioExecutor:
    """
    포트폴리오 매매 실행기

    사용법:
        executor = PortfolioExecutor(strategy, risk_manager, live_trading=False)
        executor.run_rebalance()
    """

    def __init__(self, strategy, risk_manager: RiskManager, live_trading: bool = False):
        self.strategy = strategy
        self.rm = risk_manager
        self.live = live_trading
        self.coins = strategy.coins

    def run_rebalance(self) -> dict:
        """
        리밸런싱을 실행합니다.

        반환값:
            {
                "action"  : "rebalance" | "mdd_exit" | "stop_loss" | "skip",
                "orders"  : 실행된 주문 리스트,
                "details" : 상세 정보,
            }
        """
        # 1. MDD 체크
        mdd_info = self.rm.check_mdd(self.coins)
        if mdd_info["mdd_breached"]:
            return self._execute_emergency_exit(mdd_info)

        # 2. 손절 체크
        stop_list = self.rm.check_stop_loss(self.coins)
        if stop_list:
            self._execute_stop_loss(stop_list)

        # 3. 전략 신호 확인
        signal, info = self.strategy.check_signal()

        if signal == "emergency_sell":
            # 하락장 감지 → 전량 매도
            return self._execute_regime_exit(info)

        if signal != "rebalance":
            reason = info.get("reason", "신호 없음")
            logger.debug(f"[포트폴리오] 리밸런싱 생략: {reason}")
            return {"action": "skip", "orders": [], "details": info}

        # 4. 주문 계산
        target_weights = info["target_weights"]
        orders = self.rm.calc_orders(target_weights, self.coins)

        # 5. 매도 먼저 실행
        executed_sells = []
        for coin, volume in orders["sell_orders"]:
            result = self._execute_sell(coin, volume)
            if result:
                executed_sells.append(result)

        # 매도 체결 대기
        if executed_sells:
            time.sleep(2)

        # 6. 매수 실행
        executed_buys = []
        for coin, amount in orders["buy_orders"]:
            result = self._execute_buy(coin, amount)
            if result:
                executed_buys.append(result)

        # 7. 텔레그램 리밸런싱 리포트
        self._send_rebalance_report(target_weights, executed_sells, executed_buys, orders)

        return {
            "action": "rebalance",
            "orders": {"sells": executed_sells, "buys": executed_buys},
            "details": {
                "target_weights": target_weights,
                "total_value": orders["total_value"],
            },
        }

    def _execute_buy(self, coin: str, amount: float) -> dict:
        """매수 주문 실행"""
        price = get_current_price(coin)
        if not price:
            return None

        mode = "실거래" if self.live else "시뮬"
        logger.info(f"[{mode}] 매수: {coin} {amount:,.0f}원 @ {price:,.0f}원")

        if self.live:
            result = buy_market_order(coin, amount)
            if result:
                save_trade(
                    strategy_name=self.strategy.get_strategy_name(),
                    ticker=coin,
                    side="buy",
                    price=price,
                    amount=amount,
                    signal="rebalance_buy",
                )
                self.rm.update_entry_price(coin, price)
                return {"coin": coin, "amount": amount, "price": price, "side": "buy"}
            else:
                send_error_alert(f"매수 실패: {coin} {amount:,.0f}원")
                return None
        else:
            # 시뮬레이션
            self.rm.update_entry_price(coin, price)
            return {"coin": coin, "amount": amount, "price": price, "side": "buy"}

    def _execute_sell(self, coin: str, volume: float) -> dict:
        """매도 주문 실행"""
        price = get_current_price(coin)
        if not price:
            return None

        mode = "실거래" if self.live else "시뮬"
        amount = volume * price
        logger.info(f"[{mode}] 매도: {coin} {volume:.6f} ({amount:,.0f}원) @ {price:,.0f}원")

        if self.live:
            result = sell_market_order(coin, volume)
            if result:
                save_trade(
                    strategy_name=self.strategy.get_strategy_name(),
                    ticker=coin,
                    side="sell",
                    price=price,
                    amount=amount,
                    signal="rebalance_sell",
                )
                self.rm.remove_entry_price(coin)
                return {"coin": coin, "volume": volume, "price": price, "side": "sell", "amount": amount}
            else:
                send_error_alert(f"매도 실패: {coin}")
                return None
        else:
            self.rm.remove_entry_price(coin)
            return {"coin": coin, "volume": volume, "price": price, "side": "sell", "amount": amount}

    def _execute_regime_exit(self, info: dict) -> dict:
        """하락장 감지 → 보유 코인 전량 매도, 현금 전환"""
        logger.warning(f"[하락장] 전량 현금 전환 실행!")

        executed = []
        for coin in self.coins:
            volume = get_balance_coin(coin)
            if volume and volume > 0.00001:
                result = self._execute_sell(coin, volume)
                if result:
                    executed.append(result)

        total_sold = sum(e.get("amount", 0) for e in executed if e)
        msg = (
            f"<b>하락장 감지 - 전량 현금 전환</b>\n"
            f"국면: {info.get('regime', 'bear')}\n"
            f"사유: {info.get('reason', '하락장 감지')}\n"
            f"매도 코인: {len(executed)}개\n"
            f"매도 금액: {total_sold:,.0f}원"
        )
        send_message(msg)

        return {"action": "regime_exit", "orders": executed, "details": info}

    def _execute_emergency_exit(self, mdd_info: dict) -> dict:
        """MDD 한도 초과 시 전량 매도"""
        logger.warning(f"[긴급] MDD 한도 초과 → 전량 매도 실행!")

        executed = []
        for coin in self.coins:
            volume = get_balance_coin(coin)
            if volume and volume > 0.00001:
                result = self._execute_sell(coin, volume)
                if result:
                    executed.append(result)

        msg = (
            f"<b>긴급 전량 매도</b>\n"
            f"MDD: {mdd_info['current_mdd']:.1%} (한도: {mdd_info['mdd_limit']:.1%})\n"
            f"총 자산: {mdd_info['total_value']:,.0f}원\n"
            f"최고점: {mdd_info['peak_value']:,.0f}원\n"
            f"매도 코인: {len(executed)}개"
        )
        send_message(msg)

        return {"action": "mdd_exit", "orders": executed, "details": mdd_info}

    def _execute_stop_loss(self, stop_list: list):
        """손절 실행"""
        for coin, current, entry, loss in stop_list:
            volume = get_balance_coin(coin)
            if volume and volume > 0.00001:
                self._execute_sell(coin, volume)
                send_message(
                    f"<b>손절 매도</b>\n"
                    f"코인: {coin}\n"
                    f"매수가: {entry:,.0f}원 → 현재: {current:,.0f}원\n"
                    f"손실: {loss:.1%}"
                )

    def _send_rebalance_report(self, target_weights, sells, buys, orders):
        """리밸런싱 결과를 텔레그램으로 전송"""
        mode = "실거래" if self.live else "시뮬"

        # 목표 비중 텍스트
        weight_text = "\n".join(
            f"  {c.replace('KRW-', '')}: {w:.0%}"
            for c, w in sorted(target_weights.items(), key=lambda x: x[1], reverse=True)
        )

        sell_text = ""
        if sells:
            sell_text = "\n매도:\n" + "\n".join(
                f"  {s['coin'].replace('KRW-', '')}: {s['amount']:,.0f}원"
                for s in sells if s
            )

        buy_text = ""
        if buys:
            buy_text = "\n매수:\n" + "\n".join(
                f"  {b['coin'].replace('KRW-', '')}: {b['amount']:,.0f}원"
                for b in buys if b
            )

        msg = (
            f"<b>[{mode}] 포트폴리오 리밸런싱</b>\n"
            f"전략: {self.strategy.strategy_type}\n"
            f"총 자산: {orders['total_value']:,.0f}원\n"
            f"\n목표 비중:\n{weight_text}"
            f"{sell_text}{buy_text}"
        )
        send_message(msg)

    def print_status(self):
        """현재 포트폴리오 상태를 출력합니다."""
        risk_status = self.rm.get_status(self.coins)
        mode = "실거래" if self.live else "시뮬"

        logger.info(
            f"[포트폴리오 상태] 모드: {mode} | "
            f"총 자산: {risk_status['total_value']:,.0f}원 | "
            f"MDD: {risk_status['current_mdd']:.1%} | "
            f"전략: {self.strategy.strategy_type}"
        )

        # 보유 코인 목록
        holdings = []
        for coin in self.coins:
            volume = get_balance_coin(coin)
            if volume and volume > 0.00001:
                price = get_current_price(coin)
                if price:
                    holdings.append(f"{coin.replace('KRW-', '')}({volume * price:,.0f}원)")

        if holdings:
            logger.info(f"  보유: {', '.join(holdings)}")
