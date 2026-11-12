"""Unit tests for india_client with a fake opener (no network)."""
import json
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import india_client  # noqa: E402
from india_client import ApiCallBudgetExceeded, FMPClient, to_yahoo_symbol  # noqa: E402


def http_err(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


class Resp:
    def __init__(self, body):
        self._b = body if isinstance(body, bytes) else body.encode()

    def read(self):
        return self._b


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes  # list of (substring, body | Exception | list of those)
        self.urls = []
        self.headers = []

    def open(self, req, timeout=30):
        self.urls.append(req.full_url)
        self.headers.append(dict(req.header_items()))
        for sub, body in self.routes:
            if sub in req.full_url:
                if isinstance(body, list):
                    item = body.pop(0) if len(body) > 1 else body[0]
                else:
                    item = body
                if isinstance(item, Exception):
                    raise item
                return Resp(item)
        raise http_err(404)


def chart(n=4, price=110.0, vol=1000):
    base = 1_762_800_000
    ts = [base + i * 86400 for i in range(n)]
    closes = [100.0 + i for i in range(n)]
    return json.dumps({"chart": {"result": [{
        "meta": {"regularMarketPrice": price, "regularMarketTime": ts[-1],
                 "gmtoffset": 19800, "longName": "Test Co"},
        "timestamp": ts,
        "indicators": {
            "quote": [{"open": [c - 1 for c in closes], "high": [c + 2 for c in closes],
                       "low": [c - 2 for c in closes], "close": closes,
                       "volume": [vol] * n}],
            "adjclose": [{"adjclose": closes}]}}]}})


def make(routes, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("rate_delay", 0)
    kw.setdefault("quiet", True)
    op = FakeOpener(routes)
    return FMPClient(opener=op, **kw), op


class SymbolTests(unittest.TestCase):
    def test_suffix(self):
        self.assertEqual(to_yahoo_symbol("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(to_yahoo_symbol("^NSEI"), "^NSEI")
        self.assertEqual(to_yahoo_symbol("M&M"), "M&M.NS")

    def test_url_encoding(self):
        c, op = make([("finance/chart", chart())])
        c.get_historical_prices("M&M")
        self.assertIn("M%26M.NS", op.urls[0])
        self.assertIn("interval=1d", op.urls[0])
        self.assertIn("range=2y", op.urls[0])


class PriceTests(unittest.TestCase):
    def test_newest_first_shape(self):
        c, _ = make([("finance/chart", chart(4))])
        d = c.get_historical_prices("AAA", days=365)
        self.assertEqual(d["symbol"], "AAA")
        h = d["historical"]
        self.assertEqual(len(h), 4)
        self.assertGreater(h[0]["date"], h[-1]["date"])
        self.assertEqual(h[0]["close"], 103.0)
        for k in ("date", "open", "high", "low", "close", "adjClose", "volume"):
            self.assertIn(k, h[0])

    def test_days_limit_and_null_rows(self):
        body = json.loads(chart(5))
        body["chart"]["result"][0]["indicators"]["quote"][0]["close"][2] = None
        c, _ = make([("finance/chart", json.dumps(body))])
        h = c.get_historical_prices("AAA", days=3)["historical"]
        self.assertEqual(len(h), 3)

    def test_failure_returns_none(self):
        c, _ = make([("finance/chart", http_err(404))])
        self.assertIsNone(c.get_historical_prices("ZZZ"))

    def test_fallback_host(self):
        c, op = make([("query1", http_err(500)), ("query2", chart())])
        self.assertIsNotNone(c.get_historical_prices("AAA"))
        self.assertEqual(len(op.urls), 2)

    def test_retry_on_429(self):
        sleeps = []
        c, op = make([("query1", [http_err(429), chart()])], sleep=sleeps.append)
        self.assertIsNotNone(c.get_historical_prices("AAA"))
        self.assertIn(2, sleeps)

    def test_cache(self):
        c, op = make([("finance/chart", chart())])
        c.get_historical_prices("AAA")
        c.get_historical_prices("AAA")
        c.get_quote("AAA")
        self.assertEqual(len(op.urls), 1)

    def test_batch_historical(self):
        c, _ = make([("finance/chart", chart())])
        out = c.get_batch_historical(["A", "B"])
        self.assertEqual(set(out), {"A", "B"})
        self.assertIsInstance(out["A"], list)

    def test_budget(self):
        c, _ = make([("finance/chart", chart())], max_api_calls=1)
        c.get_historical_prices("A")
        with self.assertRaises(ApiCallBudgetExceeded):
            c.get_historical_prices("B")


class QuoteTests(unittest.TestCase):
    def test_quote_fields(self):
        c, _ = make([("finance/chart", chart(4, price=110.0))])
        q = c.get_quote("AAA")[0]
        self.assertEqual(q["symbol"], "AAA")
        self.assertEqual(q["exchange"], "NSE")
        self.assertEqual(q["price"], 110.0)
        self.assertEqual(q["previousClose"], 102.0)
        self.assertAlmostEqual(q["changesPercentage"], 8.0 / 102.0 * 100)
        self.assertIsNone(q["marketCap"])
        self.assertEqual(q["avgVolume"], 1000)
        self.assertEqual(q["yearHigh"], 105.0)

    def test_batch_quotes(self):
        c, _ = make([("finance/chart", chart())])
        self.assertEqual(set(c.get_batch_quotes(["A", "B"])), {"A", "B"})

    def test_quote_none(self):
        c, _ = make([("finance/chart", http_err(404))])
        self.assertIsNone(c.get_quote("ZZZ"))


CSV = ("Company Name,Industry,Symbol,Series,ISIN Code\r\n"
       "Reliance Industries Ltd.,Oil Gas & Consumable Fuels,RELIANCE,EQ,INE002A01018\r\n"
       "Mahindra & Mahindra Ltd.,Automobile and Auto Components,M&M,EQ,INE101A01026\r\n")


class UniverseTests(unittest.TestCase):
    def test_universe_and_profiles(self):
        c, op = make([("ind_nifty500list", CSV)])
        self.assertEqual(c.get_universe("nifty500"), ["RELIANCE", "M&M"])
        p = c.get_company_profiles(["M&M"])
        self.assertEqual(p["M&M"]["sector"], "Automobile and Auto Components")
        self.assertEqual(p["M&M"]["companyName"], "Mahindra & Mahindra Ltd.")

    def test_unknown_universe(self):
        c, _ = make([])
        with self.assertRaises(ValueError):
            c.get_universe("sp500")


class EarningsTests(unittest.TestCase):
    EVENTS = json.dumps([
        {"symbol": "TCS", "company": "Tata Consultancy", "purpose": "Financial Results",
         "bm_desc": "x", "date": "12-Nov-2026"},
        {"symbol": "ITC", "company": "ITC", "purpose": "Dividend", "bm_desc": "Dividend",
         "date": "12-Nov-2026"},
        {"symbol": "INFY", "company": "Infosys", "purpose": "Financial Results",
         "bm_desc": "", "date": "30-Dec-2026"},
    ])

    def test_calendar_filter_and_cookie_flow(self):
        c, op = make([("api/event-calendar", self.EVENTS), ("nseindia.com/", "<html>")])
        ev = c.get_earnings_calendar("2026-11-10", "2026-11-20")
        self.assertEqual([e["symbol"] for e in ev], ["TCS"])
        self.assertEqual(ev[0]["date"], "2026-11-12")
        self.assertEqual(op.urls[0], india_client.NSE_HOME)
        self.assertEqual(op.headers[1].get("Referer"), india_client.NSE_HOME)

    def test_calendar_uses_board_meetings_for_past_dates(self):
        board = json.dumps([
            {"bm_symbol": "ACE", "bm_date": "05-Nov-2026", "bm_purpose": "Financial Results",
             "bm_desc": "", "sm_name": "Action Construction"},
            {"bm_symbol": "XYZ", "bm_date": "05-Nov-2026", "bm_purpose": "Board Meeting Intimation",
             "bm_desc": "consider the Unaudited Financial results", "sm_name": "Xyz"},
            {"bm_symbol": "ABC", "bm_date": "05-Nov-2026", "bm_purpose": "Dividend",
             "bm_desc": "dividend", "sm_name": "Abc"},
        ])
        c, op = make([("corporate-board-meetings", board), ("api/event-calendar", self.EVENTS),
                      ("nseindia.com/", "<html>")])
        ev = c.get_earnings_calendar("2026-11-01", "2026-11-20")
        self.assertEqual([(e["symbol"], e["date"]) for e in ev],
                         [("ACE", "2026-11-05"), ("XYZ", "2026-11-05"), ("TCS", "2026-11-12")])
        self.assertTrue(any("from_date=01-11-2026" in u for u in op.urls))

    def test_holidays(self):
        body = json.dumps({"CM": [{"tradingDate": "26-Jan-2026"}, {"tradingDate": "bad"}]})
        c, _ = make([("holiday-master", body), ("nseindia.com/", "<html>")])
        self.assertEqual(c.get_trading_holidays(), ["2026-01-26"])

    def test_stats(self):
        c, _ = make([("finance/chart", chart())])
        c.get_historical_prices("A")
        s = c.get_api_stats()
        self.assertEqual(s["api_calls_made"], 1)
        self.assertEqual(s["source"], "yahoo+nse")


if __name__ == "__main__":
    unittest.main()
