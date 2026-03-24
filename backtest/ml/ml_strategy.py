"""
backtest/ml/ml_strategy.py - ML 기반 매매 전략

LightGBM 예측 확률을 기반으로 포트폴리오 비중을 결정합니다.
기존 전략 인터페이스(get_weights)를 준수하여 백테스트 엔진과 호환됩니다.

핵심 로직:
  1. IS 기간 데이터로 LightGBM 학습
  2. 각 코인의 상승 확률 예측
  3. 상위 K개 코인을 확률 가중 배분
  4. OOS 기간 종료 시 재학습 (적응형)
"""

import numpy as np
import pandas as pd
from loguru import logger

try:
    import lightgbm as lgb
    from sklearn.preprocessing import StandardScaler
    HAS_ML = True
except ImportError:
    HAS_ML = False

from backtest.ml.feature_engineer import build_coin_features


class MLStrategy:
    """
    ML 기반 포트폴리오 전략

    기존 backtest/engine.py와 호환되는 get_weights() 인터페이스를 제공합니다.

    사용법:
        strategy = MLStrategy(top_k=5, retrain_days=30)
        result = run_backtest(strategy, prices, volumes, oos_window=30)
    """

    def __init__(
        self,
        top_k: int = 5,
        retrain_days: int = 30,
        train_days: int = 180,
        target_horizon: int = 5,
        alt_data: pd.DataFrame = None,
        weight_mode: str = "confidence",
        n_estimators: int = 200,
    ):
        """
        매개변수:
            top_k         : 선택할 상위 코인 수
            retrain_days  : 모델 재학습 주기 (일)
            train_days    : 학습 데이터 기간 (일)
            target_horizon: 수익률 예측 기간 (일)
            alt_data      : 대안 데이터 DataFrame
            weight_mode   : "equal" (균등) 또는 "confidence" (확률 가중)
            n_estimators  : LightGBM 부스팅 라운드 수
        """
        if not HAS_ML:
            raise ImportError("lightgbm, scikit-learn 설치 필요")

        self.top_k = top_k
        self.retrain_days = retrain_days
        self.train_days = train_days
        self.target_horizon = target_horizon
        self.alt_data = alt_data
        self.weight_mode = weight_mode
        self.n_estimators = n_estimators

        self.name = f"ML_LightGBM(K{top_k}_H{target_horizon})"
        self.model = None
        self.scaler = None
        self.last_train_date = None
        self.feature_cols = None

    def _train_model(self, prices, volumes, end_date, lookback_prices):
        """IS 데이터로 모델을 학습합니다."""
        coins = prices.columns.tolist()

        # 학습 데이터 범위
        train_dates = lookback_prices.index
        if len(train_dates) < 60:
            return False

        X_list, y_list = [], []

        for coin in coins:
            features = build_coin_features(prices, volumes, coin, self.alt_data)
            if features.empty:
                continue

            # 타겟: target_horizon일 후 수익률 > 0
            close = prices[coin]
            future_ret = close.shift(-self.target_horizon) / close - 1

            # 학습 기간에 해당하는 데이터만
            valid_dates = features.index.intersection(train_dates)
            valid_dates = valid_dates[valid_dates.isin(future_ret.dropna().index)]

            if len(valid_dates) < 20:
                continue

            X_coin = features.loc[valid_dates]
            y_coin = (future_ret.loc[valid_dates] > 0).astype(int)

            X_list.append(X_coin)
            y_list.append(y_coin)

        if not X_list:
            return False

        X_train = pd.concat(X_list, axis=0)
        y_train = pd.concat(y_list, axis=0)

        # NaN/Inf 제거
        valid = X_train.notna().all(axis=1) & y_train.notna() & ~np.isinf(X_train).any(axis=1)
        X_train = X_train[valid]
        y_train = y_train[valid]

        if len(X_train) < 50:
            return False

        self.feature_cols = X_train.columns.tolist()

        # 스케일링
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_train)
        X_scaled = np.nan_to_num(X_scaled, nan=0, posinf=0, neginf=0)

        # LightGBM 학습
        params = {
            "objective": "binary",
            "metric": "auc",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_child_samples": 20,
            "lambda_l1": 0.1,
            "lambda_l2": 0.1,
            "verbose": -1,
            "seed": 42,
        }

        train_data = lgb.Dataset(X_scaled, label=y_train.values)
        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=self.n_estimators,
        )

        self.last_train_date = end_date
        return True

    def get_weights(self, prices, volumes, date, lookback_prices) -> pd.Series:
        """
        ML 모델로 코인별 상승 확률을 예측하고 포트폴리오 비중을 반환합니다.

        기존 전략과 동일한 인터페이스:
          - prices         : 전체 가격 데이터
          - volumes        : 전체 거래량 데이터
          - date           : 현재 날짜
          - lookback_prices: IS 시작 ~ 현재까지의 가격 데이터
        반환값:
          - pd.Series (코인별 비중, 합계=1.0) 또는 빈 Series
        """
        # 재학습 필요 여부 판단
        need_retrain = (
            self.model is None
            or self.last_train_date is None
            or (date - self.last_train_date).days >= self.retrain_days
        )

        if need_retrain:
            success = self._train_model(prices, volumes, date, lookback_prices)
            if not success:
                return pd.Series(dtype=float)

        # 각 코인의 상승 확률 예측
        coin_proba = {}
        coins = prices.columns.tolist()

        for coin in coins:
            features = build_coin_features(prices, volumes, coin, self.alt_data)
            if features.empty or date not in features.index:
                continue

            # 해당 날짜의 피처 추출
            row = features.loc[[date]]

            # 피처 정렬 (학습 시 사용된 컬럼과 동일하게)
            missing_cols = set(self.feature_cols) - set(row.columns)
            for col in missing_cols:
                row[col] = 0
            row = row[self.feature_cols]

            # 스케일링 및 예측
            try:
                x_scaled = self.scaler.transform(row)
                x_scaled = np.nan_to_num(x_scaled, nan=0, posinf=0, neginf=0)
                proba = self.model.predict(x_scaled)[0]
                coin_proba[coin] = proba
            except Exception:
                continue

        if not coin_proba:
            return pd.Series(dtype=float)

        # 상위 K개 코인 선택
        proba_series = pd.Series(coin_proba).sort_values(ascending=False)
        top_coins = proba_series.head(self.top_k)

        # 최소 확률 임계값 (50% 이상만)
        top_coins = top_coins[top_coins > 0.5]
        if len(top_coins) == 0:
            return pd.Series(dtype=float)

        # 비중 결정
        if self.weight_mode == "equal":
            weights = pd.Series(1.0 / len(top_coins), index=top_coins.index)
        else:
            # 확률 가중 (확률이 높을수록 더 많은 비중)
            excess_proba = top_coins - 0.5  # 50% 초과분 기준
            weights = excess_proba / excess_proba.sum()

        return weights
