"""
백테스트 결과 시각화 모듈

- 누적 수익률 곡선
- 윈도우별 수익률 바 차트 (레짐별 색상)
- 성과 지표 히트맵
- 레짐별 성과 비교
- OOS 기간별 비교 차트
"""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")


def plot_equity_curves(results: list[dict], benchmarks: dict, suffix: str = "", save: bool = True):
    """전략별 누적 수익률 곡선"""
    fig, ax = plt.subplots(figsize=(14, 7))

    for name, eq in benchmarks.items():
        ax.plot(eq.index, (eq - 1) * 100, "--", linewidth=1.5, alpha=0.7, label=name)

    for r in results:
        eq = r["equity_curve"]
        ax.plot(eq.index, (eq - 1) * 100, linewidth=1.0, label=r["strategy_name"], alpha=0.8)

    title = "전략별 누적 수익률 비교"
    if suffix:
        title += f" (OOS {suffix}일)"
    ax.set_title(title, fontsize=16, fontweight="bold")
    ax.set_xlabel("날짜")
    ax.set_ylabel("수익률 (%)")
    ax.legend(loc="upper left", fontsize=6, ncol=3)
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="black", linewidth=0.5)

    plt.tight_layout()
    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        fname = f"equity_curves_{suffix}.png" if suffix else "equity_curves.png"
        fig.savefig(os.path.join(RESULTS_DIR, fname), dpi=150)
    plt.close(fig)


def plot_window_returns(window_details: pd.DataFrame, strategy_name: str, save: bool = True):
    """윈도우별 수익률 바 차트 (레짐별 색상)"""
    if window_details.empty:
        return

    fig, ax = plt.subplots(figsize=(14, 5))
    colors_map = {"불장": "#2ECC71", "하락장": "#E74C3C", "횡보": "#95A5A6"}
    colors = [colors_map.get(r, "#95A5A6") for r in window_details["레짐"]]

    ax.bar(range(len(window_details)), window_details["수익률"] * 100,
           color=colors, edgecolor="white", linewidth=0.5)

    ax.set_title(f"{strategy_name} — 윈도우별 OOS 수익률", fontsize=14, fontweight="bold")
    ax.set_xlabel("윈도우 번호")
    ax.set_ylabel("수익률 (%)")
    ax.axhline(y=0, color="black", linewidth=0.8)
    ax.grid(True, axis="y", alpha=0.3)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2ECC71", label="불장"),
        Patch(facecolor="#E74C3C", label="하락장"),
        Patch(facecolor="#95A5A6", label="횡보"),
    ]
    ax.legend(handles=legend_elements, loc="upper right")

    plt.tight_layout()
    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        safe_name = strategy_name.replace("(", "").replace(")", "").replace("/", "_")
        fig.savefig(os.path.join(RESULTS_DIR, f"windows_{safe_name}.png"), dpi=150)
    plt.close(fig)


def plot_metrics_heatmap(summary_df: pd.DataFrame, suffix: str = "", save: bool = True):
    """전략 간 성과 지표 히트맵"""
    if summary_df.empty:
        return

    metric_cols = ["누적수익률", "연환산수익률", "샤프비율", "소르티노비율", "MDD", "칼마비율", "일별승률"]
    available = [c for c in metric_cols if c in summary_df.columns]
    if not available:
        return

    data = summary_df.set_index("전략")[available].astype(float)

    fig, ax = plt.subplots(figsize=(12, max(4, len(data) * 0.4)))

    norm_data = data.copy()
    for col in norm_data.columns:
        col_min = norm_data[col].min()
        col_max = norm_data[col].max()
        if col_max != col_min:
            if col == "MDD":
                norm_data[col] = 1 - (norm_data[col] - col_min) / (col_max - col_min)
            else:
                norm_data[col] = (norm_data[col] - col_min) / (col_max - col_min)
        else:
            norm_data[col] = 0.5

    im = ax.imshow(norm_data.values, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(available)))
    ax.set_xticklabels(available, rotation=45, ha="right")
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels(data.index, fontsize=6)

    for i in range(len(data)):
        for j in range(len(available)):
            val = data.iloc[i, j]
            text = f"{val:.2%}" if abs(val) < 10 else f"{val:.2f}"
            ax.text(j, i, text, ha="center", va="center", fontsize=5,
                    color="black" if 0.3 < norm_data.iloc[i, j] < 0.7 else "white")

    title = "전략별 성과 지표 비교"
    if suffix:
        title += f" (OOS {suffix}일)"
    ax.set_title(title, fontsize=14, fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.8)
    plt.tight_layout()

    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        fname = f"metrics_heatmap_{suffix}.png" if suffix else "metrics_heatmap.png"
        fig.savefig(os.path.join(RESULTS_DIR, fname), dpi=150)
    plt.close(fig)


def plot_regime_comparison(all_window_details: list[tuple[str, pd.DataFrame]],
                           suffix: str = "", save: bool = True):
    """레짐별 성과 비교 그룹 바 차트"""
    regime_data = []
    for name, wd in all_window_details:
        if wd.empty:
            continue
        for regime in ["불장", "하락장", "횡보"]:
            rw = wd[wd["레짐"] == regime]
            if len(rw) > 0:
                regime_data.append({
                    "전략": name, "레짐": regime,
                    "평균수익률": rw["수익률"].mean() * 100,
                    "승률": (rw["수익률"] > 0).mean() * 100,
                })

    if not regime_data:
        return

    df = pd.DataFrame(regime_data)
    regimes = ["불장", "횡보", "하락장"]
    strategies = df["전략"].unique()

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    x = np.arange(len(regimes))
    width = 0.8 / max(len(strategies), 1)
    colors = plt.cm.Set2(np.linspace(0, 1, len(strategies)))

    for idx, strat in enumerate(strategies):
        vals_ret = []
        vals_wr = []
        for regime in regimes:
            row = df[(df["전략"] == strat) & (df["레짐"] == regime)]
            vals_ret.append(row["평균수익률"].values[0] if len(row) > 0 else 0)
            vals_wr.append(row["승률"].values[0] if len(row) > 0 else 0)
        axes[0].bar(x + idx * width, vals_ret, width, label=strat[:12], color=colors[idx])
        axes[1].bar(x + idx * width, vals_wr, width, label=strat[:12], color=colors[idx])

    for ax_i, (ax, title) in enumerate(zip(axes, ["레짐별 평균 수익률 (%)", "레짐별 윈도우 승률 (%)"])):
        ax.set_xticks(x + width * len(strategies) / 2)
        ax.set_xticklabels(regimes)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.legend(fontsize=5, ncol=3)
        ax.grid(True, axis="y", alpha=0.3)
        if ax_i == 0:
            ax.axhline(y=0, color="black", linewidth=0.5)

    suptitle = "시장 레짐별 전략 성과 비교"
    if suffix:
        suptitle += f" (OOS {suffix}일)"
    plt.suptitle(suptitle, fontsize=14, fontweight="bold")
    plt.tight_layout()

    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        fname = f"regime_comparison_{suffix}.png" if suffix else "regime_comparison.png"
        fig.savefig(os.path.join(RESULTS_DIR, fname), dpi=150)
    plt.close(fig)


def plot_period_comparison(period_summaries: dict[int, pd.DataFrame], save: bool = True):
    """
    OOS 기간별 최적 전략 비교 차트

    Args:
        period_summaries: {oos_days: summary_df, ...}
    """
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    metrics_to_plot = [
        ("샤프비율", "샤프 비율 (높을수록 좋음)"),
        ("누적수익률", "누적 수익률"),
        ("MDD", "최대 낙폭 (MDD)"),
        ("칼마비율", "칼마 비율 (수익/리스크)"),
    ]

    for ax, (metric, title) in zip(axes.flatten(), metrics_to_plot):
        periods = sorted(period_summaries.keys())
        x = np.arange(len(periods))

        # 각 기간에서 TOP 5 전략 추출
        all_strategies = set()
        for p in periods:
            df = period_summaries[p]
            strats = df[~df["전략"].str.contains("B&H")].nlargest(5, "샤프비율")["전략"].values
            all_strategies.update(strats)

        # 상위 전략들의 기간별 지표
        colors = plt.cm.tab10(np.linspace(0, 1, min(10, len(all_strategies))))
        width = 0.8 / max(len(all_strategies), 1)

        for idx, strat in enumerate(sorted(all_strategies)):
            vals = []
            for p in periods:
                df = period_summaries[p]
                row = df[df["전략"] == strat]
                vals.append(row[metric].values[0] if len(row) > 0 else 0)
            ax.bar(x + idx * width, vals, width, label=strat[:15],
                   color=colors[idx % len(colors)], alpha=0.8)

        ax.set_xticks(x + width * len(all_strategies) / 2)
        ax.set_xticklabels([f"{p}일" for p in periods])
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.legend(fontsize=5, ncol=2)
        ax.grid(True, axis="y", alpha=0.3)
        if metric != "MDD":
            ax.axhline(y=0, color="black", linewidth=0.5)

    plt.suptitle("OOS 기간별 전략 성과 비교", fontsize=16, fontweight="bold")
    plt.tight_layout()

    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        fig.savefig(os.path.join(RESULTS_DIR, "period_comparison.png"), dpi=150)
        print(f"  → OOS 기간별 비교 차트 저장 완료")
    plt.close(fig)


def plot_strategy_type_summary(type_summaries: dict[str, dict], save: bool = True):
    """
    전략 유형별 × OOS 기간별 평균 성과 히트맵
    """
    rows = []
    for (stype, period), metrics in type_summaries.items():
        rows.append({
            "전략유형": stype,
            "OOS기간": f"{period}일",
            "평균샤프": metrics["avg_sharpe"],
            "평균수익률": metrics["avg_return"],
            "평균MDD": metrics["avg_mdd"],
        })

    if not rows:
        return

    df = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 3, figsize=(20, 6))

    for ax, (col, title) in zip(axes, [
        ("평균샤프", "평균 샤프 비율"),
        ("평균수익률", "평균 누적 수익률"),
        ("평균MDD", "평균 MDD"),
    ]):
        pivot = df.pivot(index="전략유형", columns="OOS기간", values=col)
        # 기간 순서 정렬
        period_order = [f"{p}일" for p in [15, 30, 45, 60] if f"{p}일" in pivot.columns]
        pivot = pivot[period_order]

        cmap = "RdYlGn" if col != "평균MDD" else "RdYlGn_r"
        im = ax.imshow(pivot.values, cmap=cmap, aspect="auto")

        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index, fontsize=8)
        ax.set_title(title, fontsize=12, fontweight="bold")

        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                val = pivot.iloc[i, j]
                text = f"{val:.2%}" if abs(val) < 10 else f"{val:.2f}"
                ax.text(j, i, text, ha="center", va="center", fontsize=8, color="black")

        plt.colorbar(im, ax=ax, shrink=0.8)

    plt.suptitle("전략 유형별 × OOS 기간별 성과 요약", fontsize=14, fontweight="bold")
    plt.tight_layout()

    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        fig.savefig(os.path.join(RESULTS_DIR, "strategy_type_summary.png"), dpi=150)
        print(f"  → 전략 유형별 요약 차트 저장 완료")
    plt.close(fig)
