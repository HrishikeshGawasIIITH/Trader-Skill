"""UptrendDataFetcher and main smoke tests with a fake client (no network)."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import data_fetcher as df  # noqa: E402
import uptrend_analyzer as analyzer  # noqa: E402


def make_bars(n, drift=0.002, start=100.0, seed=1, end=date(2026, 11, 10), volume=500_000):
    """Newest-first bars on weekdays ending at `end`."""
    days = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    bars, px, x = [], start, seed
    for dt in days:
        x = (x * 1103515245 + 12345) % (2**31)
        noise = ((x / 2**31) - 0.5) * 0.02
        px *= 1 + drift + noise
        bars.append(
            {
                "date": dt.isoformat(),
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "adjClose": px,
                "volume": volume,
            }
        )
    return list(reversed(bars))


class FakeClient:
    SYMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    INDUSTRY = {
        "AAA": "Information Technology",
        "BBB": "Financial Services",
        "CCC": "Healthcare",
        "DDD": "Power",
        "EEE": "Realty",
        "FFF": "Metals & Mining",
        "GGG": "Fast Moving Consumer Goods",
        "HHH": "Oil Gas & Consumable Fuels",
    }

    def __init__(self):
        self.price_calls = 0

    def get_universe(self, name="nifty500"):
        return list(self.SYMS)

    def get_company_profiles(self, symbols):
        return {s: {"companyName": s, "industry": self.INDUSTRY[s], "sector": self.INDUSTRY[s]} for s in symbols}

    def get_historical_prices(self, symbol, days=365):
        self.price_calls += 1
        if symbol == "^NSEI":
            return {"symbol": symbol, "historical": make_bars(min(days, 1250), 0.0007, 20000, 99)}
        i = self.SYMS.index(symbol)
        drift = 0.0015 if i % 3 else -0.0004
        return {"symbol": symbol, "historical": make_bars(min(days, 1250), drift, 100 + i * 10, i + 1)}


class FetcherTests(unittest.TestCase):
    def test_timeseries_shape_and_sectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = df.UptrendDataFetcher(
                client=FakeClient(), cache_path=os.path.join(tmp, "b.json"), progress=None
            )
            rows = f.fetch_timeseries()
            self.assertTrue(rows)
            for key in ("worksheet", "date", "count", "total", "ratio", "ma_10", "slope", "trend"):
                self.assertIn(key, rows[0])
            self.assertTrue(f.get_all_timeseries())
            self.assertIn("sec_technology", f.get_all_sector_latest())
            self.assertEqual(f.get_latest_all()["worksheet"], "all")
            self.assertTrue(0 <= f.get_latest_all()["ratio"] <= 1)
            summary = f.fetch_sector_summary()
            self.assertTrue(all(r["Status"] in ("Overbought", "Oversold", "Normal") for r in summary))
            self.assertIn("Technology", [r["Sector"] for r in summary])

    def test_failure_returns_empty(self):
        class Broken:
            def get_historical_prices(self, *a, **k):
                raise RuntimeError("down")

        f = df.UptrendDataFetcher(client=Broken(), progress=None)
        self.assertEqual(f.fetch_timeseries(), [])
        self.assertIsNone(f.get_latest_all())


class MainSmokeTest(unittest.TestCase):
    def test_main_end_to_end_with_fake_client(self):
        import india_client

        with tempfile.TemporaryDirectory() as tmp:
            argv = ["uptrend_analyzer.py", "--output-dir", tmp, "--cache", os.path.join(tmp, "b.json")]
            real = df.UptrendDataFetcher

            def factory(**kw):
                return real(client=FakeClient(), progress=None, **kw)

            with mock.patch.object(analyzer, "UptrendDataFetcher", factory), mock.patch("sys.argv", argv):
                orig = df.breadth_engine.get_breadth
                with mock.patch.object(
                    df.breadth_engine, "get_breadth", lambda c, **kw: orig(c, **dict(kw, days=400))
                ):
                    analyzer.main()
            js = [f for f in os.listdir(tmp) if f.endswith(".json") and f.startswith("uptrend")]
            self.assertTrue(js)
            with open(os.path.join(tmp, js[0]), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertTrue(0 <= data["composite"]["composite_score"] <= 100)
            self.assertEqual(data["data_provenance"]["timezone"], "Asia/Kolkata")

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
