#!/usr/bin/env python3
"""
Data Integrity Validation Script for XAUUSD OHLCV Data
======================================================
This script connects to the PostgreSQL database and performs integrity checks
on the `xauusd_ohlcv` table, validating the ingested historical data.

Usage:
    python validate_data.py [--symbol XAUUSD] [--timeframe M1]
"""

import argparse
import psycopg2
import pandas as pd

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "1818",
    "dbname": "postgres",
}

def validate_integrity(symbol: str, timeframe: str):
    print(f"\n🔍 Starting Data Validation for {symbol} ({timeframe})")
    print("=" * 60)

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✅ Connected to PostgreSQL database.")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return

    try:
        with conn.cursor() as cur:
            # Check if table exists
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'xauusd_ohlcv'
                );
            """)
            if not cur.fetchone()[0]:
                print("❌ Table 'xauusd_ohlcv' does not exist. Please run ingestion first.")
                return

            print("✅ Table 'xauusd_ohlcv' exists.")

        # Load data into pandas for validation
        print("⏳ Loading data for validation...")
        query = "SELECT datetime, o, h, l, c, v FROM xauusd_ohlcv WHERE symbol = %s AND timeframe = %s ORDER BY datetime"
        df = pd.read_sql(query, conn, params=(symbol, timeframe))
        
        if df.empty:
            print(f"❌ No data found for {symbol} ({timeframe}).")
            return
            
        print(f"📊 Loaded {len(df):,} rows. Date range: {df['datetime'].min()} to {df['datetime'].max()}")
        
        issues = 0

        # Check 1: Null values
        null_counts = df.isnull().sum()
        total_nulls = null_counts.sum()
        if total_nulls > 0:
            print(f"⚠️ Found {total_nulls} NULL values in the dataset.")
            print(null_counts[null_counts > 0])
            issues += 1
        else:
            print("✅ No NULL values found.")

        # Check 2: Duplicates
        duplicates = df.duplicated(subset=['datetime']).sum()
        if duplicates > 0:
            print(f"❌ Found {duplicates} duplicate timestamps.")
            issues += 1
        else:
            print("✅ No duplicate timestamps found.")

        # Check 3: Price Anomalies (High < Low)
        invalid_hl = df[df['h'] < df['l']]
        if not invalid_hl.empty:
            print(f"❌ Found {len(invalid_hl)} rows where High price is less than Low price.")
            issues += 1
        else:
            print("✅ High >= Low for all records.")

        # Check 4: Price Anomalies (Open/Close outside High/Low range)
        # Using a small tolerance for floating point comparison issues if any, but since it's numeric it should be exact.
        invalid_oc = df[
            (df['o'] > df['h']) | (df['o'] < df['l']) |
            (df['c'] > df['h']) | (df['c'] < df['l'])
        ]
        if not invalid_oc.empty:
            print(f"❌ Found {len(invalid_oc)} rows where Open or Close is outside the High-Low range.")
            issues += 1
        else:
            print("✅ Open and Close prices are within High-Low range for all records.")

        # Check 5: Significant Gaps (e.g. > 1 week)
        df['diff'] = df['datetime'].diff()
        large_gaps = df[df['diff'] > pd.Timedelta(days=7)]
        if not large_gaps.empty:
            print(f"⚠️ Found {len(large_gaps)} large gaps (> 7 days) in the dataset.")
            # Don't strictly consider this an issue, but a warning
            for idx, row in large_gaps.iterrows():
                print(f"   Gap at {row['datetime']} of {row['diff']}")
        else:
            print("✅ No significant gaps (> 7 days) found.")

        print("=" * 60)
        if issues == 0:
            print("🎉 Validation Passed: Data integrity checks completed successfully with no critical issues.")
        else:
            print(f"⚠️ Validation Completed: Found {issues} types of integrity issues. Please review.")

    except Exception as e:
        print(f"❌ An error occurred during validation: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate XAUUSD OHLCV Data Integrity")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol to validate")
    parser.add_argument("--timeframe", type=str, default="M1", help="Timeframe (e.g., M1, H1)")
    args = parser.parse_args()
    
    validate_integrity(args.symbol, args.timeframe)
