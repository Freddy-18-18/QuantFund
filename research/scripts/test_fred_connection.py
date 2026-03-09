#!/usr/bin/env python3
"""
Test script for FRED API connection.

Usage:
    python research/scripts/test_fred_connection.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_script_dir = Path(__file__).resolve().parent
_research_dir = _script_dir.parent
sys.path.insert(0, str(_research_dir))

from quantfund.data.fred_client import FredClient


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def print_dict(data: Dict[str, Any], indent: int = 2) -> None:
    for key, value in data.items():
        print(f"{' ' * indent}{key}: {value}")


def print_list(items: List[Dict], max_items: int = 10) -> None:
    if not items:
        print("  (no results)")
        return

    for i, item in enumerate(items[:max_items]):
        print(f"  {i + 1}. ", end="")
        if "title" in item:
            print(f"{item.get('id', 'N/A')} - {item['title']}")
        elif "name" in item:
            print(f"{item.get('id', 'N/A')} - {item['name']}")
        elif "series_id" in item:
            print(f"{item['series_id']} ({item.get('title', 'N/A')})")
        else:
            print(item)

    if len(items) > max_items:
        print(f"  ... and {len(items) - max_items} more")


def test_user_info(client: FredClient) -> bool:
    """Note: FRED API does not have a /fred/user endpoint."""
    print_section("FRED API User Info")
    print("  Note: FRED API does not provide user info endpoint")
    print("  API Key configured:", f"{client.api_key[:8]}...{client.api_key[-4:]}")
    return True


def test_series_metadata(client: FredClient, series_id: str = "UNRATE") -> bool:
    print_section(f"Series Metadata: {series_id}")
    try:
        data = client.get_series(series_id)
        series_info = data.get("seriess", [{}])[0] if data.get("seriess") else {}
        if series_info:
            print(f"  ID: {series_info.get('id')}")
            print(f"  Title: {series_info.get('title')}")
            print(f"  Frequency: {series_info.get('frequency')}")
            print(f"  Units: {series_info.get('units')}")
            print(f"  Last Updated: {series_info.get('last_updated')}")
            print(f"  Observation Start: {series_info.get('observation_start')}")
            print(f"  Observation End: {series_info.get('observation_end')}")
            return True
        print("  No data returned")
        return False
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def test_observations(client: FredClient, series_id: str = "UNRATE") -> bool:
    print_section(f"Recent Observations: {series_id}")
    try:
        df = client.get_observations(
            series_id,
            observation_start="2024-01-01",
            observation_end="2025-01-01",
        )
        if not df.empty:
            print(f"  Total observations: {len(df)}")
            print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
            print(f"\n  Last 5 observations:")
            print(df.tail().to_string(index=False, header=False))
            return True
        print("  No observations returned")
        return False
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def test_search_gold(client: FredClient) -> bool:
    print_section("Search: Gold / XAU")
    try:
        results = client.search_series("gold", limit=15)
        print(f"  Found {len(results)} series")
        print_list(results, max_items=10)
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def test_search_xau(client: FredClient) -> bool:
    print_section("Search: XAU (Gold Price)")
    try:
        results = client.search_series("XAU", limit=15)
        print(f"  Found {len(results)} series")
        print_list(results, max_items=10)
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def test_categories(client: FredClient) -> bool:
    print_section("Categories")
    try:
        children = client.get_category_children(category_id=0)
        print(f"  Root categories ({len(children)}):")
        for cat in children[:10]:
            print(f"    - {cat.get('name')} (ID: {cat.get('id')})")
        if len(children) > 10:
            print(f"    ... and {len(children) - 10} more")

        if children:
            first_cat = children[0]
            cat_id = first_cat.get("id")
            if cat_id:
                cat_data = client.get_category(category_id=cat_id)
                print(f"\n  Sample category details:")
                print_dict(cat_data.get("categories", [{}])[0], indent=4)

        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def test_releases(client: FredClient) -> bool:
    print_section("Recent Releases")
    try:
        releases = client.get_all_releases(limit=10)
        print(f"  Found {len(releases)} releases")
        for rel in releases[:5]:
            print(f"    - {rel.get('name')} (ID: {rel.get('id')})")
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def test_sources(client: FredClient) -> bool:
    print_section("Data Sources")
    try:
        sources = client.get_all_sources()
        print(f"  Found {len(sources)} sources")
        for src in sources[:5]:
            print(f"    - {src.get('name')} (ID: {src.get('id')})")
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def main() -> int:
    print("\n" + "=" * 60)
    print("  FRED API Connection Test")
    print("=" * 60)

    try:
        client = FredClient()
    except Exception as e:
        print(f"\n  Failed to initialize FRED client: {e}")
        return 1

    print(f"\n  API Key: {client.api_key[:8]}...{client.api_key[-4:]}")
    print("\n  To use your own API key, set the FRED_API_KEY environment variable")
    print("  Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")

    tests = [
        ("User Info", test_user_info),
        ("Series Metadata", test_series_metadata),
        ("Observations", test_observations),
        ("Search: Gold", test_search_gold),
        ("Search: XAU", test_search_xau),
        ("Categories", test_categories),
        ("Releases", test_releases),
        ("Sources", test_sources),
    ]

    results: List[tuple[str, bool]] = []

    for name, test_func in tests:
        try:
            result = test_func(client)
            results.append((name, result))
        except Exception as e:
            print(f"  Unexpected error in {name}: {e}")
            results.append((name, False))

    print_section("Test Summary")
    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  All FRED API tests passed successfully!")
        return 0
    else:
        print(f"\n  Warning: {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
