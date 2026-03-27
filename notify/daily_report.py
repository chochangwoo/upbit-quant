"""
notify/daily_report.py - 퀀트 전략 일일 리포트 자동 전송 봇

매일 설정된 시간(기본 오전 8:00)에 텔레그램으로
다음 내용을 자동 전송합니다:
  1. 오늘 적용 중인 전략 설명
  2. 전략 성능 지표 (누적수익률, MDD, 승률, 샤프지수)
  3. 어제 실행된 매매 내역 요약
  4. 오늘 시장 상황 간단 코멘트

실행 방법:
    단독 실행: python -m notify.daily_report
    main.py에 schedule로 통합 예정
"""
import os
import yaml
from datetime import datetime, timedelta
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from notify.telegram_bot import send_report, send_message
from src.database.supabase_client import query_table
from src.api.upbit_client import get_current_price, get_ohlcv


def load_config() -> dict:
    """
    config/settings.yaml에서 리포트 관련 설정값을 읽어옵니다.
    반환값: report 설정 딕셔너리
    """
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.yaml")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("report", {})


def get_yesterday_trades() -> list:
    """
    Supabase DB에서 어제 실행된 매매 내역을 조회합니다.
    반환값: 매매 내역 리스트 (없으면 빈 리스트)
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return query_table(
        "trades",
        filters={
            "and": f"(created_at.gte.{yesterday}T00:00:00,created_at.lte.{yesterday}T23:59:59)",
        },
    )


def calculate_performance_metrics(trades: list) -> dict:
    """
    매매 내역을 기반으로 성능 지표를 계산합니다.

    계산 항목:
        - cumulative_return: 누적 수익률 (%)
        - mdd: 최대 낙폭 - Maximum DrawDown (%)
        - win_rate: 승률 (%)
        - sharpe_ratio: 샤프 지수 (수익률 / 변동성)

    매개변수:
        trades: Supabase trades 테이블에서 가져온 매매 내역 리스트
    반환값:
        성능 지표 딕셔너리
    """
    # TODO: 실제 계산 로직 구현 예정
    # 지금은 더미 데이터 반환 (DB에 충분한 데이터 쌓인 후 구현)
    return {
        "cumulative_return": 0.0,   # 누적 수익률 (%)
        "mdd": 0.0,                 # 최대 낙폭 (%)
        "win_rate": 0.0,            # 승률 (%)
        "sharpe_ratio": 0.0,        # 샤프 지수
    }


def get_market_comment() -> str:
    """
    오늘 시장 상황을 분석해 짧은 코멘트를 생성합니다.

    분석 내용:
        - BTC 전일 대비 등락률
        - 변동성 수준 (전일 고저 차이)
    반환값:
        시장 상황 코멘트 문자열
    """
    # TODO: 더 정교한 시장 분석 로직 구현 예정
    try:
        df = get_ohlcv("KRW-BTC", interval="day", count=2)
        if df is None or len(df) < 2:
            return "시장 데이터를 가져올 수 없습니다."

        yesterday_close = df.iloc[-2]["close"]
        today_open      = df.iloc[-1]["open"]

        # 전일 종가 대비 당일 시가 변화율
        change_rate = (today_open - yesterday_close) / yesterday_close * 100

        if change_rate > 2:
            comment = f"BTC 강세 출발 (+{change_rate:.1f}%). 변동성 돌파 기회 가능성 높습니다."
        elif change_rate < -2:
            comment = f"BTC 약세 출발 ({change_rate:.1f}%). 신중한 접근이 필요합니다."
        else:
            comment = f"BTC 보합 출발 ({change_rate:+.1f}%). 방향성 확인 후 대응하세요."

        return comment
    except Exception as e:
        logger.error(f"시장 코멘트 생성 실패: {e}")
        return "시장 상황 분석 중 오류가 발생했습니다."


def format_trades_summary(trades: list) -> str:
    """
    어제 매매 내역을 보기 좋은 텍스트로 정리합니다.

    매개변수:
        trades: 매매 내역 리스트
    반환값:
        정리된 매매 내역 문자열
    """
    if not trades:
        return "어제 실행된 매매 없음"

    lines = []
    for t in trades:
        side = t.get("side", t.get("trade_type", ""))
        emoji = "매수" if side == "buy" else "매도"
        signal = t.get("signal", "")
        signal_text = f" ({signal})" if signal else ""
        lines.append(
            f"{emoji} {t['ticker']} | "
            f"가격: {float(t['price']):,.0f}원 | "
            f"금액: {float(t['amount']):,.0f}원{signal_text}"
        )
    return "\n".join(lines)


def send_daily_report():
    """
    일일 리포트를 조합하여 텔레그램으로 전송합니다.
    config/settings.yaml의 report 설정을 따릅니다.

    이 함수는 main.py의 스케줄러에 등록하거나 단독 실행합니다.
    """
    logger.info("일일 리포트 생성 시작...")
    today = datetime.now().strftime("%Y년 %m월 %d일")

    # 1. 어제 매매 내역 조회
    trades = get_yesterday_trades()

    # 2. 성능 지표 계산
    metrics = calculate_performance_metrics(trades)

    # 3. 시장 코멘트 생성
    market_comment = get_market_comment()

    # 4. 현재 국면 분석
    regime_text = "분석 불가"
    try:
        df_btc = get_ohlcv("KRW-BTC", interval="day", count=60)
        if df_btc is not None and len(df_btc) >= 50:
            close = df_btc["close"]
            btc_price = close.iloc[-1]
            sma50 = close.rolling(50).mean().iloc[-1]
            mom20 = btc_price / close.iloc[-20] - 1

            if btc_price > sma50 and mom20 > 0.10:
                regime_text = f"상승장 → 거래량 돌파 매수 중"
            elif btc_price < sma50 and mom20 < -0.10:
                regime_text = f"하락장 → 전량 현금 보유"
            else:
                regime_text = f"횡보장 → 거래량 돌파 매수 중"
            regime_text += f"\nBTC: {btc_price:,.0f}원 | SMA50: {sma50:,.0f}원 | 20일 모멘텀: {mom20:+.1%}"
    except Exception:
        pass

    # 5. 리포트 섹션 조합
    sections = [
        {
            "header": "📌 오늘의 전략",
            "body": (
                "적응형 거래량돌파 전략\n"
                "→ 상승장/횡보장: 거래량 돌파 상위 5개 코인 매수\n"
                "→ 하락장: 전량 현금 보유 (자동 전환)\n"
                "→ 리밸런싱 주기: 3일"
            ),
        },
        {
            "header": "📈 현재 시장 국면",
            "body": regime_text,
        },
        {
            "header": "📊 전략 성능 지표",
            "body": (
                f"누적 수익률: {metrics['cumulative_return']:+.2f}%\n"
                f"최대 낙폭(MDD): {metrics['mdd']:.2f}%\n"
                f"승률: {metrics['win_rate']:.1f}%\n"
                f"샤프 지수: {metrics['sharpe_ratio']:.2f}"
            ),
        },
        {
            "header": "📋 어제 매매 내역",
            "body": format_trades_summary(trades),
        },
        {
            "header": "🌐 오늘 시장 상황",
            "body": market_comment,
        },
    ]

    # 5. 전송
    success = send_report(f"📈 일일 퀀트 리포트 | {today}", sections)
    if success:
        logger.info("일일 리포트 전송 완료")
    else:
        logger.error("일일 리포트 전송 실패")


# 단독 실행 시 즉시 리포트 전송 (테스트용)
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    send_daily_report()
