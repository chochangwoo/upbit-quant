"""
backtest/alt_data/onchain.py - 온체인 데이터 수집

CoinGlass 및 공개 API에서 온체인 지표를 수집합니다.
주요 지표:
  - BTC 거래소 유입/유출량 (Exchange Netflow)
  - BTC 도미넌스 (시장 점유율)
  - 총 시가총액 변화율

활용:
  - 거래소 유입 급증 → 매도 압력 시그널
  - BTC 도미넌스 상승 → 알트코인 약세 시그널
  - ML 피처로 시장 매크로 환경 반영
"""

import os
import requests
import pandas as pd
import numpy as np
from loguru import logger
from datetime import datetime, timedelta


CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def fetch_btc_dominance(days: int = 800) -> pd.DataFrame:
    """
    CoinGecko 무료 API에서 BTC 도미넌스와 총 시가총액을 수집합니다.

    반환값:
        DataFrame (index: DatetimeIndex, columns: ["btc_dominance", "total_market_cap"])
    """
    cache_file = os.path.join(CACHE_DIR, "btc_dominance.csv")

    if os.path.exists(cache_file):
        cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        last_date = cached.index.max()
        if last_date.date() >= (datetime.now() - timedelta(days=2)).date():
            logger.info(f"[BTC도미넌스] 캐시 사용 ({len(cached)}일)")
            return cached

    logger.info("[BTC도미넌스] API 수집 시작")

    try:
        # CoinGecko /global/market_cap_chart - 시가총액 차트 (무료)
        url = "https://api.coingecko.com/api/v3/global"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json().get("data", {})

        current_dominance = data.get("market_cap_percentage", {}).get("btc", 0)
        total_mcap = data.get("total_market_cap", {}).get("usd", 0)

        # 과거 데이터: BTC 시가총액 차트에서 추정
        btc_url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        btc_resp = requests.get(
            btc_url,
            params={"vs_currency": "usd", "days": min(days, 365), "interval": "daily"},
            timeout=30,
        )
        btc_resp.raise_for_status()
        btc_mcaps = btc_resp.json().get("market_caps", [])

        total_url = "https://api.coingecko.com/api/v3/global/market_cap_chart"
        total_params = {"vs_currency": "usd", "days": min(days, 365)}
        try:
            total_resp = requests.get(total_url, params=total_params, timeout=30)
            total_resp.raise_for_status()
            total_mcaps = total_resp.json().get("market_cap_chart", {}).get("market_cap", [])
        except Exception:
            total_mcaps = []

        rows = []
        if btc_mcaps:
            for item in btc_mcaps:
                ts = item[0] / 1000
                date = pd.Timestamp(datetime.fromtimestamp(ts).date())
                btc_mcap = item[1]
                rows.append({
                    "date": date,
                    "btc_market_cap": btc_mcap,
                })

        if not rows:
            logger.warning("[BTC도미넌스] 데이터 수집 실패, 빈 DataFrame 반환")
            return pd.DataFrame(columns=["btc_dominance", "total_market_cap"])

        df = pd.DataFrame(rows).set_index("date").sort_index()
        df = df[~df.index.duplicated(keep="last")]

        # 총 시가총액 매칭
        if total_mcaps:
            total_dict = {}
            for item in total_mcaps:
                ts = item[0] / 1000
                date = pd.Timestamp(datetime.fromtimestamp(ts).date())
                total_dict[date] = item[1]
            total_series = pd.Series(total_dict).reindex(df.index).ffill()
            df["total_market_cap"] = total_series
        else:
            # 도미넌스로 추정
            df["total_market_cap"] = df["btc_market_cap"] / (current_dominance / 100)

        df["btc_dominance"] = (df["btc_market_cap"] / df["total_market_cap"]) * 100
        df = df[["btc_dominance", "total_market_cap"]]

        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_csv(cache_file)
        logger.info(f"[BTC도미넌스] 수집 완료: {len(df)}일")

        return df

    except Exception as e:
        logger.error(f"[BTC도미넌스] 수집 실패: {e}")
        if os.path.exists(cache_file):
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return pd.DataFrame(columns=["btc_dominance", "total_market_cap"])


def get_onchain_features(days: int = 800) -> pd.DataFrame:
    """
    온체인 데이터를 ML 피처용으로 가공합니다.

    반환값:
        DataFrame columns:
        - btc_dom          : BTC 도미넌스 (%)
        - btc_dom_ma7      : 7일 이동평균
        - btc_dom_change_7d: 7일 변화량
        - btc_dom_trend    : 상승(1) / 하락(-1) / 횡보(0)
        - total_mcap_change_7d: 총 시가총액 7일 변화율
        - total_mcap_change_30d: 총 시가총액 30일 변화율
    """
    df = fetch_btc_dominance(days)
    if df.empty:
        return pd.DataFrame()

    features = pd.DataFrame(index=df.index)
    features["btc_dom"] = df["btc_dominance"]
    features["btc_dom_ma7"] = df["btc_dominance"].rolling(7, min_periods=1).mean()
    features["btc_dom_change_7d"] = df["btc_dominance"].diff(7)

    # 도미넌스 추세 분류
    dom_change = df["btc_dominance"].diff(14)
    features["btc_dom_trend"] = 0
    features.loc[dom_change > 1, "btc_dom_trend"] = 1
    features.loc[dom_change < -1, "btc_dom_trend"] = -1

    # 총 시가총액 변화율
    if "total_market_cap" in df.columns:
        features["total_mcap_change_7d"] = df["total_market_cap"].pct_change(7)
        features["total_mcap_change_30d"] = df["total_market_cap"].pct_change(30)
    else:
        features["total_mcap_change_7d"] = 0
        features["total_mcap_change_30d"] = 0

    return features
