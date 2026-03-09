"""
Data Pipeline
=============
OHLCV ingestion, storage, and point-in-time access.

Design principles (Renaissance-style):
- Point-in-time data only: NEVER allow future data to leak into past windows
- Immutable raw storage: raw Parquet files are append-only
- Symbol-agnostic: works for FX, futures, equities, crypto
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

__all__ = [
    "OHLCVBar",
    "DataCatalog",
    "OHLCVLoader",
    "PointInTimeWindow",
    "ResampleFreq",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_OHLCV_COLUMNS = {"open", "high", "low", "close", "volume"}


class ResampleFreq:
    """Standard resampling frequencies."""

    M1 = "1min"
    M5 = "5min"
    M15 = "15min"
    M30 = "30min"
    H1 = "1h"
    H4 = "4h"
    D1 = "1D"


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OHLCVBar:
    """Single OHLCV bar. Immutable value object."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str

    def __post_init__(self) -> None:
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"OHLCV sanity failed: O={self.open} not in [{self.low},{self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"OHLCV sanity failed: C={self.close} not in [{self.low},{self.high}]")
        if self.volume < 0:
            raise ValueError(f"Negative volume: {self.volume}")


# ---------------------------------------------------------------------------
# Data Catalog
# ---------------------------------------------------------------------------


class DataCatalog:
    """
    Manages the on-disk storage of OHLCV data.

    Layout::

        data/
          raw/
            EURUSD_M1.parquet
            GBPUSD_M1.parquet
          processed/
            features/
              EURUSD_M1_features.parquet

    Parquet is columnar, compressed, and fast for time-range queries.
    """

    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.processed_dir = self.root / "processed"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_ohlcv(
        self,
        df: pd.DataFrame,
        symbol: str,
        freq: str = ResampleFreq.M1,
        *,
        mode: str = "append",
    ) -> Path:
        """
        Persist OHLCV data.

        Parameters
        ----------
        df:
            DataFrame with DatetimeIndex (UTC) and columns
            {open, high, low, close, volume}.
        symbol:
            Instrument identifier, e.g. "EURUSD".
        freq:
            Bar frequency string, e.g. "1min".
        mode:
            ``"append"`` merges with existing data, ``"overwrite"`` replaces.
        """
        df = self._validate_and_normalise(df, symbol)

        path = self._ohlcv_path(symbol, freq)

        if mode == "append" and path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df])  # type: ignore[assignment]
            df = df[~df.index.duplicated(keep="last")]  # type: ignore[index]
            df.sort_index(inplace=True)

        df.to_parquet(path, compression="snappy")
        return path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load_ohlcv(
        self,
        symbol: str,
        freq: str = ResampleFreq.M1,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> pd.DataFrame:
        """
        Load OHLCV data with optional time-range filter.

        Returns a DataFrame with tz-aware UTC DatetimeIndex.
        """
        path = self._ohlcv_path(symbol, freq)
        if not path.exists():
            raise FileNotFoundError(f"No data for {symbol} @ {freq}. Expected: {path}")

        df = pd.read_parquet(path)

        if start is not None:
            df = df[df.index >= pd.Timestamp(start, tz="UTC")]  # type: ignore[index]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end, tz="UTC")]  # type: ignore[index]

        return df  # type: ignore[return-value]

    def list_symbols(self, freq: str = ResampleFreq.M1) -> list[str]:
        """Return all symbols that have data for a given frequency."""
        suffix = freq.replace("/", "_").replace(":", "_")
        return [p.stem.replace(f"_{suffix}", "") for p in self.raw_dir.glob(f"*_{suffix}.parquet")]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ohlcv_path(self, symbol: str, freq: str) -> Path:
        safe_freq = freq.replace("/", "_").replace(":", "_")
        return self.raw_dir / f"{symbol}_{safe_freq}.parquet"

    @staticmethod
    def _validate_and_normalise(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        missing = REQUIRED_OHLCV_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"Missing OHLCV columns: {missing}")

        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("DataFrame index must be DatetimeIndex")

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # Sanity checks
        assert (df["high"] >= df["low"]).all(), "high < low detected"
        assert (df["volume"] >= 0).all(), "negative volume detected"

        df["symbol"] = symbol
        df.sort_index(inplace=True)
        return df[["open", "high", "low", "close", "volume", "symbol"]]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# OHLCV Loader (MT5 / CSV / yfinance adapters)
# ---------------------------------------------------------------------------


class OHLCVLoader:
    """
    Unified loader with multiple source adapters.

    Usage::

        catalog = DataCatalog("research/data")
        loader  = OHLCVLoader(catalog)
        df = loader.from_csv("EURUSD", "data/EURUSD_M1.csv")
        df = loader.from_mt5("EURUSD", n_bars=50_000)
        df = loader.from_yfinance("SPY", period="5y", interval="1d")
    """

    def __init__(self, catalog: DataCatalog) -> None:
        self.catalog = catalog

    # ------------------------------------------------------------------
    # CSV adapter
    # ------------------------------------------------------------------

    def from_csv(
        self,
        symbol: str,
        path: str | Path,
        freq: str = ResampleFreq.M1,
        *,
        timestamp_col: str = "time",
        timestamp_format: str | None = None,
        save: bool = True,
    ) -> pd.DataFrame:
        """
        Load OHLCV from a CSV file.

        Accepts MT5 export format (tab or comma separated).
        """
        path = Path(path)
        sep = "\t" if path.suffix in {".tsv", ".txt"} else ","

        df = pd.read_csv(path, sep=sep)
        df.columns = [c.strip().lower() for c in df.columns]

        # Handle MT5 Date+Time split columns
        if "date" in df.columns and "time" in df.columns:
            df[timestamp_col] = df["date"].astype(str) + " " + df["time"].astype(str)
            df.drop(columns=["date", "time"], inplace=True)

        if timestamp_col not in df.columns:
            raise ValueError(
                f"Timestamp column '{timestamp_col}' not found. Available: {list(df.columns)}"
            )

        if timestamp_format:
            df.index = pd.to_datetime(df[timestamp_col], format=timestamp_format, utc=True)
        else:
            df.index = pd.to_datetime(df[timestamp_col], utc=True)

        df.drop(columns=[timestamp_col], inplace=True)

        if save:
            self.catalog.save_ohlcv(df, symbol, freq)

        return self.catalog.load_ohlcv(symbol, freq)

    # ------------------------------------------------------------------
    # MT5 adapter
    # ------------------------------------------------------------------

    def from_mt5(
        self,
        symbol: str,
        freq: str = ResampleFreq.M1,
        n_bars: int = 50_000,
        save: bool = True,
    ) -> pd.DataFrame:
        """
        Pull OHLCV directly from MetaTrader 5 terminal via Python API.

        Requires: pip install MetaTrader5
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            raise ImportError("MetaTrader5 package not installed. Run: pip install MetaTrader5")

        _MT5_TIMEFRAME_MAP = {
            ResampleFreq.M1: mt5.TIMEFRAME_M1,
            ResampleFreq.M5: mt5.TIMEFRAME_M5,
            ResampleFreq.M15: mt5.TIMEFRAME_M15,
            ResampleFreq.M30: mt5.TIMEFRAME_M30,
            ResampleFreq.H1: mt5.TIMEFRAME_H1,
            ResampleFreq.H4: mt5.TIMEFRAME_H4,
            ResampleFreq.D1: mt5.TIMEFRAME_D1,
        }

        if not mt5.initialize():  # type: ignore[attr-defined]
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")  # type: ignore[attr-defined]

        tf = _MT5_TIMEFRAME_MAP.get(freq)
        if tf is None:
            raise ValueError(f"Unsupported freq for MT5: {freq}")

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)  # type: ignore[attr-defined]
        mt5.shutdown()  # type: ignore[attr-defined]

        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No data returned for {symbol}")

        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df[["open", "high", "low", "close", "tick_volume"]].rename(  # type: ignore[call-overload]
            columns={"tick_volume": "volume"}
        )

        if save:
            self.catalog.save_ohlcv(df, symbol, freq)

        return self.catalog.load_ohlcv(symbol, freq)

    def from_mt5_range(
        self,
        symbol: str,
        date_from: datetime,
        date_to: datetime,
        freq: str = ResampleFreq.M1,
        *,
        save: bool = True,
        chunk_days: int = 30,
    ) -> pd.DataFrame:
        """
        Pull a date-range of OHLCV bars from MetaTrader 5 in chunks.

        Uses ``copy_rates_range`` to request bars within an exact window,
        chunked into ``chunk_days``-day windows to avoid MT5 API limits.

        Parameters
        ----------
        symbol:
            Instrument identifier, e.g. "EURUSD".
        date_from:
            Inclusive start date (naive dates are treated as UTC).
        date_to:
            Inclusive end date (naive dates are treated as UTC).
        freq:
            Bar frequency string, e.g. ``ResampleFreq.M1``.
        save:
            If True, appends data to the catalog after each chunk.
        chunk_days:
            Number of days per MT5 API request.  Default 30.
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            raise ImportError("MetaTrader5 package not installed. Run: pip install MetaTrader5")

        _MT5_TIMEFRAME_MAP = {
            ResampleFreq.M1: mt5.TIMEFRAME_M1,
            ResampleFreq.M5: mt5.TIMEFRAME_M5,
            ResampleFreq.M15: mt5.TIMEFRAME_M15,
            ResampleFreq.M30: mt5.TIMEFRAME_M30,
            ResampleFreq.H1: mt5.TIMEFRAME_H1,
            ResampleFreq.H4: mt5.TIMEFRAME_H4,
            ResampleFreq.D1: mt5.TIMEFRAME_D1,
        }

        # Ensure UTC
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        else:
            date_from = date_from.astimezone(timezone.utc)
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=timezone.utc)
        else:
            date_to = date_to.astimezone(timezone.utc)

        tf = _MT5_TIMEFRAME_MAP.get(freq)
        if tf is None:
            raise ValueError(f"Unsupported freq for MT5: {freq}")

        if not mt5.initialize():  # type: ignore[attr-defined]
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")  # type: ignore[attr-defined]

        chunks: list[pd.DataFrame] = []
        chunk_start = date_from
        chunk_delta = timedelta(days=chunk_days)

        try:
            while chunk_start < date_to:
                chunk_end = min(chunk_start + chunk_delta, date_to)
                rates = mt5.copy_rates_range(symbol, tf, chunk_start, chunk_end)  # type: ignore[attr-defined]
                if rates is not None and len(rates) > 0:
                    chunk_df = pd.DataFrame(rates)
                    chunk_df.index = pd.to_datetime(chunk_df["time"], unit="s", utc=True)
                    chunk_df = chunk_df[["open", "high", "low", "close", "tick_volume"]].rename(  # type: ignore[call-overload]
                        columns={"tick_volume": "volume"}
                    )
                    chunks.append(chunk_df)
                    if save:
                        self.catalog.save_ohlcv(chunk_df, symbol, freq, mode="append")
                chunk_start = chunk_end + timedelta(seconds=1)
        finally:
            mt5.shutdown()  # type: ignore[attr-defined]

        if not chunks:
            raise RuntimeError(f"No data returned for {symbol} in [{date_from}, {date_to}]")

        combined = pd.concat(chunks)  # type: ignore[assignment]
        combined = combined[~combined.index.duplicated(keep="last")]  # type: ignore[index]
        combined.sort_index(inplace=True)

        return self.catalog.load_ohlcv(symbol, freq)

    def from_yfinance(
        self,
        symbol: str,
        period: str = "5y",
        interval: str = "1d",
        save: bool = True,
    ) -> pd.DataFrame:
        """
        Pull data from Yahoo Finance.
        Useful for cross-asset signals (VIX, SPY, DXY proxies).

        Requires: pip install yfinance
        """
        try:
            import yfinance as yf  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError("yfinance not installed. Run: pip install yfinance")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]]

        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # Map yfinance interval to internal freq
        _YF_FREQ_MAP = {
            "1m": ResampleFreq.M1,
            "5m": ResampleFreq.M5,
            "15m": ResampleFreq.M15,
            "30m": ResampleFreq.M30,
            "1h": ResampleFreq.H1,
            "1d": ResampleFreq.D1,
        }
        freq = _YF_FREQ_MAP.get(interval, interval)

        if save:
            self.catalog.save_ohlcv(df, symbol, freq)

        return self.catalog.load_ohlcv(symbol, freq)


# ---------------------------------------------------------------------------
# Point-in-Time Window Generator
# ---------------------------------------------------------------------------


@dataclass
class PointInTimeWindow:
    """
    Generates train/test windows for walk-forward validation.

    CRITICAL: No data from test window can leak into train window.
    The ``embargo_bars`` gap prevents lookahead bias.

    Example (252 train / 63 test / 5 embargo bars)::

        |----train 252----|--5--|--test 63--|
                         ^embargo^
    """

    train_bars: int = 252 * 390  # 1 year of 1-min bars
    test_bars: int = 63 * 390  # 1 quarter
    embargo_bars: int = 5 * 390  # 1 week gap
    step_bars: int = 0  # 0 = derive from test_bars in __post_init__

    def __post_init__(self) -> None:
        if self.step_bars == 0:
            self.step_bars = self.test_bars

    def generate(self, df: pd.DataFrame) -> Iterator[tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Yield (train_df, test_df) pairs in chronological order.

        Never yields a pair where test data precedes train data.
        """
        n = len(df)
        start = self.train_bars

        while start + self.embargo_bars + self.test_bars <= n:
            train_start = start - self.train_bars
            train_end = start
            test_start = train_end + self.embargo_bars
            test_end = test_start + self.test_bars

            if test_end > n:
                break

            train_df = df.iloc[train_start:train_end].copy()
            test_df = df.iloc[test_start:test_end].copy()

            yield train_df, test_df

            start += self.step_bars

    def n_windows(self, n_total_bars: int) -> int:
        """How many windows will be generated for a given dataset size."""
        count = 0
        start = self.train_bars
        while start + self.embargo_bars + self.test_bars <= n_total_bars:
            count += 1
            start += self.step_bars
        return count
