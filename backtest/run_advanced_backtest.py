"""
backtest/run_advanced_backtest.py - 고급 백테스트 통합 실행 스크립트

3단계 고급 분석을 순차적으로 실행합니다:
  1단계: 베이지안 최적화 (Optuna) - 기존 전략 파라미터 최적화
  2단계: ML 전략 백테스트 (LightGBM) - 머신러닝 기반 매매
  3단계: 대안 데이터 통합 - 공포탐욕 + 온체인 + 펀딩비율

실행 방법:
  python -m backtest.run_advanced_backtest
  python -m backtest.run_advanced_backtest --phase 1      # 1단계만
  python -m backtest.run_advanced_backtest --phase 2      # 2단계만
  python -m backtest.run_advanced_backtest --phase 3      # 3단계만
  python -m backtest.run_advanced_backtest --phase all     # 전체 (기본)
"""

import os
import sys
import json
import argparse
import pandas as pd
import numpy as np
from datetime import datetime
from loguru import logger

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtest.data_collector import collect_all_data
from backtest.engine import run_backtest, run_benchmark_btc, run_benchmark_equal
from backtest.metrics import calc_all_metrics
from backtest.validators import validate_strategy


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results", "advanced")


def setup_logger():
    """로거 설정"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="INFO",
    )


def save_results(data, filename):
    """결과를 파일로 저장합니다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    filepath = os.path.join(RESULTS_DIR, filename)

    if isinstance(data, pd.DataFrame):
        data.to_csv(filepath, encoding="utf-8-sig")
        logger.info(f"저장: {filepath}")
    elif isinstance(data, dict):
        # JSON 직렬화 가능한 형태로 변환
        serializable = {}
        for k, v in data.items():
            if isinstance(v, (np.floating, np.integer)):
                serializable[k] = float(v)
            elif isinstance(v, np.ndarray):
                serializable[k] = v.tolist()
            else:
                serializable[k] = v
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"저장: {filepath}")


# ═══════════════════════════════════════════════════════
# 1단계: 베이지안 최적화 (Optuna)
# ═══════════════════════════════════════════════════════

def run_phase1_optimization(prices, volumes, n_trials=50, oos_window=30):
    """
    Optuna 베이지안 최적화를 실행합니다.

    기존 38개 고정 조합 → 연속 파라미터 공간에서 최적값 탐색
    TPE 알고리즘으로 50회 시도만에 최적 근접
    """
    logger.info("=" * 70)
    logger.info("1단계: 베이지안 최적화 (Optuna TPE)")
    logger.info("=" * 70)

    from backtest.optimizer.optuna_optimizer import optimize_all_strategies

    results = optimize_all_strategies(
        prices=prices,
        volumes=volumes,
        oos_window=oos_window,
        n_trials=n_trials,
        objective_metric="sharpe",
    )

    ranking = results.get("_ranking", pd.DataFrame())
    if not ranking.empty:
        save_results(ranking, "phase1_optuna_ranking.csv")

        # 각 전략 최적 파라미터 저장
        best_params = {}
        for st_name, st_result in results.items():
            if st_name.startswith("_"):
                continue
            best_params[st_name] = {
                "params": st_result["best_params"],
                "sharpe": float(st_result["best_value"]),
            }
        save_results(best_params, "phase1_best_params.json")

        # TOP 3 최적화 전략으로 백테스트 재실행 (상세 결과)
        logger.info("\n[1단계] TOP 3 전략 상세 백테스트:")
        top3_results = []
        for _, row in ranking.head(3).iterrows():
            st_name = row["전략"]
            if st_name in results and st_name != "_ranking":
                strategy = results[st_name]["best_strategy"]
                bt_result = run_backtest(strategy, prices, volumes, oos_window)
                metrics = calc_all_metrics(bt_result["equity_curve"])
                validation = validate_strategy(
                    bt_result["equity_curve"],
                    bt_result["window_details"],
                    strategy.name,
                )
                top3_results.append({
                    "전략": strategy.name,
                    "파라미터": str(results[st_name]["best_params"]),
                    **metrics,
                    "검증등급": validation.get("grade", "N/A"),
                    "p값": validation.get("monte_carlo", {}).get("p_value", "N/A"),
                })
                logger.info(
                    f"  {strategy.name}: 샤프 {metrics['샤프비율']:.3f} | "
                    f"수익률 {metrics['누적수익률']:.1%} | MDD {metrics['MDD']:.1%} | "
                    f"등급 {validation.get('grade', 'N/A')}"
                )

        if top3_results:
            save_results(pd.DataFrame(top3_results), "phase1_top3_detail.csv")

    return results


# ═══════════════════════════════════════════════════════
# 2단계: ML 전략 백테스트 (LightGBM)
# ═══════════════════════════════════════════════════════

def run_phase2_ml(prices, volumes, alt_data=None, oos_window=30):
    """
    ML 기반 전략을 백테스트합니다.

    여러 설정으로 ML 전략을 테스트:
      - top_k: 3, 5, 7
      - target_horizon: 3, 5, 7
      - weight_mode: equal, confidence
    """
    logger.info("=" * 70)
    logger.info("2단계: ML 전략 백테스트 (LightGBM)")
    logger.info("=" * 70)

    from backtest.ml.ml_strategy import MLStrategy

    configs = [
        {"top_k": 3, "target_horizon": 5, "weight_mode": "confidence"},
        {"top_k": 5, "target_horizon": 5, "weight_mode": "confidence"},
        {"top_k": 5, "target_horizon": 3, "weight_mode": "confidence"},
        {"top_k": 5, "target_horizon": 7, "weight_mode": "confidence"},
        {"top_k": 7, "target_horizon": 5, "weight_mode": "confidence"},
        {"top_k": 5, "target_horizon": 5, "weight_mode": "equal"},
    ]

    results = []
    best_result = None
    best_sharpe = -999

    for cfg in configs:
        logger.info(f"\n[ML] 설정: {cfg}")
        try:
            strategy = MLStrategy(
                top_k=cfg["top_k"],
                target_horizon=cfg["target_horizon"],
                weight_mode=cfg["weight_mode"],
                alt_data=alt_data,
                train_days=180,
                retrain_days=30,
                n_estimators=200,
            )

            bt_result = run_backtest(strategy, prices, volumes, oos_window)
            equity = bt_result["equity_curve"]

            if len(equity) < 10:
                logger.warning(f"  에쿼티 커브 부족: {len(equity)}일")
                continue

            metrics = calc_all_metrics(equity)
            sharpe = metrics["샤프비율"]

            results.append({
                "전략": strategy.name,
                "top_k": cfg["top_k"],
                "target_horizon": cfg["target_horizon"],
                "weight_mode": cfg["weight_mode"],
                "alt_data": "포함" if alt_data is not None else "미포함",
                **metrics,
            })

            logger.info(
                f"  결과: 샤프 {sharpe:.3f} | 수익률 {metrics['누적수익률']:.1%} | "
                f"MDD {metrics['MDD']:.1%} | 승률 {metrics['일별승률']:.1%}"
            )

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_result = bt_result

        except Exception as e:
            logger.error(f"  ML 전략 실패: {e}")

    if results:
        results_df = pd.DataFrame(results).sort_values("샤프비율", ascending=False)
        results_df = results_df.reset_index(drop=True)
        results_df.index += 1
        results_df.index.name = "순위"
        save_results(results_df, "phase2_ml_results.csv")

        logger.info("\n[2단계] ML 전략 순위:")
        for _, row in results_df.head(5).iterrows():
            logger.info(
                f"  {row['전략']}: 샤프 {row['샤프비율']:.3f} | "
                f"수익률 {row['누적수익률']:.1%}"
            )

    return results, best_result


# ═══════════════════════════════════════════════════════
# 3단계: 대안 데이터 통합
# ═══════════════════════════════════════════════════════

def collect_alt_data(days=800):
    """
    대안 데이터를 수집하고 통합합니다.

    수집 소스:
      - Alternative.me: 공포탐욕 지수
      - CoinGecko: BTC 도미넌스, 시가총액
      - Binance: 펀딩비율
    """
    logger.info("=" * 70)
    logger.info("3단계: 대안 데이터 수집")
    logger.info("=" * 70)

    from backtest.alt_data.fear_greed import get_fear_greed_features
    from backtest.alt_data.onchain import get_onchain_features
    from backtest.alt_data.funding_rate import get_funding_features

    all_features = []

    # 1) 공포탐욕 지수
    logger.info("[수집] 공포 & 탐욕 지수...")
    try:
        fg = get_fear_greed_features(days)
        if not fg.empty:
            all_features.append(fg)
            logger.info(f"  공포탐욕: {len(fg)}일, {fg.shape[1]}개 피처")
    except Exception as e:
        logger.error(f"  공포탐욕 수집 실패: {e}")

    # 2) 온체인 데이터 (BTC 도미넌스)
    logger.info("[수집] BTC 도미넌스 & 시가총액...")
    try:
        onchain = get_onchain_features(days)
        if not onchain.empty:
            all_features.append(onchain)
            logger.info(f"  온체인: {len(onchain)}일, {onchain.shape[1]}개 피처")
    except Exception as e:
        logger.error(f"  온체인 수집 실패: {e}")

    # 3) 펀딩비율
    logger.info("[수집] 펀딩비율 (BTC, ETH, SOL)...")
    try:
        funding = get_funding_features(days=min(days, 365))
        if not funding.empty:
            all_features.append(funding)
            logger.info(f"  펀딩비율: {len(funding)}일, {funding.shape[1]}개 피처")
    except Exception as e:
        logger.error(f"  펀딩비율 수집 실패: {e}")

    # 통합
    if not all_features:
        logger.warning("[대안데이터] 수집된 데이터 없음")
        return pd.DataFrame()

    # 날짜 기준으로 병합
    combined = all_features[0]
    for df in all_features[1:]:
        combined = combined.join(df, how="outer")

    combined = combined.sort_index().ffill()
    logger.info(f"[대안데이터] 통합 완료: {len(combined)}일, {combined.shape[1]}개 피처")

    save_results(combined, "phase3_alt_data.csv")
    return combined


def run_phase3_comparison(prices, volumes, alt_data, oos_window=30):
    """
    대안 데이터 포함/미포함 ML 전략을 비교합니다.
    """
    logger.info("=" * 70)
    logger.info("3단계: 대안 데이터 효과 비교")
    logger.info("=" * 70)

    from backtest.ml.ml_strategy import MLStrategy

    comparison = []

    for alt_label, alt in [("미포함", None), ("포함", alt_data)]:
        for top_k in [3, 5]:
            try:
                strategy = MLStrategy(
                    top_k=top_k,
                    target_horizon=5,
                    weight_mode="confidence",
                    alt_data=alt,
                    train_days=180,
                    retrain_days=30,
                )

                bt_result = run_backtest(strategy, prices, volumes, oos_window)
                equity = bt_result["equity_curve"]

                if len(equity) < 10:
                    continue

                metrics = calc_all_metrics(equity)
                comparison.append({
                    "전략": strategy.name,
                    "대안데이터": alt_label,
                    "top_k": top_k,
                    **metrics,
                })

                logger.info(
                    f"  [{alt_label}] {strategy.name}: "
                    f"샤프 {metrics['샤프비율']:.3f} | 수익률 {metrics['누적수익률']:.1%}"
                )

            except Exception as e:
                logger.error(f"  비교 실패 ({alt_label}, K={top_k}): {e}")

    if comparison:
        comp_df = pd.DataFrame(comparison)
        save_results(comp_df, "phase3_alt_data_comparison.csv")

        # 대안 데이터 효과 요약
        with_alt = comp_df[comp_df["대안데이터"] == "포함"]["샤프비율"].mean()
        without_alt = comp_df[comp_df["대안데이터"] == "미포함"]["샤프비율"].mean()
        improvement = with_alt - without_alt

        logger.info(f"\n[대안데이터 효과]")
        logger.info(f"  미포함 평균 샤프: {without_alt:.3f}")
        logger.info(f"  포함 평균 샤프: {with_alt:.3f}")
        logger.info(f"  개선량: {improvement:+.3f}")

    return comparison


# ═══════════════════════════════════════════════════════
# 최종 종합 비교
# ═══════════════════════════════════════════════════════

def run_final_comparison(prices, volumes, phase1_results, phase2_results, alt_data, oos_window=30):
    """
    1~3단계 전략을 벤치마크와 함께 종합 비교합니다.
    """
    logger.info("=" * 70)
    logger.info("종합 비교: 기존 전략 vs Optuna vs ML vs ML+대안데이터")
    logger.info("=" * 70)

    # 벤치마크
    equity_start = prices.index[max(60, oos_window * 3)]
    btc_bench = run_benchmark_btc(prices, equity_start)
    equal_bench = run_benchmark_equal(prices, equity_start)

    summary = []

    if len(btc_bench) > 10:
        metrics = calc_all_metrics(btc_bench)
        summary.append({"전략": "벤치마크: BTC 바이앤홀드", "유형": "벤치마크", **metrics})

    if len(equal_bench) > 10:
        metrics = calc_all_metrics(equal_bench)
        summary.append({"전략": "벤치마크: 동일비중", "유형": "벤치마크", **metrics})

    # Phase 1 TOP 전략
    if phase1_results:
        ranking = phase1_results.get("_ranking", pd.DataFrame())
        if not ranking.empty:
            top_name = ranking.iloc[0]["전략"]
            if top_name in phase1_results:
                strategy = phase1_results[top_name]["best_strategy"]
                bt = run_backtest(strategy, prices, volumes, oos_window)
                if len(bt["equity_curve"]) > 10:
                    metrics = calc_all_metrics(bt["equity_curve"])
                    summary.append({
                        "전략": f"Optuna 최적: {strategy.name}",
                        "유형": "1단계_Optuna",
                        **metrics,
                    })

    # Phase 2 TOP ML 전략
    if phase2_results:
        ml_results, _ = phase2_results
        if ml_results:
            best_ml = max(ml_results, key=lambda x: x.get("샤프비율", -999))
            summary.append({
                "전략": best_ml["전략"],
                "유형": "2단계_ML",
                **{k: v for k, v in best_ml.items() if k not in ["전략", "top_k", "target_horizon", "weight_mode", "alt_data"]},
            })

    # Phase 3: ML + 대안 데이터
    if alt_data is not None and not alt_data.empty:
        from backtest.ml.ml_strategy import MLStrategy
        try:
            strategy = MLStrategy(
                top_k=5, target_horizon=5, weight_mode="confidence",
                alt_data=alt_data, train_days=180, retrain_days=30,
            )
            bt = run_backtest(strategy, prices, volumes, oos_window)
            if len(bt["equity_curve"]) > 10:
                metrics = calc_all_metrics(bt["equity_curve"])
                summary.append({
                    "전략": "ML+대안데이터 (K5, H5)",
                    "유형": "3단계_ML+Alt",
                    **metrics,
                })
        except Exception as e:
            logger.error(f"ML+Alt 전략 실패: {e}")

    if summary:
        summary_df = pd.DataFrame(summary).sort_values("샤프비율", ascending=False)
        summary_df = summary_df.reset_index(drop=True)
        summary_df.index += 1
        summary_df.index.name = "순위"

        save_results(summary_df, "final_comparison.csv")

        logger.info("\n" + "=" * 70)
        logger.info("최종 종합 순위")
        logger.info("=" * 70)
        for _, row in summary_df.iterrows():
            logger.info(
                f"  [{row['유형']}] {row['전략']}\n"
                f"    샤프 {row['샤프비율']:.3f} | 수익률 {row['누적수익률']:.1%} | "
                f"MDD {row['MDD']:.1%} | 승률 {row['일별승률']:.1%}"
            )

    return summary


# ═══════════════════════════════════════════════════════
# 메인 실행
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="고급 백테스트 실행")
    parser.add_argument("--phase", default="all", help="실행 단계: 1, 2, 3, all")
    parser.add_argument("--days", type=int, default=800, help="데이터 수집 일수")
    parser.add_argument("--oos", type=int, default=30, help="OOS 기간")
    parser.add_argument("--trials", type=int, default=50, help="Optuna 시도 횟수")
    args = parser.parse_args()

    setup_logger()

    start_time = datetime.now()
    logger.info(f"고급 백테스트 시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"설정: 데이터 {args.days}일, OOS {args.oos}일, Optuna {args.trials}회")

    # 데이터 수집
    logger.info("데이터 수집 중...")
    prices, volumes = collect_all_data(days=args.days)
    logger.info(f"데이터: {len(prices)}일 × {len(prices.columns)}코인")

    phase1_results = None
    phase2_results = None
    alt_data = None

    # 1단계: 베이지안 최적화
    if args.phase in ["1", "all"]:
        phase1_results = run_phase1_optimization(prices, volumes, args.trials, args.oos)

    # 3단계 데이터 수집 (2단계에서도 사용하므로 먼저 수집)
    if args.phase in ["2", "3", "all"]:
        alt_data = collect_alt_data(args.days)

    # 2단계: ML 전략
    if args.phase in ["2", "all"]:
        phase2_results = run_phase2_ml(prices, volumes, alt_data, args.oos)

    # 3단계: 대안 데이터 비교
    if args.phase in ["3", "all"]:
        if alt_data is None or alt_data.empty:
            alt_data = collect_alt_data(args.days)
        run_phase3_comparison(prices, volumes, alt_data, args.oos)

    # 종합 비교
    if args.phase == "all":
        run_final_comparison(prices, volumes, phase1_results, phase2_results, alt_data, args.oos)

    elapsed = datetime.now() - start_time
    logger.info(f"\n전체 소요 시간: {elapsed}")
    logger.info("고급 백테스트 완료!")


if __name__ == "__main__":
    main()
