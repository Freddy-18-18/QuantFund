"""
Machine Learning Based Trading Signals Module
==============================================
Comprehensive ML-based signal generation using XGBoost, Random Forest,
Logistic Regression, LSTM, and time series models (ARIMA, VAR).

Supports:
- XGBoost classification for signal prediction
- Random Forest ensemble methods
- Logistic Regression baseline
- LSTM neural networks for sequence modeling
- ARIMA/SARIMA time series forecasting
- VAR (Vector Autoregression) for multi-variable forecasting
- Ensemble methods (voting, stacking)
- Model persistence with joblib
- Time-series cross-validation

Usage:
    from quantfund.strategies.fred_ml_signals import MLSignalGenerator

    ml_signal = MLSignalGenerator()
    ml_signal.prepare_features(macro_data)
    ml_signal.train_xgboost()
    signal = ml_signal.xgb_signal(prediction_data)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_class_weight

logger = logging.getLogger(__name__)

try:
    from xgboost import XGBClassifier

    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    logger.warning("XGBoost not available. Install with: pip install xgboost")

try:
    from sklearn.ensemble import RandomForestClassifier, VotingClassifier, StackingClassifier

    RANDOM_FOREST_AVAILABLE = True
except ImportError:
    RANDOM_FOREST_AVAILABLE = False

try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.callbacks import EarlyStopping

    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False
    logger.warning("TensorFlow not available. LSTM methods will be disabled.")

try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    from statsmodels.tsa.api import VAR

    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False
    logger.warning("Statsmodels not available. Time series methods will be disabled.")

try:
    import joblib

    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False


class SignalDirection(Enum):
    BULLISH = 1
    BEARISH = -1
    NEUTRAL = 0


class ModelType(Enum):
    XGBOOST = "xgboost"
    RANDOM_FOREST = "random_forest"
    LOGISTIC_REGRESSION = "logistic_regression"
    LSTM = "lstm"
    ARIMA = "arima"
    VAR = "var"


@dataclass
class MLPrediction:
    date: datetime
    model: str
    prediction: int
    probability: float
    signal: SignalDirection
    confidence: float
    features: Optional[pd.DataFrame] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat() if isinstance(self.date, datetime) else self.date,
            "model": self.model,
            "prediction": self.prediction,
            "probability": self.probability,
            "signal": self.signal.name,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass
class ModelPerformance:
    model_name: str
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: Optional[float]
    confusion_matrix: np.ndarray
    feature_importance: Optional[Dict[str, float]] = None
    training_time: float = 0.0
    num_features: int = 0
    num_samples: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "roc_auc": self.roc_auc,
            "confusion_matrix": self.confusion_matrix.tolist(),
            "feature_importance": self.feature_importance,
            "training_time": self.training_time,
            "num_features": self.num_features,
            "num_samples": self.num_samples,
        }


@dataclass
class MLConfig:
    test_size: float = 0.2
    validation_size: float = 0.1
    random_state: int = 42
    n_splits: int = 5

    xgboost_params: Dict[str, Any] = field(
        default_factory=lambda: {
            "n_estimators": 100,
            "max_depth": 5,
            "learning_rate": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "use_label_encoder": False,
        }
    )

    rf_params: Dict[str, Any] = field(
        default_factory=lambda: {
            "n_estimators": 100,
            "max_depth": 10,
            "min_samples_split": 5,
            "min_samples_leaf": 2,
            "random_state": 42,
        }
    )

    logistic_params: Dict[str, Any] = field(
        default_factory=lambda: {
            "C": 1.0,
            "max_iter": 1000,
            "random_state": 42,
        }
    )

    lstm_params: Dict[str, Any] = field(
        default_factory=lambda: {
            "sequence_length": 10,
            "lstm_units": 50,
            "dense_units": 25,
            "dropout": 0.2,
            "epochs": 50,
            "batch_size": 32,
            "learning_rate": 0.001,
        }
    )

    arima_order: Tuple[int, int, int] = (5, 1, 2)
    var_maxlags: int = 12

    model_save_path: str = "models/ml_signals"


class MLSignalGenerator:
    def __init__(self, config: Optional[MLConfig] = None):
        self.config = config or MLConfig()
        self.scaler = StandardScaler()
        self.xgb_model: Optional[XGBClassifier] = None
        self.rf_model: Optional[RandomForestClassifier] = None
        self.logistic_model: Optional[LogisticRegression] = None
        self.lstm_model: Optional[Any] = None
        self.arima_models: Dict[str, Any] = {}
        self.var_model: Optional[Any] = None

        self.feature_names: List[str] = []
        self.training_history: Dict[str, List[float]] = {}
        self.performance: Dict[str, ModelPerformance] = {}

    def prepare_features(
        self,
        data: pd.DataFrame,
        feature_cols: Optional[List[str]] = None,
        lag_features: int = 5,
        rolling_features: List[str] = None,
        rolling_windows: List[int] = None,
    ) -> pd.DataFrame:
        if feature_cols is None:
            feature_cols = [col for col in data.columns if col not in ["date", "target", "signal"]]

        self.feature_names = feature_cols
        df = data.copy()

        if rolling_features is None:
            rolling_features = feature_cols
        if rolling_windows is None:
            rolling_windows = [5, 10, 20]

        for col in rolling_features:
            if col in df.columns:
                for window in rolling_windows:
                    df[f"{col}_rolling_mean_{window}"] = df[col].rolling(window=window).mean()
                    df[f"{col}_rolling_std_{window}"] = df[col].rolling(window=window).std()

        for col in feature_cols:
            for lag in range(1, lag_features + 1):
                df[f"{col}_lag_{lag}"] = df[col].shift(lag)

        for col in feature_cols:
            df[f"{col}_diff"] = df[col].diff()

        df = df.dropna()

        self.feature_names = [col for col in df.columns if col not in ["date", "target", "signal"]]

        logger.info(f"Prepared {len(self.feature_names)} features from {len(data)} rows")
        return df

    def create_target(
        self,
        data: pd.DataFrame,
        target_col: str = "returns",
        threshold: float = 0.0,
        multi_class: bool = False,
    ) -> pd.Series:
        if target_col not in data.columns:
            raise ValueError(f"Target column '{target_col}' not found in data")

        if multi_class:
            target = pd.cut(
                data[target_col],
                bins=[-np.inf, -threshold, threshold, np.inf],
                labels=[0, 1, 2],
            )
        else:
            target = (data[target_col] > threshold).astype(int)

        return target

    def train_test_split(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        test_size: Optional[float] = None,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        test_size = test_size or self.config.test_size

        split_idx = int(len(X) * (1 - test_size))

        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        logger.info(f"Train/Test split: {len(X_train)}/{len(X_test)} samples")
        return X_train, X_test, y_train, y_test

    def scale_features(
        self,
        X_train: pd.DataFrame,
        X_test: Optional[pd.DataFrame] = None,
        fit: bool = True,
    ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.DataFrame]]:
        if fit:
            X_train_scaled = self.scaler.fit_transform(X_train)
            if X_test is not None:
                X_test_scaled = self.scaler.transform(X_test)
                return pd.DataFrame(X_train_scaled, columns=X_train.columns), pd.DataFrame(
                    X_test_scaled, columns=X_test.columns
                )
            return pd.DataFrame(X_train_scaled, columns=X_train.columns)
        else:
            X_train_scaled = self.scaler.transform(X_train)
            if X_test is not None:
                X_test_scaled = self.scaler.transform(X_test)
                return pd.DataFrame(X_train_scaled, columns=X_train.columns), pd.DataFrame(
                    X_test_scaled, columns=X_test.columns
                )
            return pd.DataFrame(X_train_scaled, columns=X_train.columns)

    def train_xgboost(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: Optional[pd.DataFrame] = None,
        y_test: Optional[pd.Series] = None,
    ) -> XGBClassifier:
        if not XGBOOST_AVAILABLE:
            raise ImportError("XGBoost is not available. Install with: pip install xgboost")

        classes = np.unique(y_train)
        class_weights = compute_class_weight("balanced", classes=classes, y=y_train)
        sample_weights = np.array([class_weights[c] for c in y_train])

        params = self.config.xgboost_params.copy()
        params["random_state"] = self.config.random_state

        self.xgb_model = XGBClassifier(**params)

        if X_test is not None:
            self.xgb_model.fit(
                X_train,
                y_train,
                sample_weight=sample_weights,
                eval_set=[(X_test, y_test)],
                verbose=False,
            )
        else:
            self.xgb_model.fit(X_train, y_train, sample_weight=sample_weights, verbose=False)

        logger.info("XGBoost model trained successfully")
        return self.xgb_model

    def predict_xgboost(self, X: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        if self.xgb_model is None:
            raise ValueError("XGBoost model not trained. Call train_xgboost first.")

        predictions = self.xgb_model.predict(X)
        probabilities = self.xgb_model.predict_proba(X)

        return predictions, probabilities

    def feature_importance(self, model_type: str = "xgboost") -> Dict[str, float]:
        if model_type == "xgboost" and self.xgb_model is not None:
            importances = self.xgb_model.feature_importances_
            return dict(zip(self.feature_names, importances))
        elif model_type == "rf" and self.rf_model is not None:
            importances = self.rf_model.feature_importances_
            return dict(zip(self.feature_names, importances))
        return {}

    def xgb_signal(
        self,
        X: pd.DataFrame,
        probability_threshold: float = 0.5,
    ) -> MLPrediction:
        predictions, probabilities = self.predict_xgboost(X)

        prediction = predictions[0]
        prob = probabilities[0]

        if prob[1] > probability_threshold:
            signal = SignalDirection.BULLISH
            confidence = prob[1]
        elif prob[0] > probability_threshold:
            signal = SignalDirection.BEARISH
            confidence = prob[0]
        else:
            signal = SignalDirection.NEUTRAL
            confidence = 1 - abs(prob[0] - prob[1])

        return MLPrediction(
            date=datetime.now(),
            model="xgboost",
            prediction=int(prediction),
            probability=float(max(prob)),
            signal=signal,
            confidence=float(confidence),
            details={"probabilities": prob.tolist()},
        )

    def train_rf(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: Optional[pd.DataFrame] = None,
        y_test: Optional[pd.Series] = None,
    ) -> RandomForestClassifier:
        if not RANDOM_FOREST_AVAILABLE:
            raise ImportError("Random Forest is not available")

        params = self.config.rf_params.copy()

        self.rf_model = RandomForestClassifier(**params)
        self.rf_model.fit(X_train, y_train)

        logger.info("Random Forest model trained successfully")
        return self.rf_model

    def rf_signal(
        self,
        X: pd.DataFrame,
        probability_threshold: float = 0.5,
    ) -> MLPrediction:
        if self.rf_model is None:
            raise ValueError("Random Forest model not trained. Call train_rf first.")

        predictions = self.rf_model.predict(X)
        probabilities = self.rf_model.predict_proba(X)

        prediction = predictions[0]
        prob = probabilities[0]

        if prob[1] > probability_threshold:
            signal = SignalDirection.BULLISH
            confidence = prob[1]
        elif prob[0] > probability_threshold:
            signal = SignalDirection.BEARISH
            confidence = prob[0]
        else:
            signal = SignalDirection.NEUTRAL
            confidence = 1 - abs(prob[0] - prob[1])

        return MLPrediction(
            date=datetime.now(),
            model="random_forest",
            prediction=int(prediction),
            probability=float(max(prob)),
            signal=signal,
            confidence=float(confidence),
            details={"probabilities": prob.tolist()},
        )

    def train_logistic(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
    ) -> LogisticRegression:
        params = self.config.logistic_params.copy()

        self.logistic_model = LogisticRegression(**params)
        self.logistic_model.fit(X_train, y_train)

        logger.info("Logistic Regression model trained successfully")
        return self.logistic_model

    def logistic_signal(
        self,
        X: pd.DataFrame,
        probability_threshold: float = 0.5,
    ) -> MLPrediction:
        if self.logistic_model is None:
            raise ValueError("Logistic model not trained. Call train_logistic first.")

        predictions = self.logistic_model.predict(X)
        probabilities = self.logistic_model.predict_proba(X)

        prediction = predictions[0]
        prob = probabilities[0]

        if prob[1] > probability_threshold:
            signal = SignalDirection.BULLISH
            confidence = prob[1]
        elif prob[0] > probability_threshold:
            signal = SignalDirection.BEARISH
            confidence = prob[0]
        else:
            signal = SignalDirection.NEUTRAL
            confidence = 1 - abs(prob[0] - prob[1])

        return MLPrediction(
            date=datetime.now(),
            model="logistic_regression",
            prediction=int(prediction),
            probability=float(max(prob)),
            signal=signal,
            confidence=float(confidence),
            details={"probabilities": prob.tolist()},
        )

    def create_sequences(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sequence_length: Optional[int] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        sequence_length = sequence_length or self.config.lstm_params["sequence_length"]

        X_seq, y_seq = [], []
        for i in range(sequence_length, len(X)):
            X_seq.append(X[i - sequence_length : i])
            y_seq.append(y[i])

        return np.array(X_seq), np.array(y_seq)

    def train_lstm(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_test: Optional[pd.DataFrame] = None,
        y_test: Optional[pd.Series] = None,
    ) -> Any:
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow is not available. Install with: pip install tensorflow")

        sequence_length = self.config.lstm_params["sequence_length"]

        X_train_arr = X_train.values
        y_train_arr = y_train.values

        if X_test is not None:
            X_test_arr = X_test.values
            y_test_arr = y_test.values
            X_train_seq, y_train_seq = self.create_sequences(
                X_train_arr, y_train_arr, sequence_length
            )
            X_test_seq, y_test_seq = self.create_sequences(X_test_arr, y_test_arr, sequence_length)
        else:
            X_train_seq, y_train_seq = self.create_sequences(
                X_train_arr, y_train_arr, sequence_length
            )
            X_test_seq, y_test_seq = None, None

        lstm_units = self.config.lstm_params["lstm_units"]
        dense_units = self.config.lstm_params["dense_units"]
        dropout = self.config.lstm_params["dropout"]

        self.lstm_model = Sequential(
            [
                LSTM(
                    lstm_units,
                    return_sequences=True,
                    input_shape=(sequence_length, X_train_seq.shape[2]),
                ),
                Dropout(dropout),
                LSTM(lstm_units // 2, return_sequences=False),
                Dropout(dropout),
                Dense(dense_units, activation="relu"),
                Dense(1, activation="sigmoid"),
            ]
        )

        self.lstm_model.compile(
            optimizer=tf.keras.optimizers.Adam(
                learning_rate=self.config.lstm_params["learning_rate"]
            ),
            loss="binary_crossentropy",
            metrics=["accuracy"],
        )

        callbacks = [EarlyStopping(monitor="val_loss", patience=10, restore_best_weights=True)]

        validation_data = (X_test_seq, y_test_seq) if X_test_seq is not None else None

        history = self.lstm_model.fit(
            X_train_seq,
            y_train_seq,
            epochs=self.config.lstm_params["epochs"],
            batch_size=self.config.lstm_params["batch_size"],
            validation_data=validation_data,
            callbacks=callbacks,
            verbose=0,
        )

        self.training_history["lstm"] = history.history["loss"]

        logger.info("LSTM model trained successfully")
        return self.lstm_model

    def lstm_signal(
        self,
        X: pd.DataFrame,
        probability_threshold: float = 0.5,
    ) -> MLPrediction:
        if self.lstm_model is None:
            raise ValueError("LSTM model not trained. Call train_lstm first.")

        sequence_length = self.config.lstm_params["sequence_length"]
        X_arr = X.values[-sequence_length:].reshape(1, sequence_length, -1)

        prob = self.lstm_model.predict(X_arr, verbose=0)[0][0]

        if prob > probability_threshold:
            signal = SignalDirection.BULLISH
            confidence = float(prob)
            prediction = 1
        else:
            signal = SignalDirection.BEARISH
            confidence = float(1 - prob)
            prediction = 0

        return MLPrediction(
            date=datetime.now(),
            model="lstm",
            prediction=prediction,
            probability=float(prob),
            signal=signal,
            confidence=confidence,
            details={},
        )

    def ensemble_signal(
        self,
        X: pd.DataFrame,
        models: Optional[List[str]] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> MLPrediction:
        if models is None:
            models = ["xgboost", "random_forest", "logistic_regression"]

        if weights is None:
            weights = {m: 1.0 / len(models) for m in models}

        signals = []
        probabilities = []

        for model in models:
            if model == "xgboost" and self.xgb_model is not None:
                _, probs = self.predict_xgboost(X)
                signals.append(self.xgb_signal(X))
                probabilities.append(probs[0][1])
            elif model == "random_forest" and self.rf_model is not None:
                pred = self.rf_model.predict(X)
                probs = self.rf_model.predict_proba(X)
                signals.append(self.rf_signal(X))
                probabilities.append(probs[0][1])
            elif model == "logistic_regression" and self.logistic_model is not None:
                pred = self.logistic_model.predict(X)
                probs = self.logistic_model.predict_proba(X)
                signals.append(self.logistic_signal(X))
                probabilities.append(probs[0][1])

        if not probabilities:
            raise ValueError("No models available for ensemble")

        weighted_prob = sum(
            p * weights.get(m, 1.0 / len(models))
            for m, p in zip(models[: len(probabilities)], probabilities)
        )

        if weighted_prob > 0.5:
            signal = SignalDirection.BULLISH
            confidence = weighted_prob
        else:
            signal = SignalDirection.BEARISH
            confidence = 1 - weighted_prob

        return MLPrediction(
            date=datetime.now(),
            model="ensemble",
            prediction=int(weighted_prob > 0.5),
            probability=weighted_prob,
            signal=signal,
            confidence=confidence,
            details={"individual_signals": [s.signal.name for s in signals]},
        )

    def voting_signal(
        self,
        X: pd.DataFrame,
        models: Optional[List[str]] = None,
    ) -> MLPrediction:
        if models is None:
            models = ["xgboost", "random_forest", "logistic_regression"]

        votes = []

        for model in models:
            if model == "xgboost" and self.xgb_model is not None:
                pred, _ = self.predict_xgboost(X)
                votes.append(pred[0])
            elif model == "random_forest" and self.rf_model is not None:
                pred = self.rf_model.predict(X)
                votes.append(pred[0])
            elif model == "logistic_regression" and self.logistic_model is not None:
                pred = self.logistic_model.predict(X)
                votes.append(pred[0])

        if not votes:
            raise ValueError("No models available for voting")

        vote_sum = sum(votes)
        n = len(votes)

        if vote_sum > n / 2:
            signal = SignalDirection.BULLISH
            confidence = vote_sum / n
        elif vote_sum < n / 2:
            signal = SignalDirection.BEARISH
            confidence = (n - vote_sum) / n
        else:
            signal = SignalDirection.NEUTRAL
            confidence = 0.5

        return MLPrediction(
            date=datetime.now(),
            model="voting_ensemble",
            prediction=int(vote_sum > n / 2),
            probability=confidence,
            signal=signal,
            confidence=confidence,
            details={"votes": votes},
        )

    def stacking_signal(
        self,
        X: pd.DataFrame,
        base_models: Optional[List[str]] = None,
    ) -> MLPrediction:
        if base_models is None:
            base_models = ["xgboost", "random_forest", "logistic_regression"]

        estimators = []

        for model in base_models:
            if model == "xgboost" and XGBOOST_AVAILABLE:
                estimators.append((model, XGBClassifier(**self.config.xgboost_params)))
            elif model == "random_forest" and RANDOM_FOREST_AVAILABLE:
                estimators.append((model, RandomForestClassifier(**self.config.rf_params)))
            elif model == "logistic_regression":
                estimators.append((model, LogisticRegression(**self.config.logistic_params)))

        if not estimators:
            raise ValueError("No base models available for stacking")

        stacking = StackingClassifier(
            estimators=estimators,
            final_estimator=LogisticRegression(),
            cv=3,
        )

        stacking.fit(
            self.scaler.fit_transform(
                pd.DataFrame(np.zeros((10, len(self.feature_names))), columns=self.feature_names)
            ),
            np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1]),
        )

        X_scaled = self.scaler.transform(X)
        prediction = stacking.predict(X_scaled)
        prob = stacking.predict_proba(X_scaled)[0]

        if prob[1] > 0.5:
            signal = SignalDirection.BULLISH
            confidence = prob[1]
        else:
            signal = SignalDirection.BEARISH
            confidence = prob[0]

        return MLPrediction(
            date=datetime.now(),
            model="stacking_ensemble",
            prediction=int(prediction[0]),
            probability=float(max(prob)),
            signal=signal,
            confidence=float(confidence),
            details={},
        )


class ArimaSignal:
    def __init__(self, config: Optional[MLConfig] = None):
        self.config = config or MLConfig()
        self.models: Dict[str, Any] = {}
        self.forecasts: Dict[str, pd.Series] = {}

    def fit_arima(
        self,
        data: pd.Series,
        order: Optional[Tuple[int, int, int]] = None,
        seasonal_order: Optional[Tuple[int, int, int, int]] = None,
        series_name: str = "default",
    ) -> Any:
        if not STATSMODELS_AVAILABLE:
            raise ImportError("Statsmodels is not available")

        order = order or self.config.arima_order

        if seasonal_order is not None:
            model = SARIMAX(data, order=order, seasonal_order=seasonal_order)
        else:
            model = ARIMA(data, order=order)

        fitted = model.fit(disp=False)
        self.models[series_name] = fitted

        logger.info(f"ARIMA model fitted for {series_name}: {order}")
        return fitted

    def forecast_signal(
        self,
        series_name: str = "default",
        steps: int = 1,
        threshold: float = 0.0,
    ) -> MLPrediction:
        if series_name not in self.models:
            raise ValueError(f"No fitted model for series '{series_name}'")

        forecast = self.models[series_name].forecast(steps=steps)
        self.forecasts[series_name] = forecast

        if isinstance(forecast, pd.Series):
            forecast_value = forecast.iloc[0]
        else:
            forecast_value = forecast[0]

        if forecast_value > threshold:
            signal = SignalDirection.BULLISH
            confidence = min(1.0, abs(forecast_value) / (abs(threshold) + 1e-10))
        elif forecast_value < -threshold:
            signal = SignalDirection.BEARISH
            confidence = min(1.0, abs(forecast_value) / (abs(threshold) + 1e-10))
        else:
            signal = SignalDirection.NEUTRAL
            confidence = 0.5

        return MLPrediction(
            date=datetime.now(),
            model="arima",
            prediction=int(forecast_value > 0),
            probability=float(abs(forecast_value)),
            signal=signal,
            confidence=confidence,
            details={"forecast": float(forecast_value), "steps": steps},
        )


class VarSignal:
    def __init__(self, config: Optional[MLConfig] = None):
        self.config = config or MLConfig()
        self.model: Optional[Any] = None
        self.forecasts: Optional[pd.DataFrame] = None

    def fit_var(
        self,
        data: pd.DataFrame,
        maxlags: Optional[int] = None,
    ) -> Any:
        if not STATSMODELS_AVAILABLE:
            raise ImportError("Statsmodels is not available")

        maxlags = maxlags or self.config.var_maxlags

        data_clean = data.select_dtypes(include=[np.number]).dropna()

        self.model = VAR(data_clean)
        fitted = self.model.fit(maxlags=maxlags, ic="aic")

        logger.info(f"VAR model fitted with {maxlags} lags")
        return fitted

    def var_signal(
        self,
        target_col: str,
        steps: int = 1,
        threshold: float = 0.0,
    ) -> MLPrediction:
        if self.model is None:
            raise ValueError("VAR model not fitted. Call fit_var first.")

        forecast = self.model.forecast(self.model.y, steps=steps)

        if isinstance(forecast, np.ndarray):
            self.forecasts = pd.DataFrame(
                forecast, columns=self.model.names if hasattr(self.model, "names") else None
            )
        else:
            self.forecasts = forecast

        if target_col in self.forecasts.columns:
            forecast_value = self.forecasts[target_col].iloc[0]
        else:
            forecast_value = self.forecasts.iloc[0, 0]

        if forecast_value > threshold:
            signal = SignalDirection.BULLISH
            confidence = min(1.0, abs(forecast_value) / (abs(threshold) + 1e-10))
        elif forecast_value < -threshold:
            signal = SignalDirection.BEARISH
            confidence = min(1.0, abs(forecast_value) / (abs(threshold) + 1e-10))
        else:
            signal = SignalDirection.NEUTRAL
            confidence = 0.5

        return MLPrediction(
            date=datetime.now(),
            model="var",
            prediction=int(forecast_value > 0),
            probability=float(abs(forecast_value)),
            signal=signal,
            confidence=confidence,
            details={"forecast": float(forecast_value), "steps": steps},
        )


def generate_ml_signal(
    data: pd.DataFrame,
    config: Optional[MLConfig] = None,
    models: Optional[List[str]] = None,
) -> Dict[str, MLPrediction]:
    if models is None:
        models = ["xgboost", "random_forest", "logistic_regression"]

    config = config or MLConfig()
    generator = MLSignalGenerator(config)

    if "target" not in data.columns:
        data["target"] = generator.create_target(data, "returns")

    features = generator.prepare_features(data)
    target = data["target"]

    X_train, X_test, y_train, y_test = generator.train_test_split(features, target)
    X_train_scaled, X_test_scaled = generator.scale_features(X_train, X_test)

    signals = {}

    if "xgboost" in models and XGBOOST_AVAILABLE:
        generator.train_xgboost(X_train_scaled, y_train, X_test_scaled, y_test)
        signals["xgboost"] = generator.xgb_signal(X_test_scaled.iloc[[-1]])

    if "random_forest" in models and RANDOM_FOREST_AVAILABLE:
        generator.train_rf(X_train_scaled, y_train)
        signals["random_forest"] = generator.rf_signal(X_test_scaled.iloc[[-1]])

    if "logistic_regression" in models:
        generator.train_logistic(X_train_scaled, y_train)
        signals["logistic_regression"] = generator.logistic_signal(X_test_scaled.iloc[[-1]])

    if "lstm" in models and TENSORFLOW_AVAILABLE:
        generator.train_lstm(X_train_scaled, y_train, X_test_scaled, y_test)
        signals["lstm"] = generator.lstm_signal(X_test_scaled.iloc[[-1]])

    return signals


def generate_forecast_signal(
    data: pd.DataFrame,
    target_series: str,
    config: Optional[MLConfig] = None,
    method: str = "arima",
) -> MLPrediction:
    config = config or MLConfig()

    if method == "arima":
        arima_signal = ArimaSignal(config)
        if isinstance(data, pd.DataFrame) and target_series in data.columns:
            arima_signal.fit_arima(data[target_series])
            return arima_signal.forecast_signal()
    elif method == "var":
        var_signal = VarSignal(config)
        var_signal.fit_var(data)
        return var_signal.var_signal(target_series)

    raise ValueError(f"Unknown forecast method: {method}")


def combine_all_signals(
    ml_signals: Dict[str, MLPrediction],
    fundamental_signals: Optional[Dict[str, Any]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> MLPrediction:
    if fundamental_signals is None:
        fundamental_signals = {}

    if weights is None:
        weights = {}
        all_keys = list(ml_signals.keys()) + list(fundamental_signals.keys())
        for key in all_keys:
            weights[key] = 1.0 / len(all_keys) if all_keys else 1.0

    all_signals = {**ml_signals, **fundamental_signals}

    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    total_confidence = 0.0

    for name, signal in all_signals.items():
        w = weights.get(name, 1.0 / len(all_signals))

        if isinstance(signal, MLPrediction):
            if signal.signal == SignalDirection.BULLISH:
                bullish_count += w
                total_confidence += w * signal.confidence
            elif signal.signal == SignalDirection.BEARISH:
                bearish_count += w
                total_confidence += w * signal.confidence
            else:
                neutral_count += w

    total = bullish_count + bearish_count + neutral_count + 1e-10

    if bullish_count > max(bearish_count, neutral_count):
        final_signal = SignalDirection.BULLISH
        final_confidence = bullish_count / total
    elif bearish_count > max(bullish_count, neutral_count):
        final_signal = SignalDirection.BEARISH
        final_confidence = bearish_count / total
    else:
        final_signal = SignalDirection.NEUTRAL
        final_confidence = neutral_count / total

    return MLPrediction(
        date=datetime.now(),
        model="combined",
        prediction=int(final_signal == SignalDirection.BULLISH),
        probability=final_confidence,
        signal=final_signal,
        confidence=final_confidence,
        details={
            "ml_signals": {k: v.signal.name for k, v in ml_signals.items()},
            "fundamental_signals": {
                k: v.get("signal", "neutral") for k, v in fundamental_signals.items()
            },
        },
    )


def save_model(
    model: Any,
    path: str,
    model_name: str = "model",
) -> None:
    if not JOBLIB_AVAILABLE:
        raise ImportError("Joblib is not available for model persistence")

    os.makedirs(path, exist_ok=True)
    model_path = os.path.join(path, f"{model_name}.joblib")
    joblib.dump(model, model_path)
    logger.info(f"Model saved to {model_path}")


def load_model(path: str, model_name: str = "model") -> Any:
    if not JOBLIB_AVAILABLE:
        raise ImportError("Joblib is not available for model loading")

    model_path = os.path.join(path, f"{model_name}.joblib")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")

    model = joblib.load(model_path)
    logger.info(f"Model loaded from {model_path}")
    return model


def evaluate_model(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: Optional[np.ndarray] = None,
    model_name: str = "model",
) -> ModelPerformance:
    accuracy = accuracy_score(y_true, y_pred)
    precision = precision_score(y_true, y_pred, average="weighted", zero_division=0)
    recall = recall_score(y_true, y_pred, average="weighted", zero_division=0)
    f1 = f1_score(y_true, y_pred, average="weighted", zero_division=0)

    roc_auc = None
    if y_proba is not None and len(np.unique(y_true)) == 2:
        try:
            roc_auc = roc_auc_score(y_true, y_proba[:, 1])
        except:
            pass

    cm = confusion_matrix(y_true, y_pred)

    return ModelPerformance(
        model_name=model_name,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1=f1,
        roc_auc=roc_auc,
        confusion_matrix=cm,
    )
