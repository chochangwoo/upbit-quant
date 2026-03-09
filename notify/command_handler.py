"""
notify/command_handler.py - 텔레그램 명령어 핸들러

텔레그램 봇에서 명령어를 수신하여 백테스팅 등 기능을 실행합니다.
별도 스레드에서 동작하며, main.py의 트레이딩 루프와 독립적으로 운영됩니다.

지원 명령어:
    /help       - 사용 가능한 명령어 목록
    /status     - 현재 봇 상태 (전략, 잔고 등)
    /backtest   - 코인 선별 전략 백테스팅 실행 (전략 4종 비교)
    /bt_momentum  - 모멘텀 전략만 백테스팅
    /bt_volume    - 거래량 급증 전략만 백테스팅
    /bt_meanrev   - 평균회귀 전략만 백테스팅
    /bt_composite - 복합 스코어링 전략만 백테스팅
    /report     - 일일 리포트 즉시 전송
"""
import os
import sys
import asyncio
import threading
from loguru import logger

# 텔레그램 봇 라이브러리 (python-telegram-bot v20+)
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
        "/help - 명령어 목록\n"
        "/status - 현재 봇 상태\n"
        "/backtest - 코인 선별 전략 백테스팅 (전체 4종 비교)\n"
        "/bt_momentum - 모멘텀 전략 백테스팅\n"
        "/bt_volume - 거래량 급증 전략 백테스팅\n"
        "/bt_meanrev - 평균회귀 전략 백테스팅\n"
        "/bt_composite - 복합 스코어링 전략 백테스팅\n"
        "/report - 일일 리포트 즉시 전송\n"
        "─────────────────\n"
        "<i>백테스팅 옵션 예시:</i>\n"
        "<code>/backtest 90 5 7</code>\n"
        "→ 90일, 상위 5개, 리밸런싱 7일"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """현재 봇 상태를 조회합니다."""
    try:
        from config.settings import STRATEGY_NAME, TICKER, LIVE_TRADING, SHORT_WINDOW, LONG_WINDOW
        from src.api.upbit_client import get_balance_krw, get_balance_coin, get_current_price

        mode = "실거래" if LIVE_TRADING else "시뮬레이션"
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


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """일일 리포트를 즉시 전송합니다."""
    await update.message.reply_text("일일 리포트 생성 중...")
    try:
        from notify.daily_report import send_daily_report
        send_daily_report()
        await update.message.reply_text("일일 리포트 전송 완료!")
    except Exception as e:
        await update.message.reply_text(f"리포트 생성 실패: {e}")


def _parse_backtest_args(context) -> dict:
    """
    백테스팅 명령어의 인자를 파싱합니다.
    /backtest [days] [top_n] [rebalance]
    """
    args = context.args if context.args else []
    config = {
        "days": 60,
        "top_n": 5,
        "rebalance": 3,
    }
    if len(args) >= 1:
        try:
            config["days"] = int(args[0])
        except ValueError:
            pass
    if len(args) >= 2:
        try:
            config["top_n"] = int(args[1])
        except ValueError:
            pass
    if len(args) >= 3:
        try:
            config["rebalance"] = int(args[2])
        except ValueError:
            pass
    return config


async def _run_screener_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                  strategy_names: list):
    """
    코인 선별 전략 백테스팅을 실행하고 결과를 텔레그램으로 전송합니다.
    데이터 수집에 시간이 걸리므로 별도 스레드에서 실행합니다.
    """
    config = _parse_backtest_args(context)
    strategy_str = ", ".join(strategy_names)

    await update.message.reply_text(
        f"백테스팅 시작!\n"
        f"전략: {strategy_str}\n"
        f"기간: {config['days']}일 | 상위: {config['top_n']}개 | 리밸런싱: {config['rebalance']}일\n"
        f"데이터 수집 중... (1~3분 소요)"
    )

    # 무거운 작업은 별도 스레드에서 실행
    loop = asyncio.get_event_loop()
    try:
        result_text, chart_path = await loop.run_in_executor(
            None, _execute_backtest, strategy_names, config
        )
        await update.message.reply_text(result_text, parse_mode="HTML")

        # 차트 이미지 전송
        if chart_path and os.path.exists(chart_path):
            with open(chart_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption="코인 선별 전략 비교 차트"
                )
    except Exception as e:
        logger.error(f"백테스팅 실행 오류: {e}")
        await update.message.reply_text(f"백테스팅 실행 실패: {e}")


def _execute_backtest(strategy_names: list, config: dict) -> tuple:
    """
    백테스팅 실제 실행 (동기 함수, run_in_executor에서 호출).
    반환값: (결과 텍스트, 차트 경로)
    """
    from backtest.coin_screener.data_collector import DataCollector
    from backtest.coin_screener.backtest_engine import ScreenerBacktestEngine
    from backtest.coin_screener.report_generator import ReportGenerator
    from backtest.coin_screener.strategies.momentum_screener import MomentumScreener
    from backtest.coin_screener.strategies.volume_screener import VolumeScreener
    from backtest.coin_screener.strategies.mean_reversion_screener import MeanReversionScreener
    from backtest.coin_screener.strategies.composite_screener import CompositeScreener

    STRATEGY_MAP = {
        "momentum": MomentumScreener,
        "volume": VolumeScreener,
        "meanrev": MeanReversionScreener,
        "composite": CompositeScreener,
    }

    days = config["days"]
    top_n = config["top_n"]
    rebalance = config["rebalance"]

    # 1. 데이터 수집
    collector = DataCollector()
    all_data = collector.collect_all(days=days + 30)

    if not all_data:
        return ("수집된 데이터가 없습니다. 다시 시도해주세요.", None)

    total_coins = len(all_data)

    # 2. 스크리너 생성
    screeners = []
    for name in strategy_names:
        if name in STRATEGY_MAP:
            screeners.append(STRATEGY_MAP[name](top_n=top_n))

    if not screeners:
        return ("유효한 전략이 없습니다.", None)

    # 3. 백테스팅 실행
    results = []
    for screener in screeners:
        engine = ScreenerBacktestEngine(
            screener=screener,
            all_data=all_data,
            initial_capital=1_000_000,
            rebalance_days=rebalance,
            fee_rate=0.0005,
        )
        result = engine.run()
        results.append(result)

    # 4. 리포트 생성
    reporter = ReportGenerator(results, {
        "days": days,
        "top_n": top_n,
        "rebalance_days": rebalance,
        "initial_capital": 1_000_000,
    })

    chart_path = reporter.save_chart()

    # 5. 결과 텍스트 생성
    sorted_results = sorted(results, key=lambda r: r.total_return(), reverse=True)

    lines = [
        "<b>코인 선별 전략 백테스팅 결과</b>",
        "═" * 24,
        f"기간: {days}일 | 코인: {top_n}개 | 리밸런싱: {rebalance}일",
        f"대상: {total_coins}개 코인",
        "─" * 24,
    ]

    for rank, result in enumerate(sorted_results, 1):
        s = result.summary()
        lines.append(
            f"<b>{rank}위 {s['strategy_name']}</b>\n"
            f"  수익률: {s['total_return']:+.2f}% | MDD: {s['mdd']:.2f}%\n"
            f"  샤프: {s['sharpe_ratio']:.2f} | 승률: {s['win_rate']:.1f}% | 거래: {s['total_trades']}건"
        )

    best = sorted_results[0]
    lines.append(f"\n최우수: {best.strategy_name} ({best.total_return():+.2f}%)")

    return ("\n".join(lines), chart_path)


# ─────────────────────────────────────────
# 전략별 개별 명령어 핸들러
# ─────────────────────────────────────────

async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """전체 4종 전략 비교 백테스팅을 실행합니다."""
    await _run_screener_backtest(
        update, context,
        ["momentum", "volume", "meanrev", "composite"]
    )


async def cmd_bt_momentum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """모멘텀 전략만 백테스팅합니다."""
    await _run_screener_backtest(update, context, ["momentum"])


async def cmd_bt_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """거래량 급증 전략만 백테스팅합니다."""
    await _run_screener_backtest(update, context, ["volume"])


async def cmd_bt_meanrev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """평균회귀 전략만 백테스팅합니다."""
    await _run_screener_backtest(update, context, ["meanrev"])


async def cmd_bt_composite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """복합 스코어링 전략만 백테스팅합니다."""
    await _run_screener_backtest(update, context, ["composite"])


# ─────────────────────────────────────────
# 봇 시작 및 스레드 실행
# ─────────────────────────────────────────

def _run_bot_in_thread():
    """
    별도 스레드에서 텔레그램 봇 폴링을 실행합니다.
    새 이벤트 루프를 생성하여 async 봇을 돌립니다.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        return

    async def _start():
        app = Application.builder().token(token).build()

        # 명령어 등록
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("start", cmd_help))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("report", cmd_report))
        app.add_handler(CommandHandler("backtest", cmd_backtest))
        app.add_handler(CommandHandler("bt_momentum", cmd_bt_momentum))
        app.add_handler(CommandHandler("bt_volume", cmd_bt_volume))
        app.add_handler(CommandHandler("bt_meanrev", cmd_bt_meanrev))
        app.add_handler(CommandHandler("bt_composite", cmd_bt_composite))

        # 봇 메뉴에 명령어 목록 등록
        commands = [
            BotCommand("help", "명령어 목록"),
            BotCommand("status", "현재 봇 상태"),
            BotCommand("backtest", "코인 선별 백테스팅 (전체)"),
            BotCommand("bt_momentum", "모멘텀 전략 백테스팅"),
            BotCommand("bt_volume", "거래량 급증 전략 백테스팅"),
            BotCommand("bt_meanrev", "평균회귀 전략 백테스팅"),
            BotCommand("bt_composite", "복합 스코어링 전략 백테스팅"),
            BotCommand("report", "일일 리포트 즉시 전송"),
        ]
        await app.bot.set_my_commands(commands)

        logger.info("텔레그램 명령어 핸들러 시작 (폴링 모드)")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        # 무한 대기 (stop 신호까지)
        stop_event = asyncio.Event()
        await stop_event.wait()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_start())
    except Exception as e:
        logger.error(f"텔레그램 봇 오류: {e}")


def start_command_handler():
    """
    텔레그램 명령어 핸들러를 데몬 스레드로 시작합니다.
    main.py에서 호출하여 트레이딩 루프와 병렬 실행합니다.
    """
    thread = threading.Thread(target=_run_bot_in_thread, daemon=True)
    thread.start()
    logger.info("텔레그램 명령어 핸들러 스레드 시작됨")
    return thread
