"""
backtest/report.py - 백테스팅 결과 시각화 및 리포트 전송

BacktestResult 객체를 받아:
  1. 누적 수익률 + 낙폭 그래프를 PNG로 저장
  2. 결과 요약을 텔레그램으로 전송 (그래프 이미지 포함)
  3. Supabase backtest_results 테이블에 결과 저장
"""
import os
import matplotlib
matplotlib.use("Agg")  # 화면 없이 파일로만 저장 (서버/헤드리스 환경 대응)
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
from loguru import logger


def _setup_korean_font():
    """
    Windows에서 한글이 깨지지 않도록 폰트를 설정합니다.
    'Malgun Gothic'(맑은 고딕)은 Windows 기본 내장 폰트입니다.
    """
    # Windows 기본 한글 폰트
    font_candidates = ["Malgun Gothic", "NanumGothic", "AppleGothic", "DejaVu Sans"]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in font_candidates:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    plt.rcParams["axes.unicode_minus"] = False  # 마이너스 기호 깨짐 방지


class BacktestReporter:
    """
    백테스팅 결과를 리포팅하는 클래스.
    """

    def __init__(self, result, strategy_name: str, ticker: str,
                 start_date: str, end_date: str):
        """
        매개변수:
            result       : BacktestEngine.run()이 반환한 BacktestResult 객체
            strategy_name: 전략 이름 (예: "변동성 돌파 K=0.5")
            ticker       : 테스트한 코인 티커 (예: "KRW-BTC")
            start_date   : 백테스팅 시작일 (예: "2023-01-01")
            end_date     : 백테스팅 종료일 (예: "2024-12-31")
        """
        self.result        = result
        self.strategy_name = strategy_name
        self.ticker        = ticker
        self.start_date    = start_date
        self.end_date      = end_date

    def save_chart(self, output_path: str = None) -> str:
        """
        누적 수익률 + 낙폭 그래프를 PNG 파일로 저장합니다.

        매개변수:
            output_path: 저장 경로 (None이면 자동 생성)
        반환값:
            저장된 파일 경로, 실패 시 None
        """
        _setup_korean_font()

        if output_path is None:
            # logs/ 폴더에 저장 (없으면 생성)
            os.makedirs("logs", exist_ok=True)
            safe_name = self.strategy_name.replace(" ", "_").replace("=", "").replace("/", "-")
            output_path = f"logs/backtest_{safe_name}_{self.ticker}_{self.end_date}.png"

        values = self.result.portfolio_values
        dates  = self.result.dates

        if not values:
            logger.warning("포트폴리오 데이터가 없어 그래프를 생성할 수 없습니다.")
            return None

        try:
            initial = self.result.initial_capital
            # 누적 수익률 (%)
            returns = [(v / initial - 1) * 100 for v in values]

            # 낙폭 계산
            values_s = pd.Series(values)
            peak      = values_s.cummax()
            drawdown  = ((values_s - peak) / peak * 100).tolist()

            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            fig.suptitle(
                f"{self.strategy_name} | {self.ticker} "
                f"({self.start_date} ~ {self.end_date})",
                fontsize=14, fontweight="bold"
            )

            x = range(len(returns))

            # ── 상단: 누적 수익률 ──
            axes[0].plot(x, returns, color="royalblue", linewidth=1.5, label="수익률")
            axes[0].axhline(0, color="gray", linestyle="--", linewidth=0.8)
            axes[0].fill_between(
                x, returns, 0,
                where=[r >= 0 for r in returns],
                color="lightblue", alpha=0.4, label="수익 구간"
            )
            axes[0].fill_between(
                x, returns, 0,
                where=[r < 0 for r in returns],
                color="lightcoral", alpha=0.4, label="손실 구간"
            )
            axes[0].set_ylabel("누적 수익률 (%)")
            axes[0].legend(loc="upper left", fontsize=9)
            axes[0].grid(True, alpha=0.3)

            # 성능 지표 텍스트 박스
            s = self.result.summary()
            stats_text = (
                f"누적수익: {s['cumulative_return']:+.1f}%  "
                f"MDD: {s['mdd']:.1f}%  "
                f"승률: {s['win_rate']:.1f}%  "
                f"샤프: {s['sharpe_ratio']:.2f}"
            )
            axes[0].text(
                0.01, 0.02, stats_text,
                transform=axes[0].transAxes,
                fontsize=9, color="dimgray",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7)
            )

            # ── 하단: 낙폭 ──
            axes[1].fill_between(x, drawdown, 0, color="crimson", alpha=0.5, label="낙폭")
            axes[1].set_ylabel("낙폭 (%)")
            axes[1].set_xlabel("거래일")
            axes[1].legend(loc="lower left", fontsize=9)
            axes[1].grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(output_path, dpi=150, bbox_inches="tight")
            plt.close()
            logger.info(f"그래프 저장 완료: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"그래프 생성 실패: {e}")
            return None

    def send_to_telegram(self, chart_path: str = None):
        """
        백테스팅 결과 요약을 텔레그램으로 전송합니다.
        chart_path가 있으면 그래프 이미지도 함께 전송합니다.
        """
        from notify.telegram_bot import send_report, send_photo

        s = self.result.summary()
        sections = [
            {
                "header": "전략 정보",
                "body"  : (
                    f"전략: {self.strategy_name}\n"
                    f"코인: {self.ticker}\n"
                    f"기간: {self.start_date} ~ {self.end_date}"
                ),
            },
            {
                "header": "성능 지표",
                "body"  : (
                    f"누적 수익률: {s['cumulative_return']:+.2f}%\n"
                    f"최대 낙폭(MDD): {s['mdd']:.2f}%\n"
                    f"승률: {s['win_rate']:.1f}%\n"
                    f"샤프 지수: {s['sharpe_ratio']:.2f}\n"
                    f"총 거래: {s['total_trades']}건\n"
                    f"평균 보유: {s['avg_hold_days']:.1f}일"
                ),
            },
        ]
        send_report(f"백테스팅 결과 | {self.strategy_name}", sections)

        # 그래프 이미지 전송
        if chart_path and os.path.exists(chart_path):
            send_photo(
                chart_path,
                caption=f"{self.strategy_name} | {self.ticker} 수익률 차트"
            )
            logger.info("텔레그램 그래프 전송 완료")

    def save_to_db(self):
        """
        백테스팅 결과를 Supabase backtest_results 테이블에 저장합니다.
        (Supabase에 backtest_results 테이블이 생성되어 있어야 합니다)
        """
        from src.database.supabase_client import get_supabase_client
        from datetime import datetime

        client = get_supabase_client()
        if not client:
            return

        s = self.result.summary()
        data = {
            "strategy_name": self.strategy_name,
            "ticker"       : self.ticker,
            "start_date"   : self.start_date,
            "end_date"     : self.end_date,
            "total_return" : round(s["cumulative_return"], 4),
            "mdd"          : round(s["mdd"], 4),
            "win_rate"     : round(s["win_rate"], 4),
            "sharpe_ratio" : round(s["sharpe_ratio"], 4),
            "total_trades" : s["total_trades"],
            "avg_hold_days": round(s["avg_hold_days"], 2),
            "created_at"   : datetime.now().isoformat(),
        }
        try:
            client.table("backtest_results").insert(data).execute()
            logger.info(f"DB 저장 완료: {self.strategy_name} | {self.ticker}")
        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")
