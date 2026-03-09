#!/usr/bin/env python3
"""
Signal Generation Pipeline Script
=================================

Comprehensive signal generation pipeline for trading signals:
- Fundamental signals (macro, momentum, mean-reversion)
- Cointegration signals
- ML signals
- Composite signals
- Backtesting
- Report generation

Usage:
    python generate_signals.py --signal-type all --backtest --save
    python generate_signals.py --signal-type fundamental --asset XAUUSD
    python generate_signals.py --all --save --verbose
    python generate_signals.py --signal-type ml --start-date 2023-01-01 --end-date 2024-01-01

Options:
    --signal-type    Type of signals: fundamental, cointegration, ml, all
    --asset          Target asset (default: XAUUSD)
    --start-date     Start date for signal generation
    --end-date       End date for signal generation
    --backtest       Run backtest on generated signals
    --save           Save signals to database
    --report         Generate report
    --verbose        Detailed logging
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

from quantfund.strategies.fred_signals import (
    MacroFundamentalSignals,
    SignalPortfolio,
    Signal,
    SignalDirection,
    SignalCategory,
    SignalConfig,
)
from quantfund.strategies.fred_cointegration import (
    CointegrationAnalyzer,
    PairsTradingSignals,
    PairsConfig,
)
from quantfund.strategies.fred_ml_signals import (
    MLSignalGenerator,
    MLConfig,
    generate_ml_signal,
    combine_all_signals,
)
from quantfund.strategies.signal_store import (
    SignalStore,
    SignalData,
    SignalDirection as StoreSignalDirection,
    SignalType as StoreSignalType,
)
from quantfund.strategies.signal_backtest import (
    SignalBacktester,
    BacktestConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    signal_type: str = "all"
    asset: str = "XAUUSD"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    run_backtest: bool = False
    save_signals: bool = False
    generate_report: bool = False
    verbose: bool = False


class SignalGenerationPipeline:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.fred_signals = None
        self.cointegration_signals = None
        self.ml_signals = None
        self.signal_store = None
        self.backtester = None
        self.macro_data: Optional[pd.DataFrame] = None
        self.price_data: Optional[pd.DataFrame] = None
        self.generated_signals: Dict[str, pd.DataFrame] = {}
        self.composite_signals: Optional[pd.DataFrame] = None

    def _setup_logging(self):
        if self.config.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            for handler in logging.getLogger().handlers:
                handler.setLevel(logging.DEBUG)

    def _get_default_dates(self) -> tuple[str, str]:
        today = date.today()
        if self.config.start_date is None:
            start_date = (today - timedelta(days=365 * 3)).isoformat()
        else:
            start_date = self.config.start_date

        if self.config.end_date is None:
            end_date = today.isoformat()
        else:
            end_date = self.config.end_date

        return start_date, end_date

    def _init_signal_store(self) -> bool:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            db_url = os.environ.get("FRED_DB_URL")
        if not db_url:
            logger.warning("No DATABASE_URL found, signals will not be saved to database")
            return False

        try:
            self.signal_store = SignalStore(db_url)
            logger.info("Signal store initialized")
            return True
        except Exception as e:
            logger.warning(f"Could not initialize signal store: {e}")
            return False

    def _load_macro_data(self, start_date: str, end_date: str) -> bool:
        logger.info(f"Step 1: Loading macro data from {start_date} to {end_date}")

        use_fred = os.environ.get("USE_FRED_API", "false").lower() == "true"

        if use_fred:
            try:
                from quantfund.data.fred_client import FredClient

                api_key = os.environ.get("FRED_API_KEY")
                if not api_key:
                    logger.warning("FRED_API_KEY not set, using fallback data")
                    return self._load_fallback_data(start_date, end_date)

                client = FredClient(api_key=api_key)

                series_map = {
                    "DFII10": "DFII10",
                    "FEDFUNDS": "FEDFUNDS",
                    "DGS10": "DGS10",
                    "DGS2": "DGS2",
                    "M2SL": "M2SL",
                    "M2V": "M2V",
                    "CPIAUCSL": "CPIAUCSL",
                    "PCEPI": "PCEPI",
                    "BEILAST": "BEILAST",
                    "PAYEMS": "PAYEMS",
                    "AHISE": "AHISE",
                    "LBSSA": "LBSSA",
                    "UNRATE": "UNRATE",
                    "VIXCLS": "VIXCLS",
                    "DTINYUS": "DTINYUS",
                }

                data = {}
                for name, series_id in series_map.items():
                    try:
                        df = client.get_observations(series_id, start_date, end_date)
                        if not df.empty:
                            df = df.set_index("date").sort_index()
                            data[name] = df["value"]
                    except Exception as e:
                        logger.debug(f"Could not fetch {series_id}: {e}")

                if not data:
                    logger.warning("No macro data loaded, using fallback")
                    return self._load_fallback_data(start_date, end_date)

                self.macro_data = pd.DataFrame(data).ffill().bfill()
                logger.info(
                    f"Loaded macro data: {len(self.macro_data)} observations, {len(self.macro_data.columns)} series"
                )
                return True

            except Exception as e:
                logger.warning(f"Could not load macro data: {e}, using fallback")
                return self._load_fallback_data(start_date, end_date)
        else:
            return self._load_fallback_data(start_date, end_date)

    def _load_fallback_data(self, start_date: str, end_date: str) -> bool:
        logger.info("Loading fallback sample data")
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        dates = pd.date_range(start=start, end=end, freq="W")

        np.random.seed(42)
        n = len(dates)

        self.macro_data = pd.DataFrame(
            {
                "DFII10": np.random.uniform(0.5, 2.5, n),
                "FEDFUNDS": np.random.uniform(0, 5, n),
                "DGS10": np.random.uniform(1, 4, n),
                "DGS2": np.random.uniform(0.5, 3, n),
                "M2SL": np.arange(n) * 1000 + 20000,
                "M2V": np.random.uniform(1, 1.5, n),
                "CPIAUCSL": np.arange(n) * 2 + 250,
                "PCEPI": np.arange(n) * 2 + 240,
                "BEILAST": np.random.uniform(1, 3, n),
                "PAYEMS": np.arange(n) * 10 + 140000,
                "AHISE": np.arange(n) * 0.5 + 25,
                "LBSSA": np.random.uniform(60, 65, n),
                "UNRATE": np.random.uniform(3, 8, n),
                "VIXCLS": np.random.uniform(10, 30, n),
                "DTINYUS": np.random.uniform(95, 110, n),
            },
            index=dates,
        )

        logger.info(f"Loaded fallback data: {len(self.macro_data)} observations")
        return True

    def _load_price_data(self, start_date: str, end_date: str) -> bool:
        logger.info(f"Loading price data for {self.config.asset}")

        try:
            from quantfund.assets.xauusd.data_feeds.dukascopy import DukascopyData

            data_feed = DukascopyData()
            self.price_data = data_feed.load_data(start_date, end_date)

            if self.price_data is not None and not self.price_data.empty:
                logger.info(f"Loaded price data: {len(self.price_data)} observations")
                return True

        except Exception as e:
            logger.debug(f"Could not load price data from Dukascopy: {e}")

        return self._load_fallback_price_data(start_date, end_date)

    def _load_fallback_price_data(self, start_date: str, end_date: str) -> bool:
        logger.info("Loading fallback price data")
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        dates = pd.date_range(start=start, end=end, freq="D")

        np.random.seed(42)
        n = len(dates)

        returns = np.random.normal(0.0002, 0.01, n)
        price = 1800 * (1 + returns).cumprod()

        self.price_data = pd.DataFrame(
            {self.config.asset: price},
            index=dates,
        )

        logger.info(f"Loaded fallback price data: {len(self.price_data)} observations")
        return True

    def generate_fundamental_signals(self) -> bool:
        if self.macro_data is None:
            logger.error("No macro data available")
            return False

        logger.info("Step 2: Generating fundamental signals")

        if self.macro_data is None or self.macro_data.empty:
            logger.error("No macro data available for fundamental signals")
            return False

        self.fred_signals = MacroFundamentalSignals()

        start_date = self.config.start_date or "2020-01-01"
        end_date = self.config.end_date or date.today().isoformat()

        for col in self.macro_data.columns:
            df = self.macro_data[[col]].copy()
            df.columns = ["value"]
            cache_key = f"{col}_{start_date}_{end_date}"
            self.fred_signals._data_cache[cache_key] = df

        portfolio = self.fred_signals.generate_all_signals(start_date, end_date)

        if portfolio.signals:
            df = portfolio.to_dataframe()
            self.generated_signals["fundamental"] = df
            logger.info(f"Generated {len(portfolio.signals)} fundamental signals")

            signals_by_name = df.groupby("name")["value"].mean()
            logger.info(f"Signal summary: {signals_by_name.to_dict()}")
            return True

        ry_signal = self.fred_signals.real_yield_signal(
            self.macro_data["DFII10"], self.macro_data["DGS10"]
        )
        ff_signal = self.fred_signals.fed_funds_signal(self.macro_data["FEDFUNDS"])
        yc_signal = self.fred_signals.yield_curve_signal(
            self.macro_data["DGS10"], self.macro_data["DGS2"]
        )
        m2_signal = self.m2_growth_signal(self.macro_data["M2SL"])
        vix_signal = self.fred_signals.vix_spike_signal(self.macro_data["VIXCLS"])
        dxy_signal = self.fred_signals.dollar_strength_signal(self.macro_data["DTINYUS"])

        signals_dict = {
            "real_yield": ry_signal,
            "fed_funds": ff_signal,
            "yield_curve": yc_signal,
            "m2_growth": m2_signal,
            "vix_spike": vix_signal,
            "dollar_strength": dxy_signal,
        }

        all_signals = []
        for name, sig in signals_dict.items():
            if sig is not None and not sig.empty:
                sig_df = sig.to_frame(name=name)
                all_signals.append(sig_df)

        if all_signals:
            combined = pd.concat(all_signals, axis=1)
            self.generated_signals["fundamental"] = combined
            logger.info(f"Generated fundamental signals: {list(signals_dict.keys())}")
            return True

        logger.warning("No fundamental signals generated")
        return False

    def m2_growth_signal(self, m2: pd.Series) -> pd.Series:
        lookback = 52
        m2_pct_change = m2.pct_change(lookback)
        threshold = 0.05
        signal = pd.Series(0.0, index=m2.index)
        signal[m2_pct_change > threshold * 2] = 1.0
        signal[m2_pct_change < -threshold] = -0.5
        return signal.fillna(0.0)

    def generate_cointegration_signals(self) -> bool:
        if self.macro_data is None:
            logger.error("No macro data available")
            return False

        logger.info("Step 3: Generating cointegration signals")

        try:
            config = PairsConfig()
            self.cointegration_signals = PairsTradingSignals(config)

            pairs_data = {}
            for col in self.macro_data.columns:
                if self.macro_data[col].notna().sum() > 30:
                    pairs_data[col] = self.macro_data[col]

            if len(pairs_data) < 2:
                logger.warning("Not enough data for cointegration")
                return False

            results = self.cointegration_signals.run_batch_analysis(
                pairs_data,
                self.config.start_date,
                self.config.end_date,
            )

            cointegration_signals = []
            for pair_name, result in results.items():
                if result.is_cointegrated and result.half_life:
                    hedge_ratio = result.hedge_ratio or 1.0
                    series_list = list(pairs_data.keys())
                    if len(series_list) >= 2:
                        spread = (
                            pairs_data[series_list[0]] - hedge_ratio * pairs_data[series_list[1]]
                        )

                        zscore_window = 20
                        rolling_mean = spread.rolling(zscore_window).mean()
                        rolling_std = spread.rolling(zscore_window).std().replace(0, 1)
                        zscore = (spread - rolling_mean) / rolling_std

                        signal = pd.DataFrame(
                            {
                                "date": spread.index,
                                "pair_name": pair_name,
                                "signal": np.clip(zscore, -1, 1),
                                "spread": spread,
                            }
                        ).set_index("date")

                        cointegration_signals.append(signal["signal"])

            if cointegration_signals:
                combined = pd.concat(cointegration_signals, axis=1).mean(axis=1)
                combined.name = "cointegration"
                self.generated_signals["cointegration"] = combined.to_frame()
                logger.info(f"Generated cointegration signals for {len(results)} pairs")
                return True

        except Exception as e:
            logger.warning(f"Cointegration signal generation failed: {e}")

        return False

    def generate_ml_signals(self) -> bool:
        if self.macro_data is None:
            logger.error("No macro data available")
            return False

        logger.info("Step 4: Generating ML signals")

        try:
            data = self.macro_data.copy()

            if self.price_data is not None:
                price_col = self.config.asset
                if price_col in self.price_data.columns:
                    data["returns"] = self.price_data[price_col].pct_change()

            data = data.dropna()

            if len(data) < 50:
                logger.warning("Insufficient data for ML signals")
                return False

            if "returns" not in data.columns:
                data["returns"] = np.random.normal(0, 0.01, len(data))

            data["target"] = (data["returns"] > 0).astype(int)

            feature_cols = [c for c in data.columns if c not in ["returns", "target"]]
            ml_config = MLConfig()
            self.ml_signals = MLSignalGenerator(ml_config)

            features = self.ml_signals.prepare_features(
                data[feature_cols],
                feature_cols=feature_cols,
                lag_features=3,
            )

            target = data["target"].loc[features.index]

            X_train, X_test, y_train, y_test = self.ml_signals.train_test_split(
                features, target, test_size=0.2
            )

            if len(X_train) < 10 or len(X_test) < 5:
                logger.warning("Insufficient training data for ML")
                return False

            X_train_scaled = self.ml_signals.scale_features(X_train, X_test)

            try:
                self.ml_signals.train_xgboost(X_train_scaled, y_train, X_test, y_test)
            except Exception as e:
                logger.debug(f"XGBoost training failed: {e}")

            try:
                self.ml_signals.train_rf(X_train_scaled, y_train)
            except Exception as e:
                logger.debug(f"Random Forest training failed: {e}")

            try:
                self.ml_signals.train_logistic(X_train_scaled, y_train)
            except Exception as e:
                logger.debug(f"Logistic regression training failed: {e}")

            if X_test is not None and len(X_test) > 0:
                ml_signal_values = []
                for idx in X_test.index:
                    row = X_test.loc[[idx]]
                    try:
                        if self.ml_signals.xgb_model is not None:
                            pred = self.ml_signals.xgb_signal(row)
                            ml_signal_values.append({"date": idx, "signal": pred.signal.value})
                    except:
                        pass

                if ml_signal_values:
                    ml_df = pd.DataFrame(ml_signal_values).set_index("date")
                    self.generated_signals["ml"] = ml_df
                    logger.info(f"Generated {len(ml_signal_values)} ML signals")
                    return True

        except Exception as e:
            logger.warning(f"ML signal generation failed: {e}")

        return False

    def generate_momentum_signals(self) -> bool:
        if self.macro_data is None:
            logger.error("No macro data available")
            return False

        logger.info("Generating momentum signals")

        momentum_signals = {}

        for col in self.macro_data.columns:
            series = self.macro_data[col].dropna()
            if len(series) > 20:
                mom_20 = series.pct_change(20)
                mom_60 = series.pct_change(60)

                signal = pd.Series(0.0, index=series.index)
                signal[mom_20 > 0] = 0.5
                signal[mom_20 < 0] = -0.5
                signal[(mom_20 > 0) & (mom_60 > 0)] = 1.0
                signal[(mom_20 < 0) & (mom_60 < 0)] = -1.0

                momentum_signals[col] = signal

        if momentum_signals:
            combined = pd.DataFrame(momentum_signals).mean(axis=1)
            combined.name = "momentum"
            self.generated_signals["momentum"] = combined.to_frame()
            logger.info("Generated momentum signals")
            return True

        return False

    def generate_mean_reversion_signals(self) -> bool:
        if self.macro_data is None:
            logger.error("No macro data available")
            return False

        logger.info("Generating mean reversion signals")

        mr_signals = {}

        for col in self.macro_data.columns:
            series = self.macro_data[col].dropna()
            if len(series) > 20:
                rolling_mean = series.rolling(20).mean()
                rolling_std = series.rolling(20).std().replace(0, 1)
                zscore = (series - rolling_mean) / rolling_std

                signal = pd.Series(0.0, index=series.index)
                signal[zscore > 1.5] = -0.5
                signal[zscore < -1.5] = 0.5
                signal[(zscore >= -0.5) & (zscore <= 0.5)] = (
                    -zscore[(zscore >= -0.5) & (zscore <= 0.5)] * 0.3
                )

                mr_signals[col] = signal

        if mr_signals:
            combined = pd.DataFrame(mr_signals).mean(axis=1)
            combined.name = "mean_reversion"
            self.generated_signals["mean_reversion"] = combined.to_frame()
            logger.info("Generated mean reversion signals")
            return True

        return False

    def generate_inflation_signals(self) -> bool:
        if self.macro_data is None or "CPIAUCSL" not in self.macro_data.columns:
            return False

        logger.info("Generating inflation signals")

        try:
            cpi = self.macro_data["CPIAUCSL"].dropna()
            cpi_yoy = cpi.pct_change(12) * 100

            signal = pd.Series(0.0, index=cpi.index)
            signal[cpi_yoy > 4] = 1.0
            signal[cpi_yoy < 2] = -0.5
            signal[(cpi_yoy >= 2) & (cpi_yoy <= 4)] = (
                cpi_yoy[(cpi_yoy >= 2) & (cpi_yoy <= 4)] - 3
            ) / 2

            signal.name = "inflation"
            self.generated_signals["inflation"] = signal.to_frame()
            logger.info("Generated inflation signals")
            return True

        except Exception as e:
            logger.warning(f"Inflation signal generation failed: {e}")
            return False

    def generate_real_yield_signals(self) -> bool:
        if self.macro_data is None:
            return False

        logger.info("Generating real yield signals")

        try:
            if "DFII10" not in self.macro_data.columns or "DGS10" not in self.macro_data.columns:
                return False

            tips = self.macro_data["DFII10"].dropna()
            nominal = self.macro_data["DGS10"].reindex(tips.index)

            real_yield = tips - nominal

            zscore_window = 252
            rolling_mean = real_yield.rolling(zscore_window, min_periods=20).mean()
            rolling_std = real_yield.rolling(zscore_window, min_periods=20).std().replace(0, 1)
            zscore = (real_yield - rolling_mean) / rolling_std

            signal = pd.Series(0.0, index=real_yield.index)
            signal[zscore < -1] = 1.0
            signal[zscore > 1] = -0.5
            signal[(zscore >= -1) & (zscore <= 1)] = np.clip(
                -zscore[(zscore >= -1) & (zscore <= 1)] * 0.5, -1, 1
            )

            signal.name = "real_yield"
            self.generated_signals["real_yield"] = signal.to_frame()
            logger.info("Generated real yield signals")
            return True

        except Exception as e:
            logger.warning(f"Real yield signal generation failed: {e}")
            return False

    def generate_dollar_strength_signals(self) -> bool:
        if self.macro_data is None or "DTINYUS" not in self.macro_data.columns:
            return False

        logger.info("Generating dollar strength signals")

        try:
            dxy = self.macro_data["DTINYUS"].dropna()
            dxy_change = dxy.pct_change(20)

            signal = pd.Series(0.0, index=dxy.index)
            signal[dxy > 105] = -0.75
            signal[dxy < 95] = 0.5
            signal[(dxy >= 95) & (dxy <= 105)] = -(dxy[(dxy >= 95) & (dxy <= 105)] - 100) / 20

            signal.name = "dollar_strength"
            self.generated_signals["dollar_strength"] = signal.to_frame()
            logger.info("Generated dollar strength signals")
            return True

        except Exception as e:
            logger.warning(f"Dollar strength signal generation failed: {e}")
            return False

    def generate_risk_off_signals(self) -> bool:
        if self.macro_data is None:
            return False

        logger.info("Generating risk-off signals")

        try:
            required_cols = ["VIXCLS", "DGS10", "DTINYUS"]
            if not all(col in self.macro_data.columns for col in required_cols):
                return False

            vix = self.macro_data["VIXCLS"].dropna()
            ten_year = self.macro_data["DGS10"].reindex(vix.index)
            dxy = self.macro_data["DTINYUS"].reindex(vix.index)

            vix_norm = (vix - vix.rolling(252, min_periods=20).mean()) / vix.rolling(
                252, min_periods=20
            ).std().replace(0, 1)
            dxy_norm = (dxy - dxy.rolling(252, min_periods=20).mean()) / dxy.rolling(
                252, min_periods=20
            ).std().replace(0, 1)

            risk_score = vix_norm * 0.5 + dxy_norm * 0.3 - ten_year.pct_change(20) * 0.2

            signal = np.clip(risk_score, -1.0, 1.0)
            signal = pd.Series(signal, index=vix.index)

            signal.name = "risk_off"
            self.generated_signals["risk_off"] = signal.to_frame()
            logger.info("Generated risk-off signals")
            return True

        except Exception as e:
            logger.warning(f"Risk-off signal generation failed: {e}")
            return False

    def combine_signals(self) -> bool:
        logger.info("Step 5: Combining signals into composite")

        if not self.generated_signals:
            logger.warning("No signals to combine")
            return False

        all_signals = []
        for name, df in self.generated_signals.items():
            if isinstance(df, pd.DataFrame):
                signal_col = df.columns[0]
                series = df[signal_col].copy()
                series.name = name
                all_signals.append(series)
            elif isinstance(df, pd.Series):
                all_signals.append(df)

        if not all_signals:
            return False

        combined = pd.concat(all_signals, axis=1)
        combined = combined.ffill().bfill().fillna(0)

        weights = {
            "fundamental": 0.20,
            "cointegration": 0.15,
            "ml": 0.20,
            "momentum": 0.10,
            "mean_reversion": 0.10,
            "inflation": 0.08,
            "real_yield": 0.07,
            "dollar_strength": 0.05,
            "risk_off": 0.05,
        }

        available_weights = {k: v for k, v in weights.items() if k in combined.columns}
        total_weight = sum(available_weights.values())

        self.composite_signals = pd.DataFrame(index=combined.index)
        self.composite_signals["composite"] = sum(
            combined[col] * (available_weights.get(col, 0) / total_weight)
            for col in combined.columns
        )

        self.composite_signals["directional"] = np.sign(self.composite_signals["composite"])

        logger.info(
            f"Combined {len(combined.columns)} signal types into composite: "
            f"{self.composite_signals['composite'].describe().to_dict()}"
        )

        return True

    def save_to_database(self) -> bool:
        if not self.composite_signals.empty:
            logger.info("Step 6: Saving signals to database")

            if self.signal_store is None:
                if not self._init_signal_store():
                    logger.warning("Could not initialize signal store")
                    return False

            try:
                if self.signal_store.is_connected:
                    signal_definitions = [
                        ("composite_signal", StoreSignalType.MACRO, "Combined composite signal"),
                        ("real_yield_signal", StoreSignalType.MACRO, "Real yield based signal"),
                        (
                            "dollar_strength_signal",
                            StoreSignalType.MACRO,
                            "Dollar index based signal",
                        ),
                        ("inflation_signal", StoreSignalType.MACRO, "Inflation based signal"),
                        ("risk_off_signal", StoreSignalType.MACRO, "Risk-off regime signal"),
                        ("momentum_signal", StoreSignalType.MOMENTUM, "Momentum based signal"),
                        (
                            "mean_reversion_signal",
                            StoreSignalType.MEAN_REVERSION,
                            "Mean reversion signal",
                        ),
                    ]

                    for name, sig_type, desc in signal_definitions:
                        try:
                            self.signal_store.register_signal_type(name, sig_type, description=desc)
                        except:
                            pass

                    signals_to_save = []

                    for idx, row in self.composite_signals.iterrows():
                        signal_date = idx.date() if hasattr(idx, "date") else idx

                        for col in self.composite_signals.columns:
                            value = row[col]
                            direction = (
                                StoreSignalDirection.BULLISH
                                if value > 0
                                else StoreSignalDirection.BEARISH
                                if value < 0
                                else StoreSignalDirection.NEUTRAL
                            )

                            signal_data = SignalData(
                                definition_name=f"{col}_signal",
                                asset=self.config.asset,
                                signal_date=signal_date,
                                value=float(value),
                                direction=direction,
                                strength=min(abs(float(value)), 1.0),
                                metadata={"source": "pipeline"},
                            )
                            signals_to_save.append(signal_data)

                    if signals_to_save:
                        saved = self.signal_store.save_signals(signals_to_save)
                        logger.info(f"Saved {saved} signals to database")
                        return True

            except Exception as e:
                logger.error(f"Failed to save signals to database: {e}")

        return False

    def run_backtest(self) -> bool:
        if self.composite_signals is None or self.composite_signals.empty:
            logger.warning("No composite signals to backtest")
            return False

        if self.price_data is None or self.price_data.empty:
            logger.warning("No price data for backtest")
            return False

        logger.info("Step 7: Running backtest")

        try:
            price_col = self.config.asset
            if price_col not in self.price_data.columns:
                logger.error(f"Price column {price_col} not found")
                return False

            prices = self.price_data[[price_col]].copy()

            signals = self.composite_signals[["directional"]].copy()

            common_idx = prices.index.intersection(signals.index)
            prices = prices.loc[common_idx]
            signals = signals.loc[common_idx]

            if len(prices) < 30:
                logger.warning("Insufficient data for backtest")
                return False

            prices.columns = [price_col]
            signals.columns = [price_col]

            backtest_config = BacktestConfig(
                initial_capital=100000.0,
                position_sizing="fixed",
                position_size=1.0,
            )

            self.backtester = SignalBacktester(backtest_config)
            self.backtester.load_data(price_data=prices, signal_data=signals)

            result = self.backtester.run()

            self.backtest_result = result

            logger.info(
                f"Backtest complete: Return={result.total_return_pct * 100:.2f}%, "
                f"Sharpe={result.sharpe_ratio:.2f}, "
                f"MaxDD={result.max_drawdown_pct * 100:.2f}%"
            )

            return True

        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            return False

    def generate_report(self) -> str:
        logger.info("Step 8: Generating report")

        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("SIGNAL GENERATION PIPELINE REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Generated: {datetime.now().isoformat()}")
        report_lines.append(f"Asset: {self.config.asset}")
        report_lines.append(f"Date Range: {self.config.start_date} to {self.config.end_date}")
        report_lines.append("")

        report_lines.append("-" * 80)
        report_lines.append("SIGNAL TYPES GENERATED")
        report_lines.append("-" * 80)

        for signal_type, df in self.generated_signals.items():
            if isinstance(df, pd.DataFrame):
                n_signals = len(df)
                report_lines.append(f"  {signal_type}: {n_signals} observations")
            elif isinstance(df, pd.Series):
                report_lines.append(f"  {signal_type}: {len(df)} observations")

        report_lines.append("")

        if self.composite_signals is not None and not self.composite_signals.empty:
            report_lines.append("-" * 80)
            report_lines.append("COMPOSITE SIGNAL STATISTICS")
            report_lines.append("-" * 80)
            stats = self.composite_signals["composite"].describe()
            report_lines.append(f"  Mean: {stats['mean']:.4f}")
            report_lines.append(f"  Std:  {stats['std']:.4f}")
            report_lines.append(f"  Min:  {stats['min']:.4f}")
            report_lines.append(f"  Max:  {stats['max']:.4f}")

            directional_dist = self.composite_signals["directional"].value_counts()
            report_lines.append(f"  Directional Distribution:")
            report_lines.append(f"    Bullish:  {directional_dist.get(1, 0)}")
            report_lines.append(f"    Bearish:  {directional_dist.get(-1, 0)}")
            report_lines.append(f"    Neutral:  {directional_dist.get(0, 0)}")
            report_lines.append("")

        if hasattr(self, "backtest_result") and self.backtest_result:
            result = self.backtest_result
            report_lines.append("-" * 80)
            report_lines.append("BACKTEST RESULTS")
            report_lines.append("-" * 80)
            report_lines.append(f"  Total Return:    {result.total_return_pct * 100:.2f}%")
            report_lines.append(f"  Annual Return:  {result.annualized_return * 100:.2f}%")
            report_lines.append(f"  Sharpe Ratio:   {result.sharpe_ratio:.4f}")
            report_lines.append(f"  Sortino Ratio:  {result.sortino_ratio:.4f}")
            report_lines.append(f"  Max Drawdown:   {result.max_drawdown_pct * 100:.2f}%")
            report_lines.append(f"  Win Rate:       {result.win_rate * 100:.2f}%")
            report_lines.append(f"  Total Trades:   {result.total_trades}")
            report_lines.append("")

        report_lines.append("=" * 80)

        report = "\n".join(report_lines)
        print(report)

        return report

    def run(self) -> bool:
        self._setup_logging()

        start_date, end_date = self._get_default_dates()
        self.config.start_date = start_date
        self.config.end_date = end_date

        logger.info(f"Starting signal generation pipeline for {self.config.asset}")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Signal types: {self.config.signal_type}")

        if not self._load_macro_data(start_date, end_date):
            logger.error("Failed to load macro data")
            return False

        if self.config.run_backtest:
            self._load_price_data(start_date, end_date)

        success = True

        signal_type = self.config.signal_type.lower()

        if signal_type in ["all", "fundamental"]:
            success = self.generate_fundamental_signals() and success

        if signal_type in ["all", "cointegration"]:
            self.generate_cointegration_signals()

        if signal_type in ["all", "ml"]:
            self.generate_ml_signals()

        if signal_type == "all":
            self.generate_momentum_signals()
            self.generate_mean_reversion_signals()
            self.generate_inflation_signals()
            self.generate_real_yield_signals()
            self.generate_dollar_strength_signals()
            self.generate_risk_off_signals()

        self.combine_signals()

        if self.config.save_signals:
            self.save_to_database()

        if self.config.run_backtest:
            self.run_backtest()

        if self.config.generate_report:
            self.generate_report()

        if self.generated_signals:
            logger.info(
                f"Pipeline complete. Generated signals: {list(self.generated_signals.keys())}"
            )
        else:
            logger.warning("Pipeline complete. No signals generated.")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Signal Generation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_signals.py --signal-type all --backtest --save
  python generate_signals.py --signal-type fundamental --asset XAUUSD
  python generate_signals.py --all --save --verbose
  python generate_signals.py --signal-type ml --start-date 2023-01-01 --end-date 2024-01-01 --report
        """,
    )

    parser.add_argument(
        "--signal-type",
        type=str,
        default="all",
        choices=["fundamental", "cointegration", "ml", "all"],
        help="Type of signals to generate (default: all)",
    )

    parser.add_argument(
        "--asset",
        type=str,
        default="XAUUSD",
        help="Target asset (default: XAUUSD)",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for signal generation (YYYY-MM-DD)",
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for signal generation (YYYY-MM-DD)",
    )

    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run backtest on generated signals",
    )

    parser.add_argument(
        "--save",
        action="store_true",
        help="Save signals to database",
    )

    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate report",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Detailed logging",
    )

    args = parser.parse_args()

    config = PipelineConfig(
        signal_type=args.signal_type,
        asset=args.asset,
        start_date=args.start_date,
        end_date=args.end_date,
        run_backtest=args.backtest,
        save_signals=args.save,
        generate_report=args.report,
        verbose=args.verbose,
    )

    pipeline = SignalGenerationPipeline(config)
    success = pipeline.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
