"""
Macro data feed for XAUUSD factor analysis.

Sources (all free, no API key required):
    - Treasury.gov daily real yield curve CSV  : 10Y TIPS real yield
    - Treasury.gov daily nominal yield curve CSV: 10Y nominal Treasury yield
    - yfinance DX-Y.NYB                        : US Dollar Index (DXY)
    - yfinance ^VIX                             : CBOE VIX
    - yfinance ^IRX                             : 13-week T-bill (fed funds proxy)

Optional: If FRED_API_KEY is set in the environment, FRED is used instead of
Treasury.gov for yields (more robust for automation).

All series are returned as daily frequency, forward-filled to remove
non-business-day gaps so they can be merged with intraday price data.

Usage:
    feed = MacroFeed()
    df = feed.fetch(start=datetime(2020, 1, 1), end=datetime(2025, 1, 1))
    # columns: real_yield, nominal_yield, dxy, vix, fed_funds
    # derived: breakeven_inflation, real_yield_1d_chg, dxy_1d_chg
"""

from __future__ import annotations

import io
import os
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

# Treasury.gov URL pattern — one CSV per year, requires fetching each year separately
_TREASURY_REAL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_real_yield_curve"
    "&field_tdr_date_value={year}&download=true"
)

_TREASURY_NOMINAL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&download=true"
)

# FRED endpoint (used only when FRED_API_KEY env var is set)
_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_SERIES = {
    "DFII10": "real_yield",
    "DGS10": "nominal_yield",
}


class MacroFeed:
    """
    Fetches macro time-series from free public sources.

    Priority:
      - Yields: Treasury.gov (always free) or FRED if FRED_API_KEY is set
      - DXY, VIX, fed_funds proxy: yfinance
    """

    def __init__(self, fred_api_key: Optional[str] = None) -> None:
        self._fred_key = fred_api_key or os.environ.get("FRED_API_KEY")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch(
        self,
        start: datetime,
        end: Optional[datetime] = None,
        forward_fill: bool = True,
    ) -> pd.DataFrame:
        """
        Download all macro series and return as a single merged DataFrame.

        Args:
            start:        Inclusive start date.
            end:          Inclusive end date. Defaults to today UTC.
            forward_fill: If True, forward-fill NaNs (weekends, holidays).

        Returns:
            DataFrame indexed by UTC date (daily frequency) with columns:
            real_yield, nominal_yield, dxy, vix, fed_funds
            Also derived columns:
              - breakeven_inflation = nominal_yield - real_yield
              - real_yield_1d_chg   = daily change in real yield
              - dxy_1d_chg          = daily change in DXY
        """
        if end is None:
            end = datetime.now(timezone.utc)

        frames: dict[str, pd.Series] = {}

        # --- Yield curves (Treasury.gov or FRED) ---
        if self._fred_key:
            yields = self._fetch_yields_fred(start, end)
        else:
            yields = self._fetch_yields_treasury(start, end)
        frames.update(yields)

        # --- Market data via yfinance (DXY, VIX, short-rate) ---
        market = self._fetch_yfinance(start, end)
        frames.update(market)

        if not frames:
            raise RuntimeError("No macro data could be downloaded.")

        combined = pd.DataFrame(frames)
        combined.index = pd.to_datetime(combined.index, utc=True)
        combined = combined.sort_index()

        if forward_fill:
            combined = combined.ffill()

        # Derived features
        if "real_yield" in combined.columns and "nominal_yield" in combined.columns:
            combined["breakeven_inflation"] = combined["nominal_yield"] - combined["real_yield"]
        if "real_yield" in combined.columns:
            combined["real_yield_1d_chg"] = combined["real_yield"].diff()
        if "dxy" in combined.columns:
            combined["dxy_1d_chg"] = combined["dxy"].diff()

        return combined

    # ------------------------------------------------------------------
    # Treasury.gov yield fetcher (no auth required)
    # ------------------------------------------------------------------

    def _fetch_yields_treasury(
        self,
        start: datetime,
        end: datetime,
    ) -> dict[str, pd.Series]:
        """
        Fetch 10Y real and nominal yields from Treasury.gov using async
        parallel requests (one per year) for speed.
        """
        import asyncio

        try:
            import httpx
        except ImportError:
            raise ImportError("httpx is required: pip install httpx")

        years = list(range(start.year, end.year + 1))

        async def _fetch_all(years: list[int]) -> tuple[list, list]:
            real_frames: list[pd.DataFrame] = []
            nominal_frames: list[pd.DataFrame] = []

            async def _get(client: httpx.AsyncClient, url: str) -> str | None:
                try:
                    r = await client.get(url, timeout=60.0)
                    r.raise_for_status()
                    return r.text
                except Exception as exc:
                    print(f"[MacroFeed] Warning: {url[:60]}... : {exc}")
                    return None

            async with httpx.AsyncClient() as client:
                real_tasks = [_get(client, _TREASURY_REAL_URL.format(year=y)) for y in years]
                nom_tasks = [_get(client, _TREASURY_NOMINAL_URL.format(year=y)) for y in years]
                real_results = await asyncio.gather(*real_tasks)
                nom_results = await asyncio.gather(*nom_tasks)

            for text in real_results:
                if text is None:
                    continue
                try:
                    df = pd.read_csv(io.StringIO(text), index_col=0, parse_dates=True)
                    if "10 YR" in df.columns:
                        real_frames.append(df[["10 YR"]].rename(columns={"10 YR": "real_yield"}))
                except Exception:
                    pass

            for text in nom_results:
                if text is None:
                    continue
                try:
                    df = pd.read_csv(io.StringIO(text), index_col=0, parse_dates=True)
                    if "10 Yr" in df.columns:
                        nominal_frames.append(
                            df[["10 Yr"]].rename(columns={"10 Yr": "nominal_yield"})
                        )
                except Exception:
                    pass

            return real_frames, nominal_frames

        # Run the async event loop (works whether or not we're already in one)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _fetch_all(years))
                    real_frames, nominal_frames = future.result()
            else:
                real_frames, nominal_frames = loop.run_until_complete(_fetch_all(years))
        except RuntimeError:
            real_frames, nominal_frames = asyncio.run(_fetch_all(years))

        result: dict[str, pd.Series] = {}

        start_ts = (
            pd.Timestamp(start).tz_localize("UTC")
            if start.tzinfo is None
            else pd.Timestamp(start).tz_convert("UTC")
        )
        end_ts = (
            pd.Timestamp(end).tz_localize("UTC")
            if end.tzinfo is None
            else pd.Timestamp(end).tz_convert("UTC")
        )

        if real_frames:
            real_df = pd.concat(real_frames).sort_index()
            real_df.index = pd.to_datetime(real_df.index, utc=True)
            real_df = real_df.loc[start_ts:end_ts]
            result["real_yield"] = real_df["real_yield"].astype(float)

        if nominal_frames:
            nom_df = pd.concat(nominal_frames).sort_index()
            nom_df.index = pd.to_datetime(nom_df.index, utc=True)
            nom_df = nom_df.loc[start_ts:end_ts]
            result["nominal_yield"] = nom_df["nominal_yield"].astype(float)

        return result

    # ------------------------------------------------------------------
    # FRED yield fetcher (used only when FRED_API_KEY is set)
    # ------------------------------------------------------------------

    def _fetch_yields_fred(
        self,
        start: datetime,
        end: datetime,
    ) -> dict[str, pd.Series]:
        """Fetch yields from FRED (requires FRED_API_KEY env var)."""
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx is required: pip install httpx")

        result: dict[str, pd.Series] = {}
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        for series_id, col_name in _FRED_SERIES.items():
            params = {
                "series_id": series_id,
                "observation_start": start_str,
                "observation_end": end_str,
                "file_type": "json",
                "frequency": "d",
                "aggregation_method": "eop",
                "api_key": self._fred_key,
            }
            try:
                r = httpx.get(_FRED_BASE, params=params, timeout=30.0)
                r.raise_for_status()
                obs = r.json().get("observations", [])
                rows = []
                for o in obs:
                    try:
                        val = float(o["value"])
                    except (ValueError, KeyError):
                        val = float("nan")
                    rows.append({"date": o["date"], "value": val})
                if rows:
                    df = pd.DataFrame(rows).set_index("date")
                    df.index = pd.to_datetime(df.index, utc=True)
                    result[col_name] = df["value"]
            except Exception as exc:
                print(f"[MacroFeed] Warning: FRED {series_id}: {exc}")
            time.sleep(0.1)

        return result

    # ------------------------------------------------------------------
    # yfinance market data (DXY, VIX, short-rate proxy)
    # ------------------------------------------------------------------

    def _fetch_yfinance(
        self,
        start: datetime,
        end: datetime,
    ) -> dict[str, pd.Series]:
        """Fetch DXY, VIX, and T-bill rate via yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("yfinance is required: pip install yfinance")

        ticker_map = {
            "DX-Y.NYB": "dxy",
            "^VIX": "vix",
            "^IRX": "fed_funds",  # 13-week T-bill annualised (%)
        }

        result: dict[str, pd.Series] = {}
        try:
            df = yf.download(
                list(ticker_map.keys()),
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
            )["Close"]
            # yfinance returns MultiIndex columns or flat depending on n tickers
            if hasattr(df.columns, "levels"):
                pass  # already multi-level, handled below
            for ticker, col_name in ticker_map.items():
                if ticker in df.columns:
                    s = df[ticker].copy()
                    s.index = pd.to_datetime(s.index, utc=True)
                    result[col_name] = s
        except Exception as exc:
            print(f"[MacroFeed] Warning: yfinance batch download failed: {exc}")
            # Fall back to individual downloads
            for ticker, col_name in ticker_map.items():
                try:
                    df = yf.download(
                        ticker,
                        start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"),
                        auto_adjust=True,
                        progress=False,
                    )["Close"]
                    df.index = pd.to_datetime(df.index, utc=True)
                    result[col_name] = df
                except Exception as exc2:
                    print(f"[MacroFeed] Warning: yfinance {ticker}: {exc2}")

        return result
