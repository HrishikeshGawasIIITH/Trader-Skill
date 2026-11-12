"""End-to-end smoke test of market_top_detector.main with a fake client (no network)."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import breadth_engine  # noqa: E402
import market_top_detector as mtd  # noqa: E402
from index_data import build_midcap_composite  # noqa: E402


def make_bars(n, drift=0.001, start=100.0, seed=1, volume=800_000):
    """Newest-first weekday bars ending on the last weekday before today."""
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    days = []
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    out, px, x = [], start, seed
    for i, dt in enumerate(days):
        x = (x * 1103515245 + 12345) % (2**31)
        px *= 1 + drift + ((x / 2**31) - 0.5) * 0.012
        out.append(
            {
                "date": dt.isoformat(),
                "open": px * 0.998,
                "high": px * 1.006,
                "low": px * 0.994,
                "close": px,
                "adjClose": px,
                "volume": volume + (i % 7) * 50_000,
            }
        )
    return list(reversed(out))


class FakeClient:
    """Implements the india_client surface used by the detector."""

    STOCKS = [f"M{i}" for i in range(12)]
    INDUSTRIES = ["Information Technology", "Financial Services", "Healthcare", "Power"]

    def __init__(self):
        self.calls = 0

    def _bars(self, symbol, days):
        n = min(max(days, 60), 600)
        if symbol.startswith("^") or symbol.endswith(".NS"):
            return make_bars(n, 0.0006, 1000.0, hash(symbol) % 97 + 1)
        i = int(symbol[1:]) if symbol[1:].isdigit() else 3
        return make_bars(n, 0.0012 if i % 3 else -0.0003, 100 + i * 7, i + 5)

    def get_historical_prices(self, symbol, days=365):
        self.calls += 1
        return {"symbol": symbol, "historical": self._bars(symbol, days)}

    def get_quote(self, symbols):
        if isinstance(symbols, str):
            symbols = [symbols]
        out = []
        for s in symbols:
            bars = self._bars(s, 300)
            out.append(
                {
                    "symbol": s,
                    "price": 15.0 if s == "^INDIAVIX" else bars[0]["close"],
                    "yearHigh": max(b["high"] for b in bars[:252]),
                    "yearLow": min(b["low"] for b in bars[:252]),
                }
            )
        return out

    def get_batch_quotes(self, symbols):
        return {q["symbol"]: q for q in self.get_quote(list(symbols))}

    def get_batch_historical(self, symbols, days=365):
        return {s: self._bars(s, days) for s in symbols}

    def get_universe(self, name="nifty500"):
        return list(self.STOCKS)

    def get_company_profiles(self, symbols):
        return {
            s: {"companyName": s, "industry": self.INDUSTRIES[i % 4], "sector": self.INDUSTRIES[i % 4]}
            for i, s in enumerate(symbols)
        }

    def get_api_stats(self):
        return {"api_calls_made": self.calls, "source": "fake"}


class SmokeTests(unittest.TestCase):
    def test_composite_uses_summed_volume(self):
        client = FakeClient()
        ref = make_bars(80, 0.0006, 1000.0, 3)
        comp = build_midcap_composite(client, days=60, reference=ref)
        self.assertEqual(len(comp), 60)
        self.assertGreater(comp[0]["volume"], 800_000)
        self.assertAlmostEqual(comp[-1]["close"], 1000.0, places=6)

    def test_breadth_from_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = mtd.parse_arguments(["--cache", os.path.join(tmp, "b.json")])
            res = mtd.compute_breadth_from_prices(FakeClient(), args, date.today())
        self.assertIsNotNone(res)
        self.assertTrue(0 <= res["value"] <= 100 and 0 <= res["value_50"] <= 100)
        self.assertTrue(res["is_fresh"])

    def test_main_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = mtd.main(
                [
                    "--output-dir",
                    tmp,
                    "--cache",
                    os.path.join(tmp, "b.json"),
                    "--put-call",
                    "0.9",
                    "--put-call-date",
                    date.today().isoformat(),
                ],
                client=FakeClient(),
            )
            self.assertEqual(code, 0)
            js = [f for f in os.listdir(tmp) if f.startswith("market_top_") and f.endswith(".json")]
            md = [f for f in os.listdir(tmp) if f.startswith("market_top_") and f.endswith(".md")]
            self.assertTrue(js and md)
            with open(os.path.join(tmp, js[0]), encoding="utf-8") as f:
                data = json.load(f)
            self.assertTrue(0 <= data["composite"]["composite_score"] <= 100)
            self.assertEqual(data["metadata"]["cli_inputs"]["breadth_universe"], "nifty500")
            self.assertEqual(data["components"]["breadth_divergence"]["breadth_source"], "auto")
            self.assertEqual(data["components"]["sentiment"]["details"]["vix_level"]["value"], 15.0)

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
