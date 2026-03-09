"""
FRED Data Ingestion Script

Comprehensive script for downloading and storing FRED economic data series.
Supports rate limiting, retry logic, resume capability, and bulk inserts.

Usage:
    python ingest_fred_data.py
    python ingest_fred_data.py --start-date 2020-01-01
    python ingest_fred_data.py --series GDP,UNRATE
    python ingest_fred_data.py --dry-run
"""

import os
import sys
import time
import logging
import argparse
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import execute_values
except ImportError:
    raise ImportError("psycopg2 is required. Install with: pip install psycopg2-binary")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class PrioritySeries:
    """FRED series priority list for XAUUSD analysis."""

    INTEREST_RATES = [
        "FEDFUNDS",  # Federal Funds Rate
        "DFF",  # Effective Federal Funds Rate
        "DFII10",  # 10-Year Treasury Inflation-Indexed Security
        "DGS10",  # 10-Year Treasury Constant Maturity Rate
        "DGS2",  # 2-Year Treasury Constant Maturity Rate
        "DGS30",  # 30-Year Treasury Constant Maturity Rate
    ]

    MONEY_SUPPLY = [
        "M2SL",  # M2 Money Supply
        "M2MV",  # M2 Velocity
    ]

    INFLATION = [
        "CPIAUCSL",  # Consumer Price Index for All Urban Consumers
        "PCEPI",  # Personal Consumption Expenditures Price Index
        "PCECTPI",  # Personal Consumption Expenditures Chain-Type Price Index
    ]

    EMPLOYMENT = [
        "UNRATE",  # Unemployment Rate
        "PAYEMS",  # Total Nonfarm Payrolls
        "CIVPART",  # Civilian Labor Force Participation Rate
    ]

    GDP = [
        "GDP",  # Gross Domestic Product
        "GDPC1",  # Real Gross Domestic Product
    ]

    CONSUMER = [
        "UMCSENT",  # University of Michigan Consumer Sentiment
        "RETAIL",  # Retail Sales
    ]

    MARKETS = [
        "SP500",  # S&P 500
        "VIX",  # CBOE Volatility Index
        "DTINY",  # Trade Weighted Dollar Index: Broad, Goods and Services
    ]

    HOUSING = [
        "HOUST",  # Housing Starts
        "CSUSHPISA",  # S&P/Case-Shiller U.S. National Home Price Index
    ]

    TRADE = [
        "BCCA",  # Balance on Current Account
        "EXCHUS",  # U.S. / Japan Foreign Exchange Rate
    ]

    GOLD = [
        "GOLDAMGBD228NLBM",  # LBMA Gold Price: Afternoon
    ]

    @classmethod
    def get_all_series(cls) -> List[str]:
        """Get all priority series IDs."""
        all_series = []
        for attr_name in dir(cls):
            if not attr_name.startswith("_"):
                attr = getattr(cls, attr_name)
                if isinstance(attr, list):
                    all_series.extend(attr)
        return all_series

    @classmethod
    def get_series_by_category(cls) -> Dict[str, List[str]]:
        """Get series grouped by category."""
        categories = {}
        for attr_name in dir(cls):
            if not attr_name.startswith("_"):
                attr = getattr(cls, attr_name)
                if isinstance(attr, list):
                    categories[attr_name.lower()] = attr
        return categories


class Frequency(Enum):
    DAILY = "d"
    WEEKLY = "w"
    BIWEEKLY = "bw"
    MONTHLY = "m"
    QUARTERLY = "q"
    SEMIANNUAL = "sa"
    ANNUAL = "a"


class Units(Enum):
    PERCENT = "percent"
    PERCENT_CHANGE = "percent_change"
    CHAINED_DOLLARS = "chained_dollars"
    DOLLARS = "dollars"
    INDEX = "index"
    MILLIONS = "millions"
    BILLIONS = "billions"
    NUMBER = "number"
    RATIO = "ratio"


class SeasonalAdjustment(Enum):
    NOT_SEASONALLY_ADJUSTED = "not_seasonally_adjusted"
    SEASONALLY_ADJUSTED = "seasonally_adjusted"
    NOT_SEASONALLY_ADJUSTED_DAILY = "not_seasonally_adjusted_daily"
    SEASONALLY_ADJUSTED_ANNUAL_RATE = "seasonally_adjusted_annual_rate"


@dataclass
class SeriesMetadata:
    """FRED series metadata."""

    series_id: str
    title: str
    frequency: str = "m"
    units: str = "percent"
    seasonal_adjustment: str = "seasonally_adjusted"
    popularity: int = 0
    notes: Optional[str] = None
    realtime_start: Optional[date] = None
    realtime_end: Optional[date] = None


@dataclass
class Observation:
    """FRED observation data point."""

    series_id: str
    date: date
    value: Optional[float]
    realtime_start: date
    realtime_end: date = field(default_factory=lambda: date(9999, 12, 31))


@dataclass
class IngestionResult:
    """Result of a series ingestion."""

    series_id: str
    success: bool
    observations_count: int = 0
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


class RateLimiter:
    """Token bucket rate limiter for FRED API."""

    def __init__(self, requests_per_minute: int = 120):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0

    def wait(self) -> None:
        """Wait until a request can be made."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()


class FredAPI:
    """FRED API client with retry logic."""

    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str, rate_limiter: Optional[RateLimiter] = None):
        self.api_key = api_key
        self.rate_limiter = rate_limiter or RateLimiter()

        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a request to the FRED API with rate limiting."""
        self.rate_limiter.wait()

        url = f"{self.BASE_URL}/{endpoint}"
        params["api_key"] = self.api_key
        params["file_type"] = "json"

        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    wait_time = 2**attempt
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/3): {e}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    raise

    def get_series_metadata(self, series_id: str) -> Optional[SeriesMetadata]:
        """Get metadata for a FRED series."""
        data = self._request("series", {"series_id": series_id})

        if "seriess" in data and data["seriess"]:
            s = data["seriess"][0]
            return SeriesMetadata(
                series_id=s.get("id", series_id),
                title=s.get("title", ""),
                frequency=s.get("frequency", "m"),
                units=s.get("units", "percent"),
                seasonal_adjustment=s.get("seasonal_adjustment", "seasonally_adjusted"),
                popularity=int(s.get("popularity", 0)),
                notes=s.get("notes"),
            )
        return None

    def get_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Observation]:
        """Get observations for a FRED series."""
        params = {"series_id": series_id}

        if start_date:
            params["observation_start"] = start_date
        if end_date:
            params["observation_end"] = end_date

        data = self._request("series/observations", params)

        observations = []
        if "observations" in data:
            for obs in data["observations"]:
                date_str = obs.get("date")
                value_str = obs.get("value")

                if date_str:
                    try:
                        obs_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        value = None
                        if value_str and value_str != ".":
                            value = float(value_str)

                        realtime_start = datetime.strptime(
                            obs.get("realtime_start", "9999-12-31"), "%Y-%m-%d"
                        ).date()
                        realtime_end = datetime.strptime(
                            obs.get("realtime_end", "9999-12-31"), "%Y-%m-%d"
                        ).date()

                        observations.append(
                            Observation(
                                series_id=series_id,
                                date=obs_date,
                                value=value,
                                realtime_start=realtime_start,
                                realtime_end=realtime_end,
                            )
                        )
                    except ValueError:
                        continue

        return observations


class FredIngestor:
    """FRED data ingestor with database operations."""

    def __init__(
        self,
        db_config: Dict[str, Any],
        api_key: str,
        requests_per_minute: int = 120,
    ):
        self.db_config = db_config
        self.api = FredAPI(api_key, RateLimiter(requests_per_minute))
        self.conn = None

    def connect(self) -> None:
        """Establish database connection."""
        self.conn = psycopg2.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )
        self.conn.autocommit = False

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    @property
    def _is_connected(self) -> bool:
        return self.conn is not None and not self.conn.closed

    def _ensure_connection(self) -> None:
        """Ensure database connection exists."""
        if not self._is_connected:
            self.connect()

    def get_existing_series(self) -> List[str]:
        """Get list of series that already have data in the database."""
        self._ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute("SELECT series_id FROM fred_series")
            return [row[0] for row in cur.fetchall()]

    def get_latest_observation_date(self, series_id: str) -> Optional[date]:
        """Get the latest observation date for a series."""
        self._ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(date) FROM fred_observations
                WHERE series_id = %s AND realtime_end = '9999-12-31'
                """,
                (series_id,),
            )
            result = cur.fetchone()
            return result[0] if result and result[0] else None

    def download_series_metadata(self, series_id: str) -> Optional[SeriesMetadata]:
        """Download series metadata from FRED API."""
        logger.info(f"Downloading metadata for {series_id}...")
        return self.api.get_series_metadata(series_id)

    def download_observations(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Observation]:
        """Download observations from FRED API."""
        logger.info(f"Downloading observations for {series_id}...")

        start_str = start_date.strftime("%Y-%m-%d") if start_date else None
        end_str = end_date.strftime("%Y-%m-%d") if end_date else None

        return self.api.get_observations(series_id, start_str, end_str)

    def save_series_metadata(self, metadata: SeriesMetadata) -> bool:
        """Save series metadata to database."""
        self._ensure_connection()
        sql = """
            INSERT INTO fred_series
                (series_id, title, frequency, units, seasonal_adjustment, popularity, notes, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (series_id) DO UPDATE SET
                title = EXCLUDED.title,
                frequency = EXCLUDED.frequency,
                units = EXCLUDED.units,
                seasonal_adjustment = EXCLUDED.seasonal_adjustment,
                popularity = EXCLUDED.popularity,
                notes = EXCLUDED.notes,
                last_updated = NOW();
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        metadata.series_id,
                        metadata.title,
                        metadata.frequency,
                        metadata.units,
                        metadata.seasonal_adjustment,
                        metadata.popularity,
                        metadata.notes,
                    ),
                )
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to save metadata for {metadata.series_id}: {e}")
            return False

    def save_observations(self, observations: List[Observation]) -> int:
        """Save observations to database using bulk insert."""
        if not observations:
            return 0

        self._ensure_connection()

        sql = """
            INSERT INTO fred_observations
                (series_id, date, value, realtime_start, realtime_end)
            VALUES %s
            ON CONFLICT (series_id, date, realtime_start, realtime_end) DO NOTHING;
        """

        try:
            data = [
                (
                    obs.series_id,
                    obs.date,
                    obs.value,
                    obs.realtime_start,
                    obs.realtime_end,
                )
                for obs in observations
            ]

            with self.conn.cursor() as cur:
                execute_values(cur, sql, data, page_size=1000)

            self.conn.commit()
            return len(observations)
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to save observations: {e}")
            return 0

    def ingest_series(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        skip_existing: bool = True,
    ) -> IngestionResult:
        """Ingest a single FRED series."""
        start_time = time.time()

        try:
            metadata = self.download_series_metadata(series_id)
            if not metadata:
                return IngestionResult(
                    series_id=series_id,
                    success=False,
                    error_message="Failed to download metadata",
                    duration_seconds=time.time() - start_time,
                )

            self.save_series_metadata(metadata)

            download_start = start_date
            if skip_existing and not start_date:
                latest_date = self.get_latest_observation_date(series_id)
                if latest_date:
                    download_start = latest_date + timedelta(days=1)
                    logger.info(f"Resuming {series_id} from {download_start}")

            observations = self.download_observations(series_id, download_start, end_date)

            saved_count = self.save_observations(observations)

            return IngestionResult(
                series_id=series_id,
                success=True,
                observations_count=saved_count,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return IngestionResult(
                series_id=series_id,
                success=False,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def ingest_all_series(
        self,
        series_list: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        skip_existing: bool = True,
    ) -> Tuple[List[IngestionResult], Dict[str, Any]]:
        """Ingest all priority FRED series."""
        if series_list is None:
            series_list = PrioritySeries.get_all_series()

        existing_series = set(self.get_existing_series()) if skip_existing else set()

        results: List[IngestionResult] = []
        skipped = 0

        total = len(series_list)
        logger.info(f"Starting ingestion of {total} series...")

        for i, series_id in enumerate(series_list, 1):
            logger.info(f"Processing {series_id} ({i}/{total})...")

            if skip_existing and series_id in existing_series:
                latest = self.get_latest_observation_date(series_id)
                logger.info(f"Skipping {series_id} (already exists, latest: {latest})")
                skipped += 1
                continue

            result = self.ingest_series(series_id, start_date, end_date, skip_existing)
            results.append(result)

            if result.success:
                logger.info(
                    f"✓ {series_id}: {result.observations_count} observations "
                    f"in {result.duration_seconds:.1f}s"
                )
            else:
                logger.error(
                    f"✗ {series_id}: {result.error_message} in {result.duration_seconds:.1f}s"
                )

        summary = {
            "total": total,
            "completed": len(results),
            "successful": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "skipped": skipped,
            "total_observations": sum(r.observations_count for r in results),
            "total_duration": sum(r.duration_seconds for r in results),
        }

        return results, summary


def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables."""
    required_vars = {
        "FRED_DB_HOST": "host",
        "FRED_DB_PORT": "port",
        "FRED_DB_NAME": "database",
        "FRED_DB_USER": "user",
        "FRED_DB_PASSWORD": "password",
        "FRED_API_KEY": "api_key",
    }

    config = {}
    missing = []

    for env_var, key in required_vars.items():
        value = os.environ.get(env_var)
        if not value:
            missing.append(env_var)
            continue

        if key in ["port"]:
            try:
                config[key] = int(value)
            except ValueError:
                config[key] = 5432
        else:
            config[key] = value

    if missing:
        logger.warning(f"Missing environment variables: {', '.join(missing)}")

    return config


def print_summary(summary: Dict[str, Any]) -> None:
    """Print ingestion summary report."""
    logger.info("=" * 60)
    logger.info("INGESTION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total series:           {summary['total']}")
    logger.info(f"Completed:              {summary['completed']}")
    logger.info(f"Successful:             {summary['successful']}")
    logger.info(f"Failed:                 {summary['failed']}")
    logger.info(f"Skipped (already exists): {summary['skipped']}")
    logger.info(f"Total observations:     {summary['total_observations']}")
    logger.info(f"Total duration:         {summary['total_duration']:.1f}s")
    logger.info("=" * 60)

    if summary["failed"] > 0:
        logger.warning(f"Warning: {summary['failed']} series failed to ingest")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Ingest FRED economic data into database")
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date for observations (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date for observations (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--series",
        type=str,
        help="Comma-separated list of series IDs to ingest",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip series that already have data (default: True)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download all data regardless of existing records",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be ingested without making changes",
    )
    parser.add_argument(
        "--list-series",
        action="store_true",
        help="List all available series and exit",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=120,
        help="FRED API requests per minute (default: 120)",
    )

    args = parser.parse_args()

    if args.list_series:
        categories = PrioritySeries.get_series_by_category()
        print("\nAvailable FRED Series:")
        print("=" * 40)
        for category, series_list in categories.items():
            print(f"\n{category.upper()}:")
            for s in series_list:
                print(f"  - {s}")
        print(f"\nTotal: {len(PrioritySeries.get_all_series())} series")
        return 0

    config = load_config()

    if not config.get("api_key"):
        logger.error("FRED_API_KEY is required. Set it in environment variables.")
        return 1

    if not config.get("host"):
        logger.error("FRED_DB_HOST is required. Set it in environment variables.")
        return 1

    start_date = None
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid start date: {args.start_date}")
            return 1

    end_date = None
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Invalid end date: {args.end_date}")
            return 1

    series_list = None
    if args.series:
        series_list = [s.strip() for s in args.series.split(",")]

    skip_existing = args.skip_existing and not args.no_skip_existing

    logger.info("FRED Data Ingestion Script")
    logger.info(f"Start date: {start_date or 'earliest available'}")
    logger.info(f"End date: {end_date or 'latest available'}")
    logger.info(f"Skip existing: {skip_existing}")

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
        if series_list:
            logger.info(f"Would ingest series: {', '.join(series_list)}")
        else:
            logger.info(f"Would ingest all {len(PrioritySeries.get_all_series())} priority series")
        return 0

    try:
        ingestor = FredIngestor(
            db_config=config,
            api_key=config["api_key"],
            requests_per_minute=args.rate_limit,
        )

        try:
            results, summary = ingestor.ingest_all_series(
                series_list=series_list,
                start_date=start_date,
                end_date=end_date,
                skip_existing=skip_existing,
            )
        finally:
            ingestor.close()

        print_summary(summary)

        return 0 if summary["failed"] == 0 else 1

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
