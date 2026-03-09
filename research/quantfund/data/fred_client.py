"""
FRED API Client for QuantFund Research Framework

Full implementation of FRED (Federal Reserve Economic Data) API
with rate limiting, caching, and pandas integration.

Usage:
    from quantfund.data.fred_client import FredClient

    client = FredClient(api_key="your-key")

    # Search for series
    results = client.search_series("unemployment")

    # Get observations as DataFrame
    df = client.get_observations("UNRATE", "2020-01-01", "2025-01-01")

    # Get series metadata
    info = client.get_series("UNRATE")
"""

import os
import time
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any, Union

import pandas as pd
import requests

_REQUEST_DELAY = 0.5
_MAX_RETRIES = 3

BASE_URL = "https://api.stlouisfed.org/fred"


class FredClient:
    """
    FRED API Client with rate limiting and caching.

    All methods respect FRED's rate limits (2 requests/second).
    """

    def __init__(self, api_key: Optional[str] = None, cache_dir: Optional[str] = None):
        """
        Initialize FRED client.

        Args:
            api_key: FRED API key. If None, reads from FRED_API_KEY env var.
            cache_dir: Optional directory for caching responses.
        """
        self.api_key = api_key or os.environ.get("FRED_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FRED_API_KEY not set. Provide it as argument or set FRED_API_KEY environment variable."
            )

        self.cache_dir = cache_dir
        self._last_request_time = 0.0
        self._lock = threading.Lock()

    def _rate_limit(self):
        """Apply rate limiting."""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < _REQUEST_DELAY:
                time.sleep(_REQUEST_DELAY - elapsed)
            self._last_request_time = time.time()

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a rate-limited request to FRED API."""
        self._rate_limit()

        url = f"{BASE_URL}{endpoint}"
        params = params or {}
        params["api_key"] = self.api_key

        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 429:
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt == _MAX_RETRIES - 1:
                    raise RuntimeError(f"FRED API error: {e}")
                time.sleep(2**attempt)

        return {}

    def get_series(self, series_id: str) -> Dict:
        """Get series metadata."""
        return self._request(f"/series", {"series_id": series_id})

    def get_observations(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
        frequency: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get series observations as DataFrame.

        Args:
            series_id: FRED series ID (e.g., 'UNRATE', 'GDP')
            observation_start: Start date (YYYY-MM-DD)
            observation_end: End date (YYYY-MM-DD)
            frequency: 'a', 'q', 'm', 'w', 'd' for annual, quarterly, monthly, weekly, daily

        Returns:
            DataFrame with columns: date, value
        """
        params = {"series_id": series_id}
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        if frequency:
            params["frequency"] = frequency

        data = self._request("/series/observations", params)

        observations = data.get("observations", [])
        if not observations:
            return pd.DataFrame(columns=["date", "value"])

        df = pd.DataFrame(observations)
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        return df

    def search_series(
        self,
        query: str,
        limit: int = 100,
        search_type: str = "full",
    ) -> List[Dict]:
        """
        Search for series by keyword.

        Args:
            query: Search text
            limit: Max results (default 100)
            search_type: 'full' or 'exact'

        Returns:
            List of series matching query
        """
        params = {
            "search_text": query,
            "limit": limit,
            "search_type": search_type,
        }
        data = self._request("/series/search", params)
        return data.get("series", [])

    def get_series_updates(
        self,
        realtime_start: Optional[str] = None,
        realtime_end: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Get recently updated series."""
        params = {"limit": limit}
        if realtime_start:
            params["realtime_start"] = realtime_start
        if realtime_end:
            params["realtime_end"] = realtime_end

        data = self._request("/series/updates", params)
        return data.get("series", [])

    def get_series_tags(self, series_id: str) -> List[Dict]:
        """Get tags for a series."""
        params = {"series_id": series_id}
        data = self._request("/series/tags", params)
        return data.get("tags", [])

    def get_all_releases(self, limit: int = 100) -> List[Dict]:
        """Get all releases."""
        params = {"limit": limit}
        data = self._request("/releases", params)
        return data.get("releases", [])

    def get_release(self, release_id: int) -> Dict:
        """Get release info."""
        return self._request("/release", {"release_id": release_id})

    def get_release_series(
        self,
        release_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """Get series in a release."""
        params = {
            "release_id": release_id,
            "limit": limit,
            "offset": offset,
        }
        data = self._request("/release/series", params)
        return data.get("series", [])

    def get_release_dates(self, release_id: int) -> List[Dict]:
        """Get release dates for a release."""
        params = {"release_id": release_id}
        data = self._request("/release/dates", params)
        return data.get("release_dates", [])

    def get_category(self, category_id: int) -> Dict:
        """Get category info."""
        return self._request("/category", {"category_id": category_id})

    def get_category_children(self, category_id: int = 0) -> List[Dict]:
        """Get child categories."""
        params = {"category_id": category_id}
        data = self._request("/category/children", params)
        return data.get("categories", [])

    def get_category_series(
        self,
        category_id: int,
        limit: int = 100,
    ) -> List[Dict]:
        """Get series in a category."""
        params = {"category_id": category_id, "limit": limit}
        data = self._request("/category/series", params)
        return data.get("series", [])

    def get_all_tags(
        self,
        limit: int = 1000,
        order_by: str = "series_count",
        sort_order: str = "desc",
    ) -> List[Dict]:
        """Get all tags."""
        params = {
            "limit": limit,
            "order_by": order_by,
            "sort_order": sort_order,
        }
        data = self._request("/tags", params)
        return data.get("tags", [])

    def get_tags_series(
        self,
        tag_names: str,
        limit: int = 100,
    ) -> List[Dict]:
        """Get series matching tags."""
        params = {"tag_names": tag_names, "limit": limit}
        data = self._request("/tags/series", params)
        return data.get("series", [])

    def get_all_sources(self) -> List[Dict]:
        """Get all sources."""
        data = self._request("/sources", {})
        return data.get("sources", [])

    def get_source(self, source_id: int) -> Dict:
        """Get source info."""
        return self._request("/source", {"source_id": source_id})

    def get_source_releases(self, source_id: int) -> List[Dict]:
        """Get releases from a source."""
        data = self._request("/source/releases", {"source_id": source_id})
        return data.get("releases", [])

    def get_unemployment(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get US unemployment rate."""
        return self.get_observations("UNRATE", start, end)

    def get_gdp(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get US GDP."""
        return self.get_observations("GDP", start, end)

    def get_cpi(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get US CPI."""
        return self.get_observations("CPIAUCSL", start, end)

    def get_fed_funds_rate(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get Federal Funds Rate."""
        return self.get_observations("FEDFUNDS", start, end)

    def get_10y_treasury(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get 10-Year Treasury Constant Maturity Rate."""
        return self.get_observations("DGS10", start, end)

    def get_dxy(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get US Dollar Index."""
        return self.get_observations("DTINYUS", start, end)

    def get_vix(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get VIX."""
        return self.get_observations("VIXCLS", start, end)

    def get_macro_indicators(
        self,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """
        Get common macro indicators as a single DataFrame.

        Columns: unemployment, gdp, cpi, fed_funds, treasury_10y
        """
        indicators = {}

        try:
            indicators["unemployment"] = self.get_unemployment(start, end).set_index("date")[
                "value"
            ]
        except Exception as e:
            print(f"Warning: Could not fetch unemployment: {e}")

        try:
            indicators["gdp"] = self.get_gdp(start, end).set_index("date")["value"]
        except Exception as e:
            print(f"Warning: Could not fetch GDP: {e}")

        try:
            indicators["cpi"] = self.get_cpi(start, end).set_index("date")["value"]
        except Exception as e:
            print(f"Warning: Could not fetch CPI: {e}")

        try:
            indicators["fed_funds"] = self.get_fed_funds_rate(start, end).set_index("date")["value"]
        except Exception as e:
            print(f"Warning: Could not fetch fed funds: {e}")

        try:
            indicators["treasury_10y"] = self.get_10y_treasury(start, end).set_index("date")[
                "value"
            ]
        except Exception as e:
            print(f"Warning: Could not fetch 10y treasury: {e}")

        if not indicators:
            raise RuntimeError("No macro data could be fetched")

        df = pd.DataFrame(indicators)
        df.index = pd.to_datetime(df.index, utc=True)
        df = df.sort_index().ffill()

        return df


def get_fred_client() -> FredClient:
    """Get a FRED client using the API key from environment."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise ValueError("FRED_API_KEY not set in environment")
    return FredClient(api_key=api_key)
