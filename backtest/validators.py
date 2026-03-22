"""
backtest/validators.py - 백테스트 결과 통계적 검증 모듈

크립토 시장의 기간 편향을 줄이기 위한 3가지 검증 도구:

1. Monte Carlo Simulation (몬테카를로 시뮬레이션)
   - 수익률 순서를 무작위로 섞어 1,000번 시뮬레이션
   - "이 전략이 운이 좋았던 건지, 진짜 실력인지" 통계적으로 판단
   - p-value < 0.05면 유의미 (95% 신뢰)

2. Bootstrap Confidence Interval (부트스트랩 신뢰구간)
   - 수익률을 복원추출로 1,000번 리샘플링
   - 결과에 95% 신뢰구간 부여 ("수익률 5~15% 범위")
   - 단일 숫자가 아닌 범위로 판단 -> 과신 방지

3. Regime-Stratified Evaluation (레짐별 층화 평가)
   - 불장/횡보/하락장 각각에서 전략 성과를 별도 평가
   - "모든 장세에서 안정적인 전략"을 선별
   - 특정 레짐에서만 좋은 전략은 위험 플래그
"""

import numpy as np
import pandas as pd
from loguru import logger


# ─────────────────────────────────────────
# 1. Monte Carlo Simulation
# ─────────────────────────────────────────

def monte_carlo_test(equity_curve: pd.Series, n_simulations: int = 1000,
                     seed: int = 42) -> dict:
    """
    몬테카를로 시뮬레이션으로 전략의 통계적 유의성을 검증합니다.

    방법:
      1. 실제 에쿼티 커브에서 일별 수익률을 추출합니다.
      2. 이 수익률 순서를 무작위로 섞어 N번 시뮬레이션합니다.
      3. 실제 전략 수익률이 무작위보다 유의미하게 좋은지 판단합니다.

    매개변수:
        equity_curve  : 에쿼티 커브 Series (1.0에서 시작)
        n_simulations : 시뮬레이션 횟수 (기본 1,000회)
        seed          : 랜덤 시드 (재현성)

    반환값:
        dict:
          - actual_return   : 실제 누적 수익률
          - mean_random     : 무작위 평균 수익률
          - p_value         : p-value (낮을수록 유의미)
          - percentile_rank : 실제 수익률의 백분위 순위
          - is_significant  : 유의미 여부 (p < 0.05)
          - simulated_returns: 시뮬레이션된 수익률 배열
    """
    if len(equity_curve) < 10:
        logger.warning("데이터 부족으로 몬테카를로 검증을 건너뜁니다.")
        return _empty_monte_carlo()

    rng = np.random.default_rng(seed)

    # 실제 일별 수익률 추출
    daily_returns = equity_curve.pct_change().dropna().values
    actual_return = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1

    # N번 시뮬레이션: 수익률 순서를 무작위로 섞기
    simulated_returns = np.zeros(n_simulations)
    for i in range(n_simulations):
        shuffled = rng.permutation(daily_returns)
        # 섞인 수익률로 에쿼티 커브 재구성
        sim_equity = np.cumprod(1 + shuffled)
        simulated_returns[i] = sim_equity[-1] - 1

    # p-value: 실제 수익률보다 높은 시뮬레이션 비율
    p_value = (simulated_returns >= actual_return).mean()
    percentile_rank = (simulated_returns < actual_return).mean() * 100

    result = {
        "actual_return": actual_return,
        "mean_random": simulated_returns.mean(),
        "std_random": simulated_returns.std(),
        "p_value": p_value,
        "percentile_rank": percentile_rank,
        "is_significant": p_value < 0.05,
        "simulated_returns": simulated_returns,
    }

    logger.info(
        f"  [몬테카를로] 실제: {actual_return:+.2%}, "
        f"무작위 평균: {simulated_returns.mean():+.2%}, "
        f"p-value: {p_value:.3f} {'(유의미)' if p_value < 0.05 else '(비유의미)'}"
    )

    return result


def _empty_monte_carlo() -> dict:
    """데이터 부족 시 빈 결과"""
    return {
        "actual_return": 0.0,
        "mean_random": 0.0,
        "std_random": 0.0,
        "p_value": 1.0,
        "percentile_rank": 50.0,
        "is_significant": False,
        "simulated_returns": np.array([]),
    }


# ─────────────────────────────────────────
# 2. Bootstrap Confidence Interval
# ─────────────────────────────────────────

def bootstrap_confidence_interval(equity_curve: pd.Series,
                                  n_bootstrap: int = 1000,
                                  confidence: float = 0.95,
                                  seed: int = 42) -> dict:
    """
    부트스트랩 리샘플링으로 성과 지표의 신뢰구간을 추정합니다.

    방법:
      1. 일별 수익률에서 복원추출(같은 것을 여러 번 뽑을 수 있음)로 리샘플링
      2. 리샘플링된 수익률로 에쿼티 커브를 N번 재구성
      3. 각 재구성에서 성과 지표를 계산
      4. 지표 분포의 하위/상위 백분위수로 신뢰구간 산출

    매개변수:
        equity_curve : 에쿼티 커브 Series
        n_bootstrap  : 리샘플링 횟수 (기본 1,000회)
        confidence   : 신뢰 수준 (기본 95%)
        seed         : 랜덤 시드

    반환값:
        dict:
          - cumulative_return: {"point": 실제값, "ci_lower": 하한, "ci_upper": 상한}
          - sharpe_ratio     : {"point": 실제값, "ci_lower": 하한, "ci_upper": 상한}
          - mdd              : {"point": 실제값, "ci_lower": 하한, "ci_upper": 상한}
          - annual_return    : {"point": 실제값, "ci_lower": 하한, "ci_upper": 상한}
    """
    if len(equity_curve) < 10:
        logger.warning("데이터 부족으로 부트스트랩 검증을 건너뜁니다.")
        return _empty_bootstrap()

    rng = np.random.default_rng(seed)

    daily_returns = equity_curve.pct_change().dropna().values
    n_days = len(daily_returns)
    alpha = (1 - confidence) / 2

    # 부트스트랩 샘플 생성
    boot_cum_returns = np.zeros(n_bootstrap)
    boot_sharpe = np.zeros(n_bootstrap)
    boot_mdd = np.zeros(n_bootstrap)
    boot_ann_returns = np.zeros(n_bootstrap)

    for i in range(n_bootstrap):
        # 복원추출로 일별 수익률 리샘플링
        sample_idx = rng.integers(0, n_days, size=n_days)
        sample_returns = daily_returns[sample_idx]

        # 에쿼티 커브 재구성
        sim_equity = np.cumprod(1 + sample_returns)

        # 누적 수익률
        boot_cum_returns[i] = sim_equity[-1] - 1

        # 연환산 수익률
        total_return = sim_equity[-1]
        boot_ann_returns[i] = total_return ** (365.0 / n_days) - 1 if n_days > 0 else 0

        # 샤프 비율
        if sample_returns.std() > 0:
            boot_sharpe[i] = (sample_returns.mean() / sample_returns.std()) * np.sqrt(365)
        else:
            boot_sharpe[i] = 0

        # MDD
        peak = np.maximum.accumulate(sim_equity)
        drawdown = (sim_equity - peak) / peak
        boot_mdd[i] = drawdown.min()

    # 실제 지표 계산
    actual_cum = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    actual_total = equity_curve.iloc[-1] / equity_curve.iloc[0]
    actual_days = (equity_curve.index[-1] - equity_curve.index[0]).days
    actual_ann = actual_total ** (365.0 / actual_days) - 1 if actual_days > 0 else 0
    actual_sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(365)) if daily_returns.std() > 0 else 0
    peak_s = equity_curve.cummax()
    actual_mdd = ((equity_curve - peak_s) / peak_s).min()

    result = {
        "cumulative_return": {
            "point": actual_cum,
            "ci_lower": np.percentile(boot_cum_returns, alpha * 100),
            "ci_upper": np.percentile(boot_cum_returns, (1 - alpha) * 100),
        },
        "sharpe_ratio": {
            "point": actual_sharpe,
            "ci_lower": np.percentile(boot_sharpe, alpha * 100),
            "ci_upper": np.percentile(boot_sharpe, (1 - alpha) * 100),
        },
        "mdd": {
            "point": actual_mdd,
            "ci_lower": np.percentile(boot_mdd, alpha * 100),
            "ci_upper": np.percentile(boot_mdd, (1 - alpha) * 100),
        },
        "annual_return": {
            "point": actual_ann,
            "ci_lower": np.percentile(boot_ann_returns, alpha * 100),
            "ci_upper": np.percentile(boot_ann_returns, (1 - alpha) * 100),
        },
    }

    logger.info(
        f"  [부트스트랩 95% CI] "
        f"수익률: {result['cumulative_return']['ci_lower']:+.2%} ~ {result['cumulative_return']['ci_upper']:+.2%}, "
        f"샤프: {result['sharpe_ratio']['ci_lower']:.2f} ~ {result['sharpe_ratio']['ci_upper']:.2f}"
    )

    return result


def _empty_bootstrap() -> dict:
    """데이터 부족 시 빈 결과"""
    empty = {"point": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}
    return {
        "cumulative_return": empty.copy(),
        "sharpe_ratio": empty.copy(),
        "mdd": empty.copy(),
        "annual_return": empty.copy(),
    }


# ─────────────────────────────────────────
# 3. Regime-Stratified Evaluation
# ─────────────────────────────────────────

def regime_stratified_evaluation(window_details: pd.DataFrame,
                                 strategy_name: str) -> dict:
    """
    시장 레짐별로 전략 성과를 분리 평가합니다.

    목적:
      특정 장세(예: 불장)에서만 좋은 전략을 걸러내기 위함입니다.
      이상적인 전략은 모든 레짐에서 일관된 성과를 보여야 합니다.

    매개변수:
        window_details: engine.run_backtest()의 윈도우별 상세 DataFrame
        strategy_name : 전략 이름

    반환값:
        dict:
          - regime_stats: 레짐별 {평균수익률, 승률, 윈도우수, 표준편차}
          - consistency_score: 일관성 점수 (0~1, 높을수록 레짐 간 성과 편차 적음)
          - worst_regime: 가장 약한 레짐 이름
          - risk_flags: 위험 플래그 리스트
    """
    if window_details.empty:
        logger.warning(f"  [{strategy_name}] 윈도우 데이터 없음 — 레짐 분석 생략")
        return _empty_regime_eval()

    regime_stats = {}
    risk_flags = []

    for regime in ["불장", "횡보", "하락장"]:
        regime_windows = window_details[window_details["레짐"] == regime]
        if len(regime_windows) == 0:
            regime_stats[regime] = {
                "평균수익률": 0.0,
                "승률": 0.0,
                "윈도우수": 0,
                "표준편차": 0.0,
            }
            continue

        returns = regime_windows["수익률"]
        regime_stats[regime] = {
            "평균수익률": returns.mean(),
            "승률": (returns > 0).mean(),
            "윈도우수": len(regime_windows),
            "표준편차": returns.std() if len(returns) > 1 else 0.0,
        }

    # 일관성 점수 계산: 레짐 간 평균수익률 편차가 작을수록 높은 점수
    means = [s["평균수익률"] for s in regime_stats.values() if s["윈도우수"] > 0]
    if len(means) >= 2:
        spread = max(means) - min(means)
        # 정규화: spread가 0이면 완벽한 일관성(1.0), 0.5 이상이면 0에 가까움
        consistency_score = max(0, 1 - spread / 0.5)
    else:
        consistency_score = 0.5  # 데이터 부족 시 중립

    # 가장 약한 레짐 찾기
    worst_regime = "없음"
    worst_return = float("inf")
    for regime, stats in regime_stats.items():
        if stats["윈도우수"] > 0 and stats["평균수익률"] < worst_return:
            worst_return = stats["평균수익률"]
            worst_regime = regime

    # 위험 플래그 판단
    # 1) 하락장에서 큰 손실
    if regime_stats["하락장"]["윈도우수"] > 0 and regime_stats["하락장"]["평균수익률"] < -0.10:
        risk_flags.append("하락장에서 평균 -10% 이상 손실")

    # 2) 불장에서만 수익
    if (regime_stats["불장"]["윈도우수"] > 0 and regime_stats["불장"]["평균수익률"] > 0.05
            and regime_stats["횡보"]["윈도우수"] > 0 and regime_stats["횡보"]["평균수익률"] < 0
            and regime_stats["하락장"]["윈도우수"] > 0 and regime_stats["하락장"]["평균수익률"] < 0):
        risk_flags.append("불장에서만 수익 — 추세 의존적 전략")

    # 3) 윈도우 간 수익률 편차가 큰 경우
    all_returns = window_details["수익률"]
    if len(all_returns) > 2 and all_returns.std() > 0.15:
        risk_flags.append(f"윈도우 간 수익률 편차 크다 (std={all_returns.std():.2%})")

    # 4) 낮은 일관성
    if consistency_score < 0.3:
        risk_flags.append(f"레짐 간 일관성 부족 (점수: {consistency_score:.2f})")

    result = {
        "regime_stats": regime_stats,
        "consistency_score": consistency_score,
        "worst_regime": worst_regime,
        "risk_flags": risk_flags,
    }

    # 로그 출력
    logger.info(f"  [{strategy_name}] 레짐별 성과:")
    for regime, stats in regime_stats.items():
        if stats["윈도우수"] > 0:
            logger.info(
                f"    {regime}: {stats['윈도우수']}개 윈도우, "
                f"평균 {stats['평균수익률']:+.2%}, "
                f"승률 {stats['승률']:.0%}"
            )
    logger.info(f"    일관성 점수: {consistency_score:.2f}")
    if risk_flags:
        for flag in risk_flags:
            logger.warning(f"    [경고] {flag}")

    return result


def _empty_regime_eval() -> dict:
    """데이터 부족 시 빈 결과"""
    return {
        "regime_stats": {},
        "consistency_score": 0.0,
        "worst_regime": "없음",
        "risk_flags": ["데이터 부족"],
    }


# ─────────────────────────────────────────
# 4. 종합 검증 실행
# ─────────────────────────────────────────

def validate_strategy(equity_curve: pd.Series,
                      window_details: pd.DataFrame,
                      strategy_name: str) -> dict:
    """
    3가지 검증을 한 번에 실행하고 종합 판정을 내립니다.

    매개변수:
        equity_curve  : 에쿼티 커브 Series
        window_details: 윈도우별 상세 DataFrame
        strategy_name : 전략 이름

    반환값:
        dict:
          - monte_carlo  : 몬테카를로 결과
          - bootstrap    : 부트스트랩 결과
          - regime       : 레짐별 평가 결과
          - overall_grade: 종합 등급 (A/B/C/D/F)
          - verdict      : 한줄 판정
    """
    logger.info(f"\n{'='*50}")
    logger.info(f"  [{strategy_name}] 통계적 검증 시작")
    logger.info(f"{'='*50}")

    # 1. 몬테카를로 시뮬레이션
    mc = monte_carlo_test(equity_curve)

    # 2. 부트스트랩 신뢰구간
    bs = bootstrap_confidence_interval(equity_curve)

    # 3. 레짐별 평가
    regime = regime_stratified_evaluation(window_details, strategy_name)

    # 종합 등급 산출
    score = 0

    # 몬테카를로: 유의미하면 +2점
    if mc["is_significant"]:
        score += 2

    # 부트스트랩: 수익률 하한이 양수면 +2점
    if bs["cumulative_return"]["ci_lower"] > 0:
        score += 2

    # 부트스트랩: 샤프 하한이 0.5 이상이면 +1점
    if bs["sharpe_ratio"]["ci_lower"] > 0.5:
        score += 1

    # 레짐: 일관성 점수 반영 (0~2점)
    score += regime["consistency_score"] * 2

    # 레짐: 위험 플래그가 없으면 +1점
    if len(regime["risk_flags"]) == 0:
        score += 1

    # 등급 변환 (0~8점)
    if score >= 7:
        grade = "A"
        verdict = "통계적으로 유의미하고 모든 장세에서 안정적 — 실거래 고려 가능"
    elif score >= 5:
        grade = "B"
        verdict = "대체로 양호하나 일부 약점 존재 — 추가 모니터링 필요"
    elif score >= 3:
        grade = "C"
        verdict = "보통 수준 — 파라미터 조정이나 추가 전략 검토 권장"
    elif score >= 1:
        grade = "D"
        verdict = "통계적 근거 부족 — 실거래 비추천"
    else:
        grade = "F"
        verdict = "무작위와 차이 없음 — 전략 교체 필요"

    logger.info(f"\n  [{strategy_name}] 종합 등급: {grade} (점수: {score:.1f}/8)")
    logger.info(f"  판정: {verdict}")

    return {
        "monte_carlo": mc,
        "bootstrap": bs,
        "regime": regime,
        "overall_grade": grade,
        "overall_score": score,
        "verdict": verdict,
    }
