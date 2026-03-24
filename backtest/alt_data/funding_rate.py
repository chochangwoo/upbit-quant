"""
backtest/alt_data/funding_rate.py - 펀딩비율 데이터 수집

Binance 무료 API에서 무기한 선물 펀딩비율을 수집합니다.

활용:
  - 양의 펀딩비(롱 과열): 하락 가능성 시그널
  - 음의 펀딩비(숏 과열): 상승 가능성 시그널 (숏 스퀴즈)
  - ML 피처로 시장 레버리지 수준 반영
"""

import os
import time
import requests
import pandas as pd
import numpy as np
from loguru import logger
from datetime import datetime, timedelta


CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
BINANCE_API = "https://fapi.binance.com"

# Upbit 코인 → Binance 심볼 매핑
COIN_MAP = {
    "KRW-BTC": "BTCUSDT",
    "KRW-ETH": "ETHUSDT",
    "KRW-SOL": "SOLUSDT",
    "KRW-XRP": "XRPUSDT",
    "KRW-DOGE": "DOGEUSDT",
    "KRW-ADA": "ADAUSDT",
    "KRW-AVAX": "AVAXUSDT",
    "KRW-LINK": "LINKUSDT",
    "KRW-DOT": "DOTUSDT",
    "KRW-XLM": "XLMUSDT",
    "KRW-NEAR": "NEARUSDT",
    "KRW-UNI": "UNIUSDT",
    "KRW-POL": "POLUSDT",
}


def fetch_funding_rates(symbol: str = "BTCUSDT", days: int = 365) -> pd.DataFrame:
    """
    Binance에서 특정 심볼의 펀딩비율 히스토리를 수집합니다.

    매개변수:
        symbol: Binance 선물 심볼 (예: "BTCUSDT")
        days  : 수집할 일수
    반환값:
        DataFrame (index: DatetimeIndex, columns: ["funding_rate"])
        펀딩비율은 8시간마다 기록, 일별로 평균 집계
    """
    cache_file = os.path.join(CACHE_DIR, f"funding_{symbol}.csv")

    if os.path.exists(cache_file):
        cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        last_date = cached.index.max()
        if last_date.date() >= (datetime.now() - timedelta(days=2)).date():
            return cached

    logger.info(f"[펀딩비율] {symbol} 수집 시작 ({days}일)")

    try:
        all_data = []
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        current = start_time
        while current < end_time:
            url = f"{BINANCE_API}/fapi/v1/fundingRate"
            params = {
                "symbol": symbol,
                "startTime": current,
                "limit": 1000,
            }
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            all_data.extend(data)
            current = data[-1]["fundingTime"] + 1
            time.sleep(0.2)

        if not all_data:
            return pd.DataFrame(columns=["funding_rate"])

        rows = []
        for item in all_data:
            ts = item["fundingTime"] / 1000
            rows.append({
                "datetime": pd.Timestamp(datetime.fromtimestamp(ts)),
                "funding_rate": float(item["fundingRate"]),
            })

        df = pd.DataFrame(rows)
        df["date"] = df["datetime"].dt.date
        # 일별 평균 펀딩비율 (하루 3회 → 평균)
        daily = df.groupby("date")["funding_rate"].mean().to_frame()
        daily.index = pd.to_datetime(daily.index)
        daily = daily.sort_index()

        os.makedirs(CACHE_DIR, exist_ok=True)
        daily.to_csv(cache_file)
        logger.info(f"[펀딩비율] {symbol} 수집 완료: {len(daily)}일")

        return daily

    except Exception as e:
        logger.error(f"[펀딩비율] {symbol} 수집 실패: {e}")
        if os.path.exists(cache_file):
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return pd.DataFrame(columns=["funding_rate"])


def get_funding_features(coins: list = None, days: int = 365) -> pd.DataFrame:
    """
    주요 코인의 펀딩비율을 ML 피처용으로 가공합니다.

    매개변수:
        coins: Upbit 티커 리스트 (기본: BTC, ETH, SOL)
        days : 수집 일수
    반환값:
        DataFrame columns (BTC 기준):
        - fr_btc          : BTC 일평균 펀딩비율
        - fr_btc_ma7      : 7일 이동평균
        - fr_btc_sum_7d   : 7일 누적 펀딩비율
        - fr_btc_extreme  : 극단값 여부 (|fr| > 0.001)
        - fr_avg          : 주요 코인 평균 펀딩비율
    """
    if coins is None:
        coins = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]

    all_fr = {}
    for coin in coins:
        symbol = COIN_MAP.get(coin)
        if not symbol:
            continue
        df = fetch_funding_rates(symbol, days)
        if not df.empty:
            col_name = coin.replace("KRW-", "").lower()
            all_fr[col_name] = df["funding_rate"]

    if not all_fr:
        return pd.DataFrame()

    fr_df = pd.DataFrame(all_fr)
    fr_df = fr_df.sort_index()

    features = pd.DataFrame(index=fr_df.index)

    # BTC 펀딩비율 피처
    if "btc" in fr_df.columns:
        features["fr_btc"] = fr_df["btc"]
        features["fr_btc_ma7"] = fr_df["btc"].rolling(7, min_periods=1).mean()
        features["fr_btc_sum_7d"] = fr_df["btc"].rolling(7, min_periods=1).sum()
        features["fr_btc_extreme"] = (fr_df["btc"].abs() > 0.001).astype(int)

    # 전체 평균 펀딩비율
    features["fr_avg"] = fr_df.mean(axis=1)
    features["fr_avg_ma7"] = features["fr_avg"].rolling(7, min_periods=1).mean()

    return features
