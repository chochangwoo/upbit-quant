"""
Supabase 데이터베이스 연동 모듈
매매 내역, 수익률 등을 DB에 저장합니다.
"""
import os
from supabase import create_client, Client
from loguru import logger
from datetime import datetime


def get_supabase_client() -> Client:
    """Supabase 클라이언트를 생성합니다."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.error(".env 파일에 SUPABASE_URL과 SUPABASE_KEY를 입력하세요!")
        return None

    try:
        client = create_client(url, key)
        logger.info("Supabase 연결 성공")
        return client
    except Exception as e:
        logger.error(f"Supabase 연결 실패: {e}")
        return None


def save_trade(ticker: str, trade_type: str, price: float, amount: float, quantity: float):
    """
    매매 내역을 DB에 저장합니다.
    trade_type: "buy" 또는 "sell"
    """
    client = get_supabase_client()
    if not client:
        return False

    try:
        data = {
            "ticker": ticker,
            "trade_type": trade_type,   # buy/sell
            "price": price,              # 체결 가격
            "amount": amount,            # 거래 금액 (원)
            "quantity": quantity,        # 거래 수량 (코인)
            "created_at": datetime.now().isoformat()
        }
        client.table("trades").insert(data).execute()
        logger.info(f"매매 내역 저장 완료: {trade_type} {ticker}")
        return True
    except Exception as e:
        logger.error(f"매매 내역 저장 실패: {e}")
        return False
