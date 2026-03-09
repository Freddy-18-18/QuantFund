"""
IMF API Client for QuantFund Research Framework

IMPORTANT: As of March 2026, the IMF API (api.imf.org) has limited data availability.
Only CPI and PPI dataflows are fully accessible via the SDMX 2.1 endpoint.

Working endpoints:
- https://api.imf.org/external/sdmx/2.1/data/CPI/{country}
- https://api.imf.org/external/sdmx/2.1/data/PPI/{country}

Other dataflows may require:
1. IMF Data website (data.imf.org) - manual download
2. Using the old dataservices.imf.org (currently down)
3. Future API updates from IMF

Installation:
    pip install sdmx1 requests pandas python-dotenv

Usage:
    from quantfund.data.imf_client import ImfClient

    client = ImfClient()

    # Working methods (limited data):
    df = client.get_cpi("USA", "2020", "2024")
    df = client.get_ppi("USA", "2020", "2024")

    # Try generic method (may work for some countries/dataflows):
    df = client.get_data("CPI", "USA", "2020", "2024")
"""

import os
import io
import json
import threading
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

try:
    import sdmx

    SDMX_AVAILABLE = True
except ImportError:
    SDMX_AVAILABLE = False

# Project setup
_project_root = Path(__file__).parent.parent.parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

# Cache directory
CACHE_DIR = _project_root / "data" / "imf_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# IMF API endpoints
API_BASE_URL = "https://api.imf.org/external/sdmx/2.1"
SDMXCENTRAL_URL = "https://sdmxcentral.imf.org/ws/public/sdmxapi/rest"

# Working dataflows (tested March 2026)
WORKING_DATAFLOWS = ["CPI", "PPI"]


class ImfClient:
    """
    IMF API Client.

    Note: Limited to CPI and PPI dataflows as of March 2026.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        offline_mode: bool = False,
    ):
        self.api_key = api_key or os.environ.get("IMF_API_KEY_PRIMARY")
        self.cache_dir = cache_dir or CACHE_DIR
        self.offline_mode = offline_mode
        self._lock = threading.Lock()

    # =========================================================================
    # Cache Methods
    # =========================================================================

    def _cache_key(self, key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{self._cache_key(key)}.json"

    def _load_from_cache(self, key: str) -> Optional[Any]:
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _save_to_cache(self, key: str, data: Any):
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: Could not save to cache: {e}")

    # =========================================================================
    # Core API Methods
    # =========================================================================

    def _fetch_data(
        self,
        dataflow: str,
        key: str,
        start_period: Optional[str] = None,
        end_period: Optional[str] = None,
    ) -> pd.Series:
        """Fetch data from IMF API."""
        url = f"{API_BASE_URL}/data/{dataflow}/{key}"

        params = {}
        if start_period:
            params["startPeriod"] = start_period
        if end_period:
            params["endPeriod"] = end_period

        response = requests.get(url, params=params, timeout=120)

        if response.status_code != 200:
            raise RuntimeError(f"API returned {response.status_code}: {response.text[:200]}")

        if not SDMX_AVAILABLE:
            raise ImportError("sdmx1 required. Install: pip install sdmx1")

        bytes_io = io.BytesIO(response.content)
        msg = sdmx.read_sdmx(bytes_io)
        return sdmx.to_pandas(msg)

    def get_data(
        self,
        dataflow: str,
        key: str,
        start_period: Optional[str] = None,
        end_period: Optional[str] = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Get data from IMF dataflow.

        Args:
            dataflow: Dataflow ID (e.g., 'CPI', 'PPI')
            key: Data key (e.g., 'USA', 'MEX')
            start_period: Start period (e.g., '2020', '2020-01')
            end_period: End period (e.g., '2024', '2024-12')
            use_cache: Use cached data

        Returns:
            DataFrame with data
        """
        cache_key = f"{dataflow}_{key}_{start_period}_{end_period}"

        if use_cache:
            cached = self._load_from_cache(cache_key)
            if cached is not None:
                if isinstance(cached, list):
                    df = pd.DataFrame(cached)
                    if "TIME_PERIOD" in df.columns or "period" in df.columns:
                        return df
                return pd.DataFrame(cached)

        try:
            series = self._fetch_data(dataflow, key, start_period, end_period)
            df = series.reset_index()
            self._save_to_cache(cache_key, df.to_dict("records"))
            return df
        except Exception as e:
            print(f"Error: {e}")
            cached = self._load_from_cache(cache_key)
            if cached:
                return pd.DataFrame(cached)
            return pd.DataFrame()

    # =========================================================================
    # Dataflow Exploration
    # =========================================================================

    def list_dataflows(self) -> pd.DataFrame:
        """Get list of all available dataflows from SDMX Central."""
        cache_key = "dataflows_list"

        cached = self._load_from_cache(cache_key)
        if cached:
            return pd.DataFrame(cached)

        url = f"{SDMXCENTRAL_URL}/dataflow/IMF"
        response = requests.get(url, timeout=60)

        if response.status_code == 200 and SDMX_AVAILABLE:
            msg = sdmx.read_sdmx(io.BytesIO(response.content))
            flows = []
            for flow_id, flow in msg.dataflow.items():
                name = (
                    flow.name.get("en", str(flow.name))
                    if hasattr(flow.name, "get")
                    else str(flow.name)
                )
                # Check if working
                working = "✓" if flow_id in WORKING_DATAFLOWS else "✗"
                flows.append({"id": flow_id, "name": name, "working": working})

            df = pd.DataFrame(flows)
            self._save_to_cache(cache_key, flows)
            return df

        return pd.DataFrame()

    def check_available_dataflows(self) -> List[str]:
        """Check which dataflows are actually available via API."""
        available = []

        for df_id in WORKING_DATAFLOWS:
            url = f"{API_BASE_URL}/data/{df_id}/"
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    available.append(df_id)
            except:
                pass

        return available

    # =========================================================================
    # PRICE INDICES (WORKING)
    # =========================================================================

    def get_cpi(
        self,
        country: str = "USA",
        start_period: Optional[str] = None,
        end_period: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Consumer Price Index (CPI).

        Working: ✓

        Args:
            country: Country code (e.g., 'USA', 'MEX', 'CHN')
            start_period: Start period (e.g., '2020')
            end_period: End period (e.g., '2024')

        Returns:
            DataFrame with CPI data
        """
        return self.get_data("CPI", country, start_period, end_period)

    def get_ppi(
        self,
        country: str = "USA",
        start_period: Optional[str] = None,
        end_period: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Producer Price Index (PPI).

        Working: ✓

        Args:
            country: Country code
            start_period: Start period
            end_period: End period

        Returns:
            DataFrame with PPI data
        """
        return self.get_data("PPI", country, start_period, end_period)

    # =========================================================================
    # Methods for other dataflows (may not work due to API limitations)
    # =========================================================================

    def get_gdp(
        self, country: str = "USA", start_period: str = "2020", end_period: str = "2024"
    ) -> pd.DataFrame:
        """GDP - Currently NOT available via API (requires manual download or alternative)."""
        print("Warning: GDP data not available via API. Try get_cpi() or get_ppi() instead.")
        return pd.DataFrame()

    def get_exchange_rates(
        self, country: str = "USA", start_period: str = "2020", end_period: str = "2024"
    ) -> pd.DataFrame:
        """Exchange Rates - Currently NOT available via API."""
        print("Warning: Exchange rates not available via API.")
        return pd.DataFrame()

    def get_balance_of_payments(
        self, country: str = "USA", start_period: str = "2020", end_period: str = "2024"
    ) -> pd.DataFrame:
        """Balance of Payments - Currently NOT available via API."""
        print("Warning: Balance of payments not available via API.")
        return pd.DataFrame()

    def get_unemployment(
        self, country: str = "USA", start_period: str = "2020", end_period: str = "2024"
    ) -> pd.DataFrame:
        """Unemployment - Currently NOT available via API."""
        print("Warning: Unemployment data not available via API.")
        return pd.DataFrame()

    def get_industrial_production(
        self, country: str = "USA", start_period: str = "2020", end_period: str = "2024"
    ) -> pd.DataFrame:
        """Industrial Production - Currently NOT available via API."""
        print("Warning: Industrial production not available via API.")
        return pd.DataFrame()

    # =========================================================================
    # Cache Management
    # =========================================================================

    def clear_cache(self):
        """Clear all cached data."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()

    def get_cache_info(self) -> Dict:
        """Get cache information."""
        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            "num_files": len(cache_files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }

    def export_to_csv(self, df: pd.DataFrame, filename: str) -> Path:
        """Export DataFrame to CSV."""
        export_dir = _project_root / "data" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        filepath = export_dir / filename
        df.to_csv(filepath, index=False)
        return filepath


# =============================================================================
# FACTORY FUNCTION
# =============================================================================


def get_imf_client(**kwargs) -> ImfClient:
    """Get an IMF client instance."""
    return ImfClient(**kwargs)
