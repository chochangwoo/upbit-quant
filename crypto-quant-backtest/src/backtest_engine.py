"""
롤링 윈도우(Walk-Forward) 백테스트 엔진

- OOS 기간을 파라미터로 받아 15/30/45/60일 등 다양한 기간 테스트 가능
- 거래비용: 편도 0.05%
"""

import numpy as np
import pandas as pd

from .metrics import calc_window_metrics, classify_regime


# 업비트 KRW 마켓 거래 수수료 (편도)
FEE_RATE = 0.0005


def _calc_rebal_freq(oos_window: int) -> int:
    """OOS 기간에 맞는 리밸런싱 주기 결정"""
    if oos_window <= 15:
        return 3
    elif oos_window <= 30:
        return 7
    elif oos_window <= 45:
        return 7
    else:
        return 10


def _calc_is_window(oos_window: int) -> int:
    """OOS 기간에 맞는 IS(학습) 윈도우 결정"""
    return max(60, oos_window * 3)


def run_backtest(strategy, prices: pd.DataFrame, volumes: pd.DataFrame,
                 oos_window: int = 30) -> dict:
    """
    단일 전략에 대해 롤링 윈도우 백테스트를 실행한다.

    Args:
        strategy: get_weights 메서드를 가진 전략 객체
        prices: 가격 데이터 (인덱스: 날짜, 컬럼: 코인)
        volumes: 거래량 데이터
        oos_window: OOS(테스트) 기간 (일)

    Returns:
        dict: equity_curve, window_details, strategy_name
    """
    is_window = _calc_is_window(oos_window)
    rebal_freq = _calc_rebal_freq(oos_window)
    slide_step = oos_window  # 겹치지 않는 OOS

    dates = prices.index
    n_dates = len(dates)

    equity = pd.Series(index=dates, dtype=float)
    equity.iloc[:] = np.nan

    window_details = []
    current_weights = pd.Series(dtype=float)

    portfolio_value = 1.0
    window_num = 0
    oos_start_idx = is_window

    while oos_start_idx + oos_window <= n_dates:
        is_start_idx = oos_start_idx - is_window
        oos_end_idx = min(oos_start_idx + oos_window, n_dates)

        is_start = dates[is_start_idx]
        is_end = dates[oos_start_idx - 1]
        oos_start = dates[oos_start_idx]
        oos_end = dates[oos_end_idx - 1]

        window_num += 1
        days_since_rebal = rebal_freq  # 첫날 바로 리밸런싱

        for i in range(oos_start_idx, oos_end_idx):
            today = dates[i]

            if days_since_rebal >= rebal_freq:
                lookback_data = prices.loc[dates[is_start_idx]:today]
                new_weights = strategy.get_weights(prices, volumes, today, lookback_data)

                if len(new_weights) > 0:
                    if len(current_weights) > 0:
                        all_coins = new_weights.index.union(current_weights.index)
                        old_w = current_weights.reindex(all_coins, fill_value=0.0)
                        new_w = new_weights.reindex(all_coins, fill_value=0.0)
                        turnover = (new_w - old_w).abs().sum()
                        portfolio_value *= (1 - turnover * FEE_RATE)

                    current_weights = new_weights
                    days_since_rebal = 0
                else:
                    days_since_rebal += 1
            else:
                days_since_rebal += 1

            if i > 0 and len(current_weights) > 0:
                prev_date = dates[i - 1]
                daily_return = 0.0
                for coin, w in current_weights.items():
                    if coin in prices.columns:
                        p_today = prices.loc[today, coin]
                        p_prev = prices.loc[prev_date, coin]
                        if pd.notna(p_today) and pd.notna(p_prev) and p_prev > 0:
                            daily_return += w * (p_today / p_prev - 1)

                portfolio_value *= (1 + daily_return)

                # 비중 드리프트
                if days_since_rebal > 0:
                    drifted = {}
                    total = 0
                    for coin, w in current_weights.items():
                        if coin in prices.columns:
                            pt = prices.loc[today, coin]
                            pp = prices.loc[prev_date, coin]
                            if pd.notna(pt) and pd.notna(pp) and pp > 0:
                                nw = w * (pt / pp)
                                drifted[coin] = nw
                                total += nw
                    if total > 0:
                        current_weights = pd.Series({c: v / total for c, v in drifted.items()})

            equity[today] = portfolio_value

        # 윈도우 결과 기록
        oos_equity = equity.loc[oos_start:oos_end].dropna()
        if len(oos_equity) >= 2:
            window_return = oos_equity.iloc[-1] / oos_equity.iloc[0] - 1
            regime = classify_regime(
                prices["KRW-BTC"] if "KRW-BTC" in prices.columns else pd.Series(dtype=float),
                oos_start,
            )
            metrics = calc_window_metrics(oos_equity)

            top_holdings = ""
            if len(current_weights) > 0:
                top3 = current_weights.nlargest(3)
                top_holdings = ", ".join(
                    [f"{c.replace('KRW-', '')}({w:.0%})" for c, w in top3.items()]
                )

            window_details.append({
                "윈도우": window_num,
                "IS시작": is_start.date(),
                "IS끝": is_end.date(),
                "OOS시작": oos_start.date(),
                "OOS끝": oos_end.date(),
                "OOS일수": oos_window,
                "수익률": window_return,
                "샤프비율": metrics["샤프비율"],
                "MDD": metrics["MDD"],
                "레짐": regime,
                "상위보유": top_holdings,
            })

        oos_start_idx += slide_step

    equity = equity.dropna()

    return {
        "equity_curve": equity,
        "window_details": pd.DataFrame(window_details),
        "strategy_name": strategy.name,
    }


def run_benchmark_btc(prices: pd.DataFrame, start_date: pd.Timestamp) -> pd.Series:
    """BTC 바이앤홀드 벤치마크"""
    if "KRW-BTC" not in prices.columns:
        return pd.Series(dtype=float)
    btc = prices["KRW-BTC"].loc[start_date:].dropna()
    if len(btc) == 0:
        return pd.Series(dtype=float)
    return btc / btc.iloc[0]


def run_benchmark_equal(prices: pd.DataFrame, start_date: pd.Timestamp) -> pd.Series:
    """동일비중 바이앤홀드 벤치마크"""
    p = prices.loc[start_date:].dropna(axis=1, how="any")
    if p.empty:
        return pd.Series(dtype=float)
    normalized = p.div(p.iloc[0])
    return normalized.mean(axis=1)
