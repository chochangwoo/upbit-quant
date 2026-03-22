"""
업비트 API를 이용한 암호화폐 과거 데이터 수집 모듈

- 13개 KRW 마켓 코인의 일봉 데이터를 수집
- 200개 제한 → 페이지네이션으로 2년 이상 수집
- CSV 캐싱: 이미 파일이 있으면 스킵
"""

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import pyupbit

# 대상 코인 목록 (업비트 KRW 마켓)
COINS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE",
    "KRW-ADA", "KRW-AVAX", "KRW-LINK", "KRW-DOT", "KRW-XLM",
    "KRW-NEAR", "KRW-UNI", "KRW-POL",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def fetch_ohlcv_full(ticker: str, days: int = 800, interval: str = "day") -> pd.DataFrame:
    """
    업비트에서 지정 코인의 일봉 데이터를 최대 days일치 수집한다.
    200개씩 페이지네이션하여 수집 후 합친다.
    """
    all_dfs = []
    to_date = None
    remaining = days

    while remaining > 0:
        count = min(remaining, 200)
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count, to=to_date)
        except Exception as e:
            print(f"  [오류] {ticker} 데이터 수집 실패: {e}")
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


def collect_all_data(days: int = 800, force: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    전체 코인 데이터를 수집하고 prices.csv, volumes.csv로 저장한다.

    Args:
        days: 수집할 일수 (기본 800일 ≈ 2.2년)
        force: True이면 기존 CSV 무시하고 재수집

    Returns:
        (prices_df, volumes_df) — 인덱스: 날짜, 컬럼: 코인 티커
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    prices_path = os.path.join(DATA_DIR, "prices.csv")
    volumes_path = os.path.join(DATA_DIR, "volumes.csv")

    # 캐싱: CSV가 이미 있으면 로드
    if not force and os.path.exists(prices_path) and os.path.exists(volumes_path):
        print("[데이터] 기존 CSV 파일을 로드합니다.")
        prices = pd.read_csv(prices_path, index_col=0, parse_dates=True)
        volumes = pd.read_csv(volumes_path, index_col=0, parse_dates=True)
        print(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
        print(f"  코인: {len(prices.columns)}개")
        return prices, volumes

    print(f"[데이터] 업비트 API에서 {len(COINS)}개 코인 데이터를 수집합니다...")
    prices_dict = {}
    volumes_dict = {}

    for i, coin in enumerate(COINS, 1):
        print(f"  ({i}/{len(COINS)}) {coin} 수집 중...")
        df = fetch_ohlcv_full(coin, days=days)
        if df.empty:
            print(f"    → 데이터 없음, 건너뜀")
            continue
        prices_dict[coin] = df["close"]
        volumes_dict[coin] = df["value"]  # 거래대금 (KRW)
        print(f"    → {len(df)}일 수집 완료 ({df.index[0].date()} ~ {df.index[-1].date()})")

    prices = pd.DataFrame(prices_dict)
    volumes = pd.DataFrame(volumes_dict)

    # NaN 처리: 상장 전 데이터는 NaN으로 유지
    prices.to_csv(prices_path)
    volumes.to_csv(volumes_path)

    print(f"\n[데이터] 저장 완료!")
    print(f"  기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    print(f"  코인: {len(prices.columns)}개")
    print(f"  파일: {prices_path}, {volumes_path}")

    return prices, volumes


if __name__ == "__main__":
    prices, volumes = collect_all_data()
    print(f"\n가격 데이터 shape: {prices.shape}")
    print(f"거래량 데이터 shape: {volumes.shape}")
