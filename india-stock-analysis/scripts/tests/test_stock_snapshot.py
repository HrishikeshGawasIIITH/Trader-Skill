import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import stock_snapshot as ss  # noqa: E402

SKILL = Path(HERE).parents[1]


def bars(n=300, drift=0.001):
    out, px = [], 100.0
    for i in range(n):
        px *= 1 + drift + (0.01 if i % 3 == 0 else -0.006)
        out.append({"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": 1000 + i})
    return list(reversed(out))


class FakeClient:
    def get_historical_prices(self, s, days=365):
        return {"symbol": s, "historical": bars()}

    def get_quote(self, s):
        return [{"symbol": s, "price": 150.0, "changesPercentage": 1.2, "yearHigh": 160.0, "yearLow": 90.0}]

    def get_company_profiles(self, syms):
        return {syms[0]: {"companyName": "Test Ltd", "industry": "Power"}}

    def get_earnings_calendar(self, a=None, b=None):
        return [{"symbol": "TEST", "date": "2026-11-20", "purpose": "Financial Results"}]


class FakeSession:
    def get_json(self, url):
        if "announcements" in url:
            return [{"an_dt": "06-Nov-2026 19:10:58", "desc": "Outcome of Board Meeting", "attchmntText": "Results approved", "attchmntFile": "x.pdf"}]
        return [{"exDate": "05-Jun-2026", "recDate": "05-Jun-2026", "subject": "Dividend - Rs 6 Per Share"}]


class Tests(unittest.TestCase):
    def test_technicals(self):
        t = ss.compute_technicals(bars())
        self.assertEqual(t["trend"], "uptrend")
        self.assertTrue(0 <= t["rsi14"] <= 100)
        self.assertIsNone(ss.compute_technicals(bars(10)))

    def test_rsi_extremes(self):
        self.assertEqual(ss.rsi([float(i) for i in range(1, 40)]), 100.0)

    def test_parsers(self):
        self.assertEqual(ss.parse_announcements(None), [])
        self.assertEqual(ss.parse_actions(FakeSession().get_json("actions"))[0]["ex_date"], "2026-06-05")

    def test_pack_and_cli(self):
        p = ss.build_pack("test", FakeClient(), FakeSession())
        self.assertEqual(p["symbol"], "TEST")
        self.assertEqual(len(p["upcoming_events"]), 1)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ss.main(["TEST"], client=FakeClient(), session=FakeSession())
        self.assertIn("Dividend - Rs 6", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            ss.main(["TEST", "--json"], client=FakeClient(), session=FakeSession())
        self.assertEqual(json.loads(buf.getvalue())[0]["profile"]["industry"], "Power")

    def test_skill_contract(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: india-stock-analysis", text)
        self.assertIn("## Secrets", text)
        self.assertIn("This is analysis, not financial advice.", text)
        for ref in ("fundamental-analysis", "financial-metrics", "report-template", "technical-analysis"):
            self.assertTrue((SKILL / "references" / f"{ref}.md").is_file())
            self.assertIn(f"references/{ref}.md", text)

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
