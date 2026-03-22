"""
크립토 멀티에셋 퀀트 전략 — 멀티기간 롤링 윈도우 백테스트

OOS 기간: 15일, 30일, 45일, 60일
전략: 8가지 유형, 총 40+ 파라미터 조합
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from src.data_collector import collect_all_data
from src.strategies import get_all_strategy_configs
from src.backtest_engine import run_backtest, run_benchmark_btc, run_benchmark_equal
from src.metrics import calc_all_metrics
from src.visualize import (
    plot_equity_curves,
    plot_window_returns,
    plot_metrics_heatmap,
    plot_regime_comparison,
    plot_period_comparison,
    plot_strategy_type_summary,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
OOS_PERIODS = [15, 30, 45, 60]  # 테스트할 OOS 기간 (일)


def print_separator(title: str = ""):
    print(f"\n{'='*70}")
    if title:
        print(f"  {title}")
        print(f"{'='*70}")


def _get_strategy_type(name: str) -> str:
    """전략 이름에서 유형 추출"""
    if name.startswith("모멘텀"):
        return "모멘텀"
    elif name.startswith("리스크패리티"):
        return "리스크패리티"
    elif name.startswith("통합"):
        return "통합"
    elif name.startswith("RSI"):
        return "RSI역추세"
    elif name.startswith("듀얼"):
        return "듀얼모멘텀"
    elif name.startswith("거래량"):
        return "거래량돌파"
    elif name.startswith("MA"):
        return "MA크로스"
    elif name.startswith("반전"):
        return "반전"
    elif name.startswith("적응형"):
        return "적응형모멘텀"
    return "기타"


def run_single_period(prices, volumes, configs, oos_days, benchmarks):
    """단일 OOS 기간에 대한 전체 백테스트 실행"""
    all_results = []
    all_window_details = []

    for i, config in enumerate(configs, 1):
        strategy = config["strategy"]
        result = run_backtest(strategy, prices, volumes, oos_window=oos_days)
        eq = result["equity_curve"]

        if len(eq) > 0:
            metrics = calc_all_metrics(eq)
            result["metrics"] = metrics

            # 윈도우 승률 추가
            wd = result["window_details"]
            if not wd.empty:
                metrics["윈도우승률"] = (wd["수익률"] > 0).mean()
            else:
                metrics["윈도우승률"] = 0.0

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
    start_time = time.time()

    # ========================================
    # 1. 데이터 수집
    # ========================================
    print_separator("1단계: 데이터 수집")
    prices, volumes = collect_all_data(days=800)

    print(f"\n  가격 데이터: {prices.shape[0]}일 × {prices.shape[1]}개 코인")
    print(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    print(f"  코인: {', '.join(c.replace('KRW-', '') for c in prices.columns)}")

    # ========================================
    # 2. 전략 구성
    # ========================================
    configs = get_all_strategy_configs()
    print(f"\n  전략 × 파라미터 조합: {len(configs)}개")
    print(f"  OOS 기간: {OOS_PERIODS}")
    print(f"  총 백테스트 횟수: {len(configs) * len(OOS_PERIODS)}회")

    # 벤치마크 (공통)
    bench_start = prices.index[max(OOS_PERIODS) * 3]  # 가장 긴 IS 윈도우 이후
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
    period_results = {}     # {oos_days: all_results}
    period_summaries = {}   # {oos_days: summary_df}
    period_windows = {}     # {oos_days: all_window_details}
    type_summaries = {}     # {(strategy_type, period): avg_metrics}

    for oos_days in OOS_PERIODS:
        print_separator(f"OOS {oos_days}일 백테스트 ({len(configs)}개 전략)")

        all_results, all_window_details, summary_df = run_single_period(
            prices, volumes, configs, oos_days, benchmarks
        )

        period_results[oos_days] = all_results
        period_summaries[oos_days] = summary_df
        period_windows[oos_days] = all_window_details

        # 상위 5개 출력
        strat_only = summary_df[~summary_df["전략"].str.contains("B&H")]
        top5 = strat_only.nlargest(5, "샤프비율")
        print(f"\n  [OOS {oos_days}일 - 샤프 TOP 5]")
        for _, row in top5.iterrows():
            print(f"    {row['전략']}: 샤프 {row['샤프비율']:.2f}, "
                  f"수익률 {row['누적수익률']:+.2%}, MDD {row['MDD']:.2%}, "
                  f"윈도우승률 {row.get('윈도우승률', 0):.0%}")

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
    # 4. 전략 유형별 × 기간별 종합 분석
    # ========================================
    print_separator("종합 분석: 전략 유형별 × OOS 기간별")

    # 유형 목록
    strategy_types = sorted(set(k[0] for k in type_avg.keys()))

    print(f"\n  {'전략유형':<14}", end="")
    for p in OOS_PERIODS:
        print(f"  {p}일(샤프)", end="")
    print()
    print("  " + "-" * 60)

    for stype in strategy_types:
        print(f"  {stype:<14}", end="")
        for p in OOS_PERIODS:
            key = (stype, p)
            if key in type_avg:
                print(f"  {type_avg[key]['avg_sharpe']:>8.2f}", end="")
            else:
                print(f"  {'N/A':>8}", end="")
        print()

    # ========================================
    # 5. 절대 TOP 전략 (전 기간 통합)
    # ========================================
    print_separator("절대 TOP 전략 (모든 OOS 기간 종합)")

    # 각 전략이 모든 기간에서 얼마나 일관적인지 평가
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

    # 종합 점수 = 평균 샤프 × 일관성 보너스
    ranked = []
    for name, scores in strategy_scores.items():
        avg_sharpe = np.mean(scores["sharpes"])
        std_sharpe = np.std(scores["sharpes"]) if len(scores["sharpes"]) > 1 else 1.0
        consistency = 1.0 / (1.0 + std_sharpe)  # 변동 작을수록 일관적
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

    print(f"\n  [종합 점수 TOP 10 (평균 샤프 × 일관성)]")
    for i, (_, row) in enumerate(ranked_df.head(10).iterrows(), 1):
        print(f"    {i:2d}. {row['전략']:<28} "
              f"종합 {row['종합점수']:.3f}  "
              f"샤프 {row['평균샤프']:.2f}  "
              f"수익률 {row['평균수익률']:+.1%}  "
              f"MDD {row['평균MDD']:.1%}  "
              f"최고기간 {row['최고기간']}")

    # 단기(15일)에 특히 강한 전략
    print(f"\n  [OOS 15일 특화 TOP 5 (단기 트레이딩 최적)]")
    if 15 in period_summaries:
        short_df = period_summaries[15]
        short_top = short_df[~short_df["전략"].str.contains("B&H")].nlargest(5, "샤프비율")
        for i, (_, row) in enumerate(short_top.iterrows(), 1):
            print(f"    {i}. {row['전략']}: 샤프 {row['샤프비율']:.2f}, "
                  f"수익률 {row['누적수익률']:+.2%}, MDD {row['MDD']:.2%}")

    # ========================================
    # 6. 파일 저장
    # ========================================
    print_separator("파일 저장")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 기간별 summary
    for oos_days, summary_df in period_summaries.items():
        summary_df.to_csv(
            os.path.join(RESULTS_DIR, f"summary_oos{oos_days}.csv"),
            index=False, encoding="utf-8-sig"
        )
    print(f"  → summary_oos*.csv 저장 (4개)")

    # 종합 랭킹
    ranked_df.to_csv(
        os.path.join(RESULTS_DIR, "overall_ranking.csv"),
        index=False, encoding="utf-8-sig"
    )
    print(f"  → overall_ranking.csv 저장")

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
    print(f"  → window_detail_oos*.csv 저장")

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
        json_data["종합TOP10"].append({
            "전략": row["전략"],
            "종합점수": round(row["종합점수"], 4),
            "평균샤프": round(row["평균샤프"], 4),
            "평균수익률": round(row["평균수익률"], 4),
            "평균MDD": round(row["평균MDD"], 4),
            "최고기간": row["최고기간"],
        })
    with open(os.path.join(RESULTS_DIR, "backtest_results.json"), "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"  → backtest_results.json 저장")

    # ========================================
    # 7. 시각화
    # ========================================
    print_separator("시각화 생성")

    for oos_days in OOS_PERIODS:
        results = period_results[oos_days]
        # 상위 10개만 차트에 표시
        if results:
            top_results = sorted(results, key=lambda x: x["metrics"]["샤프비율"], reverse=True)[:10]
            plot_equity_curves(top_results, benchmarks, suffix=str(oos_days))

            # 히트맵 (상위 15개)
            summary = period_summaries[oos_days]
            strat_only = summary[~summary["전략"].str.contains("B&H")]
            top15_names = strat_only.nlargest(15, "샤프비율")["전략"].values
            heatmap_df = summary[summary["전략"].isin(top15_names) | summary["전략"].str.contains("B&H")]
            plot_metrics_heatmap(heatmap_df, suffix=str(oos_days))

    # OOS 기간별 비교 차트
    plot_period_comparison(period_summaries)

    # 전략 유형별 요약
    plot_strategy_type_summary(type_avg)

    # TOP 3 전략 윈도우 차트 (15일 기준)
    if 15 in period_results and period_results[15]:
        top3 = sorted(period_results[15], key=lambda x: x["metrics"]["샤프비율"], reverse=True)[:3]
        for r in top3:
            plot_window_returns(r["window_details"], f"{r['strategy_name']}_OOS15")

    print(f"  → 차트 생성 완료")

    # ========================================
    # 완료
    # ========================================
    elapsed = time.time() - start_time
    print_separator("백테스트 완료!")
    print(f"\n  총 소요 시간: {elapsed:.1f}초")
    print(f"  전략 조합: {len(configs)}개 × OOS 기간: {len(OOS_PERIODS)}개 = {len(configs) * len(OOS_PERIODS)}회")
    print(f"  결과 폴더: {RESULTS_DIR}")
    print(f"\n  생성된 파일:")
    for f_name in sorted(os.listdir(RESULTS_DIR)):
        f_path = os.path.join(RESULTS_DIR, f_name)
        size = os.path.getsize(f_path)
        print(f"    - {f_name} ({size:,} bytes)")

    print(f"\n  ※ 실데이터 기반 결과이며, 과거 성과가 미래 수익을 보장하지 않습니다.")


if __name__ == "__main__":
    main()
