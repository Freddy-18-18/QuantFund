"""
Live Signal Loop
================
Continuous process that generates and exports signals on each completed bar.

Design:
- NEVER calls ``fit()`` — strategy must be pre-fitted offline
- Sleeps precisely to the next bar boundary (ceil alignment)
- Gracefully handles SIGINT/SIGTERM by setting a stop flag
- Exports both ``signals_latest.json`` and ``allocation_latest.json``
"""

from __future__ import annotations

import logging
import math
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

__all__ = ["SignalLoop"]

logger = logging.getLogger(__name__)


@dataclass
class SignalLoop:
    """
    Continuous live signal generation loop.

    Parameters
    ----------
    strategy:
        Pre-fitted strategy object implementing ``predict(features) -> pd.Series``.
    instruments:
        List of symbol strings, e.g. ``["EURUSD", "GBPUSD", "XAUUSD"]``.
    strategy_id:
        Identifier written into every exported signal event.
    bar_freq:
        Bar frequency string, e.g. ``"1min"``, ``"5min"``.
    lookback_bars:
        Number of recent bars to load per tick.
    export_dir:
        Directory for JSON signal exports.
    catalog_dir:
        DataCatalog root directory for OHLCV storage.
    target_annual_vol:
        Target annualised volatility for position sizing.
    initial_capital:
        Capital in account currency.
    pip_values:
        Dict mapping symbol → pip value in account currency (for lot sizing).
    log_every_n:
        Log a summary every N ticks (default 10).
    """

    strategy: object
    instruments: list[str]
    strategy_id: str
    bar_freq: str = "1min"
    lookback_bars: int = 500
    export_dir: str | Path = "export"
    catalog_dir: str | Path = "data"
    target_annual_vol: float = 0.20
    initial_capital: float = 100_000.0
    pip_values: dict[str, float] = field(default_factory=dict)
    log_every_n: int = 10

    def __post_init__(self) -> None:
        self.export_dir = Path(self.export_dir)
        self.catalog_dir = Path(self.catalog_dir)
        self._running = False
        self._tick_count = 0
        self._bar_secs = self._freq_to_seconds(self.bar_freq)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Start the live signal loop.

        Blocks until SIGINT or SIGTERM is received.
        Registers signal handlers that set ``_running = False``.
        """
        self._running = True
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        logger.info(
            "SignalLoop starting | strategy=%s | instruments=%s | freq=%s",
            self.strategy_id,
            self.instruments,
            self.bar_freq,
        )

        while self._running:
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.error("Tick error: %s", exc, exc_info=True)

            if self._running:
                self._sleep_to_next_bar()

        logger.info("SignalLoop stopped after %d ticks.", self._tick_count)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Execute one bar cycle: load → features → predict → allocate → export."""
        from quantfund.data import DataCatalog, OHLCVLoader
        from quantfund.features import FeaturePipeline
        from quantfund.portfolio import PortfolioAllocator, AllocationConfig
        from quantfund.export import RustExporter

        self._tick_count += 1
        catalog = DataCatalog(self.catalog_dir)
        loader = OHLCVLoader(catalog)
        pipeline = FeaturePipeline(include_cross_asset=False)
        exporter = RustExporter(output_dir=self.export_dir)

        # 1. Load OHLCV for each instrument
        ohlcv_map: dict[str, pd.DataFrame] = {}
        for symbol in self.instruments:
            try:
                df = loader.from_mt5(
                    symbol, freq=self.bar_freq, n_bars=self.lookback_bars, save=True
                )
                ohlcv_map[symbol] = df
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load %s: %s", symbol, exc)

        if not ohlcv_map:
            logger.warning("No OHLCV data loaded; skipping tick %d.", self._tick_count)
            return

        # 2. Compute features and signals per instrument
        all_signals: dict[str, float] = {}
        returns_map: dict[str, pd.Series] = {}

        for symbol, ohlcv in ohlcv_map.items():
            try:
                features = pipeline.transform(ohlcv)
                signal_series: pd.Series = self.strategy.predict(features)  # type: ignore[union-attr]
                # Latest bar signal
                all_signals[symbol] = float(signal_series.iloc[-1])
                returns_map[symbol] = ohlcv["close"].pct_change().dropna()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Predict failed for %s: %s", symbol, exc)
                all_signals[symbol] = 0.0

        # 3. Portfolio allocation
        alloc_config = AllocationConfig(
            initial_capital=self.initial_capital,
            target_annual_vol=self.target_annual_vol,
        )
        allocator = PortfolioAllocator(alloc_config)
        allocation = allocator.allocate(signals=all_signals, returns=returns_map)

        # 4. Export signals and allocation
        exporter.export_signals(all_signals, strategy_id=self.strategy_id)
        exporter.export_allocation(allocation)

        if self._tick_count % self.log_every_n == 0:
            logger.info(
                "Tick %d | signals=%s | dd_scale=%.3f",
                self._tick_count,
                {k: f"{v:.3f}" for k, v in all_signals.items()},
                allocation.dd_scale,
            )

    def _sleep_to_next_bar(self) -> None:
        """Sleep until the start of the next bar + 1 second buffer."""
        now = time.time()
        next_bar = math.ceil(now / self._bar_secs) * self._bar_secs + 1.0
        sleep_secs = max(0.0, next_bar - now)
        logger.debug("Sleeping %.1fs to next bar boundary.", sleep_secs)
        time.sleep(sleep_secs)

    def _handle_stop(self, signum: int, frame: object) -> None:
        """Signal handler: set stop flag."""
        logger.info("Received signal %d; stopping loop.", signum)
        self._running = False

    @staticmethod
    def _freq_to_seconds(freq: str) -> float:
        """Convert a pandas-style frequency string to seconds."""
        _map = {
            "1min": 60.0,
            "5min": 300.0,
            "15min": 900.0,
            "30min": 1800.0,
            "1h": 3600.0,
            "4h": 14400.0,
            "1D": 86400.0,
        }
        secs = _map.get(freq)
        if secs is None:
            raise ValueError(f"Unknown bar_freq '{freq}'. Known: {list(_map.keys())}")
        return secs
