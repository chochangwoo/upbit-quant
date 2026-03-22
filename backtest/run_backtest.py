"""
backtest/run_backtest.py - 백테스트 메인 실행 스크립트

실행 방법:
    python backtest/run_backtest.py

전체 파이프라인:
  1단계: 13개 코인 데이터 수집 (800일)
  2단계: 38개 전략 x 4개 OOS 기간 = 152회 Walk-Forward 백테스트
  3단계: 벤치마크 (BTC B&H, 동일비중 B&H)
  4단계: 기간별 성과 분석 + 전략 유형별 종합 비교
  5단계: 통계적 검증 (몬테카를로 + 부트스트랩 + 레짐분석)
  6단계: 결과 파일 저장 (CSV, JSON)
  7단계: 시각화 (7종 차트)
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from loguru import logger

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
    plot_period_comparison,
    plot_strategy_type_summary,
    RESULTS_DIR,
)

# 테스트할 OOS 기간 (일)
OOS_PERIODS = [15, 30, 45, 60]


def _get_strategy_type(name: str) -> str:
    """전략 이름에서 유형을 추출합니다."""
    prefixes = {
        "모멘텀": "모멘텀", "리스크패리티": "리스크패리티", "통합": "통합",
        "RSI": "RSI역추세", "듀얼": "듀얼모멘텀", "거래량": "거래량돌파",
        "MA": "MA크로스", "반전": "반전", "적응형": "적응형모멘텀",
    }
    for prefix, stype in prefixes.items():
        if name.startswith(prefix):
            return stype
    return "기타"


def run_single_period(prices, volumes, configs, oos_days, benchmarks):
    """단일 OOS 기간에 대한 전체 백테스트를 실행합니다."""
    all_results = []
    all_window_details = []

    for i, config in enumerate(configs, 1):
        strategy = config["strategy"]
        result = run_backtest(strategy, prices, volumes, oos_window=oos_days)
        eq = result["equity_curve"]

        if len(eq) > 0:
            metrics = calc_all_metrics(eq)

            # 윈도우 승률 추가
            wd = result["window_details"]
            if not wd.empty:
                metrics["윈도우승률"] = (wd["수익률"] > 0).mean()
            else:
                metrics["윈도우승률"] = 0.0

            result["metrics"] = metrics
            all_results.append(result)
            all_window_details.append((strategy.name, result["window_details"]))

    # 종합 테이블 구성
    summary_rows = []
    for name, eq in benchmarks.items():
        m = calc_all_metrics(eq)
        m["윈도우승률"] = 0.0
        row = {"전략": name}
        row.update(m)
        summary_rows.append(row)

    for r in all_results:
        row = {"전략": r["strategy_name"]}
        row.update(r["metrics"])
        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    return all_results, all_window_details, summary_df


def main():
    """백테스트 메인 실행 함수"""
    start_time = time.time()

    # ========================================
    # 1. 데이터 수집
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  1단계: 데이터 수집")
    logger.info(f"{'='*70}")
    prices, volumes = collect_all_data(days=800)

    logger.info(f"\n  가격 데이터: {prices.shape[0]}일 x {prices.shape[1]}개 코인")
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    logger.info(f"  코인: {', '.join(c.replace('KRW-', '') for c in prices.columns)}")

    # ========================================
    # 2. 전략 구성
    # ========================================
    configs = get_all_strategy_configs()
    logger.info(f"\n  전략 x 파라미터 조합: {len(configs)}개")
    logger.info(f"  OOS 기간: {OOS_PERIODS}")
    logger.info(f"  총 백테스트 횟수: {len(configs) * len(OOS_PERIODS)}회")

    # 벤치마크
    bench_start = prices.index[max(OOS_PERIODS) * 3]
    btc_bh = run_benchmark_btc(prices, bench_start)
    equal_bh = run_benchmark_equal(prices, bench_start)
    benchmarks = {}
    if len(btc_bh) > 0:
        benchmarks["BTC B&H"] = btc_bh
    if len(equal_bh) > 0:
        benchmarks["동일비중 B&H"] = equal_bh

    # ========================================
    # 3. OOS 기간별 백테스트
    # ========================================
    period_results = {}
    period_summaries = {}
    period_windows = {}
    type_summaries = {}

    for oos_days in OOS_PERIODS:
        logger.info(f"\n{'='*70}")
        logger.info(f"  OOS {oos_days}일 백테스트 ({len(configs)}개 전략)")
        logger.info(f"{'='*70}")

        all_results, all_window_details, summary_df = run_single_period(
            prices, volumes, configs, oos_days, benchmarks
        )

        period_results[oos_days] = all_results
        period_summaries[oos_days] = summary_df
        period_windows[oos_days] = all_window_details

        # 상위 5개 출력
        strat_only = summary_df[~summary_df["전략"].str.contains("B&H")]
        top5 = strat_only.nlargest(5, "샤프비율")
        logger.info(f"\n  [OOS {oos_days}일 - 샤프 TOP 5]")
        for _, row in top5.iterrows():
            logger.info(
                f"    {row['전략']}: 샤프 {row['샤프비율']:.2f}, "
                f"수익률 {row['누적수익률']:+.2%}, MDD {row['MDD']:.2%}, "
                f"윈도우승률 {row.get('윈도우승률', 0):.0%}"
            )

        # 전략 유형별 평균 계산
        for _, row in strat_only.iterrows():
            stype = _get_strategy_type(row["전략"])
            key = (stype, oos_days)
            if key not in type_summaries:
                type_summaries[key] = {"sharpes": [], "returns": [], "mdds": []}
            type_summaries[key]["sharpes"].append(row["샤프비율"])
            type_summaries[key]["returns"].append(row["누적수익률"])
            type_summaries[key]["mdds"].append(row["MDD"])

    # 유형별 평균 집계
    type_avg = {}
    for key, vals in type_summaries.items():
        type_avg[key] = {
            "avg_sharpe": np.mean(vals["sharpes"]),
            "avg_return": np.mean(vals["returns"]),
            "avg_mdd": np.mean(vals["mdds"]),
        }

    # ========================================
    # 4. 절대 TOP 전략 (전 기간 통합)
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  절대 TOP 전략 (모든 OOS 기간 종합)")
    logger.info(f"{'='*70}")

    strategy_scores = {}
    for oos_days, summary_df in period_summaries.items():
        strat_only = summary_df[~summary_df["전략"].str.contains("B&H")]
        for _, row in strat_only.iterrows():
            name = row["전략"]
            if name not in strategy_scores:
                strategy_scores[name] = {"sharpes": [], "returns": [], "mdds": [], "periods": []}
            strategy_scores[name]["sharpes"].append(row["샤프비율"])
            strategy_scores[name]["returns"].append(row["누적수익률"])
            strategy_scores[name]["mdds"].append(row["MDD"])
            strategy_scores[name]["periods"].append(oos_days)

    ranked = []
    for name, scores in strategy_scores.items():
        avg_sharpe = np.mean(scores["sharpes"])
        std_sharpe = np.std(scores["sharpes"]) if len(scores["sharpes"]) > 1 else 1.0
        consistency = 1.0 / (1.0 + std_sharpe)
        composite_score = avg_sharpe * consistency
        best_period = scores["periods"][np.argmax(scores["sharpes"])]

        ranked.append({
            "전략": name,
            "종합점수": composite_score,
            "평균샤프": avg_sharpe,
            "일관성": consistency,
            "최고기간": f"{best_period}일",
            "평균수익률": np.mean(scores["returns"]),
            "평균MDD": np.mean(scores["mdds"]),
        })

    ranked_df = pd.DataFrame(ranked).sort_values("종합점수", ascending=False)

    logger.info(f"\n  [종합 점수 TOP 10 (평균 샤프 x 일관성)]")
    for i, (_, row) in enumerate(ranked_df.head(10).iterrows(), 1):
        logger.info(
            f"    {i:2d}. {row['전략']:<28} "
            f"종합 {row['종합점수']:.3f}  "
            f"샤프 {row['평균샤프']:.2f}  "
            f"수익률 {row['평균수익률']:+.1%}  "
            f"MDD {row['평균MDD']:.1%}  "
            f"최고기간 {row['최고기간']}"
        )

    # ========================================
    # 5. 통계적 검증 (TOP 10 전략만)
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  통계적 검증 (TOP 10 전략)")
    logger.info(f"{'='*70}")

    validation_results = {}
    top10_names = ranked_df.head(10)["전략"].values

    if 30 in period_results:
        for r in period_results[30]:
            if r["strategy_name"] in top10_names:
                val = validate_strategy(
                    equity_curve=r["equity_curve"],
                    window_details=r["window_details"],
                    strategy_name=r["strategy_name"],
                )
                validation_results[r["strategy_name"]] = val

    if validation_results:
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
                f"수익CI=[{bs['cumulative_return']['ci_lower']:+.2%}~"
                f"{bs['cumulative_return']['ci_upper']:+.2%}], "
                f"일관성={regime['consistency_score']:.2f}"
            )

    # ========================================
    # 6. 파일 저장
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  파일 저장")
    logger.info(f"{'='*70}")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 기간별 summary
    for oos_days, summary_df in period_summaries.items():
        summary_df.to_csv(
            os.path.join(RESULTS_DIR, f"summary_oos{oos_days}.csv"),
            index=False, encoding="utf-8-sig"
        )
    logger.info(f"  -> summary_oos*.csv 저장 ({len(OOS_PERIODS)}개)")

    # 종합 랭킹
    ranked_df.to_csv(
        os.path.join(RESULTS_DIR, "overall_ranking.csv"),
        index=False, encoding="utf-8-sig"
    )
    logger.info(f"  -> overall_ranking.csv 저장")

    # 기간별 window_detail
    for oos_days, all_wd in period_windows.items():
        all_wd_list = []
        for name, wd in all_wd:
            if not wd.empty:
                wd_copy = wd.copy()
                wd_copy.insert(0, "전략", name)
                all_wd_list.append(wd_copy)
        if all_wd_list:
            window_df = pd.concat(all_wd_list, ignore_index=True)
            window_df.to_csv(
                os.path.join(RESULTS_DIR, f"window_detail_oos{oos_days}.csv"),
                index=False, encoding="utf-8-sig"
            )
    logger.info(f"  -> window_detail_oos*.csv 저장")

    # 검증 결과
    if validation_results:
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
                "수익CI하한": round(bs["cumulative_return"]["ci_lower"], 4),
                "수익CI상한": round(bs["cumulative_return"]["ci_upper"], 4),
                "레짐일관성": round(regime["consistency_score"], 4),
                "판정": val["verdict"],
            })
        val_df = pd.DataFrame(val_rows)
        val_df.to_csv(
            os.path.join(RESULTS_DIR, "validation_summary.csv"),
            index=False, encoding="utf-8-sig"
        )
        logger.info(f"  -> validation_summary.csv 저장")

    # 종합 JSON
    json_data = {
        "생성시각": pd.Timestamp.now().isoformat(),
        "데이터기간": f"{prices.index[0].date()} ~ {prices.index[-1].date()}",
        "코인수": len(prices.columns),
        "전략조합수": len(configs),
        "OOS기간": OOS_PERIODS,
        "종합TOP10": [],
    }
    for _, row in ranked_df.head(10).iterrows():
        entry = {
            "전략": row["전략"],
            "종합점수": round(row["종합점수"], 4),
            "평균샤프": round(row["평균샤프"], 4),
            "평균수익률": round(row["평균수익률"], 4),
            "평균MDD": round(row["평균MDD"], 4),
            "최고기간": row["최고기간"],
        }
        if row["전략"] in validation_results:
            val = validation_results[row["전략"]]
            entry["검증등급"] = val["overall_grade"]
            entry["검증판정"] = val["verdict"]
        json_data["종합TOP10"].append(entry)

    with open(os.path.join(RESULTS_DIR, "backtest_results.json"), "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"  -> backtest_results.json 저장")

    # ========================================
    # 7. 시각화
    # ========================================
    logger.info(f"\n{'='*70}")
    logger.info(f"  시각화 생성")
    logger.info(f"{'='*70}")

    for oos_days in OOS_PERIODS:
        results = period_results[oos_days]
        if results:
            top_results = sorted(results, key=lambda x: x["metrics"]["샤프비율"], reverse=True)[:10]
            plot_equity_curves(top_results, benchmarks, suffix=str(oos_days))

            summary = period_summaries[oos_days]
            strat_only = summary[~summary["전략"].str.contains("B&H")]
            top15_names = strat_only.nlargest(15, "샤프비율")["전략"].values
            heatmap_df = summary[
                summary["전략"].isin(top15_names) | summary["전략"].str.contains("B&H")
            ]
            plot_metrics_heatmap(heatmap_df, suffix=str(oos_days))

    # OOS 기간별 비교 차트
    plot_period_comparison(period_summaries)

    # 전략 유형별 요약
    plot_strategy_type_summary(type_avg)

    # TOP 3 전략 윈도우 차트 (30일 기준)
    if 30 in period_results and period_results[30]:
        top3 = sorted(period_results[30], key=lambda x: x["metrics"]["샤프비율"], reverse=True)[:3]
        for r in top3:
            plot_window_returns(r["window_details"], f"{r['strategy_name']}_OOS30")

    # 검증 결과 차트
    for name, val in validation_results.items():
        plot_validation_chart(val, name)

    logger.info(f"  -> 차트 생성 완료")

    # ========================================
    # 완료
    # ========================================
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*70}")
    logger.info(f"  백테스트 완료!")
    logger.info(f"{'='*70}")
    logger.info(f"\n  총 소요 시간: {elapsed:.1f}초")
    logger.info(
        f"  전략 조합: {len(configs)}개 x OOS 기간: {len(OOS_PERIODS)}개 "
        f"= {len(configs) * len(OOS_PERIODS)}회"
    )
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
