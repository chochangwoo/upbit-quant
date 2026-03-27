"""
Supabase 데이터베이스 연동 모듈
매매 내역, 수익률 등을 DB에 저장합니다.

supabase 라이브러리의 proxy 호환 문제로 REST API를 직접 호출합니다.

trades 테이블 스키마:
  strategy_name TEXT, ticker TEXT, side TEXT ('buy'/'sell'),
  price NUMERIC, amount NUMERIC, signal TEXT, ma5 NUMERIC, ma20 NUMERIC
"""
import os
import requests
from loguru import logger


def _get_headers() -> dict | None:
    """Supabase REST API 헤더를 생성합니다."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.error(".env 파일에 SUPABASE_URL과 SUPABASE_KEY를 입력하세요!")
        return None

    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _get_base_url() -> str | None:
    """Supabase REST API 베이스 URL을 반환합니다."""
    url = os.getenv("SUPABASE_URL")
    if not url:
        return None
    return f"{url}/rest/v1"


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
    headers = _get_headers()
    base_url = _get_base_url()
    if not headers or not base_url:
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
        resp = requests.post(f"{base_url}/trades", headers=headers, json=data, timeout=10)
        resp.raise_for_status()
        logger.info(f"매매 내역 저장 완료: {side} {ticker} ({signal})")
        return True
    except Exception as e:
        logger.error(f"매매 내역 저장 실패: {e}")
        return False


def save_strategy_state(strategy_name: str, key: str, value: str) -> bool:
    """
    전략 상태를 DB에 저장합니다 (컨테이너 재시작 시에도 유지).

    strategy_state 테이블: strategy_name TEXT, key TEXT, value TEXT, updated_at TIMESTAMPTZ
    (strategy_name, key)가 PK → upsert 방식으로 저장
    """
    headers = _get_headers()
    base_url = _get_base_url()
    if not headers or not base_url:
        return False

    try:
        data = {
            "strategy_name": strategy_name,
            "key": key,
            "value": value,
        }
        upsert_headers = {**headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        resp = requests.post(
            f"{base_url}/strategy_state",
            headers=upsert_headers,
            json=data,
            timeout=10,
        )
        resp.raise_for_status()
        logger.debug(f"전략 상태 저장: {strategy_name}/{key} = {value}")
        return True
    except Exception as e:
        logger.error(f"전략 상태 저장 실패: {e}")
        return False


def load_strategy_state(strategy_name: str, key: str) -> str | None:
    """전략 상태를 DB에서 로드합니다."""
    headers = _get_headers()
    base_url = _get_base_url()
    if not headers or not base_url:
        return None

    try:
        resp = requests.get(
            f"{base_url}/strategy_state",
            headers=headers,
            params={
                "select": "value",
                "strategy_name": f"eq.{strategy_name}",
                "key": f"eq.{key}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0]["value"]
        return None
    except Exception as e:
        logger.error(f"전략 상태 로드 실패: {e}")
        return None


def query_table(table: str, select: str = "*", filters: dict = None) -> list:
    """
    테이블을 조회합니다 (범용).

    매개변수:
        table  : 테이블 이름
        select : 조회할 컬럼 (기본: 전체)
        filters: PostgREST 필터 딕셔너리 (예: {"created_at": "gte.2026-03-26"})
    """
    headers = _get_headers()
    base_url = _get_base_url()
    if not headers or not base_url:
        return []

    try:
        params = {"select": select}
        if filters:
            params.update(filters)
        resp = requests.get(f"{base_url}/{table}", headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"테이블 조회 실패 ({table}): {e}")
        return []


def insert_table(table: str, data: dict) -> bool:
    """
    테이블에 데이터를 삽입합니다 (범용).

    매개변수:
        table: 테이블 이름
        data : 삽입할 데이터 딕셔너리
    """
    headers = _get_headers()
    base_url = _get_base_url()
    if not headers or not base_url:
        return False

    try:
        resp = requests.post(f"{base_url}/{table}", headers=headers, json=data, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"테이블 삽입 실패 ({table}): {e}")
        return False
