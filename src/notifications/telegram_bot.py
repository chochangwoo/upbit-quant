"""
텔레그램 알림 모듈
매매 신호, 에러 등을 텔레그램으로 알림 전송합니다.
"""
import os
import requests
from loguru import logger


def send_message(message: str) -> bool:
    """
    텔레그램으로 메시지를 전송합니다.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("텔레그램 설정이 없습니다. .env 파일을 확인하세요.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"  # <b>굵게</b>, <i>기울임</i> 사용 가능
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("텔레그램 메시지 전송 성공")
            return True
        else:
            logger.error(f"텔레그램 전송 실패: {response.text}")
            return False
    except Exception as e:
        logger.error(f"텔레그램 연결 오류: {e}")
        return False


def send_buy_alert(ticker: str, price: float, amount: float):
    """매수 알림 전송"""
    message = (
        f"🟢 <b>매수 완료</b>\n"
        f"코인: {ticker}\n"
        f"가격: {price:,.0f}원\n"
        f"금액: {amount:,.0f}원"
    )
    send_message(message)


def send_sell_alert(ticker: str, price: float, profit_rate: float):
    """매도 알림 전송"""
    emoji = "🔴" if profit_rate < 0 else "🟢"
    message = (
        f"{emoji} <b>매도 완료</b>\n"
        f"코인: {ticker}\n"
        f"가격: {price:,.0f}원\n"
        f"수익률: {profit_rate:.2f}%"
    )
    send_message(message)


def send_error_alert(error_msg: str):
    """에러 알림 전송"""
    message = f"⚠️ <b>오류 발생</b>\n{error_msg}"
    send_message(message)
