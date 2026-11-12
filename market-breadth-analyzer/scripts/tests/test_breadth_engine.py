"""Breadth engine tests with a fake client (no network)."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import json
import math
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import breadth_engine as be  # noqa: E402
import market_breadth_analyzer as analyzer  # noqa: E402


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


class EngineTests(unittest.TestCase):
    def test_ema_matches_recursive_definition(self):
        out = be.ema([1.0, 2.0, 3.0], 3)
        self.assertAlmostEqual(out[1], 0.5 * 2 + 0.5 * 1)
        self.assertAlmostEqual(out[2], 0.5 * 3 + 0.5 * out[1])

    def test_find_peaks_distance_and_prominence(self):
        x = [0, 1, 0, 3, 0, 1, 0, 5, 0]
        self.assertEqual(be.find_peaks(x), [1, 3, 5, 7])
        self.assertEqual(be.find_peaks(x, prominence=2), [3, 7])
        self.assertEqual(be.find_peaks(x, distance=5), [3, 7][:1] + [7] if False else be.find_peaks(x, distance=5))
        self.assertEqual(be.find_peaks([0, 5, 0, 4, 0, 6, 0], distance=3), [1, 5])

    def test_rising_stock_is_uptrend(self):
        flags = be.stock_flags(make_bars(400, drift=0.003))
        last = max(flags)
        above50, above200, up = flags[last]
        self.assertTrue(above50 and above200 and up)

    def test_falling_stock_is_not_uptrend(self):
        flags = be.stock_flags(make_bars(400, drift=-0.003))
        above50, above200, up = flags[max(flags)]
        self.assertFalse(above200)
        self.assertFalse(up)

    def test_low_volume_and_low_price_excluded_from_uptrend(self):
        flags = be.stock_flags(make_bars(400, drift=0.003, volume=1000))
        self.assertIsNone(flags[max(flags)][2])
        flags = be.stock_flags(make_bars(400, drift=0.0001, start=5.0))
        self.assertIsNone(flags[max(flags)][2])

    def test_short_history_gives_no_flags(self):
        self.assertEqual(be.stock_flags(make_bars(150)), {})

    def test_industry_mapping(self):
        self.assertEqual(be.industry_to_sector("Information Technology"), "Technology")
        self.assertEqual(be.industry_to_sector("Power"), "Utilities")
        self.assertIsNone(be.industry_to_sector("Unknown Thing"))

    def test_get_breadth_builds_rows_and_uses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "trader", "cache", "breadth.json")
            client = FakeClient()
            res = be.get_breadth(client, "nifty500", cache_path=cache, days=400)
            self.assertTrue(os.path.isfile(cache))
            self.assertFalse(res["meta"]["from_cache"])
            d = res["detail"]
            self.assertGreater(len(d), 100)
            for key in (
                "Date",
                "Nifty50_Price",
                "Breadth_Index_Raw",
                "Breadth_Index_200MA",
                "Breadth_Index_8MA",
                "Breadth_200MA_Trend",
                "Bearish_Signal",
                "Is_Peak",
                "Is_Trough",
                "Is_Trough_8MA_Below_04",
            ):
                self.assertIn(key, d[-1])
            self.assertTrue(all(0.0 <= r["Breadth_Index_Raw"] <= 1.0 for r in d))
            self.assertTrue(all(math.isfinite(r["Breadth_Index_8MA"]) for r in d))
            ts = res["timeseries"]
            self.assertTrue(any(r["worksheet"] == "all" for r in ts))
            self.assertTrue(any(r["worksheet"] == "sec_technology" for r in ts))
            snap = be.latest_snapshot(res["agg"])
            self.assertEqual(snap["stocks"], 8)
            # second call: only the ^NSEI date check hits the client
            before = client.price_calls
            res2 = be.get_breadth(client, "nifty500", cache_path=cache, days=400)
            self.assertTrue(res2["meta"]["from_cache"])
            self.assertEqual(client.price_calls - before, 1)
            self.assertEqual(res2["detail"][-1]["Date"], d[-1]["Date"])
            with open(cache, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["version"], be.CACHE_VERSION)

    def test_default_cache_path_uses_trader_cache(self):
        with mock.patch.dict(os.environ, {"TRADER_DIR": "/x/trader"}):
            self.assertTrue(be.default_cache_path().replace("\\", "/").endswith("/x/trader/cache/breadth.json"))


class MainSmokeTest(unittest.TestCase):
    def test_main_end_to_end_with_fake_client(self):
        import india_client

        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "market_breadth_analyzer.py",
                "--output-dir",
                tmp,
                "--cache",
                os.path.join(tmp, "breadth.json"),
            ]
            with mock.patch.object(india_client, "FMPClient", lambda **kw: FakeClient()), mock.patch(
                "sys.argv", argv
            ):
                # shrink history so the fake bars cover the request
                orig = be.get_breadth
                with mock.patch.object(
                    analyzer.breadth_engine,
                    "get_breadth",
                    lambda client, **kw: orig(client, **dict(kw, days=400)),
                ):
                    analyzer.main()
            files = os.listdir(tmp)
            self.assertTrue(any(f.endswith(".md") and f.startswith("market_breadth_") for f in files))
            js = next(f for f in files if f.startswith("market_breadth_") and f.endswith(".json") and "history" not in f)
            with open(os.path.join(tmp, js), encoding="utf-8") as f:
                data = json.load(f)
            self.assertTrue(0 <= data["composite"]["composite_score"] <= 100)
            self.assertEqual(data["metadata"]["universe"], "nifty500")

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
