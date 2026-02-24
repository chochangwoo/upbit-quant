"""
Supabase 데이터베이스 연동 모듈
매매 내역, 수익률 등을 DB에 저장합니다.

trades 테이블 스키마:
  strategy_name TEXT, ticker TEXT, side TEXT ('buy'/'sell'),
  price NUMERIC, amount NUMERIC, signal TEXT, ma5 NUMERIC, ma20 NUMERIC
"""
import os
from supabase import create_client, Client
from loguru import logger


def get_supabase_client() -> Client:
    """Supabase 클라이언트를 생성합니다."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.error(".env 파일에 SUPABASE_URL과 SUPABASE_KEY를 입력하세요!")
        return None

    try:
        client = create_client(url, key)
        return client
    except Exception as e:
        logger.error(f"Supabase 연결 실패: {e}")
        return None


def save_trade(
    strategy_name: str,
    ticker: str,
    side: str,
    price: float,
    amount: float,
    signal: str = None,
    ma5: float = None,
    ma20: float = None,
) -> bool:
    """
    매매 내역을 DB에 저장합니다.

    매개변수:
        strategy_name: 전략 이름 (예: 'ma_cross')
        ticker       : 코인 티커 (예: 'KRW-BTC')
        side         : 'buy' 또는 'sell'
        price        : 체결 가격 (원)
        amount       : 거래 금액 (원)
        signal       : 신호 종류 (예: 'golden_cross', 'dead_cross')
        ma5          : 단기 이동평균 값
        ma20         : 장기 이동평균 값
    """
    client = get_supabase_client()
    if not client:
        return False

    try:
        data = {
            "strategy_name": strategy_name,
            "ticker"       : ticker,
            "side"         : side,
            "price"        : price,
            "amount"       : amount,
            "signal"       : signal,
            "ma5"          : ma5,
            "ma20"         : ma20,
        }
        client.table("trades").insert(data).execute()
        logger.info(f"매매 내역 저장 완료: {side} {ticker} ({signal})")
        return True
    except Exception as e:
        logger.error(f"매매 내역 저장 실패: {e}")
        return False
