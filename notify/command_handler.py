"""
notify/command_handler.py - 텔레그램 명령어 핸들러

텔레그램 봇에서 명령어를 수신하여 현재 전략 상태 조회 등 기능을 실행합니다.
별도 스레드에서 동작하며, main.py의 트레이딩 루프와 독립적으로 운영됩니다.

지원 명령어:
    /help       - 사용 가능한 명령어 목록
    /status     - 현재 봇 상태 (전략, 국면, 잔고, 포트폴리오)
    /regime     - 현재 시장 국면 상세 정보
    /portfolio  - 보유 코인 포트폴리오 상세 (매입가 대비 수익률 포함)
    /report     - 일일 리포트 즉시 전송
"""
import os
import asyncio
import threading
import traceback
from datetime import datetime  # noqa: F401 - used in cmd_status
from loguru import logger

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


# ─────────────────────────────────────────
# 명령어 핸들러 함수들
# ─────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용 가능한 명령어 목록을 표시합니다."""
    text = (
        "<b>사용 가능한 명령어</b>\n"
        "─────────────────\n"
        "<b>상태 조회</b>\n"
        "/status - 봇 상태 (전략, 잔고)\n"
        "/regime - 시장 국면 (BTC SMA50, 모멘텀)\n"
        "/portfolio - 포트폴리오 (매입가, 손익)\n"
        "─────────────────\n"
        "<b>리포트</b>\n"
        "/report - 일일 리포트 즉시 전송\n"
        "─────────────────\n"
        "/help - 이 도움말 표시"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """현재 봇 상태를 조회합니다."""
    try:
        from config.settings import STRATEGY_NAME, LIVE_TRADING
        from src.api.upbit_client import get_balance_krw, get_balance_coin, get_current_price

        mode = "실거래" if LIVE_TRADING else "시뮬레이션"

        if STRATEGY_NAME == "adaptive_volume":
            from src.strategies.adaptive_volume_strategy import TARGET_COINS
            from src.database.supabase_client import load_strategy_state

            # 원화 잔고
            krw = get_balance_krw()

            # 보유 코인 평가
            holdings = []
            total_coin_value = 0
            for coin in TARGET_COINS:
                volume = get_balance_coin(coin)
                if volume and volume > 0.00001:
                    price = get_current_price(coin)
                    if price:
                        value = volume * price
                        total_coin_value += value
                        holdings.append(f"  {coin.replace('KRW-', '')}: {value:,.0f}원")

            total = krw + total_coin_value

            # 마지막 리밸런싱 날짜
            last_rebal = load_strategy_state("adaptive_volume", "last_rebalance_date")
            rebal_text = last_rebal if last_rebal else "없음"

            # 리밸런싱까지 남은 일수
            if last_rebal:
                last_date = datetime.strptime(last_rebal, "%Y-%m-%d").date()
                days_since = (datetime.now().date() - last_date).days
                days_left = max(0, 3 - days_since)
                rebal_text += f" (다음까지 {days_left}일)"

            holdings_text = "\n".join(holdings) if holdings else "  없음"

            text = (
                f"<b>봇 상태</b>\n"
                f"─────────────────\n"
                f"모드: {mode}\n"
                f"전략: 적응형 거래량돌파\n"
                f"대상: 13개 코인\n"
                f"리밸런싱 주기: 3일\n"
                f"마지막 리밸런싱: {rebal_text}\n"
                f"─────────────────\n"
                f"원화 잔고: {krw:,.0f}원\n"
                f"코인 평가: {total_coin_value:,.0f}원\n"
                f"총 자산: {total:,.0f}원\n"
                f"─────────────────\n"
                f"<b>보유 코인</b>\n{holdings_text}"
            )
        else:
            # MA Cross 등 기존 전략
            from config.settings import TICKER, SHORT_WINDOW, LONG_WINDOW
            krw = get_balance_krw()
            coin = get_balance_coin(TICKER)
            price = get_current_price(TICKER)
            coin_value = (coin or 0) * (price or 0)
            total = krw + coin_value

            text = (
                f"<b>봇 상태</b>\n"
                f"─────────────────\n"
                f"모드: {mode}\n"
                f"전략: MA 크로스 {SHORT_WINDOW}/{LONG_WINDOW}\n"
                f"코인: {TICKER}\n"
                f"─────────────────\n"
                f"원화 잔고: {krw:,.0f}원\n"
                f"코인 보유: {(coin or 0):.6f}\n"
                f"현재가: {(price or 0):,.0f}원\n"
                f"코인 평가: {coin_value:,.0f}원\n"
                f"총 자산: {total:,.0f}원"
            )
    except Exception as e:
        text = f"상태 조회 실패: {e}"

    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """현재 시장 국면 상세 정보를 조회합니다."""
    try:
        from src.api.upbit_client import get_ohlcv

        df = get_ohlcv("KRW-BTC", interval="day", count=60)
        if df is None or len(df) < 50:
            await update.message.reply_text("BTC 데이터를 가져올 수 없습니다.")
            return

        close = df["close"]
        current_price = close.iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        momentum_20d = current_price / close.iloc[-20] - 1

        # 국면 판단
        if current_price > sma50 and momentum_20d > 0.10:
            regime = "상승장 (Bull)"
            action = "거래량 돌파 상위 5개 코인 매수"
        elif current_price < sma50 and momentum_20d < -0.10:
            regime = "하락장 (Bear)"
            action = "전량 현금 보유 (매매 중지)"
        else:
            regime = "횡보장 (Sideways)"
            action = "거래량 돌파 상위 5개 코인 매수"

        # 추가 지표
        sma20 = close.rolling(20).mean().iloc[-1]
        momentum_7d = current_price / close.iloc[-7] - 1
        volatility = close.tail(20).pct_change().std() * (365 ** 0.5)

        text = (
            f"<b>시장 국면 분석</b>\n"
            f"─────────────────\n"
            f"현재 국면: <b>{regime}</b>\n"
            f"전략 행동: {action}\n"
            f"─────────────────\n"
            f"<b>BTC 지표</b>\n"
            f"  현재가: {current_price:,.0f}원\n"
            f"  SMA20: {sma20:,.0f}원\n"
            f"  SMA50: {sma50:,.0f}원\n"
            f"  7일 모멘텀: {momentum_7d:+.1%}\n"
            f"  20일 모멘텀: {momentum_20d:+.1%}\n"
            f"  연환산 변동성: {volatility:.1%}\n"
            f"─────────────────\n"
            f"<b>국면 전환 기준</b>\n"
            f"  상승장: 가격 &gt; SMA50 AND 20일 모멘텀 &gt; +10%\n"
            f"  하락장: 가격 &lt; SMA50 AND 20일 모멘텀 &lt; -10%\n"
            f"  횡보장: 그 외"
        )
    except Exception as e:
        text = f"국면 분석 실패: {e}"

    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """보유 코인 포트폴리오 상세를 조회합니다 (매입가 대비 수익률 포함)."""
    try:
        from src.api.upbit_client import (
            get_balance_krw, get_balance_coin, get_current_price,
            get_avg_buy_price, get_ohlcv,
        )
        from src.strategies.adaptive_volume_strategy import TARGET_COINS

        krw = get_balance_krw()
        holdings = []
        total_coin_value = 0
        total_invested = 0

        for coin in TARGET_COINS:
            volume = get_balance_coin(coin)
            if not volume or volume < 0.00001:
                continue
            price = get_current_price(coin)
            if not price:
                continue

            avg_price = get_avg_buy_price(coin)
            value = volume * price
            invested = volume * avg_price if avg_price else 0
            pnl = value - invested if avg_price else 0
            pnl_rate = (price / avg_price - 1) * 100 if avg_price else 0

            # 24시간 변동률
            df = get_ohlcv(coin, interval="day", count=2)
            change_24h = 0
            if df is not None and len(df) >= 2:
                change_24h = (df["close"].iloc[-1] / df["close"].iloc[-2] - 1)

            total_coin_value += value
            total_invested += invested
            holdings.append({
                "coin": coin.replace("KRW-", ""),
                "value": value,
                "price": price,
                "avg_price": avg_price,
                "volume": volume,
                "invested": invested,
                "pnl": pnl,
                "pnl_rate": pnl_rate,
                "change_24h": change_24h,
            })

        total = krw + total_coin_value
        total_pnl = total_coin_value - total_invested if total_invested else 0

        if not holdings:
            text = (
                f"<b>포트폴리오 상세</b>\n"
                f"─────────────────\n"
                f"보유 코인 없음 (전량 현금)\n"
                f"원화 잔고: {krw:,.0f}원"
            )
        else:
            holdings.sort(key=lambda h: h["value"], reverse=True)

            pnl_sign = "+" if total_pnl >= 0 else ""
            lines = [
                f"<b>포트폴리오 상세</b>",
                f"─────────────────",
                f"총 자산: {total:,.0f}원",
                f"현금: {krw:,.0f}원 ({krw/total:.0%})",
                f"코인: {total_coin_value:,.0f}원 ({total_coin_value/total:.0%})",
            ]
            if total_invested:
                pnl_rate = (total_coin_value / total_invested - 1) * 100
                lines.append(
                    f"미실현 손익: {pnl_sign}{total_pnl:,.0f}원 ({pnl_sign}{pnl_rate:.1f}%)"
                )
            lines.append(f"─────────────────")

            for h in holdings:
                weight = h["value"] / total
                sign_24h = "+" if h["change_24h"] >= 0 else ""
                sign_pnl = "+" if h["pnl_rate"] >= 0 else ""

                coin_lines = [
                    f"<b>{h['coin']}</b>  {h['value']:,.0f}원 (비중 {weight:.0%})",
                    f"  현재가: {h['price']:,.0f}원 | 24h: {sign_24h}{h['change_24h']:.1%}",
                ]
                if h["avg_price"]:
                    coin_lines.append(
                        f"  매입가: {h['avg_price']:,.0f}원 | 손익: {sign_pnl}{h['pnl_rate']:.1f}% ({sign_pnl}{h['pnl']:,.0f}원)"
                    )
                lines.append("\n".join(coin_lines))

            text = "\n".join(lines)

    except Exception as e:
        text = f"포트폴리오 조회 실패: {e}"

    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일일 리포트를 즉시 전송합니다."""
    await update.message.reply_text("일일 리포트 생성 중...")
    try:
        from notify.daily_report import send_daily_report
        send_daily_report()
        await update.message.reply_text("일일 리포트 전송 완료!")
    except Exception as e:
        await update.message.reply_text(f"리포트 생성 실패: {e}")


# ─────────────────────────────────────────
# 에러 핸들러
# ─────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """텔레그램 봇의 모든 에러를 잡아서 로그에 기록합니다."""
    logger.error(f"텔레그램 봇 에러: {context.error}\n{traceback.format_exc()}")


# ─────────────────────────────────────────
# 봇 시작 및 스레드 실행
# ─────────────────────────────────────────

async def _post_init(application: Application):
    """봇 초기화 후 명령어 메뉴를 등록합니다."""
    commands = [
        BotCommand("help", "명령어 목록"),
        BotCommand("status", "봇 상태 (전략, 국면, 잔고)"),
        BotCommand("regime", "시장 국면 상세"),
        BotCommand("portfolio", "포트폴리오 (매입가, 손익)"),
        BotCommand("report", "일일 리포트 즉시 전송"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("텔레그램 봇 명령어 메뉴 등록 완료")


def _run_bot_blocking():
    """
    별도 스레드에서 텔레그램 봇 폴링을 실행합니다.
    run_polling()은 메인 스레드에서만 signal 핸들러를 등록할 수 있으므로,
    서브 스레드에서는 수동으로 이벤트 루프를 관리합니다.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다. 명령어 핸들러 시작 불가.")
        return

    async def _run():
        app = (
            Application.builder()
            .token(token)
            .post_init(_post_init)
            .build()
        )

        # 명령어 등록
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("start", cmd_help))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("regime", cmd_regime))
        app.add_handler(CommandHandler("portfolio", cmd_portfolio))
        app.add_handler(CommandHandler("report", cmd_report))

        # 에러 핸들러
        app.add_error_handler(error_handler)

        logger.info("텔레그램 명령어 핸들러 시작 (폴링 모드)")

        # 수동으로 초기화 → 폴링 시작 → 무한 대기
        async with app:
            await app.start()
            await app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
            )
            logger.info("텔레그램 폴링 활성화 완료 - 명령어 수신 대기 중")

            # 무한 대기 (데몬 스레드이므로 메인 종료 시 함께 종료)
            stop_event = asyncio.Event()
            await stop_event.wait()

    # 서브 스레드에서 새 이벤트 루프 생성
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    except Exception as e:
        logger.error(f"텔레그램 봇 시작 실패: {e}\n{traceback.format_exc()}")
    finally:
        loop.close()


def start_command_handler():
    """
    텔레그램 명령어 핸들러를 데몬 스레드로 시작합니다.
    main.py에서 호출하여 트레이딩 루프와 병렬 실행합니다.
    """
    thread = threading.Thread(
        target=_run_bot_blocking,
        name="telegram-command-handler",
        daemon=True,
    )
    thread.start()
    logger.info("텔레그램 명령어 핸들러 스레드 시작됨")
    return thread
