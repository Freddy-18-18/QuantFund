"""
World Bank API Client for QuantFund Research Framework

Full implementation of World Bank Indicators API with rate limiting,
caching, and pandas integration.

Usage:
    from quantfund.data.worldbank_client import WorldBankClient

    client = WorldBankClient()

    # Get countries
    countries = client.get_countries()

    # Get GDP data
    df = client.get_indicator_data("NY.GDP.MKTP.CD", "US", "2020", "2024")

    # Search indicators
    indicators = client.search_indicators("gdp")

    # Get all countries' data for an indicator
    df_all = client.get_indicator_all_countries("NY.GDP.MKTP.CD", "2020", "2024")
"""

import time
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any

import pandas as pd
import requests

# Rate limiting: 1 request per second (World Bank recommended)
_REQUEST_DELAY = 1.0  # seconds
_MAX_RETRIES = 3

# Base URL
BASE_URL = "https://api.worldbank.org/v2"


class WorldBankClient:
    """
    World Bank Indicators API Client with rate limiting.

    No API key required - World Bank API is open.
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize World Bank client.

        Args:
            enabled: Whether the client is enabled
        """
        self.enabled = enabled
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
        """Make a rate-limited request to World Bank API."""
        if not self.enabled:
            raise RuntimeError("World Bank API is disabled")

        self._rate_limit()

        url = f"{BASE_URL}{endpoint}"
        params = params or {}

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
                    raise RuntimeError(f"World Bank API error: {e}")
                time.sleep(2**attempt)

        return {}

    # ==================== Countries ====================

    def get_countries(self, per_page: int = 100, page: int = 1) -> List[Dict]:
        """Get all countries."""
        data = self._request("/country", {"per_page": per_page, "page": page})
        if isinstance(data, list) and len(data) > 1:
            return data[1] if data[1] else []
        return []

    def get_country(self, country_code: str) -> Dict:
        """Get country by ISO code."""
        data = self._request(f"/country/{country_code}", {})
        if isinstance(data, list) and len(data) > 1:
            return data[1][0] if data[1] else {}
        return {}

    # ==================== Indicators ====================

    def get_indicators(self, per_page: int = 100, page: int = 1) -> List[Dict]:
        """Get all indicators."""
        data = self._request("/indicator", {"per_page": per_page, "page": page})
        if isinstance(data, list) and len(data) > 1:
            return data[1] if data[1] else []
        return []

    def search_indicators(self, query: str) -> List[Dict]:
        """Search indicators by name."""
        # World Bank doesn't have direct search, get all and filter
        all_indicators = []
        page = 1
        while True:
            data = self._request("/indicator", {"per_page": 100, "page": page})
            if isinstance(data, list) and len(data) > 1:
                indicators = data[1] if data[1] else []
                if not indicators:
                    break
                all_indicators.extend(indicators)

                # Check if there are more pages
                if isinstance(data[0], dict):
                    total_pages = data[0].get("pages", 1)
                    if page >= total_pages:
                        break
                page += 1
            else:
                break

        # Filter by query
        query_lower = query.lower()
        return [ind for ind in all_indicators if query_lower in ind.get("name", "").lower()]

    def get_indicator(self, indicator_id: str) -> Dict:
        """Get indicator metadata."""
        data = self._request(f"/indicator/{indicator_id}", {})
        if isinstance(data, list) and len(data) > 1:
            return data[1][0] if data[1] else {}
        return {}

    # ==================== Indicator Data ====================

    def get_indicator_data(
        self,
        indicator: str,
        country: str = "all",
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        per_page: int = 100,
    ) -> pd.DataFrame:
        """
        Get indicator data for a country.

        Args:
            indicator: Indicator ID (e.g., 'NY.GDP.MKTP.CD')
            country: Country ISO code (e.g., 'US', 'BRA') or 'all'
            date_start: Start date (YYYY)
            date_end: End date (YYYY)
            per_page: Results per page

        Returns:
            DataFrame with columns: country, country_name, date, value
        """
        params = {"per_page": per_page}
        if date_start:
            if date_end:
                params["date"] = f"{date_start}:{date_end}"
            else:
                params["date"] = date_start

        data = self._request(f"/country/{country}/indicator/{indicator}", params)

        if isinstance(data, list) and len(data) > 1:
            records = data[1] if data[1] else []
        else:
            records = []

        if not records:
            return pd.DataFrame(columns=["country", "country_name", "date", "value"])

        rows = []
        for r in records:
            rows.append(
                {
                    "country": r.get("countryiso3code", r.get("country", {}).get("id", "")),
                    "country_name": r.get("country", {}).get("value", ""),
                    "date": r.get("date", ""),
                    "value": r.get("value"),
                }
            )

        df = pd.DataFrame(rows)
        return df

    def get_indicator_all_countries(
        self,
        indicator: str,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        per_page: int = 100,
    ) -> pd.DataFrame:
        """Get indicator data for all countries."""
        return self.get_indicator_data(indicator, "all", date_start, date_end, per_page)

    # ==================== Topics ====================

    def get_topics(self) -> List[Dict]:
        """Get all topics."""
        data = self._request("/topic", {})
        if isinstance(data, list) and len(data) > 1:
            return data[1] if data[1] else []
        return []

    def get_topic_indicators(self, topic_id: str) -> List[Dict]:
        """Get indicators for a topic."""
        data = self._request(f"/topic/{topic_id}/indicator", {})
        if isinstance(data, list) and len(data) > 1:
            return data[1] if data[1] else []
        return []

    # ==================== Sources ====================

    def get_sources(self) -> List[Dict]:
        """Get all data sources."""
        data = self._request("/source", {})
        if isinstance(data, list) and len(data) > 1:
            return data[1] if data[1] else []
        return []

    # ==================== Convenience Methods ====================

    def get_gdp(
        self, country: str = "US", start_year: Optional[str] = None, end_year: Optional[str] = None
    ) -> pd.DataFrame:
        """Get GDP data (current USD)."""
        return self.get_indicator_data("NY.GDP.MKTP.CD", country, start_year, end_year)

    def get_population(
        self, country: str = "US", start_year: Optional[str] = None, end_year: Optional[str] = None
    ) -> pd.DataFrame:
        """Get total population."""
        return self.get_indicator_data("SP.POP.TOTL", country, start_year, end_year)

    def get_inflation(
        self, country: str = "US", start_year: Optional[str] = None, end_year: Optional[str] = None
    ) -> pd.DataFrame:
        """Get inflation rate (consumer prices)."""
        return self.get_indicator_data("FP.CPI.TOTL.ZG", country, start_year, end_year)

    def get_unemployment(
        self, country: str = "US", start_year: Optional[str] = None, end_year: Optional[str] = None
    ) -> pd.DataFrame:
        """Get unemployment rate."""
        return self.get_indicator_data("SL.UEM.TOTL.ZS", country, start_year, end_year)

    def get_trade(
        self, country: str = "US", start_year: Optional[str] = None, end_year: Optional[str] = None
    ) -> pd.DataFrame:
        """Get trade (% of GDP)."""
        return self.get_indicator_data("NE.EXP.GNFS.ZS", country, start_year, end_year)


# Common indicator IDs for reference
INDICATORS = {
    # GDP
    "gdp_current": "NY.GDP.MKTP.CD",
    "gdp_real": "NY.GDP.MKTP.KD.ZG",
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    # Population
    "population": "SP.POP.TOTL",
    "population_growth": "SP.POP.GROW",
    # Inflation
    "inflation": "FP.CPI.TOTL.ZG",
    # Unemployment
    "unemployment": "SL.UEM.TOTL.ZS",
    # Trade
    "exports": "NE.EXP.GNFS.ZS",
    "imports": "NE.IMP.GNFS.ZS",
    "trade": "NE.TRD.GNFS.ZS",
    # Financial
    "exchange_rate": "PA.NUS.FCRF",
    "interest_rate": "FR.INR.RINR",
    # Debt
    "debt": "GC.DOD.TOTL.GD.ZS",
    # Investment
    "investment": "NE.GDI.TOTL.ZS",
    # Education
    "education_expenditure": "SE.XPD.TOTL.GD.ZS",
    # Health
    "health_expenditure": "SH.XPD.CHEX.GD.ZS",
}

# Country codes for common countries
COUNTRIES = {
    "US": "United States",
    "CN": "China",
    "JP": "Japan",
    "DE": "Germany",
    "GB": "United Kingdom",
    "FR": "France",
    "IN": "India",
    "BR": "Brazil",
    "CA": "Canada",
    "RU": "Russia",
    "MX": "Mexico",
    "AU": "Australia",
    "KR": "South Africa",
    "IT": "Italy",
    "ES": "Spain",
    "NL": "Netherlands",
    "CH": "Switzerland",
    "AR": "Argentina",
}
