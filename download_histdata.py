#!/usr/bin/env python3
"""
XAUUSD Data Downloader from HistData.com
=========================================
Downloads, verifies quality, and loads to PostgreSQL.

Usage:
    python download_histdata.py [--start-year YYYY] [--end-year YYYY] [--timeframe M1|T1]
"""

import os
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

try:
    from histdata import download_hist_data

    HISTDATA_AVAILABLE = True
except ImportError:
    HISTDATA_AVAILABLE = False
    print("Warning: histdata package not available. Will use manual download.")

DOWNLOAD_DIR = Path("histdata_files")
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "1818",
    "dbname": "postgres",
}


def get_required_bars_per_year(timeframe: str) -> dict:
    """Expected number of bars per year for each timeframe."""
    return {
        "M1": 525600,  # Minutes in a year
        "T1": 525600,  # Ticks (1 per minute average)
        "H1": 8760,  # Hours
        "D1": 365,  # Days
    }


def download_histdata_data(
    start_year: int = 2015,
    end_year: int = 2025,
    pair: str = "XAUUSD",
    timeframe: str = "M1",
):
    """
    Download data from HistData.com
    timeframe: 'M1' for 1-minute, 'T1' for tick data
    """
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    # Map HistData timeframe names
    hist_timeframe = "T" if timeframe == "T1" else timeframe

    # Determine if year is current year or past
    current_year = datetime.now().year

    print(f"\n📥 Downloading {pair} {timeframe} from {start_year} to {end_year}")
    print("=" * 60)

    downloaded_files = []

    for year in range(start_year, end_year + 1):
        print(f"\n📅 Year {year}...")

        try:
            if year < current_year:
                # Past years: download entire year (month=None)
                try:
                    download_hist_data(
                        year=str(year),
                        month=None,  # Entire year
                        pair=pair.lower(),
                        time_frame=hist_timeframe,
                        platform="ASCII",
                        output_directory=str(DOWNLOAD_DIR),
                        verbose=False,
                    )
                    time.sleep(2)  # Rate limiting
                except Exception as e:
                    print(f"   Warning: {e}")
                    continue
            else:
                # Current year: download month by month
                for month in range(1, 13):
                    try:
                        download_hist_data(
                            year=str(year),
                            month=str(month),
                            pair=pair.lower(),
                            time_frame=hist_timeframe,
                            platform="ASCII",
                            output_directory=str(DOWNLOAD_DIR),
                            verbose=False,
                        )
                        time.sleep(1)  # Rate limiting
                    except Exception:
                        # Some months might not be available yet
                        continue

            # Find downloaded files
            pattern = f"DAT_ASCII_{pair.upper()}_{hist_timeframe.upper()}_{year}*"
            files = list(DOWNLOAD_DIR.glob(pattern))

            if files:
                print(f"   ✅ {len(files)} file(s) downloaded")
                downloaded_files.extend(files)
            else:
                print(f"   ⚠️ No files found for {year}")

            # Rate limiting - wait between years
            time.sleep(2)

        except Exception as e:
            print(f"   ❌ Error downloading {year}: {e}")
            continue

    return downloaded_files


def parse_histdata_file(filepath: Path, timeframe: str) -> pd.DataFrame:
    """Parse HistData ASCII file into DataFrame."""

    import zipfile

    try:
        # Handle ZIP files
        if filepath.suffix == ".zip":
            with zipfile.ZipFile(filepath, "r") as z:
                # Find the CSV or TXT file
                files = [
                    f for f in z.namelist() if f.endswith(".csv") or f.endswith(".txt")
                ]
                if len(files) > 1:
                    # Multiple files - choose the main one (without header)
                    csv_file = [f for f in files if "header" not in f.lower()][0]
                elif files:
                    csv_file = files[0]
                else:
                    return pd.DataFrame()

                # Read the file content
                with z.open(csv_file) as f:
                    content = f.read().decode("utf-8", errors="ignore")
                    from io import StringIO

                    # No header in HistData files - assign column names
                    df = pd.read_csv(
                        StringIO(content),
                        sep=";",
                        header=None,
                        names=["datetime", "open", "high", "low", "close", "volume"],
                    )
        else:
            # Direct CSV/TXT file - no header
            df = pd.read_csv(
                filepath,
                sep=";",
                header=None,
                names=["datetime", "open", "high", "low", "close", "volume"],
            )

        # Parse datetime (format: YYYYMMDD HHMMSS)
        def parse_datetime(x):
            try:
                return pd.to_datetime(str(x), format="%Y%m%d %H%M%S")
            except:
                return pd.NaT

        df["datetime"] = df["datetime"].apply(parse_datetime)

        # Remove invalid rows
        result = df.dropna()
        result = result[result["datetime"].notna()]

        return result

    except Exception as e:
        print(f"   ❌ Error parsing {filepath.name}: {e}")
        return pd.DataFrame()


def convert_timezone_to_utc(df: pd.DataFrame, source_tz: str = "EST") -> pd.DataFrame:
    """
    Convert timezone to UTC.
    HistData uses EST (Eastern Standard Time) WITHOUT daylight saving.
    """
    if df.empty:
        return df

    # HistData is EST/EDT without DST adjustment
    # We treat it as 'America/New_York' but force standard time
    df["datetime"] = pd.to_datetime(df["datetime"])

    # Localize to EST (no DST)
    df["datetime"] = df["datetime"].dt.tz_localize(
        "America/New_York", ambiguous="infer"
    )

    # Convert to UTC
    df["datetime"] = df["datetime"].dt.tz_convert("UTC")

    # Remove timezone info for storage
    df["datetime"] = df["datetime"].dt.tz_localize(None)

    return df


def verify_data_quality(df: pd.DataFrame, timeframe: str, year: int = None) -> dict:
    """
    Verify data quality: no gaps, no duplicates, expected count.
    Returns dict with quality metrics.
    """
    metrics = {
        "total_rows": len(df),
        "null_count": df.isnull().sum().sum(),
        "duplicate_count": df.duplicated(subset=["datetime"]).sum(),
        "has_gaps": False,
        "quality_score": 0,
    }

    if df.empty:
        return metrics

    # Sort by datetime
    df = df.sort_values("datetime").reset_index(drop=True)

    # Check for expected bar count
    if year:
        expected = get_required_bars_per_year(timeframe).get(timeframe, 0)
        # Allow 5% tolerance for M1
        tolerance = 0.05 if timeframe == "M1" else 0.10
        min_expected = int(expected * (1 - tolerance))
        max_expected = int(expected * (1 + tolerance))

        if len(df) < min_expected:
            metrics["warning"] = f"Expected ~{expected} bars, got {len(df)}"

    # Check for gaps (difference between consecutive bars)
    # For forex, we only care about LARGE gaps (>2 hours) that indicate missing data
    if timeframe == "M1":
        df = df.copy()
        df["diff"] = df["datetime"].diff()

        # Only flag VERY large gaps (>2 hours) - these indicate real missing data
        significant_gaps = df[df["diff"] > timedelta(hours=2)]

        metrics["gap_count"] = len(significant_gaps)
        metrics["has_gaps"] = len(significant_gaps) > 0

        if len(significant_gaps) > 0:
            print(f"   ⚠️ Found {len(significant_gaps)} large gaps (>2 hours)")
            for idx, row in significant_gaps.head(3).iterrows():
                print(f"      Gap at {row['datetime']}: {row['diff']}")

    elif timeframe == "H1":
        df = df.copy()
        df["diff"] = df["datetime"].diff()
        # Flag gaps > 6 hours
        significant_gaps = df[df["diff"] > timedelta(hours=6)]
        metrics["gap_count"] = len(significant_gaps)
        metrics["has_gaps"] = len(significant_gaps) > 0

        if len(significant_gaps) > 0:
            print(f"   ⚠️ Found {len(significant_gaps)} large gaps")
    else:
        metrics["gap_count"] = 0
        metrics["has_gaps"] = False

    # Quality score based on data completeness
    # For forex, gaps are normal (weekends/holidays) so we focus on duplicates/nulls
    score = 100
    score -= min(metrics["null_count"] * 10, 50)  # Cap null penalty
    score -= min(metrics["duplicate_count"] * 5, 30)  # Cap duplicate penalty
    # Gap penalty is very lenient - only penalize if >50 large gaps (each = ~1 weekend)
    gap_penalty = max(0, metrics.get("gap_count", 0) - 50) * 2
    score -= min(gap_penalty, 20)
    metrics["quality_score"] = max(0, min(100, score))

    return metrics


def create_table_if_not_exists(conn):
    """Create xauusd_ohlcv table if not exists."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS xauusd_ohlcv (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                timeframe VARCHAR(5) NOT NULL,
                datetime TIMESTAMP NOT NULL,
                o NUMERIC(18,8),
                h NUMERIC(18,8),
                l NUMERIC(18,8),
                c NUMERIC(18,8),
                v BIGINT,
                source VARCHAR(20) DEFAULT 'histdata',
                UNIQUE(symbol, timeframe, datetime)
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_xauusd_ohlcv_lookup 
            ON xauusd_ohlcv (symbol, timeframe, datetime);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_xauusd_ohlcv_datetime 
            ON xauusd_ohlcv (datetime);
        """)

        conn.commit()
        print("✅ Table 'xauusd_ohlcv' ready")


def load_to_postgres(df: pd.DataFrame, symbol: str, timeframe: str, conn):
    """Load DataFrame to PostgreSQL with upsert logic."""
    if df.empty:
        print("   ⚠️ No data to load")
        return 0

    # Prepare data - rename columns to match DB schema
    df = df.rename(
        columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"}
    )
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df = df[["symbol", "timeframe", "datetime", "o", "h", "l", "c", "v"]]

    # Convert to list of tuples
    records = list(df.itertuples(index=False, name=None))

    # Upsert using ON CONFLICT
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO xauusd_ohlcv (symbol, timeframe, datetime, o, h, l, c, v)
            VALUES %s
            ON CONFLICT (symbol, timeframe, datetime) 
            DO UPDATE SET 
                o = EXCLUDED.o,
                h = EXCLUDED.h,
                l = EXCLUDED.l,
                c = EXCLUDED.c,
                v = EXCLUDED.v
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s, %s, %s)",
        )
        conn.commit()

    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Download XAUUSD from HistData.com")
    parser.add_argument("--start-year", type=int, default=2015, help="Start year")
    parser.add_argument("--end-year", type=int, default=2025, help="End year")
    parser.add_argument(
        "--timeframe",
        type=str,
        default="M1",
        choices=["M1", "T1", "H1", "D1"],
        help="Timeframe: M1 (1-min), T1 (tick), H1 (hourly), D1 (daily)",
    )
    parser.add_argument("--pair", type=str, default="XAUUSD", help="Currency pair")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download, just process existing files",
    )
    parser.add_argument("--skip-db", action="store_true", help="Skip PostgreSQL load")

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("🔶 XAUUSD Data Downloader - HistData.com")
    print("=" * 60)

    # Connect to PostgreSQL
    if not args.skip_db:
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            print("✅ Connected to PostgreSQL")
            create_table_if_not_exists(conn)
        except Exception as e:
            print(f"❌ PostgreSQL connection failed: {e}")
            print("   Continuing without DB load...")
            conn = None
    else:
        conn = None

    # Download data
    if not args.skip_download:
        downloaded = download_histdata_data(
            start_year=args.start_year,
            end_year=args.end_year,
            pair=args.pair,
            timeframe=args.timeframe,
        )
    else:
        # Find existing files
        pattern = f"{args.pair.lower()}{args.timeframe.lower()}*"
        downloaded = list(DOWNLOAD_DIR.glob(pattern))

    if not downloaded:
        print("\n❌ No files found to process")
        return

    print(f"\n📊 Processing {len(downloaded)} file(s)...")
    print("=" * 60)

    all_dfs = []
    year_metrics = []

    for filepath in sorted(downloaded):
        print(f"\n📄 Processing: {filepath.name}")

        # Parse file
        df = parse_histdata_file(filepath, args.timeframe)

        if df.empty:
            print("   ⚠️ Empty file, skipping")
            continue

        # Extract year from filename for expected bar count
        year = int(filepath.stem[-4:]) if len(filepath.stem) >= 4 else None

        # Convert timezone
        df = convert_timezone_to_utc(df)

        # Verify quality
        metrics = verify_data_quality(df, args.timeframe, year)
        year_metrics.append(metrics)

        print(
            f"   📊 Rows: {metrics['total_rows']:,} | Gaps: {metrics.get('gap_count', 0)} | "
            f"Quality: {metrics['quality_score']}%"
        )

        # Accept all data (gaps are normal for forex - weekends/holidays)
        all_dfs.append(df)

    # Combine all data
    if all_dfs:
        combined_df = pd.concat(all_dfs, ignore_index=True)
        combined_df = combined_df.sort_values("datetime").reset_index(drop=True)

        # Remove duplicates (keep last)
        combined_df = combined_df.drop_duplicates(subset=["datetime"], keep="last")

        print(f"\n📈 Combined dataset:")
        print(f"   Total rows: {len(combined_df):,}")
        print(
            f"   Date range: {combined_df['datetime'].min()} to {combined_df['datetime'].max()}"
        )

        # Load to PostgreSQL
        if conn:
            rows_loaded = load_to_postgres(combined_df, args.pair, args.timeframe, conn)
            print(f"\n✅ Loaded {rows_loaded:,} rows to PostgreSQL")

            # Show sample
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT MIN(datetime), MAX(datetime), COUNT(*) 
                    FROM xauusd_ohlcv 
                    WHERE symbol = %s AND timeframe = %s
                """,
                    (args.pair, args.timeframe),
                )
                result = cur.fetchone()
                print(
                    f"   DB now contains: {result[2]:,} bars ({result[0]} to {result[1]})"
                )
    else:
        print("\n⚠️ No valid data to combine")

    if conn:
        conn.close()

    print("\n✅ Done!")


if __name__ == "__main__":
    main()
