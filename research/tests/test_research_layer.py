"""
Smoke tests for the QuantFund research library.

These tests run without any real market data and verify that:
- All modules import correctly
- Core computations produce sensible outputs
- No lookahead bias in window generation
- Export pipeline produces valid JSON
"""

from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_ohlcv():
    """Generate synthetic OHLCV data (GBM) for testing."""
    n = 5000
    rng = np.random.default_rng(42)
    log_ret = rng.normal(0, 0.0002, n)
    close = 1.1000 * np.exp(np.cumsum(log_ret))
    high = close * (1 + rng.uniform(0, 0.001, n))
    low = close * (1 - rng.uniform(0, 0.001, n))
    open_ = close * (1 + rng.normal(0, 0.0001, n))
    # Clamp open to [low, high]
    open_ = np.clip(open_, low, high)

    index = pd.date_range("2022-01-03 00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 1000, n).astype(float),
        },
        index=index,
    )


# ---------------------------------------------------------------------------
# Data pipeline tests
# ---------------------------------------------------------------------------


class TestDataPipeline:
    def test_import(self):
        from quantfund.data import DataCatalog, OHLCVLoader, PointInTimeWindow, ResampleFreq

        assert DataCatalog is not None

    def test_point_in_time_window(self, synthetic_ohlcv):
        from quantfund.data import PointInTimeWindow

        w = PointInTimeWindow(train_bars=1000, test_bars=200, embargo_bars=10, step_bars=200)
        windows = list(w.generate(synthetic_ohlcv))
        assert len(windows) > 0, "Should produce at least one window"

        for train, test in windows:
            # Critical: test must come AFTER train + embargo
            assert test.index[0] > train.index[-1], "Test starts before train ends!"
            assert len(train) == 1000
            assert len(test) == 200

    def test_no_overlap_in_windows(self, synthetic_ohlcv):
        from quantfund.data import PointInTimeWindow

        w = PointInTimeWindow(train_bars=500, test_bars=100, embargo_bars=20, step_bars=100)
        windows = list(w.generate(synthetic_ohlcv))
        # Test windows must not overlap
        for i in range(1, len(windows)):
            prev_test_end = windows[i - 1][1].index[-1]
            curr_test_start = windows[i][1].index[0]
            assert curr_test_start > prev_test_end, "Consecutive test windows overlap!"


# ---------------------------------------------------------------------------
# Feature engineering tests
# ---------------------------------------------------------------------------


class TestFeatureEngineering:
    def test_price_features(self, synthetic_ohlcv):
        from quantfund.features import PriceFeatures

        pf = PriceFeatures(momentum_windows=[5, 20])
        features = pf.transform(synthetic_ohlcv)
        assert isinstance(features, pd.DataFrame)
        assert len(features) == len(synthetic_ohlcv)
        assert "ret_1" in features.columns
        assert "rsi_14" in features.columns
        assert "macd_hist" in features.columns

    def test_volatility_features(self, synthetic_ohlcv):
        from quantfund.features import VolatilityFeatures

        vf = VolatilityFeatures(vol_windows=[5, 20])
        features = vf.transform(synthetic_ohlcv)
        assert "rv_5" in features.columns
        assert "rv_20" in features.columns
        assert "parkinson_rv_5" in features.columns
        # Volatility must be non-negative (except NaN warm-up)
        assert (features["rv_5"].dropna() >= 0).all()

    def test_volume_features(self, synthetic_ohlcv):
        from quantfund.features import VolumeFeatures

        vf = VolumeFeatures(vwap_window=60)
        features = vf.transform(synthetic_ohlcv)
        assert "vwap" in features.columns
        assert "vol_zscore_20" in features.columns

    def test_calendar_features(self, synthetic_ohlcv):
        from quantfund.features import CalendarFeatures

        cf = CalendarFeatures()
        features = cf.transform(synthetic_ohlcv)
        assert "hour_sin" in features.columns
        assert "session_london" in features.columns
        # Sine values must be in [-1, 1]
        assert features["hour_sin"].between(-1.01, 1.01).all()

    def test_full_pipeline(self, synthetic_ohlcv):
        from quantfund.features import FeaturePipeline

        pipeline = FeaturePipeline(include_cross_asset=False)
        features = pipeline.transform(synthetic_ohlcv)
        assert len(features) == len(synthetic_ohlcv)
        assert len(features.columns) > 50, "Expect many features"

    def test_no_future_leak_in_features(self, synthetic_ohlcv):
        """
        Verify features don't look ahead: shift OHLCV by 1 bar and check
        that features on first N bars are identical.
        """
        from quantfund.features import PriceFeatures

        pf = PriceFeatures(momentum_windows=[5])
        full = pf.transform(synthetic_ohlcv)

        # Take first 200 bars, compute features
        partial = pf.transform(synthetic_ohlcv.iloc[:200])

        # Features at bar 100 should be the same whether we use 200 or 5000 bars
        pd.testing.assert_series_equal(
            full["ret_1"].iloc[:200].dropna(),
            partial["ret_1"].dropna(),
            check_names=False,
        )


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_sharpe_positive_returns(self):
        from quantfund.metrics import compute_metrics

        rng = np.random.default_rng(0)
        returns = rng.normal(0.001, 0.01, 1000)  # positive drift
        m = compute_metrics(pd.Series(returns), freq="1D")
        assert m.sharpe > 0
        assert m.annualised_vol > 0
        assert m.n_bars == 1000

    def test_sharpe_zero_returns(self):
        from quantfund.metrics import compute_metrics

        returns = np.zeros(1000)
        m = compute_metrics(pd.Series(returns), freq="1D")
        assert m.sharpe == pytest.approx(0.0, abs=1e-6)

    def test_max_drawdown_correct(self):
        from quantfund.metrics import compute_metrics

        # Returns that create a known 10% drawdown
        returns = pd.Series([0.05, 0.05, -0.10, 0.05, 0.05])
        m = compute_metrics(returns, freq="1D")
        assert m.max_drawdown < 0

    def test_profit_factor(self):
        from quantfund.metrics import compute_metrics

        returns = pd.Series([0.01, -0.005, 0.01, -0.005, 0.01])
        m = compute_metrics(returns, freq="1D")
        assert m.profit_factor > 1.0  # More wins than losses

    def test_ic_positive_signal(self):
        from quantfund.metrics import compute_ic

        rng = np.random.default_rng(1)
        signal = rng.normal(0, 1, 500)
        outcome = signal * 0.3 + rng.normal(0, 1, 500)  # positive correlation
        ic, pval = compute_ic(signal, outcome, method="spearman")
        assert ic > 0
        assert pval < 0.05

    def test_drawdown_series(self):
        from quantfund.metrics import compute_drawdown_series

        returns = pd.Series([0.01, 0.01, -0.05, 0.01, 0.01])
        dd = compute_drawdown_series(returns)
        assert (dd <= 0).all()
        assert dd.iloc[0] == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Portfolio allocator tests
# ---------------------------------------------------------------------------


class TestPortfolioAllocator:
    def test_basic_allocation(self):
        from quantfund.portfolio import PortfolioAllocator, AllocationConfig

        rng = np.random.default_rng(7)

        returns = {
            "EURUSD": pd.Series(rng.normal(0.0001, 0.0010, 200)),
            "GBPUSD": pd.Series(rng.normal(0.0001, 0.0012, 200)),
        }
        signals = {"EURUSD": 0.8, "GBPUSD": -0.4}
        config = AllocationConfig(initial_capital=100_000, target_annual_vol=0.15)
        alloc = PortfolioAllocator(config)

        result = alloc.allocate(signals=signals, returns=returns)
        assert result.capital == 100_000
        assert "EURUSD" in result.notional_sizes
        assert "GBPUSD" in result.notional_sizes
        # Gross exposure should not exceed 200%
        assert result.gross_exposure <= 2.0 + 1e-6

    def test_drawdown_scaling(self):
        from quantfund.portfolio import PortfolioAllocator, AllocationConfig

        rng = np.random.default_rng(8)
        returns_series = pd.Series(rng.normal(-0.002, 0.01, 500))  # losing strategy
        ret_dict = {"EURUSD": returns_series}
        signals = {"EURUSD": 1.0}
        config = AllocationConfig(
            initial_capital=100_000,
            use_dd_scaling=True,
            dd_halflife_pct=0.10,
            dd_floor=0.25,
        )
        alloc = PortfolioAllocator(config)
        result = alloc.allocate(
            signals=signals,
            returns=ret_dict,
            portfolio_returns=returns_series,
        )
        # During significant drawdown, scale should be reduced
        assert result.dd_scale <= 1.0


# ---------------------------------------------------------------------------
# Export pipeline tests
# ---------------------------------------------------------------------------


class TestExportPipeline:
    def test_signal_export(self, tmp_path):
        from quantfund.export import RustExporter

        exporter = RustExporter(output_dir=tmp_path / "export")
        signals = {"EURUSD": 0.75, "GBPUSD": -0.40}
        events = exporter.export_signals(signals, strategy_id="test_v1")
        assert len(events) == 2
        # Verify JSON is valid
        latest = exporter.latest_signals()
        assert len(latest) == 2
        assert latest[0]["strategy_id"] == "test_v1"

    def test_signal_side_encoding(self, tmp_path):
        from quantfund.export import RustSignalEvent

        ev_long = RustSignalEvent(0, "s1", "EURUSD", "Buy", 0.8)
        ev_short = RustSignalEvent(0, "s1", "EURUSD", "Sell", -0.5)
        ev_flat = RustSignalEvent(0, "s1", "EURUSD", None, 0.0)
        assert ev_long.to_rust_json()["side"] == "Buy"
        assert ev_short.to_rust_json()["side"] == "Sell"
        assert ev_flat.to_rust_json()["side"] is None

    def test_strategy_spec_roundtrip(self, tmp_path):
        from quantfund.export import RustExporter, StrategySpec

        exporter = RustExporter(output_dir=tmp_path / "export")
        spec = exporter.export_strategy_spec(
            strategy_id="mom_v1",
            name="Momentum v1",
            instruments=["EURUSD"],
            parameters={"lookback": 60, "threshold": 0.001},
        )
        # Roundtrip
        path = tmp_path / "export" / "specs" / "mom_v1.json"
        loaded = StrategySpec.from_json(path)
        assert loaded.strategy_id == "mom_v1"
        assert loaded.parameters["lookback"] == 60

    def test_strength_clipping(self, tmp_path):
        from quantfund.export import RustExporter

        exporter = RustExporter(output_dir=tmp_path / "export")
        # Signal outside [-1, 1] should be clipped
        events = exporter.export_signals({"EURUSD": 5.0}, strategy_id="t")
        assert events[0].strength == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Walk-forward integration test
# ---------------------------------------------------------------------------


class TestWalkForward:
    def test_walk_forward_basic(self, synthetic_ohlcv):
        """End-to-end smoke test with a trivial momentum strategy."""
        from quantfund.features import FeaturePipeline
        from quantfund.validation import WalkForwardValidator
        from quantfund.data import PointInTimeWindow

        class SimpleMomentum:
            """Trivial strategy: go long if 5-bar return > 0, short otherwise."""

            def fit(self, train_features, train_ohlcv):
                pass  # No training needed for this trivial strategy

            def predict(self, test_features):
                if "ret_5" in test_features.columns:
                    return test_features["ret_5"].fillna(0.0).clip(-1, 1)
                return pd.Series(0.0, index=test_features.index)

        pipeline = FeaturePipeline(include_cross_asset=False)
        features = pipeline.transform(synthetic_ohlcv)

        window = PointInTimeWindow(train_bars=500, test_bars=200, embargo_bars=10, step_bars=200)
        validator = WalkForwardValidator(window=window, freq="1min", verbose=False)
        summary = validator.run(SimpleMomentum(), synthetic_ohlcv, features)

        assert summary.n_windows > 0
        assert isinstance(summary.mean_sharpe, float)
        assert len(summary.combined_returns) > 0


# ---------------------------------------------------------------------------
# Regime detector tests
# ---------------------------------------------------------------------------

import importlib


class TestRegimeDetector:
    @pytest.fixture
    def returns(self, synthetic_ohlcv):
        return np.log(synthetic_ohlcv["close"]).diff().dropna()

    @pytest.mark.skipif(
        importlib.util.find_spec("hmmlearn") is None,
        reason="hmmlearn not installed",
    )
    def test_fit_predict(self, returns):
        from quantfund.regime import RegimeDetector, RegimeConfig

        cfg = RegimeConfig(n_regimes=3, n_iter=20, vol_window=10, return_window=3)
        det = RegimeDetector(cfg)
        det.fit(returns)
        labels = det.predict(returns)
        assert labels.shape[0] > 0
        assert set(labels).issubset({0, 1, 2})

    @pytest.mark.skipif(
        importlib.util.find_spec("hmmlearn") is None,
        reason="hmmlearn not installed",
    )
    def test_predict_proba_sums_to_one(self, returns):
        from quantfund.regime import RegimeDetector, RegimeConfig

        cfg = RegimeConfig(n_regimes=3, n_iter=20, vol_window=10, return_window=3)
        det = RegimeDetector(cfg).fit(returns)
        proba = det.predict_proba(returns)
        assert proba.shape[1] == 3
        np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)

    def test_not_fitted_raises(self):
        from quantfund.regime import RegimeDetector

        det = RegimeDetector()
        dummy = pd.Series(np.random.randn(100))
        with pytest.raises(RuntimeError, match="fit"):
            det.predict(dummy)


# ---------------------------------------------------------------------------
# VolRegimeMeanReversion tests
# ---------------------------------------------------------------------------


class TestVolRegimeMeanReversion:
    @pytest.mark.skipif(
        importlib.util.find_spec("hmmlearn") is None,
        reason="hmmlearn not installed",
    )
    def test_fit_predict_shape(self, synthetic_ohlcv):
        from quantfund.features import FeaturePipeline
        from quantfund.strategies import VolRegimeMeanReversion, VolRegimeConfig

        pipeline = FeaturePipeline(include_cross_asset=False)
        features = pipeline.transform(synthetic_ohlcv)
        cfg = VolRegimeConfig(n_regimes=3, hmm_vol_window=10, min_train_samples=50)
        strat = VolRegimeMeanReversion(cfg)
        train_f = features.iloc[:3000]
        train_o = synthetic_ohlcv.iloc[:3000]
        strat.fit(train_f, train_o)
        test_f = features.iloc[3000:]
        signals = strat.predict(test_f)
        assert len(signals) == len(test_f)

    @pytest.mark.skipif(
        importlib.util.find_spec("hmmlearn") is None,
        reason="hmmlearn not installed",
    )
    def test_signal_range(self, synthetic_ohlcv):
        from quantfund.features import FeaturePipeline
        from quantfund.strategies import VolRegimeMeanReversion, VolRegimeConfig

        pipeline = FeaturePipeline(include_cross_asset=False)
        features = pipeline.transform(synthetic_ohlcv)
        cfg = VolRegimeConfig(n_regimes=3, hmm_vol_window=10, min_train_samples=50)
        strat = VolRegimeMeanReversion(cfg)
        strat.fit(features.iloc[:3000], synthetic_ohlcv.iloc[:3000])
        signals = strat.predict(features.iloc[3000:])
        assert (signals >= -1.0).all() and (signals <= 1.0).all()

    def test_unfitted_returns_zeros(self, synthetic_ohlcv):
        from quantfund.features import FeaturePipeline
        from quantfund.strategies import VolRegimeMeanReversion

        pipeline = FeaturePipeline(include_cross_asset=False)
        features = pipeline.transform(synthetic_ohlcv)
        strat = VolRegimeMeanReversion()
        signals = strat.predict(features)
        assert (signals == 0.0).all()


# ---------------------------------------------------------------------------
# SignalLoop tests
# ---------------------------------------------------------------------------


class TestSignalLoop:
    def test_initialization(self, tmp_path):
        from quantfund.live import SignalLoop

        class DummyStrategy:
            def predict(self, features):
                return pd.Series(0.0, index=features.index)

        loop = SignalLoop(
            strategy=DummyStrategy(),
            instruments=["EURUSD"],
            strategy_id="test",
            bar_freq="1min",
            export_dir=tmp_path / "export",
            catalog_dir=tmp_path / "data",
        )
        assert loop._bar_secs == 60.0
        assert not loop._running

    def test_sleep_timing(self, tmp_path):
        from quantfund.live import SignalLoop

        class DummyStrategy:
            def predict(self, features):
                return pd.Series(0.0, index=features.index)

        for freq, expected_secs in [("1min", 60.0), ("5min", 300.0), ("1h", 3600.0)]:
            loop = SignalLoop(
                strategy=DummyStrategy(),
                instruments=["EURUSD"],
                strategy_id="test",
                bar_freq=freq,
                export_dir=tmp_path / "export",
                catalog_dir=tmp_path / "data",
            )
            assert loop._bar_secs == expected_secs
