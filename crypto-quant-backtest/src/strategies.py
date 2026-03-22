"""
크립토 멀티에셋 퀀트 전략 모듈

8가지 전략 유형:
1. 크로스섹셔널 모멘텀 (Cross-Sectional Momentum)
2. 변동성 가중 포트폴리오 (Risk Parity Lite)
3. 통합 전략 (모멘텀 + 변동성 가중 + 거래량 시그널)
4. RSI 역추세 (Mean Reversion)
5. 듀얼 모멘텀 (단기 + 장기)
6. 거래량 브레이크아웃
7. 추세추종 이동평균 크로스
8. 모멘텀 반전 (단기 하락 후 반등)
"""

import numpy as np
import pandas as pd


def _volume_filter(volumes: pd.DataFrame, date, columns, quantile=0.2):
    """거래량 하위 quantile% 코인 제외 필터"""
    if volumes is None or volumes.empty:
        return columns
    vol_window = min(7, len(volumes.loc[:date]))
    recent_vol = volumes.loc[:date].tail(vol_window).mean()
    recent_vol = recent_vol.reindex(columns).dropna()
    if len(recent_vol) > 2:
        threshold = recent_vol.quantile(quantile)
        return recent_vol[recent_vol >= threshold].index
    return columns


def _inverse_volatility_weights(daily_returns: pd.DataFrame, lookback: int) -> pd.Series:
    """역변동성 비중 계산"""
    if len(daily_returns) < lookback:
        return pd.Series(dtype=float)
    vol = daily_returns.tail(lookback).std()
    vol = vol[vol > 0]
    if len(vol) == 0:
        return pd.Series(dtype=float)
    inv_vol = 1.0 / vol
    return inv_vol / inv_vol.sum()


class CrossSectionalMomentum:
    """
    크로스섹셔널 모멘텀: 최근 N일 수익률 상위 K개 동일비중
    """
    def __init__(self, lookback: int = 14, top_k: int = 5):
        self.lookback = lookback
        self.top_k = top_k
        self.name = f"모멘텀(L{lookback}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.lookback:
            return pd.Series(dtype=float)

        valid_coins = _volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0 or len(available) < self.lookback:
            return pd.Series(dtype=float)

        returns = available.iloc[-1] / available.iloc[-self.lookback] - 1
        returns = returns.dropna()
        if len(returns) == 0:
            return pd.Series(dtype=float)

        top_coins = returns.nlargest(min(self.top_k, len(returns)))
        return pd.Series(1.0 / len(top_coins), index=top_coins.index)


class RiskParityLite:
    """변동성 가중 포트폴리오: 역변동성 비중"""
    def __init__(self, vol_lookback: int = 20):
        self.vol_lookback = vol_lookback
        self.name = f"리스크패리티(V{vol_lookback})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.vol_lookback:
            return pd.Series(dtype=float)
        daily_returns = available.pct_change().dropna()
        return _inverse_volatility_weights(daily_returns, self.vol_lookback)


class CombinedStrategy:
    """통합 전략: 모멘텀 순위 × 거래량 시그널 → 상위 K개 역변동성 가중"""
    def __init__(self, mom_lookback: int = 14, vol_lookback: int = 20, top_k: int = 5):
        self.mom_lookback = mom_lookback
        self.vol_lookback = vol_lookback
        self.top_k = top_k
        self.name = f"통합(M{mom_lookback}_V{vol_lookback}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < max(self.mom_lookback, self.vol_lookback):
            return pd.Series(dtype=float)

        coins = available.columns
        momentum = available.iloc[-1] / available.iloc[-self.mom_lookback] - 1
        momentum = momentum.dropna()
        if len(momentum) == 0:
            return pd.Series(dtype=float)

        mom_rank = momentum.rank(ascending=True)

        # 거래량 변화 시그널
        vol_change = pd.Series(0.0, index=coins)
        if volumes is not None and not volumes.empty:
            vol_data = volumes.loc[:date]
            for coin in coins:
                if coin in vol_data.columns:
                    v = vol_data[coin].dropna()
                    if len(v) >= 30:
                        avg_7 = v.tail(7).mean()
                        avg_30 = v.tail(30).mean()
                        if avg_30 > 0:
                            vol_change[coin] = avg_7 / avg_30 - 1

        common = mom_rank.index.intersection(vol_change.index)
        composite = mom_rank[common] * (1 + vol_change[common] * 0.3)
        top_coins = composite.nlargest(min(self.top_k, len(composite))).index

        daily_returns = available[top_coins].pct_change().dropna()
        weights = _inverse_volatility_weights(daily_returns, self.vol_lookback)
        if len(weights) == 0:
            return pd.Series(1.0 / len(top_coins), index=top_coins)
        return weights


class RSIMeanReversion:
    """
    RSI 역추세 전략: RSI 과매도 코인을 매수

    - 14일 RSI 계산
    - RSI < threshold인 코인 중 가장 낮은 K개 매수
    - 과매도 반등을 노리는 역추세 전략
    """
    def __init__(self, rsi_period: int = 14, threshold: int = 40, top_k: int = 5):
        self.rsi_period = rsi_period
        self.threshold = threshold
        self.top_k = top_k
        self.name = f"RSI역추세(P{rsi_period}_T{threshold}_K{top_k})"

    def _calc_rsi(self, series: pd.Series) -> float:
        delta = series.diff().dropna()
        if len(delta) < self.rsi_period:
            return 50.0
        gain = delta.where(delta > 0, 0.0).tail(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0.0)).tail(self.rsi_period).mean()
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.rsi_period + 1:
            return pd.Series(dtype=float)

        valid_coins = _volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]

        # 각 코인의 RSI 계산
        rsi_values = {}
        for coin in available.columns:
            rsi = self._calc_rsi(available[coin])
            if rsi < self.threshold:
                rsi_values[coin] = rsi

        if not rsi_values:
            # 과매도 코인이 없으면 RSI가 가장 낮은 K개 선택
            for coin in available.columns:
                rsi_values[coin] = self._calc_rsi(available[coin])

        rsi_series = pd.Series(rsi_values)
        # RSI 낮은 순서로 K개 선택 (과매도 = 반등 기대)
        selected = rsi_series.nsmallest(min(self.top_k, len(rsi_series)))
        return pd.Series(1.0 / len(selected), index=selected.index)


class DualMomentum:
    """
    듀얼 모멘텀: 단기 + 장기 모멘텀 결합

    - 장기 모멘텀(60일)으로 상승 추세 필터
    - 단기 모멘텀(7~14일)으로 순위 결정
    - 장기 모멘텀 > 0인 코인 중 단기 모멘텀 상위 K개
    """
    def __init__(self, short_lookback: int = 7, long_lookback: int = 60, top_k: int = 5):
        self.short_lookback = short_lookback
        self.long_lookback = long_lookback
        self.top_k = top_k
        self.name = f"듀얼모멘텀(S{short_lookback}_L{long_lookback}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.long_lookback:
            return pd.Series(dtype=float)

        valid_coins = _volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0 or len(available) < self.long_lookback:
            return pd.Series(dtype=float)

        # 장기 모멘텀 필터: > 0 (상승 추세)
        long_mom = available.iloc[-1] / available.iloc[-self.long_lookback] - 1
        uptrend = long_mom[long_mom > 0].index

        if len(uptrend) == 0:
            # 상승 추세 코인이 없으면 장기 모멘텀 상위 절반
            uptrend = long_mom.nlargest(max(1, len(long_mom) // 2)).index

        # 단기 모멘텀으로 순위
        short_mom = available[uptrend].iloc[-1] / available[uptrend].iloc[-self.short_lookback] - 1
        short_mom = short_mom.dropna()
        if len(short_mom) == 0:
            return pd.Series(dtype=float)

        selected = short_mom.nlargest(min(self.top_k, len(short_mom)))
        return pd.Series(1.0 / len(selected), index=selected.index)


class VolumeBreakout:
    """
    거래량 브레이크아웃: 거래량 급증 + 가격 상승 코인

    - 최근 5일 평균 거래량 / 이전 20일 평균 거래량 > vol_ratio
    - 동시에 최근 N일 가격 상승인 코인만 선택
    - 조건 충족 코인 중 거래량 비율 상위 K개
    """
    def __init__(self, price_lookback: int = 5, vol_ratio: float = 1.5, top_k: int = 5):
        self.price_lookback = price_lookback
        self.vol_ratio = vol_ratio
        self.top_k = top_k
        self.name = f"거래량돌파(P{price_lookback}_R{vol_ratio}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < 30:
            return pd.Series(dtype=float)
        if volumes is None or volumes.empty:
            return pd.Series(dtype=float)

        vol_data = volumes.loc[:date]
        scores = {}

        for coin in available.columns:
            if coin not in vol_data.columns:
                continue
            v = vol_data[coin].dropna()
            if len(v) < 25:
                continue

            avg_5 = v.tail(5).mean()
            avg_20 = v.iloc[-25:-5].mean()
            if avg_20 <= 0:
                continue

            vol_ratio = avg_5 / avg_20

            # 가격 상승 확인
            p = available[coin]
            if len(p) < self.price_lookback:
                continue
            price_change = p.iloc[-1] / p.iloc[-self.price_lookback] - 1

            if vol_ratio >= self.vol_ratio and price_change > 0:
                scores[coin] = vol_ratio

        if not scores:
            # 조건 충족 코인이 없으면 거래량 비율 상위 K개 (가격 상승 필터만)
            for coin in available.columns:
                if coin not in vol_data.columns:
                    continue
                v = vol_data[coin].dropna()
                if len(v) < 25:
                    continue
                avg_5 = v.tail(5).mean()
                avg_20 = v.iloc[-25:-5].mean()
                if avg_20 > 0:
                    p = available[coin]
                    price_change = p.iloc[-1] / p.iloc[-self.price_lookback] - 1
                    if price_change > 0:
                        scores[coin] = avg_5 / avg_20

        if not scores:
            return pd.Series(dtype=float)

        score_series = pd.Series(scores)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))
        return pd.Series(1.0 / len(selected), index=selected.index)


class MACrossRotation:
    """
    이동평균 크로스 로테이션

    - 단기 MA > 장기 MA인 코인만 선택 (골든크로스)
    - 선택된 코인 중 (단기MA/장기MA - 1) 비율 상위 K개
    - 역변동성 가중
    """
    def __init__(self, short_ma: int = 5, long_ma: int = 20, top_k: int = 5):
        self.short_ma = short_ma
        self.long_ma = long_ma
        self.top_k = top_k
        self.name = f"MA크로스(S{short_ma}_L{long_ma}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.long_ma:
            return pd.Series(dtype=float)

        valid_coins = _volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0:
            return pd.Series(dtype=float)

        scores = {}
        for coin in available.columns:
            short_avg = available[coin].tail(self.short_ma).mean()
            long_avg = available[coin].tail(self.long_ma).mean()
            if long_avg > 0 and short_avg > long_avg:
                scores[coin] = short_avg / long_avg - 1

        if not scores:
            # 골든크로스 코인 없으면 비율 상위 K개
            for coin in available.columns:
                short_avg = available[coin].tail(self.short_ma).mean()
                long_avg = available[coin].tail(self.long_ma).mean()
                if long_avg > 0:
                    scores[coin] = short_avg / long_avg - 1

        if not scores:
            return pd.Series(dtype=float)

        score_series = pd.Series(scores)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))

        # 역변동성 가중
        daily_returns = available[selected.index].pct_change().dropna()
        weights = _inverse_volatility_weights(daily_returns, min(20, len(daily_returns)))
        if len(weights) == 0:
            return pd.Series(1.0 / len(selected), index=selected.index)
        return weights


class MomentumReversal:
    """
    모멘텀 반전 전략: 단기 하락 후 반등 시그널

    - 중기(30일) 모멘텀 양수 (전체 추세 상승)
    - 단기(5일) 하락 후 최근 2일 반등 시작
    - 조건: 30일 수익률 > 0, 5일 수익률 < 0, 2일 수익률 > 0
    """
    def __init__(self, mid_lookback: int = 30, short_lookback: int = 5, top_k: int = 5):
        self.mid_lookback = mid_lookback
        self.short_lookback = short_lookback
        self.top_k = top_k
        self.name = f"반전(M{mid_lookback}_S{short_lookback}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.mid_lookback:
            return pd.Series(dtype=float)

        valid_coins = _volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0:
            return pd.Series(dtype=float)

        scores = {}
        for coin in available.columns:
            p = available[coin]
            mid_ret = p.iloc[-1] / p.iloc[-self.mid_lookback] - 1
            short_ret = p.iloc[-1] / p.iloc[-self.short_lookback] - 1
            bounce_ret = p.iloc[-1] / p.iloc[-2] - 1 if len(p) >= 2 else 0

            # 이상적 조건: 중기 상승 + 단기 하락 + 반등
            if mid_ret > 0 and short_ret < 0 and bounce_ret > 0:
                scores[coin] = bounce_ret  # 반등 강도
            elif mid_ret > 0 and short_ret < -0.05:
                # 중기 상승 + 단기 급락 (반등 아직 안 해도 매수 기회)
                scores[coin] = -short_ret * 0.5  # 하락폭에 비례

        if not scores:
            # 조건 충족 없으면 중기 모멘텀 상위 K개 (단기 하락 우선)
            for coin in available.columns:
                p = available[coin]
                mid_ret = p.iloc[-1] / p.iloc[-self.mid_lookback] - 1
                short_ret = p.iloc[-1] / p.iloc[-self.short_lookback] - 1
                if mid_ret > 0:
                    scores[coin] = mid_ret - short_ret  # 단기 하락폭 반영

        if not scores:
            return pd.Series(dtype=float)

        score_series = pd.Series(scores)
        selected = score_series.nlargest(min(self.top_k, len(score_series)))
        return pd.Series(1.0 / len(selected), index=selected.index)


class AdaptiveMomentum:
    """
    적응형 모멘텀: 시장 변동성에 따라 룩백 기간 자동 조절

    - 시장 변동성 높으면 → 짧은 룩백 (빠른 반응)
    - 시장 변동성 낮으면 → 긴 룩백 (안정적 추세)
    - BTC 20일 변동성 기준으로 적응
    """
    def __init__(self, short_lb: int = 5, long_lb: int = 30, top_k: int = 5):
        self.short_lb = short_lb
        self.long_lb = long_lb
        self.top_k = top_k
        self.name = f"적응형모멘텀(S{short_lb}_L{long_lb}_K{top_k})"

    def get_weights(self, prices, volumes, date, lookback_prices):
        available = lookback_prices.dropna(axis=1, how="any")
        if available.shape[1] == 0 or len(available) < self.long_lb:
            return pd.Series(dtype=float)

        valid_coins = _volume_filter(volumes, date, available.columns)
        available = available[available.columns.intersection(valid_coins)]
        if available.shape[1] == 0 or len(available) < self.long_lb:
            return pd.Series(dtype=float)

        # BTC 변동성으로 적응형 룩백 결정
        btc_col = "KRW-BTC"
        if btc_col in available.columns:
            btc_vol = available[btc_col].pct_change().tail(20).std()
            # 변동성 높으면(>4%) 짧은 룩백, 낮으면(<2%) 긴 룩백
            if btc_vol > 0.04:
                lookback = self.short_lb
            elif btc_vol < 0.02:
                lookback = self.long_lb
            else:
                # 선형 보간
                ratio = (btc_vol - 0.02) / 0.02
                lookback = int(self.long_lb - ratio * (self.long_lb - self.short_lb))
        else:
            lookback = (self.short_lb + self.long_lb) // 2

        lookback = max(self.short_lb, min(lookback, len(available) - 1))

        returns = available.iloc[-1] / available.iloc[-lookback] - 1
        returns = returns.dropna()
        if len(returns) == 0:
            return pd.Series(dtype=float)

        selected = returns.nlargest(min(self.top_k, len(returns)))
        return pd.Series(1.0 / len(selected), index=selected.index)


def get_all_strategy_configs() -> list[dict]:
    """전체 전략 × 파라미터 조합을 반환한다."""
    configs = []

    # 1. 크로스섹셔널 모멘텀
    for lookback in [7, 14, 21]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": CrossSectionalMomentum(lookback=lookback, top_k=top_k),
                "params": {"lookback": lookback, "top_k": top_k},
            })

    # 2. 리스크 패리티
    for vol_lookback in [20, 60]:
        configs.append({
            "strategy": RiskParityLite(vol_lookback=vol_lookback),
            "params": {"vol_lookback": vol_lookback},
        })

    # 3. 통합 전략
    for mom_lookback in [7, 14]:
        for top_k in [5, 7]:
            configs.append({
                "strategy": CombinedStrategy(mom_lookback=mom_lookback, vol_lookback=20, top_k=top_k),
                "params": {"mom_lookback": mom_lookback, "vol_lookback": 20, "top_k": top_k},
            })

    # 4. RSI 역추세
    for threshold in [30, 40]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": RSIMeanReversion(rsi_period=14, threshold=threshold, top_k=top_k),
                "params": {"rsi_period": 14, "threshold": threshold, "top_k": top_k},
            })

    # 5. 듀얼 모멘텀
    for short_lb in [7, 14]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": DualMomentum(short_lookback=short_lb, long_lookback=60, top_k=top_k),
                "params": {"short_lookback": short_lb, "long_lookback": 60, "top_k": top_k},
            })

    # 6. 거래량 브레이크아웃
    for vol_ratio in [1.3, 1.5, 2.0]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": VolumeBreakout(price_lookback=5, vol_ratio=vol_ratio, top_k=top_k),
                "params": {"price_lookback": 5, "vol_ratio": vol_ratio, "top_k": top_k},
            })

    # 7. MA 크로스 로테이션
    for short_ma, long_ma in [(5, 20), (10, 30), (3, 10)]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": MACrossRotation(short_ma=short_ma, long_ma=long_ma, top_k=top_k),
                "params": {"short_ma": short_ma, "long_ma": long_ma, "top_k": top_k},
            })

    # 8. 모멘텀 반전
    for mid_lb in [20, 30]:
        for top_k in [3, 5]:
            configs.append({
                "strategy": MomentumReversal(mid_lookback=mid_lb, short_lookback=5, top_k=top_k),
                "params": {"mid_lookback": mid_lb, "short_lookback": 5, "top_k": top_k},
            })

    # 9. 적응형 모멘텀
    for top_k in [3, 5]:
        configs.append({
            "strategy": AdaptiveMomentum(short_lb=5, long_lb=30, top_k=top_k),
            "params": {"short_lb": 5, "long_lb": 30, "top_k": top_k},
        })

    return configs
