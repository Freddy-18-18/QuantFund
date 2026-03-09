"""
FRED Incremental Update Script

Daily/weekly job to update FRED data with new observations only.
Efficiently fetches only new data since last update.

Usage:
    python update_fred_data.py              # Update all series
    python update_fred_data.py --parallel   # Parallel execution
    python update_fred_data.py --verbose   # Detailed logging
    python update_fred_data.py --series GDP,UNRATE  # Specific series

Cron Integration Example:
    # Run daily at 6 AM
    0 6 * * * /path/to/venv/bin/python /path/to/research/scripts/update_fred_data.py >> /var/log/fred_update.log 2>&1

    # Run weekly on Sunday at 2 AM
    0 2 * * 0 /path/to/venv/bin/python /path/to/research/scripts/update_fred_data.py --parallel >> /var/log/fred_update.log 2>&1
"""

import os
import sys
import time
import logging
import argparse
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

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
        "FEDFUNDS",
        "DFF",
        "DFII10",
        "DGS10",
        "DGS2",
        "DGS30",
    ]

    MONEY_SUPPLY = [
        "M2SL",
        "M2MV",
    ]

    INFLATION = [
        "CPIAUCSL",
        "PCEPI",
        "PCECTPI",
    ]

    EMPLOYMENT = [
        "UNRATE",
        "PAYEMS",
        "CIVPART",
    ]

    GDP = [
        "GDP",
        "GDPC1",
    ]

    CONSUMER = [
        "UMCSENT",
        "RETAIL",
    ]

    MARKETS = [
        "SP500",
        "VIX",
        "DTINY",
    ]

    HOUSING = [
        "HOUST",
        "CSUSHPISA",
    ]

    TRADE = [
        "BCCA",
        "EXCHUS",
    ]

    GOLD = [
        "GOLDAMGBD228NLBM",
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


class UpdateStatus(Enum):
    """Status of an incremental update."""

    SUCCESS = "success"
    NO_NEW_DATA = "no_new_data"
    FAILED = "failed"
    SERIES_NOT_FOUND = "series_not_found"


@dataclass
class UpdateResult:
    """Result of a series update."""

    series_id: str
    status: UpdateStatus
    last_observation_date: Optional[date]
    new_observations_count: int = 0
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class UpdateSummary:
    """Summary of all updates."""

    total_series: int
    successful: int
    no_new_data: int
    failed: int
    total_observations: int
    total_duration: float
    start_time: datetime
    end_time: datetime


class RateLimiter:
    """Token bucket rate limiter for FRED API."""

    def __init__(self, requests_per_minute: int = 120):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0

    def wait(self) -> None:
        """Wait until a request can be made."""
        import threading

        with threading.Lock():
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
                    logger.debug(
                        f"Request failed (attempt {attempt + 1}/3): {e}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    raise

    def get_series_metadata(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a FRED series."""
        try:
            data = self._request("series", {"series_id": series_id})
            if "seriess" in data and data["seriess"]:
                return data["seriess"][0]
        except Exception:
            pass
        return None

    def get_latest_observation_date(self, series_id: str) -> Optional[date]:
        """Get the latest observation date from FRED API."""
        try:
            params = {
                "series_id": series_id,
                "limit": 1,
            }
            data = self._request("series/observations", params)

            if "observations" in data and data["observations"]:
                latest = data["observations"][0]
                date_str = latest.get("date")
                if date_str:
                    return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            pass
        return None

    def get_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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
                            {
                                "series_id": series_id,
                                "date": obs_date,
                                "value": value,
                                "realtime_start": realtime_start,
                                "realtime_end": realtime_end,
                            }
                        )
                    except ValueError:
                        continue

        return observations


class FredUpdater:
    """FRED data updater with database operations."""

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

    def get_last_observation_date(self, series_id: str) -> Optional[date]:
        """
        Get the latest date in DB for a series.

        Returns the most recent observation date that is currently in the database
        for the specified FRED series.

        Args:
            series_id: The FRED series identifier

        Returns:
            The latest observation date, or None if no data exists
        """
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

    def update_last_update_timestamp(self, series_id: str) -> bool:
        """Update the last_update timestamp for a series."""
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE fred_series 
                    SET last_updated = NOW()
                    WHERE series_id = %s
                    """,
                    (series_id,),
                )
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update timestamp for {series_id}: {e}")
            return False

    def fetch_new_observations(
        self, series_id: str, since_date: Optional[date] = None
    ) -> Tuple[Optional[date], List[Dict[str, Any]]]:
        """
        Get observations newer than since_date.

        Fetches observations from the FRED API that are newer than the specified date.
        If since_date is None, fetches only the most recent observations to check for updates.

        Args:
            series_id: The FRED series identifier
            since_date: The date to fetch observations since (exclusive)

        Returns:
            Tuple of (latest_date_in_api, new_observations)
        """
        start_str = None
        if since_date:
            start_str = (since_date + timedelta(days=1)).strftime("%Y-%m-%d")

        latest_api_date = self.api.get_latest_observation_date(series_id)

        if not latest_api_date:
            return None, []

        observations = self.api.get_observations(series_id, start_str)

        return latest_api_date, observations

    def save_observations(self, observations: List[Dict[str, Any]]) -> int:
        """Save new observations to database using bulk insert."""
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
                    obs["series_id"],
                    obs["date"],
                    obs["value"],
                    obs["realtime_start"],
                    obs["realtime_end"],
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

    def update_series(self, series_id: str) -> UpdateResult:
        """
        Update a single series.

        Gets the last observation date from the database, fetches new observations
        from the FRED API, and saves them to the database.

        Args:
            series_id: The FRED series identifier

        Returns:
            UpdateResult with update status and details
        """
        start_time = time.time()

        try:
            last_db_date = self.get_last_observation_date(series_id)

            if last_db_date:
                logger.debug(f"Last DB date for {series_id}: {last_db_date}")
            else:
                logger.debug(f"No existing data for {series_id}")

            latest_api_date, new_observations = self.fetch_new_observations(series_id, last_db_date)

            if not latest_api_date:
                return UpdateResult(
                    series_id=series_id,
                    status=UpdateStatus.SERIES_NOT_FOUND,
                    last_observation_date=last_db_date,
                    error_message="Series not found in FRED API",
                    duration_seconds=time.time() - start_time,
                )

            if last_db_date and latest_api_date <= last_db_date:
                return UpdateResult(
                    series_id=series_id,
                    status=UpdateStatus.NO_NEW_DATA,
                    last_observation_date=last_db_date,
                    new_observations_count=0,
                    duration_seconds=time.time() - start_time,
                )

            saved_count = self.save_observations(new_observations)

            if saved_count > 0:
                self.update_last_update_timestamp(series_id)

            actual_last_date = latest_api_date

            return UpdateResult(
                series_id=series_id,
                status=UpdateStatus.SUCCESS if saved_count > 0 else UpdateStatus.NO_NEW_DATA,
                last_observation_date=actual_last_date,
                new_observations_count=saved_count,
                duration_seconds=time.time() - start_time,
            )

        except Exception as e:
            return UpdateResult(
                series_id=series_id,
                status=UpdateStatus.FAILED,
                last_observation_date=None,
                error_message=str(e),
                duration_seconds=time.time() - start_time,
            )

    def get_all_series_in_db(self) -> List[str]:
        """Get list of all series in the database."""
        self._ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute("SELECT series_id FROM fred_series ORDER BY series_id")
            return [row[0] for row in cur.fetchall()]

    def update_all_series(
        self,
        series_list: Optional[List[str]] = None,
        max_workers: int = 1,
    ) -> Tuple[List[UpdateResult], UpdateSummary]:
        """
        Update all series in database.

        Args:
            series_list: Optional list of specific series to update.
                        If None, updates all series in database.
            max_workers: Number of parallel workers (1 = sequential)

        Returns:
            Tuple of (list of UpdateResults, UpdateSummary)
        """
        start_time = datetime.now()

        if series_list is None:
            series_list = self.get_all_series_in_db()

        if not series_list:
            logger.warning("No series found in database to update")
            return [], UpdateSummary(
                total_series=0,
                successful=0,
                no_new_data=0,
                failed=0,
                total_observations=0,
                total_duration=0.0,
                start_time=start_time,
                end_time=datetime.now(),
            )

        results: List[UpdateResult] = []

        logger.info(f"Starting update of {len(series_list)} series...")
        if max_workers > 1:
            logger.info(f"Using parallel execution with {max_workers} workers")

        if max_workers <= 1:
            for i, series_id in enumerate(series_list, 1):
                logger.info(f"Updating {series_id} ({i}/{len(series_list)})...")
                result = self.update_series(series_id)
                results.append(result)

                if result.status == UpdateStatus.SUCCESS:
                    logger.info(
                        f"✓ {series_id}: {result.new_observations_count} new observations "
                        f"in {result.duration_seconds:.1f}s"
                    )
                elif result.status == UpdateStatus.NO_NEW_DATA:
                    logger.debug(f"- {series_id}: No new data ({result.duration_seconds:.1f}s)")
                elif result.status == UpdateStatus.SERIES_NOT_FOUND:
                    logger.warning(f"⚠ {series_id}: {result.error_message}")
                else:
                    logger.error(
                        f"✗ {series_id}: {result.error_message} ({result.duration_seconds:.1f}s)"
                    )
        else:

            def update_single(series_id: str) -> Tuple[str, UpdateResult]:
                updater = FredUpdater(
                    db_config=self.db_config,
                    api_key=self.api.api_key,
                    requests_per_minute=self.api.rate_limiter.requests_per_minute,
                )
                try:
                    return series_id, updater.update_series(series_id)
                finally:
                    updater.close()

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(update_single, series_id): series_id
                    for series_id in series_list
                }

                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    series_id, result = future.result()
                    results.append(result)

                    if result.status == UpdateStatus.SUCCESS:
                        logger.info(
                            f"✓ {series_id}: {result.new_observations_count} new observations "
                            f"in {result.duration_seconds:.1f}s"
                        )
                    elif result.status == UpdateStatus.NO_NEW_DATA:
                        logger.debug(f"- {series_id}: No new data ({result.duration_seconds:.1f}s)")
                    elif result.status == UpdateStatus.SERIES_NOT_FOUND:
                        logger.warning(f"⚠ {series_id}: {result.error_message}")
                    else:
                        logger.error(
                            f"✗ {series_id}: {result.error_message} ({result.duration_seconds:.1f}s)"
                        )

        end_time = datetime.now()

        summary = UpdateSummary(
            total_series=len(series_list),
            successful=sum(1 for r in results if r.status == UpdateStatus.SUCCESS),
            no_new_data=sum(1 for r in results if r.status == UpdateStatus.NO_NEW_DATA),
            failed=sum(1 for r in results if r.status == UpdateStatus.FAILED),
            total_observations=sum(r.new_observations_count for r in results),
            total_duration=sum(r.duration_seconds for r in results),
            start_time=start_time,
            end_time=end_time,
        )

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


def print_summary(summary: UpdateSummary) -> None:
    """Print update summary report."""
    duration = (summary.end_time - summary.start_time).total_seconds()

    logger.info("=" * 60)
    logger.info("INCREMENTAL UPDATE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total series:           {summary.total_series}")
    logger.info(f"Successful updates:     {summary.successful}")
    logger.info(f"No new data:            {summary.no_new_data}")
    logger.info(f"Failed updates:         {summary.failed}")
    logger.info(f"Total new observations: {summary.total_observations}")
    logger.info(f"Total duration:         {duration:.1f}s")
    logger.info(f"Start time:             {summary.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"End time:               {summary.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    if summary.failed > 0:
        logger.warning(f"Warning: {summary.failed} series failed to update")

    if summary.successful == 0 and summary.no_new_data > 0:
        logger.info("All series are up to date!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Incrementally update FRED economic data in database"
    )
    parser.add_argument(
        "--series",
        type=str,
        help="Comma-separated list of series IDs to update",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable parallel execution",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=120,
        help="FRED API requests per minute (default: 120)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config()

    if not config.get("api_key"):
        logger.error("FRED_API_KEY is required. Set it in environment variables.")
        return 1

    if not config.get("host"):
        logger.error("FRED_DB_HOST is required. Set it in environment variables.")
        return 1

    series_list = None
    if args.series:
        series_list = [s.strip() for s in args.series.split(",")]

    max_workers = args.workers if args.parallel else 1

    logger.info("FRED Incremental Update Script")
    logger.info(f"Parallel execution: {max_workers > 1} (workers: {max_workers})")

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

        updater = FredUpdater(
            db_config=config,
            api_key=config["api_key"],
            requests_per_minute=args.rate_limit,
        )

        try:
            updater.connect()
            if series_list:
                for sid in series_list:
                    last_date = updater.get_last_observation_date(sid)
                    logger.info(f"Would update {sid} (last DB date: {last_date})")
            else:
                db_series = updater.get_all_series_in_db()
                logger.info(f"Would update {len(db_series)} series from database")
        finally:
            updater.close()

        return 0

    try:
        updater = FredUpdater(
            db_config=config,
            api_key=config["api_key"],
            requests_per_minute=args.rate_limit,
        )

        try:
            results, summary = updater.update_all_series(
                series_list=series_list,
                max_workers=max_workers,
            )
        finally:
            updater.close()

        print_summary(summary)

        return 0 if summary.failed == 0 else 1

    except Exception as e:
        logger.error(f"Update failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
