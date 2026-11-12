#!/usr/bin/env python3
"""
Uptrend Analyzer - data fetcher

Computes uptrend-ratio time series for an NSE universe (default Nifty 500)
from stock prices, using breadth_engine and india_client. Replaces the
upstream CSV dashboard, which does not exist for India. Results are cached
in trader/cache/breadth.json.

Rows keep the same shape the calculators expect:
  timeseries: worksheet, date, count, total, ratio, ma_10, slope, trend
  sector summary: Sector, Ratio, 10MA, Trend, Slope, Status
"""

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import breadth_engine

SOURCE_NAME = "india_client (Yahoo prices, NSE index lists)"
SOURCE_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart"

WORKSHEET_TO_DISPLAY = {ws: sector for sector, ws in breadth_engine.SECTOR_TO_WORKSHEET.items()}

# Overbought and oversold thresholds on the uptrend-ratio scale.
OVERBOUGHT_THRESHOLD = 0.37
OVERSOLD_THRESHOLD = 0.097


def build_summary_from_timeseries(sector_timeseries: dict[str, dict]) -> list[dict]:
    """Build sector_summary-compatible list from timeseries latest rows.

    Used as fallback when sector_summary.csv is unavailable.

    Args:
        sector_timeseries: Dict mapping worksheet name -> latest timeseries row
            e.g. {"sec_technology": {"ratio": 0.288, "ma_10": 0.266, ...}}

    Returns:
        List of dicts matching sector_summary format:
            [{"Sector": "Technology", "Ratio": 0.288, "10MA": 0.266, ...}]
    """
    rows = []
    for ws_name, row in sector_timeseries.items():
        display_name = WORKSHEET_TO_DISPLAY.get(ws_name, ws_name)
        ratio = row.get("ratio")
        status = (
            "Overbought"
            if ratio is not None and ratio > OVERBOUGHT_THRESHOLD
            else "Oversold"
            if ratio is not None and ratio < OVERSOLD_THRESHOLD
            else "Normal"
        )
        rows.append(
            {
                "Sector": display_name,
                "Ratio": ratio,
                "10MA": row.get("ma_10"),
                "Trend": (row.get("trend") or "").capitalize(),
                "Slope": row.get("slope"),
                "Status": status,
                "Count": row.get("count"),
                "Total": row.get("total"),
            }
        )
    return rows


class UptrendDataFetcher:
    """Computes (or reads from cache) the uptrend-ratio time series."""

    def __init__(
        self,
        client=None,
        universe: str = "nifty500",
        max_symbols: Optional[int] = None,
        cache_path: Optional[str] = None,
        refresh: bool = False,
        progress=print,
    ):
        self.client = client
        self.universe = universe
        self.max_symbols = max_symbols
        self.cache_path = cache_path
        self.refresh = refresh
        self.progress = progress
        self.meta: dict = {}
        self.snapshot: dict = {}
        self._timeseries_cache: Optional[list[dict]] = None
        self._sector_summary_cache: Optional[list[dict]] = None

    def _client(self):
        if self.client is None:
            from india_client import FMPClient

            self.client = FMPClient(quiet=True)
        return self.client

    def fetch_timeseries(self) -> list[dict]:
        """Compute the timeseries rows (all + 11 sectors), cached per run."""
        if self._timeseries_cache is not None:
            return self._timeseries_cache
        try:
            res = breadth_engine.get_breadth(
                self._client(),
                universe=self.universe,
                max_symbols=self.max_symbols,
                cache_path=self.cache_path,
                refresh=self.refresh,
                progress=self.progress,
            )
        except Exception as exc:  # network or data problems must not crash the run
            print(f"WARNING: breadth computation failed: {exc}", file=sys.stderr)
            self._timeseries_cache = []
            return []
        self.meta = res["meta"]
        self.snapshot = breadth_engine.latest_snapshot(res["agg"])
        self._timeseries_cache = res["timeseries"]
        return self._timeseries_cache

    def fetch_sector_summary(self) -> list[dict]:
        """Sector summary built from the latest timeseries row of each sector."""
        if self._sector_summary_cache is not None:
            return self._sector_summary_cache
        rows = build_summary_from_timeseries(self.get_all_sector_latest())
        self._sector_summary_cache = rows
        return rows

    def get_all_timeseries(self) -> list[dict]:
        """Timeseries filtered to worksheet=='all', sorted by date ascending."""
        filtered = [r for r in self.fetch_timeseries() if r["worksheet"] == "all"]
        filtered.sort(key=lambda r: r["date"])
        return filtered

    def get_sector_timeseries(self, sector: str) -> list[dict]:
        """Timeseries for one sector worksheet, sorted by date ascending."""
        filtered = [r for r in self.fetch_timeseries() if r["worksheet"] == sector]
        filtered.sort(key=lambda r: r["date"])
        return filtered

    def get_latest_all(self) -> Optional[dict]:
        ts = self.get_all_timeseries()
        return ts[-1] if ts else None

    def get_all_sector_latest(self) -> dict[str, dict]:
        """Latest row for each sector (excluding 'all')."""
        sectors: dict[str, dict] = {}
        for row in self.fetch_timeseries():
            ws = row["worksheet"]
            if ws == "all":
                continue
            if ws not in sectors or row["date"] > sectors[ws]["date"]:
                sectors[ws] = row
        return sectors
