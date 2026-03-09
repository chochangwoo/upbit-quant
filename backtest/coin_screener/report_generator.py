"""
backtest/coin_screener/report_generator.py - 비교 리포트 생성

4가지 전략의 백테스팅 결과를 비교하여:
1. 콘솔 요약 리포트 출력
2. 누적 수익률 비교 차트 PNG 저장
3. CSV 내보내기
4. Supabase 저장
5. 텔레그램 전송
"""
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
from loguru import logger


def _setup_korean_font():
    """Windows에서 한글 폰트를 설정합니다."""
    font_candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in font_candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False


class ReportGenerator:
    """
    코인 선별 전략 비교 리포트 생성기.
    """

    def __init__(self, results: list, config: dict):
        """
        매개변수:
            results: ScreenerBacktestResult 객체 리스트
            config : 백테스팅 설정 딕셔너리
        """
        self.results = results
        self.config = config
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "results"
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def print_console_report(self, total_coins: int = 0):
        """
        콘솔에 전략별 비교 결과를 표 형태로 출력합니다.

        매개변수:
            total_coins: 수집된 코인 수 (리포트 출력용)
        """
        if not self.results:
            print("비교할 결과가 없습니다.")
            return

        # 기간 정보
        first = self.results[0]
        start = str(first.dates[0].date()) if first.dates else "N/A"
        end = str(first.dates[-1].date()) if first.dates else "N/A"
        days = len(first.dates)

        print("\n" + "=" * 66)
        print("        코인 선별 전략 백테스팅 결과 비교")
        print("=" * 66)
        print(f"기간: {start} ~ {end} ({days}일)")
        print(f"선별 코인 수: {self.config.get('top_n', 5)}개 | "
              f"리밸런싱: {self.config.get('rebalance_days', 3)}일 | "
              f"초기자본: {self.config.get('initial_capital', 1_000_000):,.0f}원")
        if total_coins:
            print(f"대상 코인: Upbit KRW 마켓 전체 (수집 완료: {total_coins}개)")
        print("=" * 66)
        print()
        print(f" {'순위':>4}  {'전략':<18} {'수익률':>8}  {'MDD':>8}  "
              f"{'샤프':>6}  {'승률':>6}  {'거래수':>6}")
        print("─" * 66)

        # 수익률 기준 정렬
        sorted_results = sorted(
            self.results, key=lambda r: r.total_return(), reverse=True
        )

        for rank, result in enumerate(sorted_results, 1):
            s = result.summary()
            ret_str = f"{s['total_return']:+.2f}%"
            mdd_str = f"{s['mdd']:.2f}%"
            sharpe_str = f"{s['sharpe_ratio']:.2f}"
            wr_str = f"{s['win_rate']:.1f}%"
            trades_str = f"{s['total_trades']}"
            print(f" {rank:>3}위  {s['strategy_name']:<18} {ret_str:>8}  "
                  f"{mdd_str:>8}  {sharpe_str:>6}  {wr_str:>6}  {trades_str:>6}")

        print("─" * 66)

        best = sorted_results[0]
        print(f"\n최우수 전략: {best.strategy_name} ({best.total_return():+.2f}%)")
        print()

    def save_chart(self) -> str:
        """
        4가지 전략의 누적 수익률 곡선을 하나의 차트에 저장합니다.

        반환값:
            저장된 PNG 파일 경로
        """
        _setup_korean_font()

        fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})

        date_str = datetime.now().strftime("%Y%m%d")

        # 상단: 누적 수익률 비교
        for result in self.results:
            if not result.equity_curve:
                continue
            initial = result.initial_capital
            returns = [(v / initial - 1) * 100 for v in result.equity_curve]
            axes[0].plot(result.dates, returns, linewidth=1.5, label=result.strategy_name)

        axes[0].axhline(0, color="gray", linestyle="--", linewidth=0.8)
        axes[0].set_title("코인 선별 전략 누적 수익률 비교", fontsize=14, fontweight="bold")
        axes[0].set_ylabel("누적 수익률 (%)")
        axes[0].legend(loc="upper left", fontsize=9)
        axes[0].grid(True, alpha=0.3)

        # 하단: MDD 비교
        for result in self.results:
            if not result.equity_curve:
                continue
            values = pd.Series(result.equity_curve)
            peak = values.cummax()
            drawdown = ((values - peak) / peak * 100).tolist()
            axes[1].plot(result.dates, drawdown, linewidth=1.2, label=result.strategy_name)

        axes[1].set_ylabel("낙폭 (%)")
        axes[1].set_xlabel("날짜")
        axes[1].legend(loc="lower left", fontsize=8)
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()
        output_path = os.path.join(
            self.output_dir, f"coin_screening_comparison_{date_str}.png"
        )
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        logger.info(f"차트 저장: {output_path}")
        return output_path

    def save_csv(self) -> str:
        """
        전략별 일별 equity curve를 CSV로 저장합니다.

        반환값:
            저장된 CSV 파일 경로
        """
        date_str = datetime.now().strftime("%Y%m%d")
        data = {}

        for result in self.results:
            if result.dates and result.equity_curve:
                data[result.strategy_name] = pd.Series(
                    result.equity_curve, index=result.dates
                )

        if not data:
            logger.warning("CSV로 저장할 데이터가 없습니다.")
            return None

        df = pd.DataFrame(data)
        output_path = os.path.join(
            self.output_dir, f"equity_curves_{date_str}.csv"
        )
        df.to_csv(output_path)
        logger.info(f"CSV 저장: {output_path}")
        return output_path

    def save_to_db(self):
        """전략별 결과를 Supabase backtest_results 테이블에 저장합니다."""
        try:
            from src.database.supabase_client import get_supabase_client
        except ImportError:
            logger.warning("Supabase 클라이언트를 임포트할 수 없습니다.")
            return

        client = get_supabase_client()
        if not client:
            return

        for result in self.results:
            s = result.summary()
            start = str(result.dates[0].date()) if result.dates else ""
            end = str(result.dates[-1].date()) if result.dates else ""

            data = {
                "strategy_name": s["strategy_name"],
                "ticker": "KRW-ALL",  # 전체 코인 대상
                "start_date": start,
                "end_date": end,
                "total_return": round(s["total_return"], 4),
                "mdd": round(s["mdd"], 4),
                "win_rate": round(s["win_rate"], 4),
                "sharpe_ratio": round(s["sharpe_ratio"], 4),
                "total_trades": s["total_trades"],
                "avg_hold_days": self.config.get("rebalance_days", 3),
                "created_at": datetime.now().isoformat(),
            }
            try:
                client.table("backtest_results").insert(data).execute()
                logger.info(f"DB 저장 완료: {s['strategy_name']}")
            except Exception as e:
                logger.error(f"DB 저장 실패 ({s['strategy_name']}): {e}")

    def send_telegram(self, chart_path: str = None):
        """비교 결과 요약 + 그래프 이미지를 텔레그램으로 전송합니다."""
        try:
            from notify.telegram_bot import send_message, send_photo
        except ImportError:
            logger.warning("텔레그램 봇을 임포트할 수 없습니다.")
            return

        sorted_results = sorted(
            self.results, key=lambda r: r.total_return(), reverse=True
        )

        lines = ["<b>코인 선별 전략 백테스팅 결과</b>", "─" * 20, ""]

        for rank, result in enumerate(sorted_results, 1):
            s = result.summary()
            lines.append(
                f"{rank}위 {s['strategy_name']}: "
                f"{s['total_return']:+.2f}% | "
                f"MDD {s['mdd']:.2f}% | "
                f"샤프 {s['sharpe_ratio']:.2f}"
            )

        best = sorted_results[0]
        lines.append(f"\n최우수: {best.strategy_name} ({best.total_return():+.2f}%)")

        send_message("\n".join(lines))

        if chart_path and os.path.exists(chart_path):
            send_photo(chart_path, caption="코인 선별 전략 비교 차트")
            logger.info("텔레그램 차트 전송 완료")
