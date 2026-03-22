"""
backtest/report.py - 백테스트 결과 시각화 및 리포트

5종류의 차트를 생성합니다:
  1. 누적 수익률 곡선 (전략 + 벤치마크)
  2. 윈도우별 수익률 바 차트 (레짐별 색상)
  3. 성과 지표 히트맵
  4. 레짐별 성과 비교
  5. 몬테카를로 분포 + 부트스트랩 신뢰구간 차트

추가로 텔레그램 전송, Supabase DB 저장 기능을 제공합니다.
"""

import os

import matplotlib
matplotlib.use("Agg")  # 화면 없이 파일로만 저장
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd
from loguru import logger


# 한글 폰트 설정 (Windows)
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _ensure_dir():
    """결과 저장 폴더 생성"""
    os.makedirs(RESULTS_DIR, exist_ok=True)


# ─────────────────────────────────────────
# 1. 누적 수익률 곡선
# ─────────────────────────────────────────

def plot_equity_curves(results: list, benchmarks: dict):
    """
    전략별 누적 수익률 곡선을 그립니다.

    매개변수:
        results   : 백테스트 결과 리스트 [{strategy_name, equity_curve}, ...]
        benchmarks: {"BTC B&H": series, "동일비중 B&H": series}
    """
    _ensure_dir()
    fig, ax = plt.subplots(figsize=(14, 7))

    # 벤치마크 (점선)
    for name, eq in benchmarks.items():
        ax.plot(eq.index, (eq - 1) * 100, "--", linewidth=1.5, alpha=0.7, label=name)

    # 전략별 곡선
    for r in results:
        eq = r["equity_curve"]
        ax.plot(eq.index, (eq - 1) * 100, linewidth=1.2, label=r["strategy_name"])

    ax.set_title("전략별 누적 수익률 비교", fontsize=16, fontweight="bold")
    ax.set_xlabel("날짜")
    ax.set_ylabel("수익률 (%)")
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="black", linewidth=0.5)

    plt.tight_layout()
    fig.savefig(os.path.join(RESULTS_DIR, "equity_curves.png"), dpi=150)
    logger.info("  -> 누적 수익률 차트 저장 완료")
    plt.close(fig)


# ─────────────────────────────────────────
# 2. 윈도우별 수익률 바 차트
# ─────────────────────────────────────────

def plot_window_returns(window_details: pd.DataFrame, strategy_name: str):
    """
    윈도우별 OOS 수익률을 바 차트로 그립니다.
    레짐별 색상 구분: 불장=녹색, 하락장=빨강, 횡보=회색
    """
    if window_details.empty:
        return

    _ensure_dir()
    fig, ax = plt.subplots(figsize=(14, 5))

    colors_map = {"불장": "#2ECC71", "하락장": "#E74C3C", "횡보": "#95A5A6"}
    colors = [colors_map.get(r, "#95A5A6") for r in window_details["레짐"]]

    ax.bar(
        range(len(window_details)),
        window_details["수익률"] * 100,
        color=colors,
        edgecolor="white",
        linewidth=0.5,
    )

    ax.set_title(f"{strategy_name} - 윈도우별 OOS 수익률", fontsize=14, fontweight="bold")
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
    safe_name = strategy_name.replace("(", "").replace(")", "").replace("/", "_")
    fig.savefig(os.path.join(RESULTS_DIR, f"windows_{safe_name}.png"), dpi=150)
    plt.close(fig)


# ─────────────────────────────────────────
# 3. 성과 지표 히트맵
# ─────────────────────────────────────────

def plot_metrics_heatmap(summary_df: pd.DataFrame):
    """전략 간 성과 지표를 히트맵으로 비교합니다."""
    if summary_df.empty:
        return

    _ensure_dir()
    metric_cols = ["누적수익률", "연환산수익률", "샤프비율", "소르티노비율", "MDD", "칼마비율", "일별승률"]
    available = [c for c in metric_cols if c in summary_df.columns]
    if not available:
        return

    data = summary_df.set_index("전략")[available].astype(float)

    fig, ax = plt.subplots(figsize=(12, max(4, len(data) * 0.5)))

    # 정규화 (열별 0~1)
    norm_data = data.copy()
    for col in norm_data.columns:
        col_min = norm_data[col].min()
        col_max = norm_data[col].max()
        if col_max != col_min:
            if col == "MDD":  # MDD는 작을수록(덜 음수) 좋으므로 반전
                norm_data[col] = 1 - (norm_data[col] - col_min) / (col_max - col_min)
            else:
                norm_data[col] = (norm_data[col] - col_min) / (col_max - col_min)
        else:
            norm_data[col] = 0.5

    im = ax.imshow(norm_data.values, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(available)))
    ax.set_xticklabels(available, rotation=45, ha="right")
    ax.set_yticks(range(len(data)))
    ax.set_yticklabels(data.index, fontsize=8)

    # 셀에 실제 값 표시
    for i in range(len(data)):
        for j in range(len(available)):
            val = data.iloc[i, j]
            text = f"{val:.2%}" if abs(val) < 10 else f"{val:.2f}"
            ax.text(j, i, text, ha="center", va="center", fontsize=7,
                    color="black" if 0.3 < norm_data.iloc[i, j] < 0.7 else "white")

    ax.set_title("전략별 성과 지표 비교 (히트맵)", fontsize=14, fontweight="bold")
    plt.colorbar(im, ax=ax, shrink=0.8, label="상대 성과 (높을수록 좋음)")
    plt.tight_layout()

    fig.savefig(os.path.join(RESULTS_DIR, "metrics_heatmap.png"), dpi=150)
    logger.info("  -> 성과 히트맵 저장 완료")
    plt.close(fig)


# ─────────────────────────────────────────
# 4. 레짐별 성과 비교
# ─────────────────────────────────────────

def plot_regime_comparison(all_window_details: list):
    """레짐별 평균 수익률 및 승률을 그룹 바 차트로 비교합니다."""
    regime_data = []
    for name, wd in all_window_details:
        if wd.empty:
            continue
        for regime in ["불장", "하락장", "횡보"]:
            regime_windows = wd[wd["레짐"] == regime]
            if len(regime_windows) > 0:
                regime_data.append({
                    "전략": name,
                    "레짐": regime,
                    "평균수익률": regime_windows["수익률"].mean() * 100,
                    "승률": (regime_windows["수익률"] > 0).mean() * 100,
                })

    if not regime_data:
        return

    _ensure_dir()
    df = pd.DataFrame(regime_data)
    regimes = ["불장", "횡보", "하락장"]
    strategies = df["전략"].unique()

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    x = np.arange(len(regimes))
    width = 0.8 / max(len(strategies), 1)
    colors = plt.cm.Set2(np.linspace(0, 1, len(strategies)))

    # 평균 수익률
    for idx, strat in enumerate(strategies):
        vals = []
        for regime in regimes:
            row = df[(df["전략"] == strat) & (df["레짐"] == regime)]
            vals.append(row["평균수익률"].values[0] if len(row) > 0 else 0)
        axes[0].bar(x + idx * width, vals, width, label=strat[:15], color=colors[idx])

    axes[0].set_xticks(x + width * len(strategies) / 2)
    axes[0].set_xticklabels(regimes)
    axes[0].set_title("레짐별 평균 수익률 (%)", fontsize=12, fontweight="bold")
    axes[0].legend(fontsize=6, ncol=2)
    axes[0].grid(True, axis="y", alpha=0.3)
    axes[0].axhline(y=0, color="black", linewidth=0.5)

    # 승률
    for idx, strat in enumerate(strategies):
        vals = []
        for regime in regimes:
            row = df[(df["전략"] == strat) & (df["레짐"] == regime)]
            vals.append(row["승률"].values[0] if len(row) > 0 else 0)
        axes[1].bar(x + idx * width, vals, width, label=strat[:15], color=colors[idx])

    axes[1].set_xticks(x + width * len(strategies) / 2)
    axes[1].set_xticklabels(regimes)
    axes[1].set_title("레짐별 윈도우 승률 (%)", fontsize=12, fontweight="bold")
    axes[1].legend(fontsize=6, ncol=2)
    axes[1].grid(True, axis="y", alpha=0.3)

    plt.suptitle("시장 레짐별 전략 성과 비교", fontsize=14, fontweight="bold")
    plt.tight_layout()

    fig.savefig(os.path.join(RESULTS_DIR, "regime_comparison.png"), dpi=150)
    logger.info("  -> 레짐별 비교 차트 저장 완료")
    plt.close(fig)


# ─────────────────────────────────────────
# 5. 검증 결과 차트 (몬테카를로 + 부트스트랩)
# ─────────────────────────────────────────

def plot_validation_chart(validation_result: dict, strategy_name: str):
    """
    몬테카를로 분포와 부트스트랩 신뢰구간을 시각화합니다.

    왼쪽: 무작위 시뮬레이션 분포 히스토그램 + 실제 수익률 위치
    오른쪽: 주요 지표의 95% 신뢰구간 바 차트
    """
    _ensure_dir()

    mc = validation_result["monte_carlo"]
    bs = validation_result["bootstrap"]
    grade = validation_result["overall_grade"]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # ── 왼쪽: 몬테카를로 분포 ──
    sim_returns = mc["simulated_returns"]
    if len(sim_returns) > 0:
        axes[0].hist(sim_returns * 100, bins=50, alpha=0.7, color="#3498DB",
                     edgecolor="white", label="무작위 시뮬레이션")
        axes[0].axvline(mc["actual_return"] * 100, color="#E74C3C", linewidth=2,
                        linestyle="--", label=f"실제: {mc['actual_return']:+.2%}")
        axes[0].axvline(mc["mean_random"] * 100, color="#95A5A6", linewidth=1.5,
                        linestyle=":", label=f"무작위 평균: {mc['mean_random']:+.2%}")

        axes[0].set_title(
            f"몬테카를로 검증 (p={mc['p_value']:.3f})",
            fontsize=12, fontweight="bold"
        )
        axes[0].set_xlabel("수익률 (%)")
        axes[0].set_ylabel("빈도")
        axes[0].legend(fontsize=9)
        axes[0].grid(True, alpha=0.3)

        # 유의미 여부 표시
        sig_text = "유의미 (p < 0.05)" if mc["is_significant"] else "비유의미 (p >= 0.05)"
        sig_color = "#2ECC71" if mc["is_significant"] else "#E74C3C"
        axes[0].text(0.02, 0.95, sig_text, transform=axes[0].transAxes,
                     fontsize=10, color=sig_color, fontweight="bold",
                     verticalalignment="top",
                     bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    # ── 오른쪽: 부트스트랩 신뢰구간 ──
    metrics = ["cumulative_return", "sharpe_ratio", "annual_return"]
    labels = ["누적수익률", "샤프비율", "연환산수익률"]
    y_pos = range(len(metrics))

    for i, (metric, label) in enumerate(zip(metrics, labels)):
        ci = bs[metric]
        point = ci["point"]
        lower = ci["ci_lower"]
        upper = ci["ci_upper"]

        # 수익률 계열은 % 표시
        if metric != "sharpe_ratio":
            point *= 100
            lower *= 100
            upper *= 100

        axes[1].barh(i, point, height=0.5, color="#3498DB", alpha=0.7)
        axes[1].plot([lower, upper], [i, i], "|-", color="#E74C3C",
                     linewidth=2, markersize=10, label="95% CI" if i == 0 else "")

        # 값 텍스트
        fmt = ".1f" if metric != "sharpe_ratio" else ".2f"
        unit = "%" if metric != "sharpe_ratio" else ""
        axes[1].text(max(point, upper) + 0.5, i,
                     f"{point:{fmt}}{unit} [{lower:{fmt}} ~ {upper:{fmt}}]",
                     va="center", fontsize=9)

    axes[1].set_yticks(list(y_pos))
    axes[1].set_yticklabels(labels)
    axes[1].set_title("부트스트랩 95% 신뢰구간", fontsize=12, fontweight="bold")
    axes[1].legend(fontsize=9)
    axes[1].grid(True, axis="x", alpha=0.3)
    axes[1].axvline(x=0, color="black", linewidth=0.5)

    # 종합 등급 표시
    fig.suptitle(
        f"{strategy_name} - 통계적 검증 결과 (등급: {grade})",
        fontsize=14, fontweight="bold"
    )
    plt.tight_layout()

    safe_name = strategy_name.replace("(", "").replace(")", "").replace("/", "_")
    fig.savefig(os.path.join(RESULTS_DIR, f"validation_{safe_name}.png"), dpi=150)
    plt.close(fig)


# ─────────────────────────────────────────
# 텔레그램 전송
# ─────────────────────────────────────────

def send_summary_to_telegram(summary_text: str, chart_paths: list = None):
    """
    백테스트 요약 결과를 텔레그램으로 전송합니다.

    매개변수:
        summary_text: 전송할 텍스트
        chart_paths : 전송할 차트 이미지 경로 리스트
    """
    try:
        from src.notifications.telegram_bot import send_message
        send_message(summary_text)
        logger.info("텔레그램 요약 전송 완료")
    except Exception as e:
        logger.warning(f"텔레그램 전송 실패: {e}")


# ─────────────────────────────────────────
# Supabase DB 저장
# ─────────────────────────────────────────

def save_results_to_db(results: list, validation_results: dict):
    """
    백테스트 결과를 Supabase backtest_results 테이블에 저장합니다.

    매개변수:
        results           : 전략별 백테스트 결과 리스트
        validation_results: 전략별 검증 결과 딕셔너리
    """
    try:
        from src.database.supabase_client import get_supabase_client
        from datetime import datetime

        client = get_supabase_client()
        if not client:
            return

        for r in results:
            name = r["strategy_name"]
            metrics = r.get("metrics", {})
            val = validation_results.get(name, {})

            data = {
                "strategy_name": name,
                "ticker": "MULTI_COIN",
                "start_date": str(r["equity_curve"].index[0].date()) if len(r["equity_curve"]) > 0 else "",
                "end_date": str(r["equity_curve"].index[-1].date()) if len(r["equity_curve"]) > 0 else "",
                "total_return": round(metrics.get("누적수익률", 0), 6),
                "mdd": round(metrics.get("MDD", 0), 6),
                "win_rate": round(metrics.get("일별승률", 0), 6),
                "sharpe_ratio": round(metrics.get("샤프비율", 0), 6),
                "total_trades": 0,
                "avg_hold_days": 0,
                "created_at": datetime.now().isoformat(),
            }
            client.table("backtest_results").insert(data).execute()
            logger.info(f"  DB 저장 완료: {name}")

    except Exception as e:
        logger.warning(f"DB 저장 실패: {e}")
