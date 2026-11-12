"""Checks for the 1.1 fixes: F&O universe, still-above and index columns in the scanner,
the missing-bar previous close, promoter holding and pledge, and the option plan. No network."""

import datetime
import os
import sys
import unittest
from types import SimpleNamespace

from _load import load, ROOT

scan = load("trader-scanner", "scan")
sys.path.insert(0, os.path.join(ROOT, "options-strategy-advisor", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "india-stock-analysis", "scripts"))
import option_chain as oc  # noqa: E402
import stock_snapshot as snap  # noqa: E402
from india_client import FMPClient  # noqa: E402

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def ts(day, hh, mm):
    return int(datetime.datetime(day.year, day.month, day.day, hh, mm, tzinfo=IST).timestamp())


class Scanner(unittest.TestCase):
    def test_fno_list_drops_index_rows(self):
        text = ("UNDERLYING,SYMBOL,NOV-26\nNIFTY 50,NIFTY,65\nNIFTY BANK,BANKNIFTY,30\n"
                "Derivatives on Individual Securities,Symbol,NOV-26\nDLF LTD,DLF,950\nMAHINDRA,M&M,200\n")
        self.assertEqual(scan.parse_fno(text), {"DLF", "M&M"})

    def test_prev_close_prefers_real_bars_over_meta(self):
        day = datetime.date(2026, 11, 12)
        series = {"t": [ts(datetime.date(2026, 11, 11), 15, 25), ts(day, 9, 15)], "c": [100.0, 103.0],
                  "meta": {"chartPreviousClose": 90.0}}
        self.assertEqual(scan.prev_close(series, day), 100.0)
        self.assertEqual(scan.prev_close({"t": [ts(day, 9, 15)], "c": [103.0],
                                          "meta": {"chartPreviousClose": 90.0}}, day), 90.0)

    def test_hit_says_if_it_is_still_above_the_range(self):
        day = datetime.date(2026, 11, 12)
        bars = [{"start": scan.slot(day, k), "c": c, "h": c + 0.5, "l": c - 0.5, "v": 100}
                for k, c in enumerate([100, 101, 100.5, 102, 100.8])]
        h = scan.orb_hit(bars, 3)
        self.assertEqual(h["or_high"], 101.5)
        self.assertEqual(h["last"], 100.8)
        self.assertFalse(h["still_above"])


class MissingBar(unittest.TestCase):
    def test_weekdays_between(self):
        self.assertEqual(FMPClient._weekdays_between("2026-11-09", "2026-11-12"), 2)   # 10th and 11th missing
        self.assertEqual(FMPClient._weekdays_between("2026-11-06", "2026-11-09"), 0)   # a weekend only
        self.assertEqual(FMPClient._weekdays_between(None, "2026-11-09"), 0)

    def test_quote_uses_intraday_close_when_a_daily_bar_is_missing(self):
        c = FMPClient(opener=lambda *a, **k: None, sleep=lambda s: None)
        d9, d12 = datetime.date(2026, 11, 9), datetime.date(2026, 11, 12)
        daily = {"meta": {"regularMarketPrice": 110.0, "regularMarketTime": ts(d12, 11, 0)},
                 "timestamp": [ts(d9, 9, 15), ts(d12, 9, 15)],
                 "indicators": {"quote": [{"open": [90, 104], "high": [91, 111], "low": [89, 103],
                                           "close": [90.0, 110.0], "volume": [1, 1]}]}}
        intraday = {"timestamp": [ts(datetime.date(2026, 11, 11), 15, 25), ts(d12, 9, 15)],
                    "indicators": {"quote": [{"close": [100.0, 104.0]}]}}
        c.cache[("chart", "X.NS", "2y", "1d")] = daily
        c.cache[("chart", "X.NS", "5d", "5m")] = intraday
        q = c._quote_one("X")
        self.assertEqual(q["previousClose"], 100.0)
        self.assertAlmostEqual(q["changesPercentage"], 10.0)


class Holding(unittest.TestCase):
    def test_pledge_and_holding(self):
        pl = snap.parse_pledge({"data": [{"shp": "30-Sep-2026", "percPromoterHolding": "    44.44",
                                          "percPromoterShares": "    12.21", "percTotShares": "     5.43"}]})
        self.assertEqual(pl, {"as_of": "30-Sep-2026", "promoter_pct": 44.44, "pledged_pct_of_promoter": 12.21,
                              "pledged_pct_of_total": 5.43})
        self.assertIsNone(snap.parse_pledge({"comNameList": [], "data": []}))
        h = snap.parse_holding([{"date": "30-SEP-2026", "pr_and_prgrp": "42.41", "public_val": "57.59"}])
        self.assertEqual(h, [{"date": "30-SEP-2026", "promoter_pct": 42.41, "public_pct": 57.59}])

    def test_short_history_still_gives_indicators(self):
        bars = [{"date": "d%02d" % i, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i,
                 "volume": 10} for i in range(20)]
        t = snap.compute_technicals(list(reversed(bars)))
        self.assertEqual(t["history_days"], 20)
        self.assertIsNone(t["sma50"])
        self.assertIsNotNone(t["atr14"])


CHAIN = {"records": {"timestamp": "12-Nov-2026 11:36:00", "underlyingValue": 4264.8, "data": [
    {"strikePrice": 4400, "CE": {"buyPrice1": 106.2, "sellPrice1": 108.25, "lastPrice": 107, "impliedVolatility": 55.0,
                                 "openInterest": 766, "totalTradedVolume": 4349}},
    {"strikePrice": 4300, "CE": {"buyPrice1": 150, "sellPrice1": 152, "lastPrice": 151, "impliedVolatility": 55.0,
                                 "openInterest": 500, "totalTradedVolume": 900}}]}}


class OptionPlan(unittest.TestCase):
    def setUp(self):
        spot, _, rows = oc.parse_chain(CHAIN, "call")
        self.spot = spot
        now = datetime.datetime(2026, 11, 12, 11, 40, tzinfo=IST)
        self.T = oc.years_to_expiry("23-Nov-2026", now)
        self.rows = oc.enrich(rows, spot, self.T, 125, "call")

    def args(self, **kw):
        base = dict(stop=4190.0, target1=4330.0, target2=4400.0, lots=1, max_loss=2000.0, max_cost=15000.0,
                    min_stop_atr=0.5, max_spread=3.0, hold_days=0.25)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_chain_rows(self):
        r = [x for x in self.rows if x["strike"] == 4400][0]
        self.assertEqual(r["cost_lot"], 13531)
        self.assertAlmostEqual(r["spread_pct"], 1.9, places=1)
        self.assertTrue(0.3 < r["delta"] < 0.5)

    def test_tight_stop_is_rejected(self):
        r = [x for x in self.rows if x["strike"] == 4400][0]
        p = oc.build_plan(r, self.spot, self.T, 125, "call", self.args(), atr=220.0, symbol="DATAPATTNS",
                          expiry="23-Nov-2026")
        self.assertFalse(p["ok"])
        self.assertTrue(any("ATR" in b for b in p["blocks"]))

    def test_wide_stop_that_fits_the_loss_passes_and_builds_an_order(self):
        r = [x for x in self.rows if x["strike"] == 4400][0]
        p = oc.build_plan(r, self.spot, self.T, 125, "call", self.args(stop=4140.0, max_loss=6000.0), atr=220.0,
                          symbol="DATAPATTNS", expiry="23-Nov-2026")
        self.assertTrue(p["ok"], p["blocks"])
        o = oc.order_from(p, "intraday")
        self.assertEqual(o["symbol"], "DATAPATTNS23NOV264400CE")
        self.assertEqual((o["exchange"], o["qty"], o["type"]), ("NFO", "125", "limit"))
        self.assertLess(float(o["stop_loss_stop_price"]), float(o["limit_price"]))
        self.assertGreater(float(o["take_profit_limit_price"]), float(o["limit_price"]))

    def test_loss_over_the_limit_is_rejected(self):
        r = [x for x in self.rows if x["strike"] == 4400][0]
        p = oc.build_plan(r, self.spot, self.T, 125, "call", self.args(stop=4100.0), atr=220.0,
                          symbol="DATAPATTNS", expiry="23-Nov-2026")
        self.assertFalse(p["ok"])
        self.assertTrue(any("over the Rs 2,000 limit" in b for b in p["blocks"]))


if __name__ == "__main__":
    unittest.main()
