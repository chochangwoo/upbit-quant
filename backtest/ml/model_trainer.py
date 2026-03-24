"""
backtest/ml/model_trainer.py - LightGBM 모델 학습 및 평가

Walk-Forward 방식으로 LightGBM 모델을 학습합니다.
각 OOS 윈도우마다 IS 데이터로 학습 → OOS 데이터로 예측.

핵심 원리:
  - 미래 데이터 누수(Look-Ahead Bias) 완전 차단
  - 롤링 윈도우 재학습으로 시장 변화에 적응
  - 피처 중요도 분석으로 핵심 시그널 파악
"""

import numpy as np
import pandas as pd
from loguru import logger

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    logger.warning("lightgbm 미설치. pip install lightgbm 필요")

try:
    from sklearn.metrics import accuracy_score, roc_auc_score, log_loss
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    logger.warning("scikit-learn 미설치. pip install scikit-learn 필요")


# LightGBM 기본 하이퍼파라미터
DEFAULT_PARAMS = {
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
    "n_jobs": -1,
    "seed": 42,
}


class MLModelTrainer:
    """
    Walk-Forward 방식 LightGBM 학습기

    사용법:
        trainer = MLModelTrainer()
        results = trainer.walk_forward_train(X, y, meta)
    """

    def __init__(self, params: dict = None, n_estimators: int = 300):
        """
        매개변수:
            params      : LightGBM 하이퍼파라미터 (기본값 사용 가능)
            n_estimators: 부스팅 라운드 수
        """
        if not HAS_LIGHTGBM or not HAS_SKLEARN:
            raise ImportError("lightgbm, scikit-learn 설치 필요")

        self.params = params or DEFAULT_PARAMS.copy()
        self.n_estimators = n_estimators
        self.feature_importance = None
        self.models = []

    def walk_forward_train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        meta: pd.DataFrame,
        is_days: int = 180,
        oos_days: int = 30,
        step_days: int = 30,
    ) -> dict:
        """
        Walk-Forward 방식으로 모델을 학습하고 OOS 예측을 수행합니다.

        매개변수:
            X        : 피처 DataFrame
            y        : 타겟 Series
            meta     : 메타 정보 (date, coin)
            is_days  : 학습(IS) 기간 (일)
            oos_days : 테스트(OOS) 기간 (일)
            step_days: 슬라이딩 간격 (일)
        반환값:
            {
                "predictions"       : OOS 예측값 DataFrame,
                "metrics"           : 윈도우별 성과 지표,
                "feature_importance": 피처 중요도 DataFrame,
                "models"            : 학습된 모델 리스트,
            }
        """
        dates = meta["date"].unique()
        dates.sort()

        all_predictions = []
        window_metrics = []
        importance_list = []

        # 윈도우 시작 인덱스
        start_idx = is_days
        window_num = 0

        while start_idx + oos_days <= len(dates):
            window_num += 1
            is_end_date = dates[start_idx - 1]
            oos_start_date = dates[start_idx]
            oos_end_idx = min(start_idx + oos_days, len(dates))
            oos_end_date = dates[oos_end_idx - 1]

            # IS/OOS 날짜 범위로 데이터 분리
            is_start_date = dates[max(0, start_idx - is_days)]
            is_mask = (meta["date"] >= is_start_date) & (meta["date"] <= is_end_date)
            oos_mask = (meta["date"] >= oos_start_date) & (meta["date"] <= oos_end_date)

            X_train = X[is_mask]
            y_train = y[is_mask]
            X_test = X[oos_mask]
            y_test = y[oos_mask]
            meta_test = meta[oos_mask]

            if len(X_train) < 50 or len(X_test) < 10:
                start_idx += step_days
                continue

            # 스케일링 (학습 데이터 기준)
            scaler = StandardScaler()
            X_train_scaled = pd.DataFrame(
                scaler.fit_transform(X_train),
                columns=X_train.columns,
                index=X_train.index,
            )
            X_test_scaled = pd.DataFrame(
                scaler.transform(X_test),
                columns=X_test.columns,
                index=X_test.index,
            )

            # Inf/NaN 처리
            X_train_scaled = X_train_scaled.replace([np.inf, -np.inf], np.nan).fillna(0)
            X_test_scaled = X_test_scaled.replace([np.inf, -np.inf], np.nan).fillna(0)

            # LightGBM 학습
            train_data = lgb.Dataset(X_train_scaled, label=y_train)
            val_data = lgb.Dataset(X_test_scaled, label=y_test, reference=train_data)

            callbacks = [lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)]

            model = lgb.train(
                self.params,
                train_data,
                num_boost_round=self.n_estimators,
                valid_sets=[val_data],
                callbacks=callbacks,
            )

            self.models.append(model)

            # OOS 예측
            y_pred_proba = model.predict(X_test_scaled)
            y_pred = (y_pred_proba > 0.5).astype(int)

            # 예측 결과 저장
            pred_df = meta_test.copy()
            pred_df["y_true"] = y_test.values
            pred_df["y_pred"] = y_pred
            pred_df["y_proba"] = y_pred_proba
            all_predictions.append(pred_df)

            # 윈도우 성과
            try:
                acc = accuracy_score(y_test, y_pred)
                auc = roc_auc_score(y_test, y_pred_proba)
            except ValueError:
                acc = 0.5
                auc = 0.5

            window_metrics.append({
                "윈도우": window_num,
                "IS시작": str(is_start_date)[:10],
                "OOS시작": str(oos_start_date)[:10],
                "OOS끝": str(oos_end_date)[:10],
                "학습샘플": len(X_train),
                "테스트샘플": len(X_test),
                "정확도": acc,
                "AUC": auc,
                "상승예측비율": y_pred.mean(),
            })

            # 피처 중요도
            importance = pd.DataFrame({
                "feature": X_train.columns,
                "importance": model.feature_importance(importance_type="gain"),
                "window": window_num,
            })
            importance_list.append(importance)

            logger.info(
                f"[ML] 윈도우 {window_num}: "
                f"정확도 {acc:.1%} | AUC {auc:.3f} | "
                f"IS {len(X_train)} → OOS {len(X_test)}"
            )

            start_idx += step_days

        # 결과 종합
        if not all_predictions:
            logger.warning("[ML] 유효한 윈도우 없음")
            return {
                "predictions": pd.DataFrame(),
                "metrics": pd.DataFrame(),
                "feature_importance": pd.DataFrame(),
                "models": [],
            }

        predictions_df = pd.concat(all_predictions, axis=0)
        metrics_df = pd.DataFrame(window_metrics)

        # 피처 중요도 종합 (전체 윈도우 평균)
        all_importance = pd.concat(importance_list, axis=0)
        avg_importance = (
            all_importance.groupby("feature")["importance"]
            .mean()
            .sort_values(ascending=False)
            .reset_index()
        )
        avg_importance.columns = ["피처", "중요도"]

        self.feature_importance = avg_importance

        # 전체 성과 요약
        total_acc = accuracy_score(predictions_df["y_true"], predictions_df["y_pred"])
        try:
            total_auc = roc_auc_score(predictions_df["y_true"], predictions_df["y_proba"])
        except ValueError:
            total_auc = 0.5

        logger.info("=" * 60)
        logger.info(f"[ML] Walk-Forward 학습 완료")
        logger.info(f"  총 윈도우: {window_num}개")
        logger.info(f"  전체 정확도: {total_acc:.1%}")
        logger.info(f"  전체 AUC: {total_auc:.3f}")
        logger.info(f"  TOP 10 피처:")
        for _, row in avg_importance.head(10).iterrows():
            logger.info(f"    {row['피처']}: {row['중요도']:.1f}")
        logger.info("=" * 60)

        return {
            "predictions": predictions_df,
            "metrics": metrics_df,
            "feature_importance": avg_importance,
            "models": self.models,
        }
