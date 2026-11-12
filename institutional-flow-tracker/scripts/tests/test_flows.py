"""Tests for nse_flows and the tracker CLI (fake session and client, no network)."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import nse_flows as nf  # noqa: E402
import track_institutional_flow as tif  # noqa: E402

FII_PAYLOAD = [
    {"buyValue": "19704.39", "category": "DII", "date": "11-Nov-2026", "netValue": "-8434.53", "sellValue": "28138.92"},
    {"buyValue": "30087.21", "category": "FII/FPI", "date": "11-Nov-2026", "netValue": "12563.33", "sellValue": "17523.88"},
]
BULK_CSV = (
    "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
    "11-NOV-2026,AAA,AAA Ltd,ACME CAPITAL MARKET LIMITED,BUY,100000,500.00,-\n"
    "11-NOV-2026,AAA,AAA Ltd,SBI MUTUAL FUND,BUY,200000,500.00,-\n"
    "11-NOV-2026,BBB,BBB Ltd,SOME TRADER,SELL,300000,200.00,-\n"
    "11-NOV-2026,CCC,CCC Ltd,BAD ROW,HOLD,1,1,-\n"
)
BLOCK_CSV = (
    "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price\n"
    "11-NOV-2026,AAA,AAA Ltd,LIFE INSURANCE CORPORATION OF INDIA,SELL,50000,510.00\n"
)


class FakeSession:
    def __init__(self, payload=FII_PAYLOAD, bulk=BULK_CSV, block=BLOCK_CSV):
        self.payload, self.bulk, self.block = payload, bulk, block

    def get_json(self, url):
        return self.payload

    def get_text(self, url):
        return self.bulk if "bulk" in url else self.block


class FakeClient:
    def get_historical_prices(self, symbol, days=365):
        d, rows, px = date(2026, 11, 10), [], 100.0
        for i in range(80):
            rows.append({"date": (d - timedelta(days=i)).isoformat(), "close": px - i * 0.2, "open": px, "high": px, "low": px, "volume": 1})
        return {"symbol": symbol, "historical": rows}


class ParseTests(unittest.TestCase):
    def test_parse_fii_dii(self):
        day = nf.parse_fii_dii(FII_PAYLOAD)
        self.assertEqual(day["date"], "2026-11-11")
        self.assertAlmostEqual(day["fii"]["net"], 12563.33)
        self.assertAlmostEqual(day["dii"]["sell"], 28138.92)

    def test_parse_fii_dii_rejects_bad_payload(self):
        self.assertIsNone(nf.parse_fii_dii(None))
        self.assertIsNone(nf.parse_fii_dii([{"category": "FII/FPI"}]))
        self.assertIsNone(nf.parse_fii_dii(FII_PAYLOAD[:1]))

    def test_parse_deals_skips_bad_rows_and_classifies(self):
        deals = nf.parse_deals(BULK_CSV, "bulk")
        self.assertEqual(len(deals), 3)
        self.assertEqual(deals[1]["client_type"], "mutual_fund")
        self.assertAlmostEqual(deals[0]["value"], 5e7)
        self.assertEqual(deals[0]["date"], "2026-11-11")
        self.assertEqual(nf.parse_deals("", "bulk"), [])

    def test_classify_client(self):
        self.assertEqual(nf.classify_client("HDFC MUTUAL FUND"), "mutual_fund")
        self.assertEqual(nf.classify_client("LIFE INSURANCE CORPORATION OF INDIA"), "insurance")
        self.assertEqual(nf.classify_client("GOLDMAN SACHS SINGAPORE PTE"), "foreign")
        self.assertEqual(nf.classify_client("RAMESH KUMAR"), "other")


class SummaryTests(unittest.TestCase):
    def _history(self, n, fii, dii):
        return [
            {"date": (date(2026, 10, 1) + timedelta(days=i)).isoformat(), "fii": {"buy": 0, "sell": 0, "net": fii}, "dii": {"buy": 0, "sell": 0, "net": dii}}
            for i in range(n)
        ]

    def test_windows_and_regime(self):
        s = nf.summarize_flows(self._history(25, -1000.0, 1500.0))
        self.assertEqual(s["windows"]["5"]["fii_net"], -5000.0)
        self.assertEqual(s["windows"]["20"]["sessions"], 20)
        self.assertEqual(s["regime"], "DII absorbing FII selling")

    def test_regime_labels(self):
        self.assertIn("broad buying", nf.classify_regime(5000, 5000))
        self.assertIn("broad selling", nf.classify_regime(-5000, -5000))
        self.assertIn("FII buying", nf.classify_regime(5000, -5000))
        self.assertEqual(nf.classify_regime(100, -100), "no material net flow")

    def test_append_day_replaces_same_date(self):
        h = self._history(3, 1.0, 1.0)
        day = dict(h[-1], fii={"buy": 0, "sell": 0, "net": 99.0})
        out = nf.append_day(h, day)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[-1]["fii"]["net"], 99.0)

    def test_summarize_deals_net_and_filters(self):
        deals = nf.parse_deals(BULK_CSV, "bulk") + nf.parse_deals(BLOCK_CSV, "block")
        s = nf.summarize_deals(deals, min_value_cr=0.0)
        top = s["accumulation"][0]
        self.assertEqual(top["symbol"], "AAA")
        self.assertAlmostEqual(top["net_cr"], 15.0 - 2.55, places=2)
        self.assertEqual(s["distribution"][0]["symbol"], "BBB")
        self.assertEqual(nf.summarize_deals(deals, min_value_cr=1000.0)["symbols"], 0)


class CliTests(unittest.TestCase):
    def test_flows_saves_history_and_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fii_dii.json")
            args = tif.parse_arguments(["--history", path, "flows"])
            out = tif.run(args, session=FakeSession())
            self.assertIn("FII / DII Flows", out)
            self.assertIn("2026-11-11", out)
            self.assertEqual(len(nf.load_history(path)), 1)
            out2 = tif.run(args, session=FakeSession())  # same date does not duplicate
            self.assertEqual(len(nf.load_history(path)), 1)
            self.assertIn("only 1 sessions", out2)

    def test_flows_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = tif.parse_arguments(["--history", os.path.join(tmp, "h.json"), "flows"])
            out = tif.run(args, session=FakeSession(payload=None))
            self.assertIn("No flow data", out)

    def test_deals_and_json(self):
        args = tif.parse_arguments(["--json", "deals", "--min-value-cr", "0"])
        data = json.loads(tif.run(args, session=FakeSession()))
        self.assertEqual(data["deals_read"], 4)
        self.assertEqual(data["accumulation"][0]["symbol"], "AAA")

    def test_stock_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = tif.parse_arguments(["--history", os.path.join(tmp, "h.json"), "stock", "AAA"])
            out = tif.run(args, session=FakeSession(), client=FakeClient())
            self.assertIn("Institutional activity: AAA", out)
            self.assertIn("mutual_fund", out)
            self.assertIn("50-day average", out)

    def test_main_saves_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = tif.parse_arguments(["--output-dir", tmp, "deals"])
            self.assertEqual(args.command, "deals")


if __name__ == "__main__":
    unittest.main()
