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
