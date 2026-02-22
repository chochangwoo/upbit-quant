"""
notify/telegram_bot.py - 텔레그램 알림 봇 (기능 확장 버전)

기존 src/notifications/telegram_bot.py를 기반으로,
일일 리포트 전송에 필요한 기능을 추가합니다.

사용 예시:
    from notify.telegram_bot import send_message, send_report
"""
import os
import requests
from loguru import logger


def _get_bot_info() -> tuple:
    """
    .env 파일에서 텔레그램 봇 토큰과 채팅 ID를 읽어옵니다.
    반환값: (token, chat_id) 튜플
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return token, chat_id


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    텔레그램으로 일반 메시지를 전송합니다.

    매개변수:
        text: 전송할 메시지 내용 (HTML 태그 사용 가능)
        parse_mode: 메시지 형식 ("HTML" 또는 "Markdown")
    반환값:
        True = 전송 성공, False = 전송 실패
    """
    token, chat_id = _get_bot_info()
    if not token or not chat_id:
        logger.warning("텔레그램 설정이 없습니다. .env 파일을 확인하세요.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True
        logger.error(f"텔레그램 전송 실패: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"텔레그램 연결 오류: {e}")
        return False


def send_photo(image_path: str, caption: str = "") -> bool:
    """
    텔레그램으로 이미지 파일을 전송합니다.
    백테스팅 결과 그래프 전송에 사용합니다.

    매개변수:
        image_path: 전송할 이미지 파일 경로 (예: "backtest/result.png")
        caption: 이미지 아래에 표시할 설명 텍스트
    반환값:
        True = 전송 성공, False = 전송 실패
    """
    # TODO: 구현 예정
    token, chat_id = _get_bot_info()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(image_path, "rb") as photo:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": photo},
                timeout=30,
            )
        return resp.status_code == 200
    except FileNotFoundError:
        logger.error(f"이미지 파일을 찾을 수 없습니다: {image_path}")
        return False
    except Exception as e:
        logger.error(f"이미지 전송 실패: {e}")
        return False


def send_report(title: str, sections: list) -> bool:
    """
    섹션으로 구분된 리포트 형식의 메시지를 전송합니다.

    매개변수:
        title: 리포트 제목
        sections: 섹션 목록. 각 섹션은 {"header": "제목", "body": "내용"} 형태
    반환값:
        True = 전송 성공, False = 전송 실패

    사용 예시:
        send_report("일일 리포트", [
            {"header": "누적 수익률", "body": "+12.3%"},
            {"header": "오늘 매매", "body": "BTC 매수 1건"},
        ])
    """
    # 메시지 조립
    lines = [f"<b>{title}</b>", "─" * 20]
    for section in sections:
        lines.append(f"\n<b>{section['header']}</b>")
        lines.append(section["body"])

    message = "\n".join(lines)
    return send_message(message)
