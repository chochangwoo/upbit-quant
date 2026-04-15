"""
backtest/walk_forward.py - 공통 walk-forward 하네스

train_days / test_days / step_days 로 시계열을 분할하여
사용자 정의 run_fn 을 fold 별로 실행하고, OOS(=test) 구간 메트릭을
fold 별 + 평균/표준편차로 집계합니다.

run_fn 시그니처:
    run_fn(train_slice: pd.DatetimeIndex, test_slice: pd.DatetimeIndex)
        -> {"equity": pd.Series, "trades": int}

이번 PR 시점에는 train 구간을 파라미터 튜닝에 사용하지 않지만,
인터페이스는 보존하여 추후 in-sample 최적화를 끼워넣을 수 있게 합니다.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from backtest.metrics import (
    calc_cumulative_return,
    calc_sharpe_ratio,
    calc_mdd,
    calc_daily_win_rate,
    calc_profit_factor,
)


def split_walk_forward(
    index: pd.DatetimeIndex,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
) -> list[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """
    날짜 인덱스를 (train, test) 페어 리스트로 분할합니다.
    step_days 가 None 이면 test_days 와 동일 (겹치지 않는 fold).
    """
    if step_days is None:
        step_days = test_days

    index = pd.DatetimeIndex(sorted(set(index)))
    if len(index) < train_days + test_days:
        return []

    folds = []
    start = 0
    while True:
        train_end = start + train_days
        test_end = train_end + test_days
        if test_end > len(index):
            break
        train_idx = index[start:train_end]
        test_idx = index[train_end:test_end]
        folds.append((train_idx, test_idx))
        start += step_days
    return folds


def run_walk_forward(
    index: pd.DatetimeIndex,
    run_fn: Callable[[pd.DatetimeIndex, pd.DatetimeIndex], dict],
    train_days: int = 180,
    test_days: int = 60,
    step_days: int | None = None,
) -> dict:
    """
    walk-forward 실행. 각 fold 의 OOS equity 곡선에 대해
    수익률 / Sharpe / MDD / 승률 / 프로핏팩터 / 거래수를 계산.

    반환값:
        {
            "folds": [
                {
                    "train_start", "train_end", "test_start", "test_end",
                    "수익률", "샤프비율", "MDD", "일별승률", "프로핏팩터", "거래수"
                },
                ...
            ],
            "summary": {
                "n_folds", "평균수익률", "평균샤프", "평균MDD",
                "샤프표준편차", "샤프열화_OOS"  # = 평균샤프 (간단판)
            }
        }
    """
    folds = split_walk_forward(index, train_days, test_days, step_days)
    fold_records: list[dict] = []

    for train_idx, test_idx in folds:
        result = run_fn(train_idx, test_idx)
        eq = result.get("equity")
        if eq is None or len(eq) < 2:
            continue
        trades = int(result.get("trades", 0))
        fold_records.append(
            {
                "train_start": train_idx[0].date().isoformat(),
                "train_end": train_idx[-1].date().isoformat(),
                "test_start": test_idx[0].date().isoformat(),
                "test_end": test_idx[-1].date().isoformat(),
                "수익률": calc_cumulative_return(eq),
                "샤프비율": calc_sharpe_ratio(eq),
                "MDD": calc_mdd(eq),
                "일별승률": calc_daily_win_rate(eq),
                "프로핏팩터": calc_profit_factor(eq),
                "거래수": trades,
            }
        )

    if not fold_records:
        return {"folds": [], "summary": {}}

    sharpe_vals = np.array([f["샤프비율"] for f in fold_records], dtype=float)
    ret_vals = np.array([f["수익률"] for f in fold_records], dtype=float)
    mdd_vals = np.array([f["MDD"] for f in fold_records], dtype=float)

    # IQR 기반 이상치 제거 평균 (극단 fold 방어)
    def _trimmed_mean(arr: np.ndarray) -> float:
        q1, q3 = np.percentile(arr, [25, 75])
        iqr = q3 - q1
        mask = (arr >= q1 - 1.5 * iqr) & (arr <= q3 + 1.5 * iqr)
        return float(arr[mask].mean()) if mask.any() else float(arr.mean())

    summary = {
        "n_folds": len(fold_records),
        "평균수익률": float(ret_vals.mean()),
        "중앙수익률": float(np.median(ret_vals)),
        "평균샤프": float(sharpe_vals.mean()),
        "중앙샤프": float(np.median(sharpe_vals)),
        "trimmed샤프": _trimmed_mean(sharpe_vals),
        "샤프표준편차": float(sharpe_vals.std(ddof=0)),
        "평균MDD": float(mdd_vals.mean()),
        "중앙MDD": float(np.median(mdd_vals)),
        "총거래수": int(sum(f["거래수"] for f in fold_records)),
    }
    return {"folds": fold_records, "summary": summary}
