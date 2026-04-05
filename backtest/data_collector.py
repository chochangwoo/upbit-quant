"""
backtest/data_collector.py - 멀티 코인 데이터 수집 모듈

업비트 API에서 13개 KRW 마켓 코인의 일봉 데이터를 수집합니다.
- 200개 제한 → 페이지네이션으로 800일 이상 수집
- CSV 캐싱: 이미 파일이 있으면 재수집 생략
"""

import os
import time
from datetime import timedelta

import pandas as pd
import pyupbit
from loguru import logger


# 백테스트 대상 코인 목록 (업비트 KRW 마켓 주요 13종)
COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]

# 데이터 캐시 폴더
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def fetch_ohlcv_full(ticker: str, days: int = 800) -> pd.DataFrame:
    """
    업비트에서 지정 코인의 일봉 데이터를 최대 days일치 수집합니다.
    200개씩 페이지네이션하여 수집 후 합칩니다.

    매개변수:
        ticker: 코인 티커 (예: "KRW-BTC")
        days  : 수집할 일수 (기본 800일 ≈ 2.2년)
    반환값:
        OHLCV DataFrame (인덱스: 날짜)
    """
    all_dfs = []
    to_date = None
    remaining = days

    while remaining > 0:
        count = min(remaining, 200)
        try:
            df = pyupbit.get_ohlcv(ticker, interval="day", count=count, to=to_date)
        except Exception as e:
            logger.error(f"  [{ticker}] 데이터 수집 오류: {e}")
            break

        if df is None or df.empty:
            break

        all_dfs.append(df)
        to_date = df.index[0] - timedelta(days=1)
        remaining -= len(df)

        # API 속도 제한 준수 (0.5초 대기)
        time.sleep(0.5)

    if not all_dfs:
        return pd.DataFrame()

    result = pd.concat(all_dfs)
    result = result[~result.index.duplicated(keep="first")]
    result.sort_index(inplace=True)
    return result


def collect_all_data(days: int = 800, force: bool = False) -> tuple:
    """
    전체 코인 데이터를 수집하고 prices.csv, volumes.csv로 저장합니다.

    매개변수:
        days : 수집할 일수 (기본 800일)
        force: True이면 기존 CSV 무시하고 재수집
    반환값:
        (prices_df, volumes_df) 튜플
        - prices_df : 종가 데이터 (인덱스: 날짜, 컬럼: 코인 티커)
        - volumes_df: 거래대금 데이터 (인덱스: 날짜, 컬럼: 코인 티커)
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    prices_path = os.path.join(DATA_DIR, "prices.csv")
    volumes_path = os.path.join(DATA_DIR, "volumes.csv")

    # 캐싱: CSV가 이미 있으면 로드
    if not force and os.path.exists(prices_path) and os.path.exists(volumes_path):
        logger.info("[데이터] 기존 CSV 파일을 로드합니다.")
        prices = pd.read_csv(prices_path, index_col=0, parse_dates=True)
        volumes = pd.read_csv(volumes_path, index_col=0, parse_dates=True)
        logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
        logger.info(f"  코인: {len(prices.columns)}개")
        return prices, volumes

    logger.info(f"[데이터] 업비트 API에서 {len(COINS)}개 코인 데이터를 수집합니다...")
    prices_dict = {}
    volumes_dict = {}

    for i, coin in enumerate(COINS, 1):
        logger.info(f"  ({i}/{len(COINS)}) {coin} 수집 중...")
        df = fetch_ohlcv_full(coin, days=days)
        if df.empty:
            logger.warning(f"    → 데이터 없음, 건너뜀")
            continue
        prices_dict[coin] = df["close"]
        volumes_dict[coin] = df["value"]  # 거래대금 (KRW)
        logger.info(f"    → {len(df)}일 수집 완료 ({df.index[0].date()} ~ {df.index[-1].date()})")

    prices = pd.DataFrame(prices_dict)
    volumes = pd.DataFrame(volumes_dict)

    # CSV로 캐시 저장
    prices.to_csv(prices_path)
    volumes.to_csv(volumes_path)

    logger.info(f"[데이터] 저장 완료!")
    logger.info(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    logger.info(f"  코인: {len(prices.columns)}개")

    return prices, volumes


def collect_ohlcv_full(days: int = 1500, force: bool = False) -> dict:
    """
    전체 코인의 OHLCV 전체 컬럼을 수집합니다 (신뢰도 강화용).

    기존 collect_all_data()는 close/value만 저장했지만,
    이 함수는 open/high/low/close/volume/value 전부 저장합니다.
    ADX, ATR, Choppiness Index 등 정밀 지표 계산에 필요합니다.

    매개변수:
        days : 수집할 일수 (기본 1500일, 약 4년)
        force: True이면 기존 캐시 무시하고 재수집
    반환값:
        dict: {
            "prices": 종가 DataFrame,
            "volumes": 거래대금 DataFrame,
            "highs": 고가 DataFrame,
            "lows": 저가 DataFrame,
            "opens": 시가 DataFrame,
            "coin_volumes": 코인 수량 거래량 DataFrame,
            "ohlcv_raw": {ticker: 원본 OHLCV DataFrame} (코인별 원본),
        }
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # 캐시 파일 경로
    cache_files = {
        "prices": os.path.join(DATA_DIR, "prices_full.csv"),
        "highs": os.path.join(DATA_DIR, "highs.csv"),
        "lows": os.path.join(DATA_DIR, "lows.csv"),
        "opens": os.path.join(DATA_DIR, "opens.csv"),
        "volumes": os.path.join(DATA_DIR, "volumes_full.csv"),
        "coin_volumes": os.path.join(DATA_DIR, "coin_volumes.csv"),
    }

    # 캐싱: 전부 있으면 로드
    if not force and all(os.path.exists(p) for p in cache_files.values()):
        logger.info("[OHLCV] 기존 캐시 파일을 로드합니다.")
        result = {}
        for key, path in cache_files.items():
            result[key] = pd.read_csv(path, index_col=0, parse_dates=True)
        logger.info(f"  기간: {result['prices'].index[0].date()} ~ {result['prices'].index[-1].date()}")
        logger.info(f"  코인: {len(result['prices'].columns)}개 | 일수: {len(result['prices'])}일")
        return result

    logger.info(f"[OHLCV] 업비트 API에서 {len(COINS)}개 코인 × {days}일 전체 OHLCV 수집...")
    data_dict = {"close": {}, "high": {}, "low": {}, "open": {}, "value": {}, "volume": {}}
    ohlcv_raw = {}

    for i, coin in enumerate(COINS, 1):
        logger.info(f"  ({i}/{len(COINS)}) {coin} 수집 중...")
        df = fetch_ohlcv_full(coin, days=days)
        if df.empty:
            logger.warning(f"    → 데이터 없음, 건너뜀")
            continue

        ohlcv_raw[coin] = df
        data_dict["close"][coin] = df["close"]
        data_dict["high"][coin] = df["high"]
        data_dict["low"][coin] = df["low"]
        data_dict["open"][coin] = df["open"]
        data_dict["value"][coin] = df["value"]
        data_dict["volume"][coin] = df["volume"]
        logger.info(f"    → {len(df)}일 수집 완료 ({df.index[0].date()} ~ {df.index[-1].date()})")

    result = {
        "prices": pd.DataFrame(data_dict["close"]),
        "highs": pd.DataFrame(data_dict["high"]),
        "lows": pd.DataFrame(data_dict["low"]),
        "opens": pd.DataFrame(data_dict["open"]),
        "volumes": pd.DataFrame(data_dict["value"]),
        "coin_volumes": pd.DataFrame(data_dict["volume"]),
    }

    # CSV로 캐시 저장
    for key, path in cache_files.items():
        result[key].to_csv(path)

    p = result["prices"]
    logger.info(f"[OHLCV] 저장 완료!")
    logger.info(f"  기간: {p.index[0].date()} ~ {p.index[-1].date()}")
    logger.info(f"  코인: {len(p.columns)}개 | 일수: {len(p)}일")

    return result
