"""
src/strategies/strategy_router.py - 시장 국면별 전략 자동 스위칭 (v2)

v2 변경사항 (crypto_strategy_guide_v2.md 기반):
  - 국면 판단: SMA50+모멘텀 → ADX 기반 (횡보 72%→44%, 전환비용 1%p 절감)
  - 전략 매핑: 상승장+횡보장 → 거래량돌파 유지, 하락장만 → 현금보유
  - BB+RSI 제거 (횡보장 실측 -119%, 전략 스위칭이 성과 악화)

국면 판단 기준 (BTC 기준, ADX):
  - 상승장(Bull) : ADX > 25 AND +DI > -DI (강한 상승 추세)
  - 하락장(Bear) : ADX > 25 AND -DI > +DI (강한 하락 추세)
  - 횡보장(Sideways): ADX <= 25 (추세 약함)

전략 매핑:
  - 상승장 → 적응형 거래량돌파 (AdaptiveVolumeStrategy)
  - 횡보장 → 적응형 거래량돌파 (횡보장에서도 +25.72% 실측)
  - 하락장 → 현금 보유 (CashHoldStrategy)

국면 전환 안정성:
  - 전환 감지 후 confirmation_days(2일) 동안 동일 국면 유지 시에만 실제 전환
"""

import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

from src.api.upbit_client import get_ohlcv, get_current_price, get_balance_coin
from src.strategies.base import BaseStrategy
from src.strategies.adaptive_volume_strategy import AdaptiveVolumeStrategy
from src.strategies.cash_hold import CashHoldStrategy
from src.notifications.telegram_bot import send_message, send_error_alert
from src.database.supabase_client import (
    insert_table,
    save_strategy_state,
    load_strategy_state,
)


# 대상 코인 13종
TARGET_COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]

# 국면별 한국어 이름
REGIME_NAMES = {
    "bull": "상승장",
    "sideways": "횡보장",
    "bear": "하락장",
}

# 국면별 전략 이름
STRATEGY_NAMES = {
    "bull": "거래량돌파",
    "sideways": "거래량돌파",
    "bear": "현금보유",
}


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict:
    """
    ADX(Average Directional Index)를 계산합니다.

    매개변수:
        high: 고가 시리즈
        low: 저가 시리즈
        close: 종가 시리즈
        period: ADX 기간 (기본 14)

    반환값:
        {"adx": float, "plus_di": float, "minus_di": float}
    """
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # +DM, -DM
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

    # Wilder 평활 (EMA와 유사)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1/period, min_periods=period).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1/period, min_periods=period).mean()

    # +DI, -DI
    plus_di = 100 * plus_dm_smooth / atr
    minus_di = 100 * minus_dm_smooth / atr

    # DX → ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()

    return {
        "adx": adx.iloc[-1],
        "plus_di": plus_di.iloc[-1],
        "minus_di": minus_di.iloc[-1],
    }


class StrategyRouter(BaseStrategy):
    """
    시장 국면에 따라 적절한 전략을 자동 선택하는 라우터 (v2)

    v2: ADX 기반 국면 판단, 거래량돌파 중심, BB+RSI 제거

    사용법:
        router = StrategyRouter(config)
        signal, info = router.check_signal()
    """

    def __init__(self, config: dict):
        """
        매개변수:
            config: settings.yaml 전체 설정 딕셔너리
        """
        regime_cfg = config.get("regime_detection", {})
        strategies_cfg = config.get("strategies", {})
        portfolio_cfg = config.get("portfolio", {})
        bear_filter_cfg = config.get("bear_filter", {})

        # ADX 기반 국면 감지 파라미터
        self.adx_period = regime_cfg.get("adx_period", 14)
        self.adx_trend_threshold = regime_cfg.get("adx_trend_threshold", 25)
        self.confirmation_days = regime_cfg.get("confirmation_days", 2)

        # v3: 보조 하락 필터 (BTC SMA + 모멘텀)
        self.bear_filter_enabled = bear_filter_cfg.get("enabled", False)
        self.sma_period = bear_filter_cfg.get("sma_period", 200)
        self.mom_window = bear_filter_cfg.get("mom_window", 30)
        self.mom_threshold = bear_filter_cfg.get("mom_threshold", -0.03)

        # OHLCV 데이터: ADX/SMA/모멘텀 모두 충족하도록 충분히 확보
        self.ohlcv_count = max(
            self.adx_period * 3 + 10,
            self.sma_period + 30 if self.bear_filter_enabled else 0,
        )

        # 거래량돌파 전략 (상승장 + 횡보장 공통)
        vol_cfg = strategies_cfg.get("volume_breakout", {})
        volume_strategy = AdaptiveVolumeStrategy(
            price_lookback=vol_cfg.get("price_lookback", 4),
            vol_ratio=vol_cfg.get("vol_ratio", 1.26),
            top_k=vol_cfg.get("top_k", portfolio_cfg.get("top_k", 5)),
            rebalance_days=vol_cfg.get("rebalance_days", portfolio_cfg.get("rebalance_days", 3)),
            # 횡보장 완화 파라미터 (v2.1)
            sideways_vol_ratio=vol_cfg.get("sideways_vol_ratio", 1.1),
            sideways_momentum_min=vol_cfg.get("sideways_momentum_min", -0.03),
        )

        self.strategies = {
            "bull": volume_strategy,
            "sideways": volume_strategy,  # 횡보장에서도 거래량돌파 유지 (+25.72% 실측)
            "bear": CashHoldStrategy(),
        }

        self.coins = TARGET_COINS

        # 국면 상태
        self.current_regime = None
        self.current_strategy = None
        self.regime_history = []

        # 국면 전환 확인용 (잦은 전환 방지)
        self._pending_regime = None
        self._pending_since = None

        # DB에서 이전 국면 복원
        self._restore_regime()

        version = "v3" if self.bear_filter_enabled else "v2"
        bear_filter_msg = (
            f" | bear필터: SMA{self.sma_period} OR mom{self.mom_window}<{self.mom_threshold*100:+.0f}%"
            if self.bear_filter_enabled
            else ""
        )
        logger.info(
            f"[라우터 {version}] 초기화 완료 | ADX({self.adx_period}) | "
            f"추세 임계값: {self.adx_trend_threshold} | "
            f"확인대기: {self.confirmation_days}일{bear_filter_msg} | "
            f"전략: 상승+횡보→거래량돌파, 하락→현금보유"
        )

    def get_strategy_name(self) -> str:
        if self.current_strategy:
            return f"router_{self.current_strategy.get_strategy_name()}"
        return "strategy_router"

    def _restore_regime(self):
        """DB에서 마지막 국면 상태를 복원합니다."""
        try:
            saved_regime = load_strategy_state("strategy_router", "current_regime")
            if saved_regime and saved_regime in self.strategies:
                self.current_regime = saved_regime
                self.current_strategy = self.strategies[saved_regime]
                logger.info(f"[라우터 v2] 국면 복원: {REGIME_NAMES.get(saved_regime, saved_regime)}")
        except Exception as e:
            logger.warning(f"[라우터 v2] 국면 복원 실패: {e}")

    def _save_regime(self, regime: str):
        """현재 국면을 DB에 저장합니다."""
        save_strategy_state("strategy_router", "current_regime", regime)

    def detect_regime(self) -> tuple[str, dict]:
        """
        BTC OHLCV 데이터 기반 ADX 국면 판단

        ADX > adx_trend_threshold:
          - +DI > -DI → 상승장 (bull)
          - -DI > +DI → 하락장 (bear)
        ADX <= adx_trend_threshold → 횡보장 (sideways)

        반환값:
            (국면 문자열, 판단 근거 딕셔너리)
        """
        df = get_ohlcv("KRW-BTC", interval="day", count=self.ohlcv_count)
        if df is None or len(df) < self.adx_period * 2:
            logger.warning("[라우터 v2] BTC 데이터 부족, sideways로 판단")
            return "sideways", {}

        adx_result = calc_adx(df["high"], df["low"], df["close"], self.adx_period)
        adx_val = adx_result["adx"]
        plus_di = adx_result["plus_di"]
        minus_di = adx_result["minus_di"]
        current_price = df["close"].iloc[-1]

        regime_info = {
            "btc_price": current_price,
            "adx": round(adx_val, 2),
            "plus_di": round(plus_di, 2),
            "minus_di": round(minus_di, 2),
        }

        # 1차: ADX 기반 1차 국면
        if adx_val > self.adx_trend_threshold:
            adx_regime = "bull" if plus_di > minus_di else "bear"
        else:
            adx_regime = "sideways"

        # v3: 보조 하락 필터 — SMA / 모멘텀 중 하나라도 hit 시 강제 bear
        if self.bear_filter_enabled:
            close = df["close"]
            sma = close.tail(self.sma_period).mean() if len(close) >= self.sma_period else None
            mom = (
                current_price / close.iloc[-self.mom_window - 1] - 1
                if len(close) > self.mom_window
                else None
            )
            regime_info["sma"] = round(sma, 2) if sma is not None else None
            regime_info["mom"] = round(mom, 4) if mom is not None else None

            sma_hit = sma is not None and current_price < sma
            mom_hit = mom is not None and mom < self.mom_threshold

            if sma_hit or mom_hit:
                triggers = []
                if sma_hit:
                    triggers.append(f"BTC<SMA{self.sma_period}")
                if mom_hit:
                    triggers.append(f"mom{self.mom_window}<{self.mom_threshold*100:+.0f}%")
                regime_info["bear_filter_triggers"] = triggers
                logger.info(
                    f"[라우터 v3] bear 필터 발동 ({', '.join(triggers)}) → 강제 현금"
                )
                return "bear", regime_info

        return adx_regime, regime_info

    def _confirm_regime_change(self, detected_regime: str) -> bool:
        """
        국면 전환 확인 (잦은 전환 방지)

        confirmation_days 동안 동일 국면이 유지되어야 실제 전환합니다.
        """
        today = datetime.now().date()

        if detected_regime == self.current_regime:
            self._pending_regime = None
            self._pending_since = None
            return False

        if self._pending_regime != detected_regime:
            self._pending_regime = detected_regime
            self._pending_since = today
            logger.info(
                f"[라우터 v2] 국면 전환 감지 대기 시작: "
                f"{REGIME_NAMES.get(self.current_regime, '초기')} → "
                f"{REGIME_NAMES.get(detected_regime)} | "
                f"확인 대기: {self.confirmation_days}일"
            )
            return False

        days_pending = (today - self._pending_since).days
        if days_pending >= self.confirmation_days:
            logger.info(
                f"[라우터 v2] 국면 전환 확정! ({days_pending}일 확인) | "
                f"{REGIME_NAMES.get(self.current_regime, '초기')} → "
                f"{REGIME_NAMES.get(detected_regime)}"
            )
            self._pending_regime = None
            self._pending_since = None
            return True

        logger.debug(
            f"[라우터 v2] 국면 전환 대기 중: {days_pending}/{self.confirmation_days}일"
        )
        return False

    def switch_strategy(self, new_regime: str, regime_info: dict) -> list:
        """
        국면 전환 시 전략을 교체합니다.

        반환값: 청산된 포지션 리스트 (하락장 전환 시에만 청산 필요)
        """
        prev_regime = self.current_regime or "초기"
        prev_strategy_name = STRATEGY_NAMES.get(prev_regime, "없음")
        new_strategy_name = STRATEGY_NAMES.get(new_regime, "알 수 없음")

        logger.warning(
            f"[라우터 v2] 전략 전환: {REGIME_NAMES.get(prev_regime, prev_regime)}({prev_strategy_name}) → "
            f"{REGIME_NAMES.get(new_regime)}({new_strategy_name})"
        )

        # 하락장 방어 전략 리셋
        if isinstance(self.strategies.get("bear"), CashHoldStrategy):
            self.strategies["bear"].reset()

        # 전략 교체
        self.current_regime = new_regime
        self.current_strategy = self.strategies[new_regime]
        self._save_regime(new_regime)

        # 전환 이력 기록
        self.regime_history.append({
            "from": prev_regime,
            "to": new_regime,
            "timestamp": datetime.now().isoformat(),
        })

        # 텔레그램 알림
        btc_price = regime_info.get("btc_price", 0)
        adx = regime_info.get("adx", 0)
        plus_di = regime_info.get("plus_di", 0)
        minus_di = regime_info.get("minus_di", 0)
        sma_val = regime_info.get("sma")
        mom_val = regime_info.get("mom")
        bear_triggers = regime_info.get("bear_filter_triggers", [])

        version = "v3" if self.bear_filter_enabled else "v2"
        msg = (
            f"<b>시장 국면 전환 감지 (ADX {version})</b>\n"
            f"{'─' * 15}\n"
            f"이전: {REGIME_NAMES.get(prev_regime, prev_regime)} ({prev_strategy_name})\n"
            f"현재: {REGIME_NAMES.get(new_regime)} ({new_strategy_name})\n"
            f"{'─' * 15}\n"
            f"BTC: {btc_price:,.0f}원\n"
            f"ADX: {adx:.1f} | +DI: {plus_di:.1f} | -DI: {minus_di:.1f}\n"
        )
        if self.bear_filter_enabled and (sma_val is not None or mom_val is not None):
            sma_str = f"{sma_val:,.0f}" if sma_val is not None else "N/A"
            mom_str = f"{mom_val*100:+.2f}%" if mom_val is not None else "N/A"
            msg += f"SMA{self.sma_period}: {sma_str} | mom{self.mom_window}: {mom_str}\n"
        if bear_triggers:
            msg += f"bear 필터 발동: {', '.join(bear_triggers)}\n"

        # 하락장 전환 시에만 포지션 청산
        if new_regime == "bear":
            msg += f"{'─' * 15}\n보유 포지션 전량 청산 진행"
        else:
            msg += f"{'─' * 15}\n거래량돌파 전략 유지"

        send_message(msg)

        # Supabase에 전환 이력 기록
        try:
            insert_table("strategy_switches", {
                "prev_regime": prev_regime,
                "new_regime": new_regime,
                "prev_strategy": prev_strategy_name,
                "new_strategy": new_strategy_name,
                "btc_price": btc_price,
                "sma50": None,
                "momentum_20d": None,
                "adx": adx,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "positions_closed": None,
            })
        except Exception as e:
            logger.error(f"[라우터 v2] 전환 이력 DB 기록 실패: {e}")

        # 하락장 전환 시에만 보유 포지션 청산
        if new_regime == "bear":
            return self._get_held_positions()
        return []

    def _get_held_positions(self) -> list:
        """현재 보유 중인 코인 목록을 반환합니다."""
        held = []
        for coin in self.coins:
            try:
                volume = get_balance_coin(coin)
                if volume and volume > 0.00001:
                    price = get_current_price(coin)
                    held.append({
                        "ticker": coin,
                        "volume": volume,
                        "price": price,
                        "amount": volume * price if price else 0,
                    })
            except Exception:
                continue
        return held

    def check_signal(self, ticker: str = None) -> tuple[str | None, dict]:
        """
        현재 국면을 판단하고 적절한 전략의 신호를 반환합니다.

        반환값:
            ('rebalance', info)         → 거래량돌파 리밸런싱 (상승장/횡보장)
            ('emergency_sell', info)    → 전량 매도 (하락장 전환)
            ('regime_change_sell', info) → 국면 전환에 의한 청산
            (None, info)                → 대기
        """
        try:
            # 1. 국면 감지
            detected_regime, regime_info = self.detect_regime()

            # 2. 초기 상태 → 바로 전략 설정
            if self.current_regime is None:
                self.current_regime = detected_regime
                self.current_strategy = self.strategies[detected_regime]
                self._save_regime(detected_regime)
                logger.info(
                    f"[라우터 v2] 초기 국면 설정: {REGIME_NAMES.get(detected_regime)} | "
                    f"전략: {STRATEGY_NAMES.get(detected_regime)} | "
                    f"ADX: {regime_info.get('adx', 0):.1f}"
                )

            # 3. 국면 전환 확인 (confirmation_days 대기)
            elif self._confirm_regime_change(detected_regime):
                held_positions = self.switch_strategy(detected_regime, regime_info)
                if held_positions:
                    return "regime_change_sell", {
                        "regime": detected_regime,
                        "prev_regime": self.regime_history[-1]["from"] if self.regime_history else None,
                        "positions_to_close": held_positions,
                        "regime_info": regime_info,
                        "reason": f"국면 전환: {REGIME_NAMES.get(detected_regime)} → 포지션 청산",
                    }

            # 4. 현재 전략 실행
            if self.current_strategy is None:
                return None, {"regime": detected_regime, "reason": "전략 초기화 대기"}

            # 현재 국면을 전략에 전달 (횡보장 필터 완화 등에 사용)
            if hasattr(self.current_strategy, "set_external_regime"):
                self.current_strategy.set_external_regime(self.current_regime)

            signal, info = self.current_strategy.check_signal(ticker)

            # 국면 정보 추가
            info["regime"] = self.current_regime
            info["regime_info"] = regime_info
            info["active_strategy"] = self.current_strategy.get_strategy_name()

            return signal, info

        except Exception as e:
            logger.exception(f"[라우터 v2] 신호 확인 오류: {e}")
            send_error_alert(f"전략 라우터 v2 오류:\n{type(e).__name__}: {e}")
            return None, {"error": str(e)}

    def get_current_regime(self) -> str:
        """현재 시장 국면을 반환합니다."""
        return self.current_regime

    def get_current_strategy_name(self) -> str:
        """현재 활성 전략 이름을 반환합니다."""
        if self.current_strategy:
            return self.current_strategy.get_strategy_name()
        return "없음"

    def get_regime_history(self) -> list:
        """국면 전환 이력을 반환합니다."""
        return self.regime_history


if __name__ == "__main__":
    """단독 실행 테스트"""
    import sys
    import yaml
    from dotenv import load_dotenv
    load_dotenv()

    logger.remove()
    logger.add(sys.stdout, format="{time:HH:mm:ss} | {level: <8} | {message}", level="DEBUG")

    # 설정 로드
    with open("config/settings.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    router = StrategyRouter(config)
    logger.info("=== 전략 라우터 v2 단독 테스트 ===")

    # 국면 감지
    regime, regime_info = router.detect_regime()
    logger.info(
        f"현재 국면: {REGIME_NAMES.get(regime)} | "
        f"BTC: {regime_info.get('btc_price', 0):,.0f}원 | "
        f"ADX: {regime_info.get('adx', 0):.1f} | "
        f"+DI: {regime_info.get('plus_di', 0):.1f} | "
        f"-DI: {regime_info.get('minus_di', 0):.1f}"
    )

    # 신호 확인
    signal, info = router.check_signal()
    logger.info(f"신호: {signal}")
    logger.info(f"정보: {info}")
