"""
backtest/coin_screener/data_collector.py - Upbit 전체 코인 일봉 데이터 수집 + 캐싱

Upbit KRW 마켓 전체 코인의 일봉 데이터를 수집하고,
로컬 CSV 파일에 캐싱하여 반복 실행 시 재수집을 방지합니다.
"""
import os
import time
import pandas as pd
import pyupbit
from loguru import logger


class DataCollector:
    """
    Upbit KRW 마켓 전체 코인의 일봉 데이터를 수집하고 캐싱하는 클래스.
    """

    def __init__(self, cache_dir: str = None, min_volume_krw: float = 1e8):
        """
        매개변수:
            cache_dir      : 데이터 캐시 디렉토리 경로
            min_volume_krw : 최소 일평균 거래대금 (기본 1억원, 미만 코인 제외)
        """
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        self.cache_dir = cache_dir
        self.min_volume_krw = min_volume_krw
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_krw_tickers(self) -> list:
        """
        Upbit KRW 마켓에 상장된 전체 코인 티커 목록을 반환합니다.
        API 실패 시 3회 재시도 후 빈 리스트를 반환합니다.
        """
        for attempt in range(3):
            try:
                tickers = pyupbit.get_tickers(fiat="KRW")
                if tickers:
                    logger.info(f"KRW 마켓 코인 수: {len(tickers)}개")
                    return tickers
            except Exception as e:
                logger.warning(f"티커 목록 조회 실패 (시도 {attempt + 1}/3): {e}")
                time.sleep(1)
        logger.error("티커 목록 조회 최종 실패")
        return []

    def _cache_path(self, ticker: str) -> str:
        """캐시 파일 경로를 생성합니다."""
        safe_name = ticker.replace("-", "_")
        return os.path.join(self.cache_dir, f"{safe_name}.csv")

    def _load_cache(self, ticker: str) -> pd.DataFrame:
        """캐시 파일이 존재하면 로드합니다."""
        path = self._cache_path(ticker)
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, index_col=0, parse_dates=True)
                if not df.empty:
                    return df
            except Exception:
                pass
        return None

    def _save_cache(self, ticker: str, df: pd.DataFrame):
        """데이터를 CSV 캐시 파일로 저장합니다."""
        path = self._cache_path(ticker)
        df.to_csv(path)

    def fetch_ohlcv(self, ticker: str, days: int = 120) -> pd.DataFrame:
        """
        단일 코인의 일봉 데이터를 수집합니다.
        캐시가 있고 충분한 데이터가 있으면 캐시를 사용합니다.

        매개변수:
            ticker: 코인 티커 (예: "KRW-BTC")
            days  : 수집할 일수 (기본 120일)
        반환값:
            OHLCV DataFrame, 실패 시 None
        """
        # 캐시 확인
        cached = self._load_cache(ticker)
        if cached is not None and len(cached) >= days:
            return cached.tail(days)

        # API로 수집 (3회 재시도)
        for attempt in range(3):
            try:
                df = pyupbit.get_ohlcv(ticker, interval="day", count=days + 30)
                if df is not None and not df.empty:
                    self._save_cache(ticker, df)
                    return df
            except Exception as e:
                logger.warning(f"[{ticker}] 데이터 수집 실패 (시도 {attempt + 1}/3): {e}")
                time.sleep(0.5)

        logger.error(f"[{ticker}] 데이터 수집 최종 실패")
        return None

    def collect_all(self, days: int = 120) -> dict:
        """
        KRW 마켓 전체 코인의 일봉 데이터를 수집합니다.

        매개변수:
            days: 수집할 일수
        반환값:
            {ticker: DataFrame} 딕셔너리
            - 데이터 부족(20일 미만) 코인은 제외
            - 일평균 거래대금 기준 미달 코인은 제외
        """
        tickers = self.get_krw_tickers()
        all_data = {}
        skipped = 0

        for i, ticker in enumerate(tickers):
            logger.info(f"[{i + 1}/{len(tickers)}] {ticker} 데이터 수집 중...")
            df = self.fetch_ohlcv(ticker, days)

            if df is None or len(df) < 20:
                logger.warning(f"[{ticker}] 데이터 부족 (20일 미만) → 제외")
                skipped += 1
                continue

            # 일평균 거래대금 필터링
            avg_volume = (df["close"] * df["volume"]).mean()
            if avg_volume < self.min_volume_krw:
                logger.info(f"[{ticker}] 일평균 거래대금 {avg_volume:,.0f}원 → 기준 미달 제외")
                skipped += 1
                continue

            all_data[ticker] = df
            time.sleep(0.15)  # API 호출 제한 준수

        logger.info(f"데이터 수집 완료: {len(all_data)}개 코인 (제외: {skipped}개)")
        return all_data
