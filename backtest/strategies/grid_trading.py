"""
backtest/strategies/grid_trading.py - 그리드 트레이딩 (백테스트용)

일봉 high/low 근사 시뮬레이션:
  - 코인별 독립 그리드. anchor (재설정 시점 종가) 기준으로
    하단 n_levels 개의 매수 레벨을 깔아둠 (anchor * (1 - i * spacing)).
  - 매일 해당 레벨이 일봉 low 에 닿으면 그 레벨에서 슬롯 예산만큼 매수.
  - 매수 후엔 entry * (1 + spacing) 을 매도 목표가로 설정. 일봉 high 가
    목표가에 닿으면 매도(= 1 spacing 차익 확정).
  - reanchor_days 마다 보유분 종가 청산 후 anchor 재설정.

주의:
  - 일봉 high/low 만으로 체결을 근사하므로 일내 매수→매도 동시 충족 시
    순서를 "매도 먼저, 매수 나중"으로 처리 (보수적 가정).
  - 강추세가 발생해 anchor 아래로 깊게 떨어지면 평가손 누적 → reanchor
    시점에 종가 청산하면서 손실 실현. 강추세 위험은 메모리에 알려진 그대로.
"""

from __future__ import annotations

import pandas as pd

from backtest.data_collector import COINS as DEFAULT_COINS


class GridTradingBT:
    """
    매개변수:
        coins              : 운용 대상 코인 컬럼 리스트
        spacing_pct        : 그리드 간격 (예: 0.025 = 2.5%)
        n_levels           : anchor 하단 매수 레벨 개수
        reanchor_days      : anchor 재설정 주기 (일)
        commission         : 단방향 수수료
        slot_budget_ratio  : 각 매수 슬롯이 사용하는 초기 자본 대비 비율
                             (전체 최대 노출 = ratio * n_levels * n_coins)
    """

    def __init__(
        self,
        coins: list[str] | None = None,
        spacing_pct: float = 0.025,
        n_levels: int = 5,
        reanchor_days: int = 30,
        commission: float = 0.0005,
        slot_budget_ratio: float = 0.01,
    ):
        self.coins = coins if coins is not None else list(DEFAULT_COINS)
        self.spacing_pct = spacing_pct
        self.n_levels = n_levels
        self.reanchor_days = reanchor_days
        self.commission = commission
        self.slot_budget_ratio = slot_budget_ratio
        self.name = (
            f"Grid(spc={spacing_pct*100:.1f}%_n={n_levels}_re={reanchor_days})"
        )

    def simulate(
        self,
        prices: pd.DataFrame,
        highs: pd.DataFrame,
        lows: pd.DataFrame,
        dates: pd.DatetimeIndex,
        initial_capital: float,
        mask: pd.Series | None = None,
    ) -> dict:
        """
        반환값: {"equity": pd.Series, "trades": int}
        mask 가 주어지면 해당 날짜 False 인 날은 신규 매수 진입을 막음
        (기존 보유 포지션의 매도 청산은 항상 허용 — 자금 회수 우선).
        """
        cash = float(initial_capital)
        # state[coin] = {"anchor": float, "last_anchor": Timestamp, "filled": {lvl: (qty, entry)}}
        state: dict[str, dict] = {}
        equity_curve = []
        trades = 0
        slot_cash = initial_capital * self.slot_budget_ratio

        for date in dates:
            for coin in self.coins:
                if coin not in prices.columns:
                    continue
                close = prices.loc[date, coin] if date in prices.index else None
                if close is None or pd.isna(close):
                    continue
                high = (
                    highs.loc[date, coin]
                    if coin in highs.columns and date in highs.index
                    else close
                )
                low = (
                    lows.loc[date, coin]
                    if coin in lows.columns and date in lows.index
                    else close
                )
                if pd.isna(high):
                    high = close
                if pd.isna(low):
                    low = close

                st = state.get(coin)
                need_reanchor = st is None or (
                    (date - st["last_anchor"]).days >= self.reanchor_days
                )
                if need_reanchor:
                    # 기존 포지션 종가 청산
                    if st:
                        for _, (qty, _) in st["filled"].items():
                            cash += qty * close * (1 - self.commission)
                            trades += 1
                    state[coin] = {
                        "anchor": float(close),
                        "last_anchor": date,
                        "filled": {},
                    }
                    continue  # 재설정 직후엔 이 코인 거래 스킵

                anchor = st["anchor"]

                # 1) 매도 먼저 (보수적 가정)
                to_remove = []
                for lvl, (qty, entry) in st["filled"].items():
                    target = entry * (1 + self.spacing_pct)
                    if high >= target:
                        cash += qty * target * (1 - self.commission)
                        trades += 1
                        to_remove.append(lvl)
                for lvl in to_remove:
                    del st["filled"][lvl]

                # 2) 매수 (마스크 통과 시)
                allow_buy = True if mask is None else bool(mask.get(date, False))
                if allow_buy:
                    for i in range(1, self.n_levels + 1):
                        if i in st["filled"]:
                            continue
                        lvl_price = anchor * (1 - i * self.spacing_pct)
                        if low <= lvl_price and cash >= slot_cash:
                            qty = (slot_cash * (1 - self.commission)) / lvl_price
                            cash -= slot_cash
                            st["filled"][i] = (qty, lvl_price)
                            trades += 1

            # 일별 평가
            value = cash
            for coin, st in state.items():
                if coin in prices.columns and date in prices.index:
                    p = prices.loc[date, coin]
                    if pd.notna(p):
                        for qty, _ in st["filled"].values():
                            value += qty * p
            equity_curve.append({"date": date, "value": value})

        eq = pd.DataFrame(equity_curve).set_index("date")["value"]
        return {"equity": eq, "trades": trades}
