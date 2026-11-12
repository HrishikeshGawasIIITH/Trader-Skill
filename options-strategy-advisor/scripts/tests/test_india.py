"""India additions: lot sizes, CLI, client helpers (no network)."""

import pytest as _pt0  # noqa: F401  (loads conftest path setup)

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import black_scholes as bs  # noqa: E402

LOT_CSV = (
    "UNDERLYING                          ,SYMBOL    ,NOV-26     ,DEC-26     ,JAN-27     \n"
    "NIFTY 50                            ,NIFTY     ,65         ,65         ,65         \n"
    "NIFTY BANK                          ,BANKNIFTY ,30         ,30         ,           \n"
    "Derivatives on Individual Securities,Symbol    ,NOV-26     ,DEC-26     ,JAN-27     \n"
    "RELIANCE INDUSTRIES LTD             ,RELIANCE  ,500        ,500        ,500        \n"
    "BROKEN ROW                          ,BADCO     ,           ,           ,           \n"
)


class FakeClient:
    def get_quote(self, symbols):
        return [{"symbol": symbols, "price": 24500.0}]

    def get_historical_prices(self, symbol, days=365):
        rows, px = [], 24500.0
        for i in range(90):
            rows.append(
                {"date": (date(2026, 11, 10) - timedelta(days=i)).isoformat(), "close": px * (1 + 0.004 * (-1) ** i)}
            )
        return {"symbol": symbol, "historical": rows}


class OpenerStub:
    def __init__(self, body):
        self.body = body

    def open(self, req, timeout=30):
        return io.BytesIO(self.body.encode("utf-8"))


class IndiaTests(unittest.TestCase):
    def test_default_rate_is_six_point_five_percent(self):
        self.assertEqual(bs.DEFAULT_RISK_FREE_RATE, 0.065)
        p = bs.OptionPricer(S=100, K=100, T=0.5, sigma=0.2)
        self.assertEqual(p.r, 0.065)

    def test_known_value_against_reference(self):
        # S=K=100, T=1, r=5%, sigma=20%: textbook call = 10.4506, put = 5.5735
        p = bs.OptionPricer(S=100, K=100, T=1.0, r=0.05, sigma=0.2)
        self.assertAlmostEqual(p.call_price(), 10.4506, places=3)
        self.assertAlmostEqual(p.put_price(), 5.5735, places=3)

    def test_parse_lot_sizes(self):
        lots = bs.parse_lot_sizes(LOT_CSV)
        self.assertEqual(lots["NIFTY"]["lot"], 65)
        self.assertEqual(lots["BANKNIFTY"]["months"], {"NOV-26": 30, "DEC-26": 30})
        self.assertEqual(lots["RELIANCE"]["lot"], 500)
        self.assertNotIn("BADCO", lots)
        self.assertNotIn("SYMBOL", lots)
        self.assertEqual(bs.lot_size("nifty", lots), 65)
        self.assertIsNone(bs.lot_size("UNKNOWN", lots))

    def test_fetch_lot_sizes_with_stub_and_failure(self):
        self.assertEqual(bs.fetch_lot_sizes(opener=OpenerStub(LOT_CSV))["NIFTY"]["lot"], 65)

        class Boom:
            def open(self, req, timeout=30):
                raise OSError("down")

        self.assertEqual(bs.fetch_lot_sizes(opener=Boom()), {})

    def test_spot_and_history_helpers(self):
        c = FakeClient()
        self.assertEqual(bs.get_current_stock_price("NIFTY", c), 24500.0)
        closes = bs.fetch_historical_prices_for_hv("NIFTY", c, days=90)
        self.assertEqual(len(closes), 90)
        hv = bs.calculate_historical_volatility(closes, 30)
        self.assertTrue(0.01 < hv < 1.0)
        self.assertEqual(bs.get_dividend_yield("NIFTY"), 0.0)
        self.assertEqual(bs.yahoo_spot_symbol("BANKNIFTY"), "^NSEBANK")
        self.assertEqual(bs.yahoo_spot_symbol("NIFTY"), "^NSEI")

    def test_cli_report(self):
        lots = bs.parse_lot_sizes(LOT_CSV)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = bs.main(
                ["--symbol", "NIFTY", "--spot", "24500", "--strike", "24600", "--days", "14", "--iv", "14"],
                lots=lots,
            )
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("European (index option)", out)
        self.assertIn("Lot size: 65", out)
        self.assertIn("one lot (65)", out)

    def test_cli_live_uses_client(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            bs.main(["--symbol", "NIFTY", "--strike", "24500", "--days", "7", "--live"], client=FakeClient(), lots={})
        self.assertIn("Spot Rs 24,500.00", buf.getvalue())

import pytest as _pt  # noqa: E402

if hasattr(_pt, "make_load_tests"):
    load_tests = _pt.make_load_tests(__name__)


if __name__ == "__main__":
    unittest.main()
