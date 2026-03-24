"""
backtest/alt_data/fear_greed.py - 공포 & 탐욕 지수 수집

Alternative.me 무료 API에서 Crypto Fear & Greed Index를 수집합니다.
지수 범위: 0(극도의 공포) ~ 100(극도의 탐욕)

활용:
  - 공포 구간(0~25): 역추세 매수 시그널
  - 탐욕 구간(75~100): 과열 경고, 매도 시그널
  - ML 피처로 활용 시 시장 심리 반영 가능
"""

import os
import json
import requests
import pandas as pd
from loguru import logger
from datetime import datetime, timedelta


CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "fear_greed.csv")
API_URL = "https://api.alternative.me/fng/"


def fetch_fear_greed(days: int = 800) -> pd.DataFrame:
    """
    공포탐욕 지수를 수집합니다. 캐시가 있으면 캐시를 우선 사용합니다.

    매개변수:
        days: 수집할 일수 (기본 800일)
    반환값:
        DataFrame (index: DatetimeIndex, columns: ["fear_greed", "classification"])
        - fear_greed: 0~100 정수
        - classification: "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    """
    # 캐시 확인
    if os.path.exists(CACHE_FILE):
        cached = pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        last_date = cached.index.max()
        if last_date.date() >= (datetime.now() - timedelta(days=2)).date():
            logger.info(f"[공포탐욕] 캐시 사용 ({len(cached)}일)")
            return cached

    logger.info(f"[공포탐욕] API 수집 시작 ({days}일)")

    try:
        response = requests.get(
            API_URL,
            params={"limit": days, "format": "json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json().get("data", [])

        if not data:
            logger.warning("[공포탐욕] 데이터 없음")
            return pd.DataFrame(columns=["fear_greed", "classification"])

        rows = []
        for item in data:
            ts = int(item["timestamp"])
            date = datetime.fromtimestamp(ts).date()
            rows.append({
                "date": pd.Timestamp(date),
                "fear_greed": int(item["value"]),
                "classification": item["value_classification"],
            })

        df = pd.DataFrame(rows).set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")]

        # 캐시 저장
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(CACHE_FILE)
        logger.info(f"[공포탐욕] 수집 완료: {len(df)}일")

        return df

    except Exception as e:
        logger.error(f"[공포탐욕] 수집 실패: {e}")
        if os.path.exists(CACHE_FILE):
            logger.info("[공포탐욕] 이전 캐시로 대체")
            return pd.read_csv(CACHE_FILE, index_col=0, parse_dates=True)
        return pd.DataFrame(columns=["fear_greed", "classification"])


def get_fear_greed_features(days: int = 800) -> pd.DataFrame:
    """
    공포탐욕 지수를 ML 피처용으로 가공합니다.

    반환값:
        DataFrame columns:
        - fg_value       : 원시 지수 (0~100)
        - fg_ma7         : 7일 이동평균
        - fg_ma30        : 30일 이동평균
        - fg_change_7d   : 7일 변화량
        - fg_extreme_fear: 극도의 공포 여부 (bool)
        - fg_extreme_greed: 극도의 탐욕 여부 (bool)
    """
    df = fetch_fear_greed(days)
    if df.empty:
        return pd.DataFrame()

    features = pd.DataFrame(index=df.index)
    features["fg_value"] = df["fear_greed"]
    features["fg_ma7"] = df["fear_greed"].rolling(7, min_periods=1).mean()
    features["fg_ma30"] = df["fear_greed"].rolling(30, min_periods=1).mean()
    features["fg_change_7d"] = df["fear_greed"].diff(7)
    features["fg_extreme_fear"] = (df["fear_greed"] <= 25).astype(int)
    features["fg_extreme_greed"] = (df["fear_greed"] >= 75).astype(int)

    return features
