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
from src.database.supabase_client import query_table, load_strategy_state
from src.api.upbit_client import (
    get_current_price, get_ohlcv, get_balance_krw,
    get_avg_buy_price, get_balance_coin, get_balances_all,
)


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


def calculate_performance_metrics() -> dict:
    """
    현재 포트폴리오 + DB 매매 이력 기반으로 성능 지표를 계산합니다.

    계산 항목:
        - total_asset: 현재 총 자산 (원)
        - total_invested: 총 매수 금액 (원)
        - total_sold: 총 매도 금액 (원)
        - unrealized_pnl: 미실현 손익 (원)
        - realized_pnl: 실현 손익 (원)
        - holdings: 보유 코인별 손익 정보
        - total_trades: 총 거래 횟수
        - win_count: 수익 매도 횟수
        - lose_count: 손실 매도 횟수
    """
    from src.strategies.adaptive_volume_strategy import TARGET_COINS

    result = {
        "total_asset": 0,
        "krw_balance": 0,
        "coin_value": 0,
        "unrealized_pnl": 0,
        "holdings": [],
        "total_trades": 0,
        "win_count": 0,
        "lose_count": 0,
    }

    try:
        # 현재 보유 자산 조회
        krw = get_balance_krw()
        result["krw_balance"] = krw

        coin_value = 0
        unrealized_pnl = 0
        holdings = []

        for coin in TARGET_COINS:
            volume = get_balance_coin(coin)
            if not volume or volume < 0.00001:
                continue
            price = get_current_price(coin)
            avg_price = get_avg_buy_price(coin)
            if not price:
                continue

            value = volume * price
            invested = volume * avg_price if avg_price else 0
            pnl = value - invested if avg_price else 0
            pnl_rate = (price / avg_price - 1) * 100 if avg_price else 0

            coin_value += value
            unrealized_pnl += pnl
            holdings.append({
                "coin": coin.replace("KRW-", ""),
                "ticker": coin,
                "volume": volume,
                "price": price,
                "avg_price": avg_price,
                "value": value,
                "invested": invested,
                "pnl": pnl,
                "pnl_rate": pnl_rate,
            })

        result["coin_value"] = coin_value
        result["total_asset"] = krw + coin_value
        result["unrealized_pnl"] = unrealized_pnl
        result["holdings"] = holdings

        # DB에서 매도 기록 기반 승률 계산
        all_sells = query_table("trades", filters={"side": "eq.sell"})
        if all_sells:
            result["total_trades"] = len(all_sells)
            for trade in all_sells:
                # amount이 양수면 수익 매도
                signal = trade.get("signal", "")
                # 매도 가격과 매수 평균가를 비교할 수 없으므로
                # 매도 기록 수만 카운트
                result["total_trades"] = len(all_sells)

        all_trades = query_table("trades")
        result["total_trades"] = len(all_trades) if all_trades else 0

    except Exception as e:
        logger.error(f"성과 지표 계산 실패: {e}")

    return result


def get_market_comment() -> str:
    """
    시장 상황을 다각도로 분석해 코멘트를 생성합니다.

    분석 내용:
        - BTC 전일 대비 등락률
        - 7일/20일 모멘텀
        - 변동성 수준
        - 거래대금 추이
    """
    try:
        df = get_ohlcv("KRW-BTC", interval="day", count=25)
        if df is None or len(df) < 20:
            return "시장 데이터를 가져올 수 없습니다."

        close = df["close"]
        current = close.iloc[-1]
        prev_close = close.iloc[-2]
        change_1d = (current / prev_close - 1) * 100
        change_7d = (current / close.iloc[-7] - 1) * 100

        # 변동성 (20일 연환산)
        vol = close.tail(20).pct_change().std() * (365 ** 0.5) * 100

        # 거래대금 추이
        value = df["value"]
        vol_recent = value.tail(3).mean()
        vol_avg = value.tail(20).mean()
        vol_ratio = vol_recent / vol_avg if vol_avg > 0 else 1

        lines = []

        # 1일 변동
        if change_1d > 3:
            lines.append(f"BTC 강세 ({change_1d:+.1f}%)")
        elif change_1d < -3:
            lines.append(f"BTC 약세 ({change_1d:+.1f}%)")
        else:
            lines.append(f"BTC {change_1d:+.1f}%")

        # 7일 추세
        if change_7d > 5:
            lines.append(f"7일 상승 추세 ({change_7d:+.1f}%)")
        elif change_7d < -5:
            lines.append(f"7일 하락 추세 ({change_7d:+.1f}%)")
        else:
            lines.append(f"7일 횡보 ({change_7d:+.1f}%)")

        # 변동성
        if vol > 80:
            lines.append(f"변동성 높음 ({vol:.0f}%)")
        elif vol > 50:
            lines.append(f"변동성 보통 ({vol:.0f}%)")
        else:
            lines.append(f"변동성 낮음 ({vol:.0f}%)")

        # 거래대금
        if vol_ratio > 1.5:
            lines.append(f"거래대금 급증 (평균 대비 {vol_ratio:.1f}배)")
        elif vol_ratio < 0.5:
            lines.append(f"거래대금 위축 (평균 대비 {vol_ratio:.1f}배)")

        return " | ".join(lines)
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

    섹션:
        1. 포트폴리오 현황 (총 자산, 보유 코인별 손익)
        2. 시장 국면 분석
        3. 리밸런싱 현황
        4. 어제 매매 내역
        5. 시장 코멘트
    """
    logger.info("일일 리포트 생성 시작...")
    today = datetime.now().strftime("%Y년 %m월 %d일")

    # 1. 포트폴리오 성과 지표
    metrics = calculate_performance_metrics()

    # 포트폴리오 현황 텍스트
    portfolio_lines = [
        f"총 자산: {metrics['total_asset']:,.0f}원",
        f"현금: {metrics['krw_balance']:,.0f}원",
        f"코인: {metrics['coin_value']:,.0f}원",
    ]
    if metrics["unrealized_pnl"] != 0:
        sign = "+" if metrics["unrealized_pnl"] > 0 else ""
        portfolio_lines.append(f"미실현 손익: {sign}{metrics['unrealized_pnl']:,.0f}원")

    if metrics["holdings"]:
        portfolio_lines.append("")
        for h in sorted(metrics["holdings"], key=lambda x: x["value"], reverse=True):
            sign = "+" if h["pnl_rate"] >= 0 else ""
            avg_text = f"매입가 {h['avg_price']:,.0f}" if h["avg_price"] else "매입가 미상"
            portfolio_lines.append(
                f"  {h['coin']}: {h['value']:,.0f}원 ({sign}{h['pnl_rate']:.1f}%)\n"
                f"    현재가 {h['price']:,.0f} | {avg_text}"
            )

    # 2. 시장 국면 (ADX v2)
    regime_text = "분석 불가"
    try:
        from src.strategies.strategy_router import calc_adx
        df_btc = get_ohlcv("KRW-BTC", interval="day", count=60)
        if df_btc is not None and len(df_btc) >= 30:
            close = df_btc["close"]
            btc_price = close.iloc[-1]

            adx_result = calc_adx(df_btc["high"], df_btc["low"], close, 14)
            adx = adx_result["adx"]
            plus_di = adx_result["plus_di"]
            minus_di = adx_result["minus_di"]

            if adx > 25 and plus_di > minus_di:
                regime_text = "상승장 → 거래량돌파 매수 중"
            elif adx > 25 and minus_di > plus_di:
                regime_text = "하락장 → 전량 현금 보유"
            else:
                regime_text = "횡보장 → 거래량돌파 매수 중 (유지)"
            regime_text += (
                f"\nBTC: {btc_price:,.0f}원\n"
                f"ADX: {adx:.1f} | +DI: {plus_di:.1f} | -DI: {minus_di:.1f}"
            )
    except Exception:
        pass

    # 3. 리밸런싱 현황
    rebal_text = "기록 없음"
    try:
        last_rebal = load_strategy_state("adaptive_volume", "last_rebalance_date")
        if last_rebal:
            last_date = datetime.strptime(last_rebal, "%Y-%m-%d").date()
            days_since = (datetime.now().date() - last_date).days
            days_left = max(0, 3 - days_since)
            rebal_text = (
                f"마지막 리밸런싱: {last_rebal} ({days_since}일 전)\n"
                f"다음 리밸런싱: {'오늘 실행 가능' if days_left == 0 else f'{days_left}일 후'}\n"
                f"리밸런싱 주기: 3일"
            )
        else:
            rebal_text = "리밸런싱 기록 없음 (다음 실행 시 즉시 리밸런싱)"
    except Exception:
        pass

    # 4. 어제 매매 내역
    trades = get_yesterday_trades()
    trades_text = format_trades_summary(trades)
    if metrics["total_trades"] > 0:
        trades_text += f"\n\n누적 거래: {metrics['total_trades']}건"

    # 5. 시장 코멘트
    market_comment = get_market_comment()

    # 섹션 조합
    sections = [
        {"header": "💰 포트폴리오 현황", "body": "\n".join(portfolio_lines)},
        {"header": "📈 시장 국면", "body": regime_text},
        {"header": "🔄 리밸런싱 현황", "body": rebal_text},
        {"header": "📋 어제 매매 내역", "body": trades_text},
        {"header": "🌐 시장 코멘트", "body": market_comment},
    ]

    success = send_report(f"📊 일일 리포트 | {today}", sections)
    if success:
        logger.info("일일 리포트 전송 완료")
    else:
        logger.error("일일 리포트 전송 실패")


# 단독 실행 시 즉시 리포트 전송 (테스트용)
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    send_daily_report()
