"""
backtest/run_backtest.py - 백테스트 메인 실행 스크립트

실행 방법:
    python backtest/run_backtest.py

전체 파이프라인:
  1단계: 13개 코인 데이터 수집 (800일)
  2단계: 12개 전략 x Walk-Forward 백테스트
  3단계: 벤치마크 (BTC B&H, 동일비중 B&H)
  4단계: 성과 지표 계산 및 비교
  5단계: 통계적 검증 (몬테카를로 + 부트스트랩 + 레짐분석)
  6단계: 결과 파일 저장 (CSV, JSON)
  7단계: 시각화 (5종 차트)
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from loguru import logger

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data_collector import collect_all_data
from backtest.strategies import get_all_strategy_configs
from backtest.engine import run_backtest, run_benchmark_btc, run_benchmark_equal
from backtest.metrics import calc_all_metrics
from backtest.validators import validate_strategy
from backtest.report import (
    plot_equity_curves,
    plot_window_returns,
    plot_metrics_heatmap,
    plot_regime_comparison,
    plot_validation_chart,
    send_summary_to_telegram,
    save_results_to_db,
    RESULTS_DIR,
)


def print_separator(title: str = ""):
    """구분선 출력"""
    logger.info(f"\n{'='*70}")
    if title:
        logger.info(f"  {title}")
        logger.info(f"{'='*70}")


def main():
    """백테스트 메인 실행 함수"""
    start_time = time.time()

    # ========================================
    # 1. 데이터 수집
    # ========================================
    print_separator("1단계: 데이터 수집")
    prices, volumes = collect_all_data(days=800)

    logger.info(f"\n  가격 데이터: {prices.shape[0]}일 x {prices.shape[1]}개 코인")
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    logger.info(f"  코인 목록: {', '.join(c.replace('KRW-', '') for c in prices.columns)}")

    # ========================================
    # 2. 전략 x 파라미터 조합 백테스트
    # ========================================
    print_separator("2단계: Walk-Forward 롤링 윈도우 백테스트")
    configs = get_all_strategy_configs()
    logger.info(f"  전략 x 파라미터 조합: {len(configs)}개\n")

    all_results = []
    all_window_details = []

    for i, config in enumerate(configs, 1):
        strategy = config["strategy"]
        logger.info(f"  [{i}/{len(configs)}] {strategy.name} 백테스트 중...")

        result = run_backtest(strategy, prices, volumes)
        eq = result["equity_curve"]

        if len(eq) > 0:
            metrics = calc_all_metrics(eq)
            result["metrics"] = metrics
            all_results.append(result)
            all_window_details.append((strategy.name, result["window_details"]))

            logger.info(
                f"    -> 누적수익률: {metrics['누적수익률']:+.2%}, "
                f"샤프: {metrics['샤프비율']:.2f}, "
                f"MDD: {metrics['MDD']:.2%}, "
                f"윈도우: {len(result['window_details'])}개"
            )
        else:
            logger.warning(f"    -> 데이터 부족으로 스킵")

    # ========================================
    # 3. 벤치마크
    # ========================================
    print_separator("3단계: 벤치마크 계산")

    if all_results:
        bench_start = all_results[0]["equity_curve"].index[0]
    else:
        bench_start = prices.index[90]

    btc_bh = run_benchmark_btc(prices, bench_start)
    equal_bh = run_benchmark_equal(prices, bench_start)

    benchmarks = {}
    if len(btc_bh) > 0:
        benchmarks["BTC B&H"] = btc_bh
        btc_metrics = calc_all_metrics(btc_bh)
        logger.info(
            f"  BTC 바이앤홀드: {btc_metrics['누적수익률']:+.2%}, "
            f"샤프: {btc_metrics['샤프비율']:.2f}, MDD: {btc_metrics['MDD']:.2%}"
        )

    if len(equal_bh) > 0:
        benchmarks["동일비중 B&H"] = equal_bh
        eq_metrics = calc_all_metrics(equal_bh)
        logger.info(
            f"  동일비중 바이앤홀드: {eq_metrics['누적수익률']:+.2%}, "
            f"샤프: {eq_metrics['샤프비율']:.2f}, MDD: {eq_metrics['MDD']:.2%}"
        )

    # ========================================
    # 4. 종합 성과 비교 테이블
    # ========================================
    print_separator("4단계: 종합 성과 비교")

    summary_rows = []
    for name, eq in benchmarks.items():
        m = calc_all_metrics(eq)
        row = {"전략": name}
        row.update(m)
        summary_rows.append(row)

    for r in all_results:
        row = {"전략": r["strategy_name"]}
        row.update(r["metrics"])
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)

    # 콘솔 출력
    logger.info("\n[전략별 종합 성과]")
    display_df = summary_df.copy()
    for col in display_df.columns:
        if col == "전략":
            continue
        display_df[col] = display_df[col].apply(
            lambda x: f"{x:.2%}" if abs(x) < 100 else f"{x:.2f}"
        )
    logger.info(f"\n{display_df.to_string(index=False)}")

    # ========================================
    # 5. 통계적 검증 (핵심 업그레이드)
    # ========================================
    print_separator("5단계: 통계적 검증 (몬테카를로 + 부트스트랩 + 레짐분석)")

    validation_results = {}
    for r in all_results:
        name = r["strategy_name"]
        val = validate_strategy(
            equity_curve=r["equity_curve"],
            window_details=r["window_details"],
            strategy_name=name,
        )
        validation_results[name] = val

    # 등급별 요약
    logger.info(f"\n{'='*50}")
    logger.info("  [검증 등급 요약]")
    logger.info(f"{'='*50}")
    sorted_by_grade = sorted(
        validation_results.items(),
        key=lambda x: x[1]["overall_score"],
        reverse=True,
    )
    for name, val in sorted_by_grade:
        mc = val["monte_carlo"]
        bs = val["bootstrap"]
        regime = val["regime"]
        logger.info(
            f"  {val['overall_grade']} | {name}: "
            f"p={mc['p_value']:.3f}, "
            f"수익CI=[{bs['cumulative_return']['ci_lower']:+.2%}~{bs['cumulative_return']['ci_upper']:+.2%}], "
            f"일관성={regime['consistency_score']:.2f}"
        )
        if val["regime"]["risk_flags"]:
            for flag in val["regime"]["risk_flags"]:
                logger.warning(f"      [경고] {flag}")

    # ========================================
    # 6. 파일 출력
    # ========================================
    print_separator("6단계: 결과 파일 저장")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # summary.csv
    summary_df.to_csv(
        os.path.join(RESULTS_DIR, "summary.csv"),
        index=False, encoding="utf-8-sig"
    )
    logger.info(f"  -> summary.csv 저장")

    # equity_curves.csv
    eq_dict = {}
    for name, eq in benchmarks.items():
        eq_dict[name] = eq
    for r in all_results:
        eq_dict[r["strategy_name"]] = r["equity_curve"]
    equity_df = pd.DataFrame(eq_dict)
    equity_df.to_csv(
        os.path.join(RESULTS_DIR, "equity_curves.csv"),
        encoding="utf-8-sig"
    )
    logger.info(f"  -> equity_curves.csv 저장")

    # window_detail.csv
    all_wd = []
    for name, wd in all_window_details:
        wd_copy = wd.copy()
        wd_copy.insert(0, "전략", name)
        all_wd.append(wd_copy)
    if all_wd:
        window_df = pd.concat(all_wd, ignore_index=True)
        window_df.to_csv(
            os.path.join(RESULTS_DIR, "window_detail.csv"),
            index=False, encoding="utf-8-sig"
        )
        logger.info(f"  -> window_detail.csv 저장")

    # validation_summary.csv (검증 결과)
    val_rows = []
    for name, val in validation_results.items():
        mc = val["monte_carlo"]
        bs = val["bootstrap"]
        regime = val["regime"]
        val_rows.append({
            "전략": name,
            "등급": val["overall_grade"],
            "점수": round(val["overall_score"], 1),
            "p_value": round(mc["p_value"], 4),
            "실제수익률": round(mc["actual_return"], 4),
            "무작위평균": round(mc["mean_random"], 4),
            "수익CI하한": round(bs["cumulative_return"]["ci_lower"], 4),
            "수익CI상한": round(bs["cumulative_return"]["ci_upper"], 4),
            "샤프CI하한": round(bs["sharpe_ratio"]["ci_lower"], 4),
            "샤프CI상한": round(bs["sharpe_ratio"]["ci_upper"], 4),
            "레짐일관성": round(regime["consistency_score"], 4),
            "취약레짐": regime["worst_regime"],
            "경고수": len(regime["risk_flags"]),
            "판정": val["verdict"],
        })
    val_df = pd.DataFrame(val_rows)
    val_df.to_csv(
        os.path.join(RESULTS_DIR, "validation_summary.csv"),
        index=False, encoding="utf-8-sig"
    )
    logger.info(f"  -> validation_summary.csv 저장")

    # backtest_results.json
    json_data = {
        "생성시각": pd.Timestamp.now().isoformat(),
        "데이터기간": f"{prices.index[0].date()} ~ {prices.index[-1].date()}",
        "코인수": len(prices.columns),
        "전략수": len(all_results),
        "벤치마크": {},
        "전략결과": [],
    }
    for name, eq in benchmarks.items():
        m = calc_all_metrics(eq)
        json_data["벤치마크"][name] = {k: round(v, 6) for k, v in m.items()}
    for r in all_results:
        val = validation_results.get(r["strategy_name"], {})
        json_data["전략결과"].append({
            "전략": r["strategy_name"],
            "지표": {k: round(v, 6) for k, v in r["metrics"].items()},
            "검증등급": val.get("overall_grade", "N/A"),
            "검증판정": val.get("verdict", "N/A"),
            "윈도우수": len(r["window_details"]),
        })

    with open(os.path.join(RESULTS_DIR, "backtest_results.json"), "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"  -> backtest_results.json 저장")

    # ========================================
    # 7. 시각화
    # ========================================
    print_separator("7단계: 시각화 생성")

    # 누적 수익률 곡선
    plot_equity_curves(all_results, benchmarks)

    # 윈도우별 수익률 (상위 3개 전략)
    if all_results:
        top3 = sorted(all_results, key=lambda x: x["metrics"]["샤프비율"], reverse=True)[:3]
        for r in top3:
            plot_window_returns(r["window_details"], r["strategy_name"])

    # 성과 히트맵
    plot_metrics_heatmap(summary_df)

    # 레짐별 비교
    plot_regime_comparison(all_window_details)

    # 검증 결과 차트 (전체 전략)
    for name, val in validation_results.items():
        plot_validation_chart(val, name)

    # ========================================
    # 8. 최적 전략 추천
    # ========================================
    print_separator("8단계: 최적 전략 추천")

    # 검증 등급 + 샤프 비율 기준 정렬
    if all_results:
        ranked = sorted(
            all_results,
            key=lambda x: (
                validation_results.get(x["strategy_name"], {}).get("overall_score", 0),
                x["metrics"]["샤프비율"],
            ),
            reverse=True,
        )

        logger.info("\n  [검증 등급 + 샤프 비율 기준 TOP 5]")
        for rank, r in enumerate(ranked[:5], 1):
            m = r["metrics"]
            val = validation_results.get(r["strategy_name"], {})
            grade = val.get("overall_grade", "?")
            logger.info(
                f"    {rank}. [{grade}] {r['strategy_name']}: "
                f"샤프 {m['샤프비율']:.2f}, "
                f"수익률 {m['누적수익률']:+.2%}, "
                f"MDD {m['MDD']:.2%}"
            )

        # 실거래 추천 (A등급만)
        a_grade = [r for r in ranked if validation_results.get(r["strategy_name"], {}).get("overall_grade") == "A"]
        if a_grade:
            logger.info(f"\n  [실거래 고려 가능 전략 (A등급)]")
            for r in a_grade:
                logger.info(f"    - {r['strategy_name']}")
        else:
            logger.info(f"\n  [A등급 전략 없음 — 추가 파라미터 탐색이나 전략 수정 필요]")

    # ========================================
    # 완료
    # ========================================
    elapsed = time.time() - start_time
    print_separator("백테스트 완료!")
    logger.info(f"\n  총 소요 시간: {elapsed:.1f}초")
    logger.info(f"  결과 폴더: {RESULTS_DIR}")
    logger.info(f"\n  생성된 파일:")
    for f_name in sorted(os.listdir(RESULTS_DIR)):
        f_path = os.path.join(RESULTS_DIR, f_name)
        size = os.path.getsize(f_path)
        logger.info(f"    - {f_name} ({size:,} bytes)")

    logger.info(f"\n  * 과거 성과가 미래 수익을 보장하지 않습니다.")
    logger.info(f"  * A등급 전략도 실거래 전 소액 테스트를 권장합니다.")


if __name__ == "__main__":
    main()
