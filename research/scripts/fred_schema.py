"""
FRED Database Schema Management Module

This module provides functionality to create and manage the FRED database schema
using PostgreSQL/TimescaleDB. It supports both sync and async operations.

Usage:
    # Synchronous
    from fred_schema import FredSchemaManager
    manager = FredSchemaManager()
    manager.create_schema()

    # Asynchronous
    import asyncio
    from fred_schema import FredSchemaManagerAsync
    async def main():
        manager = FredSchemaManagerAsync()
        await manager.create_schema()
"""

import os
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import date, datetime
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FredFrequency(Enum):
    DAILY = "d"
    WEEKLY = "w"
    BIWEEKLY = "bw"
    MONTHLY = "m"
    QUARTERLY = "q"
    SEMIANNUAL = "sa"
    ANNUAL = "a"


class FredUnits(Enum):
    PERCENT = "percent"
    PERCENT_CHANGE = "percent_change"
    CHAINED_DOLLARS = "chained_dollars"
    DOLLARS = "dollars"
    INDEX = "index"
    MILLIONS = "millions"
    BILLIONS = "billions"
    NUMBER = "number"
    RATIO = "ratio"


class FredSeasonalAdjustment(Enum):
    NOT_SEASONALLY_ADJUSTED = "not_seasonally_adjusted"
    SEASONALLY_ADJUSTED = "seasonally_adjusted"
    NOT_SEASONALLY_ADJUSTED_DAILY = "not_seasonally_adjusted_daily"
    SEASONALLY_ADJUSTED_ANNUAL_RATE = "seasonally_adjusted_annual_rate"


class AnomalySeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FredSeries:
    series_id: str
    title: str
    frequency: FredFrequency = FredFrequency.MONTHLY
    units: FredUnits = FredUnits.PERCENT
    seasonal_adjustment: FredSeasonalAdjustment = FredSeasonalAdjustment.SEASONALLY_ADJUSTED
    popularity: int = 0
    notes: Optional[str] = None


@dataclass
class FredObservation:
    series_id: str
    date: date
    value: Optional[float]
    realtime_start: date
    realtime_end: date = date(9999, 12, 31)


@dataclass
class FredTag:
    name: str
    group_id: Optional[str] = None
    notes: Optional[str] = None
    popularity: int = 0


@dataclass
class FredCategory:
    id: int
    name: str
    parent_id: Optional[int] = None


@dataclass
class FredRelease:
    id: int
    name: str
    press_release: bool = False
    link: Optional[str] = None


class SchemaManagerBase:
    """Base class for schema management operations."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 5432,
        database: str = "freddata",
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host or os.environ.get("FRED_DB_HOST", "localhost")
        self.port = port
        self.database = database
        self.user = user or os.environ.get("FRED_DB_USER", "postgres")
        self.password = password or os.environ.get("FRED_DB_PASSWORD", "")

        self._connection_string = (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )

    def _get_sql_path(self) -> str:
        """Get the path to the SQL migration file."""
        import os as _os

        current_dir = _os.path.dirname(_os.path.abspath(__file__))
        migration_path = _os.path.join(
            _os.path.dirname(current_dir), "migrations", "001_fred_schema.sql"
        )
        return migration_path

    def _read_sql_file(self) -> str:
        """Read the SQL migration file."""
        sql_path = self._get_sql_path()
        with open(sql_path, "r", encoding="utf-8") as f:
            return f.read()

    def _split_sql_statements(self, sql: str) -> List[str]:
        """Split SQL file into individual statements."""
        statements = []
        current_statement = []
        in_comment = False
        in_string = False

        for line in sql.split("\n"):
            stripped = line.strip()

            if stripped.startswith("--"):
                continue

            if "/*" in stripped:
                in_comment = True
            if "*/" in stripped:
                in_comment = False
                continue

            if in_comment:
                continue

            for char in stripped:
                if char == "'" and not in_string:
                    in_string = True
                elif char == "'" and in_string:
                    in_string = False

            current_statement.append(line)

            if not in_string and (stripped.endswith(";") or stripped == ""):
                stmt = "\n".join(current_statement).strip()
                if stmt and not stmt.startswith("--"):
                    statements.append(stmt)
                current_statement = []

        return [s for s in statements if s and not s.startswith("--")]


class FredSchemaManager(SchemaManagerBase):
    """
    Synchronous schema manager for FRED database.
    Uses psycopg2 for database operations.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conn = None
        self._psycopg2 = None

    def _ensure_psycopg2(self):
        """Lazy import psycopg2."""
        if self._psycopg2 is None:
            try:
                import psycopg2

                self._psycopg2 = psycopg2
            except ImportError:
                raise ImportError("psycopg2 is required. Install with: pip install psycopg2-binary")
        return self._psycopg2

    def connect(self):
        """Establish database connection."""
        psycopg2 = self._ensure_psycopg2()
        self._conn = psycopg2.connect(self._connection_string)
        self._conn.autocommit = False
        return self._conn

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def connection(self):
        """Context manager for database connections."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.close()

    def execute_sql(self, sql: str, params: Optional[Tuple] = None) -> None:
        """Execute a single SQL statement."""
        psycopg2 = self._ensure_psycopg2()
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    def create_schema(self, drop_existing: bool = False) -> bool:
        """
        Create the complete FRED database schema.

        Args:
            drop_existing: If True, drops existing tables before creating new ones.

        Returns:
            True if successful, False otherwise.
        """
        try:
            logger.info("Starting schema creation...")

            sql = self._read_sql_file()
            statements = self._split_sql_statements(sql)

            with self.connection() as conn:
                with conn.cursor() as cur:
                    for i, stmt in enumerate(statements):
                        if not stmt.strip():
                            continue
                        try:
                            cur.execute(stmt)
                            if (i + 1) % 10 == 0:
                                logger.info(f"Executed {i + 1}/{len(statements)} statements...")
                        except Exception as e:
                            logger.warning(f"Statement {i + 1} failed: {e}")
                            logger.warning(f"Statement: {stmt[:200]}...")
                            continue

            logger.info("Schema created successfully!")
            return True

        except Exception as e:
            logger.error(f"Failed to create schema: {e}")
            return False

    def create_hypertable(self, table_name: str, time_column: str) -> bool:
        """Create a TimescaleDB hypertable."""
        sql = f"""
        SELECT create_hypertable(
            '{table_name}',
            '{time_column}',
            chunk_time_interval => INTERVAL '1 year',
            if_not_exists => TRUE
        );
        """
        try:
            self.execute_sql(sql)
            return True
        except Exception as e:
            logger.error(f"Failed to create hypertable: {e}")
            return False

    def insert_series(self, series: FredSeries) -> bool:
        """Insert a FRED series."""
        sql = """
        INSERT INTO fred_series (series_id, title, frequency, units, seasonal_adjustment, popularity, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
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
            self.execute_sql(
                sql,
                (
                    series.series_id,
                    series.title,
                    series.frequency.value,
                    series.units.value,
                    series.seasonal_adjustment.value,
                    series.popularity,
                    series.notes,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to insert series: {e}")
            return False

    def insert_observation(self, obs: FredObservation) -> bool:
        """Insert a FRED observation."""
        sql = """
        INSERT INTO fred_observations (series_id, date, value, realtime_start, realtime_end)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING;
        """
        try:
            self.execute_sql(
                sql,
                (
                    obs.series_id,
                    obs.date,
                    obs.value,
                    obs.realtime_start,
                    obs.realtime_end,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to insert observation: {e}")
            return False

    def insert_observations_batch(self, observations: List[FredObservation]) -> int:
        """Insert multiple observations in a batch."""
        sql = """
        INSERT INTO fred_observations (series_id, date, value, realtime_start, realtime_end)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING;
        """
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    data = [
                        (o.series_id, o.date, o.value, o.realtime_start, o.realtime_end)
                        for o in observations
                    ]
                    cur.executemany(sql, data)
                    return cur.rowcount
        except Exception as e:
            logger.error(f"Failed to insert observations batch: {e}")
            return 0

    def insert_tag(self, tag: FredTag) -> bool:
        """Insert a FRED tag."""
        sql = """
        INSERT INTO fred_tags (name, group_id, notes, popularity)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            group_id = EXCLUDED.group_id,
            notes = EXCLUDED.notes,
            popularity = EXCLUDED.popularity;
        """
        try:
            self.execute_sql(
                sql,
                (
                    tag.name,
                    tag.group_id,
                    tag.notes,
                    tag.popularity,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to insert tag: {e}")
            return False

    def insert_category(self, category: FredCategory) -> bool:
        """Insert a FRED category."""
        sql = """
        INSERT INTO fred_categories (id, name, parent_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            parent_id = EXCLUDED.parent_id;
        """
        try:
            self.execute_sql(
                sql,
                (
                    category.id,
                    category.name,
                    category.parent_id,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to insert category: {e}")
            return False

    def insert_release(self, release: FredRelease) -> bool:
        """Insert a FRED release."""
        sql = """
        INSERT INTO fred_releases (id, name, press_release, link)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            press_release = EXCLUDED.press_release,
            link = EXCLUDED.link;
        """
        try:
            self.execute_sql(
                sql,
                (
                    release.id,
                    release.name,
                    release.press_release,
                    release.link,
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to insert release: {e}")
            return False

    def link_series_tag(self, series_id: str, tag_name: str) -> bool:
        """Link a series to a tag."""
        sql = """
        INSERT INTO fred_series_tags (series_id, tag_name)
        VALUES (%s, %s)
        ON CONFLICT (series_id, tag_name) DO NOTHING;
        """
        try:
            self.execute_sql(sql, (series_id, tag_name))
            return True
        except Exception as e:
            logger.error(f"Failed to link series-tag: {e}")
            return False

    def link_series_category(self, series_id: str, category_id: int) -> bool:
        """Link a series to a category."""
        sql = """
        INSERT INTO fred_series_categories (series_id, category_id)
        VALUES (%s, %s)
        ON CONFLICT (series_id, category_id) DO NOTHING;
        """
        try:
            self.execute_sql(sql, (series_id, category_id))
            return True
        except Exception as e:
            logger.error(f"Failed to link series-category: {e}")
            return False

    def get_series(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Get series metadata."""
        sql = "SELECT * FROM fred_series WHERE series_id = %s;"
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (series_id,))
                row = cur.fetchone()
                if row:
                    cols = [desc[0] for desc in cur.description]
                    return dict(zip(cols, row))
        return None

    def get_observations(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Get observations for a series."""
        sql = "SELECT * FROM fred_observations WHERE series_id = %s"
        params = [series_id]

        if start_date:
            sql += " AND date >= %s"
            params.append(start_date)
        if end_date:
            sql += " AND date <= %s"
            params.append(end_date)

        sql += " ORDER BY date ASC"

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                if rows:
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in rows]
        return []

    def setup_sample_data(self) -> bool:
        """Insert sample data for testing."""
        logger.info("Setting up sample data...")

        series_list = [
            FredSeries(
                "GDP",
                "Gross Domestic Product",
                FredFrequency.QUARTERLY,
                FredUnits.BILLIONS,
                FredSeasonalAdjustment.SEASONALLY_ADJUSTED,
                100,
            ),
            FredSeries(
                "CPIAUCSL",
                "Consumer Price Index for All Urban Consumers",
                FredFrequency.MONTHLY,
                FredUnits.INDEX,
                FredSeasonalAdjustment.SEASONALLY_ADJUSTED,
                99,
            ),
            FredSeries(
                "UNRATE",
                "Unemployment Rate",
                FredFrequency.MONTHLY,
                FredUnits.PERCENT,
                FredSeasonalAdjustment.SEASONALLY_ADJUSTED,
                98,
            ),
            FredSeries(
                "FEDFUNDS",
                "Federal Funds Rate",
                FredFrequency.MONTHLY,
                FredUnits.PERCENT,
                FredSeasonalAdjustment.NOT_SEASONALLY_ADJUSTED,
                97,
            ),
            FredSeries(
                "M2SL",
                "M2 Money Supply",
                FredFrequency.WEEKLY,
                FredUnits.BILLIONS,
                FredSeasonalAdjustment.SEASONALLY_ADJUSTED,
                85,
            ),
        ]

        for s in self.insert_series(s):
            pass

        tags_list = [
            FredTag("gdp", "national", "Gross Domestic Product", 100),
            FredTag("price-index", "price", "Price Index related", 95),
            FredTag("employment", "labor", "Employment related", 90),
            FredTag("money-supply", "financial", "Money Supply related", 85),
            FredTag("interest-rate", "financial", "Interest Rate related", 88),
        ]

        for t in tags_list:
            self.insert_tag(t)

        observations = [
            FredObservation("GDP", date(2024, 1, 1), 26984.8, date(2024, 3, 27)),
            FredObservation("GDP", date(2024, 4, 1), 27380.8, date(2024, 6, 26)),
            FredObservation("GDP", date(2024, 7, 1), 27734.1, date(2024, 9, 25)),
            FredObservation("GDP", date(2024, 10, 1), 28118.3, date(2024, 12, 20)),
            FredObservation("CPIAUCSL", date(2024, 1, 1), 310.175, date(2024, 2, 13)),
            FredObservation("CPIAUCSL", date(2024, 2, 1), 310.593, date(2024, 3, 12)),
            FredObservation("CPIAUCSL", date(2024, 3, 1), 312.230, date(2024, 4, 10)),
            FredObservation("UNRATE", date(2024, 1, 1), 3.7, date(2024, 2, 2)),
            FredObservation("UNRATE", date(2024, 2, 1), 3.9, date(2024, 3, 5)),
            FredObservation("UNRATE", date(2024, 3, 1), 3.8, date(2024, 4, 5)),
            FredObservation("FEDFUNDS", date(2024, 1, 1), 5.33, date(2024, 2, 1)),
            FredObservation("FEDFUNDS", date(2024, 2, 1), 5.33, date(2024, 3, 1)),
            FredObservation("FEDFUNDS", date(2024, 3, 1), 5.33, date(2024, 4, 1)),
            FredObservation("M2SL", date(2024, 1, 22), 20920.0, date(2024, 1, 29)),
            FredObservation("M2SL", date(2024, 1, 29), 20960.0, date(2024, 2, 5)),
            FredObservation("M2SL", date(2024, 2, 5), 21010.0, date(2024, 2, 12)),
        ]

        self.insert_observations_batch(observations)

        self.link_series_tag("GDP", "gdp")
        self.link_series_tag("CPIAUCSL", "price-index")
        self.link_series_tag("UNRATE", "employment")
        self.link_series_tag("FEDFUNDS", "interest-rate")
        self.link_series_tag("M2SL", "money-supply")

        logger.info("Sample data setup complete!")
        return True


class FredSchemaManagerAsync(SchemaManagerBase):
    """
    Asynchronous schema manager for FRED database.
    Uses asyncpg for database operations.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conn = None
        self._asyncpg = None

    def _ensure_asyncpg(self):
        """Lazy import asyncpg."""
        if self._asyncpg is None:
            try:
                import asyncpg

                self._asyncpg = asyncpg
            except ImportError:
                raise ImportError("asyncpg is required. Install with: pip install asyncpg")
        return self._asyncpg

    async def connect(self):
        """Establish async database connection."""
        asyncpg = self._ensure_asyncpg()
        self._conn = await asyncpg.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
        )
        return self._conn

    async def close(self):
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @contextmanager
    async def connection(self):
        """Context manager for async database connections."""
        conn = await self.connect()
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
        finally:
            await self.close()

    async def create_schema(self, drop_existing: bool = False) -> bool:
        """Create the complete FRED database schema asynchronously."""
        try:
            logger.info("Starting async schema creation...")

            sql = self._read_sql_file()
            statements = self._split_sql_statements(sql)

            conn = await self.connect()
            try:
                for i, stmt in enumerate(statements):
                    if not stmt.strip():
                        continue
                    try:
                        await conn.execute(stmt)
                        if (i + 1) % 10 == 0:
                            logger.info(f"Executed {i + 1}/{len(statements)} statements...")
                    except Exception as e:
                        logger.warning(f"Statement {i + 1} failed: {e}")
                        continue
            finally:
                await self.close()

            logger.info("Async schema created successfully!")
            return True

        except Exception as e:
            logger.error(f"Failed to create async schema: {e}")
            return False

    async def insert_series(self, series: FredSeries) -> bool:
        """Insert a FRED series asynchronously."""
        sql = """
        INSERT INTO fred_series (series_id, title, frequency, units, seasonal_adjustment, popularity, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
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
            conn = await self.connect()
            try:
                await conn.execute(
                    sql,
                    series.series_id,
                    series.title,
                    series.frequency.value,
                    series.units.value,
                    series.seasonal_adjustment.value,
                    series.popularity,
                    series.notes,
                )
            finally:
                await self.close()
            return True
        except Exception as e:
            logger.error(f"Failed to insert series async: {e}")
            return False

    async def insert_observations_batch(self, observations: List[FredObservation]) -> int:
        """Insert multiple observations in a batch asynchronously."""
        sql = """
        INSERT INTO fred_observations (series_id, date, value, realtime_start, realtime_end)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT DO NOTHING;
        """
        try:
            conn = await self.connect()
            try:
                data = [
                    (o.series_id, o.date, o.value, o.realtime_start, o.realtime_end)
                    for o in observations
                ]
                await conn.executemany(sql, data)
                return len(observations)
            finally:
                await self.close()
        except Exception as e:
            logger.error(f"Failed to insert observations batch async: {e}")
            return 0

    async def get_observations(
        self,
        series_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Get observations for a series asynchronously."""
        sql = "SELECT * FROM fred_observations WHERE series_id = $1"
        params = [series_id]
        param_count = 1

        if start_date:
            param_count += 1
            sql += f" AND date >= ${param_count}"
            params.append(start_date)
        if end_date:
            param_count += 1
            sql += f" AND date <= ${param_count}"
            params.append(end_date)

        sql += " ORDER BY date ASC"

        try:
            conn = await self.connect()
            try:
                rows = await conn.fetch(sql, *params)
                return [dict(row) for row in rows]
            finally:
                await self.close()
        except Exception as e:
            logger.error(f"Failed to get observations async: {e}")
            return []


def create_schema_sync(
    host: Optional[str] = None,
    database: str = "freddata",
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> bool:
    """
    Convenience function to create the FRED schema synchronously.

    Args:
        host: Database host (default: from FRED_DB_HOST env var)
        database: Database name (default: freddata)
        user: Database user (default: from FRED_DB_USER env var)
        password: Database password (default: from FRED_DB_PASSWORD env var)

    Returns:
        True if successful, False otherwise.
    """
    manager = FredSchemaManager(
        host=host,
        database=database,
        user=user,
        password=password,
    )
    return manager.create_schema()


async def create_schema_async(
    host: Optional[str] = None,
    database: str = "freddata",
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> bool:
    """
    Convenience function to create the FRED schema asynchronously.

    Args:
        host: Database host (default: from FRED_DB_HOST env var)
        database: Database name (default: freddata)
        user: Database user (default: from FRED_DB_USER env var)
        password: Database password (default: from FRED_DB_PASSWORD env var)

    Returns:
        True if successful, False otherwise.
    """
    manager = FredSchemaManagerAsync(
        host=host,
        database=database,
        user=user,
        password=password,
    )
    return await manager.create_schema()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if len(sys.argv) > 1 and sys.argv[1] == "--async":
        import asyncio

        result = asyncio.run(create_schema_async())
    else:
        result = create_schema_sync()

    sys.exit(0 if result else 1)
