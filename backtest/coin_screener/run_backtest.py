"""
backtest/coin_screener/run_backtest.py - 코인 선별 전략 백테스팅 실행 진입점 (CLI)

4가지 코인 선별 전략을 동일 조건으로 백테스팅하고 비교 리포트를 생성합니다.

실행 방법:
    # 프로젝트 루트에서 실행
    python -m backtest.coin_screener.run_backtest

    # 파라미터 지정
    python -m backtest.coin_screener.run_backtest --days 60 --top-n 5 --rebalance 3

    # 단일 전략만 테스트
    python -m backtest.coin_screener.run_backtest --strategies momentum
"""
import sys
import os
import argparse

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from backtest.coin_screener.data_collector import DataCollector
from backtest.coin_screener.backtest_engine import ScreenerBacktestEngine
from backtest.coin_screener.report_generator import ReportGenerator
from backtest.coin_screener.strategies.momentum_screener import MomentumScreener
from backtest.coin_screener.strategies.volume_screener import VolumeScreener
from backtest.coin_screener.strategies.mean_reversion_screener import MeanReversionScreener
from backtest.coin_screener.strategies.composite_screener import CompositeScreener


# 전략 이름 → 클래스 매핑
STRATEGY_MAP = {
    "momentum": MomentumScreener,
    "volume": VolumeScreener,
    "meanrev": MeanReversionScreener,
    "composite": CompositeScreener,
}


def parse_args():
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="코인 선별 전략 백테스팅 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python -m backtest.coin_screener.run_backtest
  python -m backtest.coin_screener.run_backtest --days 90 --top-n 3
  python -m backtest.coin_screener.run_backtest --strategies momentum,composite
  python -m backtest.coin_screener.run_backtest --save-csv --send-telegram --save-db
        """,
    )
    parser.add_argument("--days", type=int, default=60,
                        help="백테스트 기간 일수 (기본: 60)")
    parser.add_argument("--top-n", type=int, default=5,
                        help="선별 코인 수 (기본: 5)")
    parser.add_argument("--rebalance", type=int, default=3,
                        help="리밸런싱 주기 일수 (기본: 3)")
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="초기 자본금 (기본: 1000000)")
    parser.add_argument("--fee", type=float, default=0.0005,
                        help="편도 수수료율 (기본: 0.0005)")
    parser.add_argument("--strategies", type=str, default="momentum,volume,meanrev,composite",
                        help="실행할 전략 (콤마 구분, 기본: 전체)")
    parser.add_argument("--save-csv", action="store_true",
                        help="CSV 저장 여부")
    parser.add_argument("--send-telegram", action="store_true",
                        help="텔레그램 전송 여부")
    parser.add_argument("--save-db", action="store_true",
                        help="Supabase 저장 여부")
    parser.add_argument("--cache-dir", type=str, default=None,
                        help="데이터 캐시 디렉토리 (기본: backtest/coin_screener/cache/)")
    parser.add_argument("--min-volume", type=float, default=1e8,
                        help="최소 일평균 거래대금 (기본: 1억원)")
    return parser.parse_args()


def create_screeners(strategy_names: list, top_n: int) -> list:
    """
    전략 이름 리스트로부터 스크리너 객체를 생성합니다.

    매개변수:
        strategy_names: 전략 이름 리스트 (예: ["momentum", "volume"])
        top_n         : 선별할 코인 수
    반환값:
        스크리너 객체 리스트
    """
    screeners = []
    for name in strategy_names:
        name = name.strip().lower()
        if name not in STRATEGY_MAP:
            logger.warning(f"알 수 없는 전략: {name} (가능한 값: {list(STRATEGY_MAP.keys())})")
            continue
        screener = STRATEGY_MAP[name](top_n=top_n)
        screeners.append(screener)
        logger.info(f"전략 로드: {screener.name}")
    return screeners


def main():
    """메인 실행 함수"""
    args = parse_args()

    logger.info("=" * 50)
    logger.info("코인 선별 전략 백테스팅 시작")
    logger.info("=" * 50)

    config = {
        "days": args.days,
        "top_n": args.top_n,
        "rebalance_days": args.rebalance,
        "initial_capital": args.capital,
        "fee_rate": args.fee,
    }

    # 1. 전략 생성
    strategy_names = args.strategies.split(",")
    screeners = create_screeners(strategy_names, args.top_n)
    if not screeners:
        logger.error("실행할 전략이 없습니다.")
        return

    # 2. 데이터 수집
    logger.info(f"데이터 수집 시작 (최근 {args.days}일)...")
    collector = DataCollector(
        cache_dir=args.cache_dir,
        min_volume_krw=args.min_volume,
    )

    try:
        all_data = collector.collect_all(days=args.days + 30)  # 워밍업용 추가 데이터
    except Exception as e:
        logger.error(f"데이터 수집 실패: {e}")
        if args.send_telegram:
            try:
                from notify.telegram_bot import send_message
                send_message(f"코인 스크리너 백테스팅 실패: {e}")
            except Exception:
                pass
        return

    if not all_data:
        logger.error("수집된 데이터가 없습니다.")
        return

    total_coins = len(all_data)
    logger.info(f"수집 완료: {total_coins}개 코인")

    # 3. 각 전략 백테스팅 실행
    results = []
    for screener in screeners:
        logger.info(f"\n전략 실행 중: {screener.name}")
        engine = ScreenerBacktestEngine(
            screener=screener,
            all_data=all_data,
            initial_capital=args.capital,
            rebalance_days=args.rebalance,
            fee_rate=args.fee,
        )
        result = engine.run()
        results.append(result)

    # 4. 리포트 생성
    reporter = ReportGenerator(results, config)

    # 4-1. 콘솔 출력
    reporter.print_console_report(total_coins=total_coins)

    # 4-2. 차트 저장
    chart_path = reporter.save_chart()
    if chart_path:
        print(f"차트 저장: {chart_path}")

    # 4-3. CSV 저장
    if args.save_csv:
        csv_path = reporter.save_csv()
        if csv_path:
            print(f"CSV 저장: {csv_path}")

    # 4-4. DB 저장
    if args.save_db:
        reporter.save_to_db()
        print("DB 저장: Supabase backtest_results 테이블 저장 완료")

    # 4-5. 텔레그램 전송
    if args.send_telegram:
        reporter.send_telegram(chart_path=chart_path)
        print("텔레그램 전송 완료")

    print("=" * 50)
    logger.info("모든 백테스팅 완료!")


if __name__ == "__main__":
    main()
