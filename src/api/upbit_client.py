"""
업비트 API 연결 모듈
pyupbit 라이브러리를 사용해 업비트와 통신합니다.
"""
import pyupbit
import os
from loguru import logger


def get_upbit_client():
    """업비트 API 클라이언트를 생성합니다."""
    access_key = os.getenv("UPBIT_ACCESS_KEY")
    secret_key = os.getenv("UPBIT_SECRET_KEY")

    if not access_key or not secret_key:
        logger.error(".env 파일에 UPBIT_ACCESS_KEY와 UPBIT_SECRET_KEY를 입력하세요!")
        return None

    try:
        upbit = pyupbit.Upbit(access_key, secret_key)
        return upbit
    except Exception as e:
        logger.error(f"업비트 API 연결 실패: {e}")
        return None


def get_current_price(ticker: str) -> float:
    """현재가를 조회합니다. 예: 'KRW-BTC'"""
    try:
        price = pyupbit.get_current_price(ticker)
        return price
    except Exception as e:
        logger.error(f"{ticker} 현재가 조회 실패: {e}")
        return None


def get_ohlcv(ticker: str, interval: str = "day", count: int = 2):
    """
    캔들 데이터(시가/고가/저가/종가/거래량)를 조회합니다.
    interval: "day"=일봉, "minute60"=1시간봉
    """
    try:
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
        return df
    except Exception as e:
        logger.error(f"{ticker} OHLCV 데이터 조회 실패: {e}")
        return None


def get_balance_krw() -> float:
    """보유 원화(KRW) 잔고를 조회합니다."""
    upbit = get_upbit_client()
    if not upbit:
        return 0
    try:
        import requests, jwt, uuid
        # 실제 아웃바운드 IP 확인
        my_ip = requests.get("https://api.ipify.org", timeout=5).text
        logger.info(f"[잔고 진단] Railway 아웃바운드 IP: {my_ip}")
        # Upbit API 직접 호출
        access_key = os.getenv("UPBIT_ACCESS_KEY")
        secret_key = os.getenv("UPBIT_SECRET_KEY")
        payload = {"access_key": access_key, "nonce": str(uuid.uuid4())}
        jwt_token = jwt.encode(payload, secret_key, algorithm="HS256")
        headers = {"Authorization": f"Bearer {jwt_token}"}
        resp = requests.get("https://api.upbit.com/v1/accounts", headers=headers, timeout=10)
        logger.info(f"[잔고 진단] Upbit API 응답: status={resp.status_code}, body={resp.text[:300]}")
        balance = upbit.get_balance("KRW")
        return balance if balance else 0
    except Exception as e:
        logger.error(f"원화 잔고 조회 실패: {e}")
        return 0


def get_balance_coin(ticker: str) -> float:
    """
    특정 코인의 보유 수량을 조회합니다.
    ticker 예: 'KRW-BTC' → 'BTC' 부분만 추출해서 조회
    """
    upbit = get_upbit_client()
    if not upbit:
        return 0
    try:
        coin = ticker.split("-")[1]  # 'KRW-BTC' → 'BTC'
        balance = upbit.get_balance(coin)
        return balance if balance else 0
    except Exception as e:
        logger.error(f"{ticker} 코인 잔고 조회 실패: {e}")
        return 0


def buy_market_order(ticker: str, amount_krw: float):
    """
    시장가 매수 주문을 실행합니다.
    amount_krw: 매수할 금액 (원화)
    반환값: 주문 결과 dict 또는 None
    """
    upbit = get_upbit_client()
    if not upbit:
        return None
    try:
        result = upbit.buy_market_order(ticker, amount_krw)
        logger.info(f"매수 주문 완료: {ticker} {amount_krw:,.0f}원 → {result}")
        return result
    except Exception as e:
        logger.error(f"매수 주문 실패 ({ticker}): {e}")
        return None


def sell_market_order(ticker: str, volume: float):
    """
    시장가 매도 주문을 실행합니다.
    volume: 매도할 코인 수량
    반환값: 주문 결과 dict 또는 None
    """
    upbit = get_upbit_client()
    if not upbit:
        return None
    try:
        result = upbit.sell_market_order(ticker, volume)
        logger.info(f"매도 주문 완료: {ticker} {volume} → {result}")
        return result
    except Exception as e:
        logger.error(f"매도 주문 실패 ({ticker}): {e}")
        return None
