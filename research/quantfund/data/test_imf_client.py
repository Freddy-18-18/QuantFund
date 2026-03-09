"""
Test script for IMF API Client

Usage:
    python -m quantfund.data.test_imf_client
"""

import sys
from quantfund.data.imf_client import ImfClient
import pandas as pd

# Fix Windows console encoding
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def test_connection():
    print("=" * 60)
    print("IMF API Client Test")
    print("=" * 60)

    # Initialize client
    try:
        client = ImfClient()
        print("[OK] Client initialized")
    except Exception as e:
        print(f"[ERROR] Failed to initialize client: {e}")
        return

    # Check API status
    print("\n1. Checking API status...")
    is_available = client.check_api_status()
    print(f"   API available: {is_available}")

    # Get cache info
    cache_info = client.get_cache_info()
    print(f"   Cache: {cache_info['num_files']} files, {cache_info['total_size_mb']} MB")

    # Test dataflows (no cache first to test API)
    print("\n2. Testing Dataflows...")
    try:
        # Try without cache to test API
        dataflows = client.get_dataflows(use_cache=False)
        if not dataflows.empty:
            print(f"   [OK] Found {len(dataflows)} dataflows")
            for _, row in dataflows.head(3).iterrows():
                print(f"     - {row['id']}: {str(row['name'])[:40]}...")
        else:
            # Try with cache
            dataflows = client.get_dataflows(use_cache=True)
            if not dataflows.empty:
                print(f"   [OK] Found {len(dataflows)} dataflows (from cache)")
            else:
                print("   [WARN] No dataflows found (API may be down)")
    except Exception as e:
        print(f"   [ERROR] {e}")

    # Test GDP growth
    print("\n3. Testing GDP Growth for USA (2020-2024)...")
    try:
        df = client.get_gdp_growth("USA", "2020", "2024", use_cache=False)
        if not df.empty:
            print(f"   [OK] Got {len(df)} rows")
            print(df.head())
        else:
            # Try with cache
            df = client.get_gdp_growth("USA", "2020", "2024", use_cache=True)
            if not df.empty:
                print(f"   [OK] Got {len(df)} rows (from cache)")
            else:
                print("   [WARN] No data (API may be down)")
    except Exception as e:
        print(f"   [ERROR] {e}")

    # Test inflation
    print("\n4. Testing Inflation for USA (2020-2024)...")
    try:
        df = client.get_inflation("USA", "2020", "2024", use_cache=False)
        if not df.empty:
            print(f"   [OK] Got {len(df)} rows")
            print(df.head())
    except Exception as e:
        print(f"   [ERROR] {e}")

    # Show final cache status
    cache_info = client.get_cache_info()
    print(f"\n5. Cache status:")
    print(f"   Files: {cache_info['num_files']}")
    print(f"   Size: {cache_info['total_size_mb']} MB")

    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    test_connection()
