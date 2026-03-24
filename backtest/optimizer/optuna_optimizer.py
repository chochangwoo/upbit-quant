"""
backtest/optimizer/optuna_optimizer.py - 베이지안 최적화 엔진

Optuna를 활용하여 전략 파라미터를 자동 최적화합니다.
기존 38개 고정 조합 → 연속 공간에서 최적 파라미터 탐색

핵심 원리:
  - TPE(Tree-structured Parzen Estimator) 알고리즘 사용
  - 이전 시도 결과를 학습하여 유망한 영역을 집중 탐색
  - Grid Search 대비 10~50배 적은 시도로 최적값 근접
"""

import optuna
import pandas as pd
import numpy as np
from loguru import logger

from backtest.engine import run_backtest
from backtest.metrics import calc_all_metrics


# Optuna 로그 레벨 조정 (너무 많은 출력 방지)
optuna.logging.set_verbosity(optuna.logging.WARNING)


def _create_strategy_from_trial(trial: optuna.Trial, strategy_type: str):
    """
    Optuna Trial에서 전략 파라미터를 샘플링하여 전략 객체를 생성합니다.

    매개변수:
        trial        : Optuna Trial 객체
        strategy_type: 전략 유형 이름
    반환값:
        전략 객체 (get_weights 메서드 보유)
    """
    if strategy_type == "cross_sectional_momentum":
        from backtest.strategies.cross_sectional_momentum import CrossSectionalMomentum
        lookback = trial.suggest_int("lookback", 5, 30)
        top_k = trial.suggest_int("top_k", 2, 7)
        return CrossSectionalMomentum(lookback=lookback, top_k=top_k)

    elif strategy_type == "risk_parity":
        from backtest.strategies.risk_parity import RiskParityLite
        vol_lookback = trial.suggest_int("vol_lookback", 10, 90)
        return RiskParityLite(vol_lookback=vol_lookback)

    elif strategy_type == "combined":
        from backtest.strategies.combined_strategy import CombinedStrategy
        mom_lookback = trial.suggest_int("mom_lookback", 5, 21)
        vol_lookback = trial.suggest_int("vol_lookback", 10, 30)
        top_k = trial.suggest_int("top_k", 3, 8)
        return CombinedStrategy(
            mom_lookback=mom_lookback, vol_lookback=vol_lookback, top_k=top_k
        )

    elif strategy_type == "rsi_mean_reversion":
        from backtest.strategies.rsi_mean_reversion import RSIMeanReversion
        rsi_period = trial.suggest_int("rsi_period", 7, 21)
        threshold = trial.suggest_int("threshold", 20, 45)
        top_k = trial.suggest_int("top_k", 2, 7)
        return RSIMeanReversion(
            rsi_period=rsi_period, threshold=threshold, top_k=top_k
        )

    elif strategy_type == "dual_momentum":
        from backtest.strategies.dual_momentum import DualMomentum
        short_lookback = trial.suggest_int("short_lookback", 5, 21)
        long_lookback = trial.suggest_int("long_lookback", 40, 90)
        top_k = trial.suggest_int("top_k", 2, 7)
        return DualMomentum(
            short_lookback=short_lookback, long_lookback=long_lookback, top_k=top_k
        )

    elif strategy_type == "volume_breakout":
        from backtest.strategies.volume_breakout import VolumeBreakout
        price_lookback = trial.suggest_int("price_lookback", 3, 10)
        vol_ratio = trial.suggest_float("vol_ratio", 1.1, 3.0)
        top_k = trial.suggest_int("top_k", 2, 7)
        return VolumeBreakout(
            price_lookback=price_lookback, vol_ratio=vol_ratio, top_k=top_k
        )

    elif strategy_type == "ma_cross_rotation":
        from backtest.strategies.ma_cross_rotation import MACrossRotation
        short_ma = trial.suggest_int("short_ma", 3, 15)
        long_ma = trial.suggest_int("long_ma", 15, 60)
        top_k = trial.suggest_int("top_k", 2, 7)
        return MACrossRotation(ma_pair=[short_ma, long_ma], top_k=top_k)

    elif strategy_type == "momentum_reversal":
        from backtest.strategies.momentum_reversal import MomentumReversal
        mid_lookback = trial.suggest_int("mid_lookback", 14, 40)
        short_lookback = trial.suggest_int("short_lookback", 3, 10)
        top_k = trial.suggest_int("top_k", 2, 7)
        return MomentumReversal(
            mid_lookback=mid_lookback, short_lookback=short_lookback, top_k=top_k
        )

    elif strategy_type == "adaptive_momentum":
        from backtest.strategies.adaptive_momentum import AdaptiveMomentum
        short_lb = trial.suggest_int("short_lb", 3, 10)
        long_lb = trial.suggest_int("long_lb", 20, 60)
        top_k = trial.suggest_int("top_k", 2, 7)
        return AdaptiveMomentum(short_lb=short_lb, long_lb=long_lb, top_k=top_k)

    else:
        raise ValueError(f"알 수 없는 전략 유형: {strategy_type}")


def optimize_strategy(
    strategy_type: str,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    oos_window: int = 30,
    n_trials: int = 100,
    objective_metric: str = "sharpe",
    seed: int = 42,
) -> dict:
    """
    단일 전략 유형에 대해 베이지안 최적화를 실행합니다.

    매개변수:
        strategy_type   : 전략 유형 이름
        prices          : 가격 데이터
        volumes         : 거래량 데이터
        oos_window      : OOS 기간 (일)
        n_trials        : 최적화 시도 횟수 (기본 100)
        objective_metric: 최적화 목표 ("sharpe", "calmar", "return")
        seed            : 랜덤 시드
    반환값:
        {
            "best_params"  : 최적 파라미터 딕셔너리,
            "best_value"   : 최적 목표값,
            "best_strategy": 최적 전략 객체,
            "study"        : Optuna Study 객체,
            "all_trials"   : 전체 시행 결과 DataFrame,
        }
    """

    def objective(trial):
        try:
            strategy = _create_strategy_from_trial(trial, strategy_type)
            result = run_backtest(strategy, prices, volumes, oos_window)
            equity = result["equity_curve"]

            if len(equity) < 10:
                return float("-inf")

            metrics = calc_all_metrics(equity)

            if objective_metric == "sharpe":
                value = metrics["샤프비율"]
            elif objective_metric == "calmar":
                value = metrics["칼마비율"]
            elif objective_metric == "return":
                value = metrics["누적수익률"]
            else:
                value = metrics["샤프비율"]

            # 추가 지표를 사용자 속성에 저장
            trial.set_user_attr("누적수익률", metrics["누적수익률"])
            trial.set_user_attr("MDD", metrics["MDD"])
            trial.set_user_attr("샤프비율", metrics["샤프비율"])
            trial.set_user_attr("소르티노비율", metrics["소르티노비율"])
            trial.set_user_attr("칼마비율", metrics["칼마비율"])
            trial.set_user_attr("일별승률", metrics["일별승률"])

            if np.isnan(value) or np.isinf(value):
                return float("-inf")

            return value

        except Exception as e:
            logger.debug(f"Trial {trial.number} 실패: {e}")
            return float("-inf")

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        study_name=f"optuna_{strategy_type}_oos{oos_window}",
    )

    logger.info(f"[Optuna] {strategy_type} 최적화 시작 (시도 {n_trials}회, OOS {oos_window}일)")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_trial
    logger.info(
        f"[Optuna] {strategy_type} 최적화 완료 | "
        f"최적 {objective_metric}: {best.value:.4f} | "
        f"파라미터: {best.params}"
    )

    # 최적 전략 재생성
    best_strategy = _create_strategy_from_trial(best, strategy_type)

    # 전체 시행 결과를 DataFrame으로 변환
    trials_data = []
    for t in study.trials:
        if t.state == optuna.trial.TrialState.COMPLETE:
            row = {**t.params, "value": t.value}
            row.update(t.user_attrs)
            trials_data.append(row)

    return {
        "best_params": best.params,
        "best_value": best.value,
        "best_strategy": best_strategy,
        "study": study,
        "all_trials": pd.DataFrame(trials_data),
    }


def optimize_all_strategies(
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    oos_window: int = 30,
    n_trials: int = 50,
    objective_metric: str = "sharpe",
) -> dict:
    """
    전체 9종 전략에 대해 최적화를 실행하고 종합 순위를 반환합니다.

    반환값:
        {
            전략이름: optimize_strategy() 결과,
            ...
            "_ranking": 종합 순위 DataFrame,
        }
    """
    strategy_types = [
        "cross_sectional_momentum",
        "risk_parity",
        "combined",
        "rsi_mean_reversion",
        "dual_momentum",
        "volume_breakout",
        "ma_cross_rotation",
        "momentum_reversal",
        "adaptive_momentum",
    ]

    results = {}
    ranking_rows = []

    for st in strategy_types:
        try:
            opt_result = optimize_strategy(
                strategy_type=st,
                prices=prices,
                volumes=volumes,
                oos_window=oos_window,
                n_trials=n_trials,
                objective_metric=objective_metric,
            )
            results[st] = opt_result

            best_trial = opt_result["study"].best_trial
            ranking_rows.append({
                "전략": st,
                "최적_파라미터": str(opt_result["best_params"]),
                "샤프비율": best_trial.user_attrs.get("샤프비율", 0),
                "누적수익률": best_trial.user_attrs.get("누적수익률", 0),
                "MDD": best_trial.user_attrs.get("MDD", 0),
                "소르티노비율": best_trial.user_attrs.get("소르티노비율", 0),
                "칼마비율": best_trial.user_attrs.get("칼마비율", 0),
                "일별승률": best_trial.user_attrs.get("일별승률", 0),
            })

        except Exception as e:
            logger.error(f"[Optuna] {st} 최적화 실패: {e}")

    ranking_df = pd.DataFrame(ranking_rows)
    if not ranking_df.empty:
        ranking_df = ranking_df.sort_values("샤프비율", ascending=False).reset_index(drop=True)
        ranking_df.index += 1
        ranking_df.index.name = "순위"

    results["_ranking"] = ranking_df

    logger.info("=" * 60)
    logger.info("전략별 베이지안 최적화 완료 - 종합 순위")
    logger.info("=" * 60)
    if not ranking_df.empty:
        for _, row in ranking_df.iterrows():
            logger.info(
                f"  {row['전략']}: 샤프 {row['샤프비율']:.3f} | "
                f"수익률 {row['누적수익률']:.1%} | MDD {row['MDD']:.1%}"
            )

    return results
