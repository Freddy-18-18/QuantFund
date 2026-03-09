"""
Dukascopy tick data feed for XAUUSD via tick-vault.

Downloads and caches bid/ask tick data, resamples to OHLCV bars at any
timeframe, and returns clean DataFrames with UTC timestamps.

Usage:
    feed = DukascopyFeed()
    # Download (idempotent — resumes from last downloaded point)
    await feed.download(start=datetime(2020, 1, 1))
    # Read as ticks
    ticks = feed.ticks(start=datetime(2024, 1, 1), end=datetime(2025, 1, 1))
    # Read as OHLCV bars
    ohlcv_h1 = feed.ohlcv(start=..., end=..., freq="1h")
    ohlcv_d1 = feed.ohlcv(start=..., end=..., freq="1D")
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

SYMBOL = "XAUUSD"

# tick-vault uses UTC internally; no TZ conversion needed.
_TICK_COLS = ["time", "ask", "bid", "ask_volume", "bid_volume"]


class DukascopyFeed:
    """
    Thin wrapper around tick-vault for XAUUSD.

    All timestamps returned are timezone-aware UTC.
    OHLCV is mid-price based: mid = (ask + bid) / 2.
    Volume is the sum of ask_volume + bid_volume per bar.
    """

    def __init__(self) -> None:
        # Import lazily so the module can be imported even when tick-vault
        # is not installed (e.g., in CI environments that only use macro data).
        try:
            from tick_vault import download_range, read_tick_data  # type: ignore[import]

            self._download_range = download_range
            self._read_tick_data = read_tick_data
        except ImportError as exc:  # pragma: no cover
            raise ImportError("tick-vault is required: pip install tick-vault") from exc

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(
        self,
        start: datetime,
        end: Optional[datetime] = None,
    ) -> None:
        """
        Synchronously download XAUUSD ticks from Dukascopy.

        Wraps tick-vault's async ``download_range`` in a blocking call.
        Safe to call repeatedly — tick-vault resumes from the last
        downloaded hour automatically.

        Args:
            start: Inclusive start datetime (UTC assumed if tz-naive).
            end:   Exclusive end datetime.  Defaults to now (UTC).
        """
        if end is None:
            end = datetime.now(timezone.utc)
        start = _ensure_utc(start)
        end = _ensure_utc(end)

        asyncio.run(self._download_range(symbol=SYMBOL, start=start, end=end))

    # ------------------------------------------------------------------
    # Read ticks
    # ------------------------------------------------------------------

    def ticks(
        self,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """
        Return raw tick data as a DataFrame.

        Columns: time (UTC DatetimeIndex), ask, bid, ask_volume, bid_volume
        mid column is added: mid = (ask + bid) / 2
        spread column is added: spread = ask - bid  (in price units)
        """
        start = _ensure_utc(start)
        end = _ensure_utc(end)
        df: pd.DataFrame = self._read_tick_data(symbol=SYMBOL, start=start, end=end)
        if df.empty:
            return df

        # Normalise index to UTC DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            if "time" in df.columns:
                df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)  # type: ignore[assignment]

        # Derived columns
        df["mid"] = (df["ask"] + df["bid"]) / 2.0
        df["spread"] = df["ask"] - df["bid"]

        return df.sort_index()

    # ------------------------------------------------------------------
    # Resample to OHLCV
    # ------------------------------------------------------------------

    def ohlcv(
        self,
        start: datetime,
        end: datetime,
        freq: str = "1h",
        price: str = "mid",
    ) -> pd.DataFrame:
        """
        Return resampled OHLCV bars.

        Args:
            start: Inclusive bar start.
            end:   Exclusive bar end.
            freq:  Pandas offset alias: "1min", "5min", "1h", "4h", "1D", etc.
                   Note: Use "min" not "m" for minutes (pandas >= 2.2).
            price: Which price series to OHLCV-aggregate.
                   "mid" (default), "ask", or "bid".

        Returns:
            DataFrame with columns: open, high, low, close, volume, vwap
            Index: UTC DatetimeIndex (bar open time).
            Bars with zero ticks are dropped (not forward-filled) so callers
            control their own fill policy.
        """
        # Normalize frequency aliases for pandas >= 2.2
        freq_map = {"m": "min", "M": "ME"}
        for old, new in freq_map.items():
            if freq.endswith(old):
                freq = freq[:-1] + new

        raw = self.ticks(start=start, end=end)
        if raw.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "vwap"])

        p = raw[price]
        vol = raw["ask_volume"] + raw["bid_volume"]

        ohlc = p.resample(freq).ohlc()  # type: ignore[union-attr]
        volume = vol.resample(freq).sum()

        # VWAP: sum(price * volume) / sum(volume) per bar
        pv = (p * vol).resample(freq).sum()
        vwap = pv / volume.replace(0, float("nan"))

        bars = ohlc.copy()
        bars.columns = pd.Index(["open", "high", "low", "close"])
        bars["volume"] = volume
        bars["vwap"] = vwap

        # Drop bars where no ticks occurred
        bars = bars.dropna(subset=["open"])

        return bars.sort_index()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _ensure_utc(dt: datetime) -> datetime:
    """Attach UTC timezone to naive datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
