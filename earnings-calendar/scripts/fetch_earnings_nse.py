#!/usr/bin/env python3
"""
NSE Earnings Calendar Fetcher

Retrieves upcoming and recent results announcements from NSE, keeps only
Nifty 500 companies, tags each with its index tier and writes JSON.

No API key. Standard library only.

Usage:
    python fetch_earnings_nse.py 2026-11-12 2026-11-18
    python fetch_earnings_nse.py 2026-11-12 2026-11-18 --universe nifty50
    python fetch_earnings_nse.py --help
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from india_client import FMPClient  # noqa: E402

# Index tiers, largest first. A symbol takes the first tier that lists it.
TIERS = [("nifty50", "Nifty 50"), ("midcap150", "Midcap 150"), ("smallcap250", "Smallcap 250")]
TIER_RANK = {"Nifty 50": 0, "Midcap 150": 1, "Smallcap 250": 2, "Nifty 500": 3}


class NSEEarningsCalendar:
    """Results calendar pipeline over the India data client."""

    def __init__(self, client: Optional[FMPClient] = None, universe: str = "nifty500"):
        self.client = client or FMPClient()
        self.universe = universe

    def fetch_earnings_calendar(self, start_date: str, end_date: str) -> Optional[list[dict]]:
        """Results meetings between two dates (YYYY-MM-DD). None on failure."""
        try:
            data = self.client.get_earnings_calendar(start_date, end_date)
        except Exception as exc:  # network or budget errors
            print(f"ERROR: could not read the NSE calendar: {exc}", file=sys.stderr)
            return None
        if not isinstance(data, list):
            print("ERROR: NSE calendar returned no usable data", file=sys.stderr)
            return None
        print(f"OK: retrieved {len(data)} results announcements", file=sys.stderr)
        return data

    def fetch_company_profiles(self, symbols: list[str]) -> dict[str, dict]:
        """Name and industry per symbol from the NSE index lists."""
        profiles = self.client.get_company_profiles(symbols)
        print(f"OK: retrieved {len(profiles)} company profiles", file=sys.stderr)
        return profiles

    def tier_map(self) -> dict[str, str]:
        """Symbol -> index tier (Nifty 50, Midcap 150, Smallcap 250 or Nifty 500)."""
        tiers = {}
        for name, label in TIERS:
            for symbol in self.client.get_universe(name):
                tiers.setdefault(symbol, label)
        for symbol in self.client.get_universe(self.universe):
            tiers.setdefault(symbol, "Nifty 500")
        return tiers

    def filter_by_universe(
        self, earnings: list[dict], profiles: dict[str, dict], tiers: dict[str, str]
    ) -> list[dict]:
        """Keep rows whose symbol is in the chosen universe and enrich them."""
        members = set(self.client.get_universe(self.universe))
        filtered = []
        seen = set()
        for earning in earnings:
            symbol = earning.get("symbol")
            if not symbol or symbol not in members:
                continue
            key = (symbol, earning.get("date"))
            if key in seen:
                continue
            seen.add(key)
            profile = profiles.get(symbol, {})
            row = dict(earning)
            row["companyName"] = profile.get("companyName") or earning.get("company") or symbol
            row["sector"] = profile.get("sector", "N/A")
            row["industry"] = profile.get("industry", "N/A")
            row["index"] = tiers.get(symbol, "Nifty 500")
            row["exchange"] = "NSE"
            filtered.append(row)
        print(
            f"OK: filtered to {len(filtered)} companies in {self.universe}",
            file=sys.stderr,
        )
        return filtered

    def normalize_timing(self, time_value: Optional[str]) -> str:
        """Normalize timing values to BMO/AMC/TAS. NSE gives no time, so TAS is common."""
        if not time_value:
            return "TAS"
        time_lower = str(time_value).lower()
        if time_lower in ["bmo", "pre-market", "before market open"]:
            return "BMO"
        if time_lower in ["amc", "after-market", "after market close"]:
            return "AMC"
        return "TAS"

    def process_earnings(self, earnings: list[dict]) -> list[dict]:
        """Standardize rows for the report."""
        processed = []
        for earning in earnings:
            processed.append(
                {
                    "symbol": earning.get("symbol"),
                    "companyName": earning.get("companyName", earning.get("symbol")),
                    "date": earning.get("date"),
                    "timing": self.normalize_timing(earning.get("time")),
                    "index": earning.get("index", "Nifty 500"),
                    "purpose": earning.get("purpose", ""),
                    "sector": earning.get("sector", "N/A"),
                    "industry": earning.get("industry", "N/A"),
                    "exchange": earning.get("exchange", "NSE"),
                }
            )
        return processed

    def sort_earnings(self, earnings: list[dict]) -> list[dict]:
        """Sort by date, timing, index tier (largest first), then symbol."""
        timing_order = {"BMO": 1, "AMC": 2, "TAS": 3}
        return sorted(
            earnings,
            key=lambda x: (
                x.get("date", ""),
                timing_order.get(x.get("timing", "TAS"), 3),
                TIER_RANK.get(x.get("index", "Nifty 500"), 3),
                x.get("symbol") or "",
            ),
        )


def validate_date(date_str: str) -> bool:
    """Validate date format (YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch NSE results announcements for Nifty 500 companies. JSON goes to stdout."
    )
    parser.add_argument("start_date", help="Start date YYYY-MM-DD")
    parser.add_argument("end_date", help="End date YYYY-MM-DD")
    parser.add_argument(
        "--universe",
        default="nifty500",
        choices=["nifty50", "nifty500", "midcap150", "smallcap250"],
        help="Index universe to keep (default: nifty500)",
    )
    return parser


def run(start_date: str, end_date: str, universe: str, client: Optional[FMPClient] = None):
    """Run the pipeline and return the sorted rows, or None on failure."""
    pipeline = NSEEarningsCalendar(client=client, universe=universe)
    print("Step 1: Fetching results calendar...", file=sys.stderr)
    earnings = pipeline.fetch_earnings_calendar(start_date, end_date)
    if earnings is None:
        return None
    if not earnings:
        print("WARNING: No results announcements found for date range", file=sys.stderr)
        return []

    print("Step 2: Fetching company profiles...", file=sys.stderr)
    symbols = sorted({e.get("symbol") for e in earnings if e.get("symbol")})
    profiles = pipeline.fetch_company_profiles(symbols)
    tiers = pipeline.tier_map()

    print("Step 3: Filtering to the universe...", file=sys.stderr)
    filtered = pipeline.filter_by_universe(earnings, profiles, tiers)
    if not filtered:
        print(f"WARNING: No {universe} companies found", file=sys.stderr)
        return []

    print("Step 4: Processing and sorting...", file=sys.stderr)
    rows = pipeline.sort_earnings(pipeline.process_earnings(filtered))
    print(f"OK: final dataset has {len(rows)} companies", file=sys.stderr)
    return rows


def main(argv=None):
    args = build_parser().parse_args(argv)
    for label, value in (("start", args.start_date), ("end", args.end_date)):
        if not validate_date(value):
            print(f"ERROR: Invalid {label} date format: {value} (use YYYY-MM-DD)", file=sys.stderr)
            sys.exit(1)
    rows = run(args.start_date, args.end_date, args.universe)
    if rows is None:
        sys.exit(1)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    import sys as _sys
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(errors="replace")
    main()
