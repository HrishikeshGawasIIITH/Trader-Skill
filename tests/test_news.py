import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

news = load("trader-news", "news")
us_news = load("trader-news", "news", us=True)
DIR = os.path.join(FIX, "trader-news")
NOW = "2026-11-11T21:00:00+05:30"
UTC = datetime.timezone.utc
FEED = {f[0]: f for f in news.NSE_FEEDS}


def raw(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = news.main(args)
    return code, out.getvalue(), err.getvalue()


class Filings(unittest.TestCase):
    def test_announcements_feed(self):
        items = news.parse_nse_rss(raw("nse-announcements.xml"), FEED["ann"])
        self.assertEqual(len(items), 6)
        first = items[0]
        self.assertEqual(first["company"], "Adani Enterprises Limited")
        self.assertEqual(first["source"], "NSE announcements")
        self.assertEqual(first["kind"], "filing")
        self.assertIn("deal", first["items"])
        self.assertTrue(first["important"])
        # 20:15:25 India time is 14:45:25 UTC
        self.assertEqual(first["time"], datetime.datetime(2026, 11, 11, 14, 45, 25, tzinfo=UTC))
        by = {i["company"]: i for i in items}
        self.assertEqual(by["Hindustan Aeronautics Limited"]["items"], ["rating"])
        self.assertEqual(by["Time Technoplast Limited"]["items"], ["orders"])
        self.assertIn("resign", by["Shalimar Paints Limited"]["items"])
        self.assertEqual(by["Mahindra & Mahindra Limited"]["items"], [])
        self.assertFalse(by["Mahindra & Mahindra Limited"]["important"])

    def test_results_board_actions_insider_feeds(self):
        res = news.parse_nse_rss(raw("nse-results.xml"), FEED["results"])
        self.assertEqual(res[0]["items"], ["results"])
        self.assertTrue(res[0]["important"])
        self.assertIn("financial results for First Quarter", res[0]["title"])
        self.assertIn("unaudited, non-consolidated", res[0]["title"])
        board = news.parse_nse_rss(raw("nse-board.xml"), FEED["board"])
        self.assertEqual(board[0]["items"], ["board"])
        self.assertEqual(board[0]["company"], "Himatsingka Seide Limited")
        acts = news.parse_nse_rss(raw("nse-actions.xml"), FEED["actions"])
        self.assertEqual(acts[0]["company"], "Godfrey Phillips India Limited")  # the "- Ex-Date" part is cut
        self.assertEqual(acts[0]["items"], ["dividend"])
        self.assertIn("record date 12-Nov-2026", acts[0]["title"])
        ins = news.parse_nse_rss(raw("nse-insider.xml"), FEED["insider"])
        self.assertEqual(ins[0]["items"], ["insider"])
        self.assertEqual(len({i["id"] for i in res + board + acts + ins}), 11)  # the feed repeats one insider row

    def test_per_symbol_api(self):
        items = news.parse_nse_api(raw("api-RELIANCE.json"), "RELIANCE")
        self.assertEqual(len(items), 5)
        times = [i["time"] for i in items]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertTrue(all(i["source"] == "NSE API" and i["ticker"] == "RELIANCE" for i in items))
        by = {i["form"]: i for i in items}
        self.assertEqual(by["Credit Rating"]["items"], ["rating"])
        self.assertIn("board", by["Outcome of Board Meeting"]["items"])
        self.assertIn("deal", by["Acquisition"]["items"])
        with self.assertRaises(news.NewsError):
            news.parse_nse_api(b'{"nope": 1}', "RELIANCE")

    def test_subject_categories(self):
        self.assertEqual(news.classify("Disclosure under SEBI Takeover Regulations"), ["insider"])
        self.assertEqual(news.classify("Reg.7(1A) -SEBI (Substantial Acq of shares & Takeovers),1997"), ["insider"])
        self.assertIn("dividend", news.classify("Bonus issue and stock split"))
        self.assertIn("funding", news.classify("Issue of Non-Convertible Debentures"))
        self.assertIn("insolvency", news.classify("Initiation of CIRP under NCLT"))
        self.assertEqual(news.classify("Press Release"), [])

    def test_company_list_and_names(self):
        fetcher = news.Fetcher(offline=DIR)
        names = news.equity_names(fetcher)
        self.assertEqual(names["M&M"], "Mahindra & Mahindra Limited")
        self.assertEqual(news.norm_name("Mahindra &amp; Mahindra Limited"), news.norm_name(names["M&M"]))
        self.assertNotEqual(news.norm_name("Mahindra & Mahindra Financial Services Limited"),
                            news.norm_name(names["M&M"]))
        self.assertEqual(news.short_name("Reliance Industries Limited"), "Reliance Industries")

    def test_company_list_is_cached(self):
        class Counting(news.Fetcher):
            hits = 0

            def get(self, url, name, nse=False):
                Counting.hits += 1
                return raw("EQUITY_L.csv")

        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "cache")
            news.equity_names(Counting(), cache)
            news.equity_names(Counting(), cache)
            self.assertEqual(Counting.hits, 1)
            self.assertTrue(os.path.isfile(os.path.join(cache, "EQUITY_L.csv")))


class Headlines(unittest.TestCase):
    def test_google_news(self):
        items = news.parse_rss(raw("google-RELIANCE.xml"), "RELIANCE", "Google News")
        self.assertEqual(len(items), 4)
        first = items[0]
        self.assertEqual(first["source"], "Moneycontrol.com via Google News")
        self.assertTrue(first["title"].startswith("Reliance Industries shares jump"))
        self.assertFalse(first["title"].endswith("Moneycontrol.com"))
        self.assertTrue(first["id"].startswith("rss:"))
        self.assertIsNotNone(first["time"])

    def test_times(self):
        self.assertEqual(news.parse_time("Tue, 13 Oct 2026 20:02:03 +0000").hour, 20)
        self.assertEqual(news.parse_time("2026-09-01T16:30:35-04:00").hour, 20)
        self.assertEqual(news.parse_time("11 Nov 2026 20:00:02 +0530").isoformat(), "2026-11-11T14:30:02+00:00")
        self.assertEqual(news.parse_time("11-NOV-2026 20:18").isoformat(), "2026-11-11T14:48:00+00:00")
        self.assertEqual(news.parse_time("03-Nov-2026 10:29:23").hour, 4)
        self.assertIsNone(news.parse_time("soon"))

    def test_market_wide_feeds_are_filtered_by_symbol_and_name(self):
        watch = {"M&M": "Mahindra & Mahindra Limited", "INFY": "Infosys Limited", "TCS": None}
        items = news.parse_rss(raw("et-markets.xml"), "", "ET Markets")
        kept = news._market_wide(items, watch)
        self.assertEqual(sorted(i["ticker"] for i in kept), ["INFY", "M&M"])
        self.assertTrue(all(i["source"] == "ET Markets" for i in kept))

    def test_touches_and_tags(self):
        items = news.parse_rss(raw("et-stocks.xml"), "", "ET Stocks")
        watch = {"M&M": "Mahindra & Mahindra Limited", "INFY": "Infosys Limited", "ITC": "ITC Limited"}
        news.tag(items, watch)
        by = {i["title"][:6]: i for i in items}
        self.assertEqual(by["M&M Sh"]["touches"], ["M&M"])
        self.assertEqual(by["Infosy"]["touches"], ["INFY"])

    def test_earnings_filings_are_tagged(self):
        items = news.tag(news.parse_nse_rss(raw("nse-results.xml"), FEED["results"]), {"X": None})
        self.assertEqual(items[0]["tags"][0], "earnings")

    def test_dedupe_merges_the_same_story(self):
        a = news.parse_rss(raw("google-RELIANCE.xml"), "RELIANCE")
        b = news.parse_rss(raw("google-RELIANCE.xml"), "TCS")
        items = news.dedupe(news.tag(a + b, {"RELIANCE": None, "TCS": None}))
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["touches"], ["RELIANCE", "TCS"])

    def test_dedupe_keeps_filings_that_share_a_page_link(self):
        items = news.tag(news.parse_nse_rss(raw("nse-results.xml"), FEED["results"]), {"X": None})
        self.assertEqual(len({i["link"] for i in items}), 1)
        self.assertEqual(len(news.dedupe(items)), 3)

    def test_trading_tags(self):
        items = [{"id": "x", "source": "Mint", "kind": "headline", "ticker": "TCS",
                  "title": "Circuit hit in XYZ after USFDA approval; RBI repo cut lifts futures",
                  "summary": "", "link": "", "time": None}]
        tags = news.tag(items, {"TCS": None})[0]["tags"]
        for t in ("halt", "regulatory", "macro"):
            self.assertIn(t, tags)


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state", "news.json")
        self.base = ["--offline", DIR, "--state", self.state, "--now", NOW,
                     "--portfolio", os.path.join(self.tmp.name, "none.json"),
                     "--watchlist", os.path.join(self.tmp.name, "none.json"),
                     "--plan", os.path.join(self.tmp.name, "none.json")]

    def tearDown(self):
        self.tmp.cleanup()

    def test_filings_first_then_headlines_newest_first(self):
        code, out, err = run(["--tickers", "RELIANCE", "ADANIENT", "M&M", "--hours", "400", "--json"] + self.base)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        kinds = [i["kind"] for i in data["items"]]
        self.assertEqual(kinds, sorted(kinds, key=lambda k: k != "filing"))
        self.assertIn("filing", kinds)
        self.assertIn("headline", kinds)
        for kind in ("filing", "headline"):
            times = [i["time"] for i in data["items"] if i["kind"] == kind]
            self.assertEqual(times, sorted(times, reverse=True))
        self.assertTrue(all(i["source"] for i in data["items"]))  # every item names its source
        # one item per story, and the second run shows nothing new
        code, out, _ = run(["--tickers", "RELIANCE", "ADANIENT", "M&M", "--hours", "400"] + self.base)
        self.assertEqual(code, 1)
        self.assertIn("Nothing new.", out)

    def test_counts_per_source(self):
        code, out, err = run(["--tickers", "RELIANCE", "ADANIENT", "--hours", "400", "--json", "--dry-run"] + self.base)
        src = json.loads(out)["sources"]
        self.assertEqual(src["NSE announcements"], 1)      # Adani Enterprises
        self.assertEqual(src["NSE API"], 5)                # RELIANCE has no RSS item, so the API fills in
        self.assertEqual(src["Google News"], 4)
        self.assertEqual(src["NSE insider trading"], 0)
        self.assertFalse(os.path.exists(self.state))

    def test_filings_show_with_ist_time_and_important_mark(self):
        code, out, err = run(["--tickers", "ADANIENT", "RELIANCE", "--hours", "400", "--no-moves"] + self.base)
        self.assertEqual(code, 0, err)
        self.assertIn("! 2026-11-11 20:15 IST  ADANIENT", out)
        self.assertIn("NSE announcements", out)
        self.assertIn("Credit Rating", out)
        self.assertIn("Checked 2026-11-11 21:00 IST", out)
        self.assertIn("Not financial advice", out)
        self.assertNotIn(chr(0x2014), out)

    def test_a_failed_source_is_named_and_the_run_continues(self):
        class Broken(news.Fetcher):
            def get(self, url, name, nse=False):
                if name in ("et-markets.xml", "nse-board.xml", "fiidii.json"):
                    raise news.NewsError("HTTP 503 for " + url)
                return news.Fetcher.get(self, url, name, nse)

        errors, counts = [], {}
        fetcher = Broken(offline=DIR)
        names = news.equity_names(fetcher)
        items = news.collect(fetcher, {"ADANIENT": None}, {}, errors=errors, names=names, counts=counts)
        self.assertTrue(items)
        self.assertTrue(any(e.startswith("no data from ET Markets: HTTP 503") for e in errors))
        self.assertTrue(any(e.startswith("no data from NSE board meetings") for e in errors))
        self.assertEqual(counts["ET Markets"], 0)
        self.assertEqual(counts["NSE announcements"], 1)
        errors = []
        context = news.collect_context(fetcher, errors)
        self.assertEqual({c["source"] for c in context}, {"RBI", "SEBI"})
        self.assertEqual(errors[0].split(":")[0], "no data from NSE FII/DII")

    def test_market_context_section(self):
        code, out, err = run(["--tickers", "RELIANCE", "--hours", "400", "--no-moves"] + self.base)
        self.assertIn("Market context", out)
        self.assertIn("RBI", out)
        self.assertIn("SEBI", out)
        self.assertIn("FII/FPI net buying Rs 12,563.33 crore", out)
        code, out, _ = run(["--tickers", "RELIANCE", "--hours", "400", "--no-moves", "--no-context",
                            "--dry-run"] + self.base)
        self.assertNotIn("Market context", out)

    def test_tickers_from_watchlist_and_plan(self):
        wl = os.path.join(self.tmp.name, "watchlist.json")
        with open(wl, "w") as fh:
            json.dump({"created_by": "trader-scanner", "hits": [{"symbol": "ADANIENT", "setups": ["orb"]}]}, fh)
        plan = os.path.join(self.tmp.name, "plan.json")
        with open(plan, "w") as fh:
            json.dump({"created_by": "trader-exit", "symbol": "RELIANCE.NS"}, fh)
        self.assertEqual(sorted(news.watch_from_files("/nonexistent.json", wl, plan)), ["ADANIENT", "RELIANCE"])
        args = list(self.base)
        args[args.index("--watchlist") + 1] = wl
        args[args.index("--plan") + 1] = plan
        code, out, err = run(["--json", "--dry-run", "--hours", "400"] + args)
        self.assertEqual(code, 0, err)
        tickers = {t for i in json.loads(out)["items"] for t in i["touches"]}
        self.assertEqual(tickers, {"ADANIENT", "RELIANCE"})
        self.assertFalse(os.path.exists(self.state))

    def test_no_tickers_is_an_error(self):
        code, _, err = run(self.base)
        self.assertEqual(code, 2)
        self.assertIn("no tickers", err)

    def test_moves(self):
        m = news.parse_chart(raw("chart-RELIANCE.json"), "RELIANCE")
        self.assertEqual(m["prev_close"], 1324.4)
        self.assertEqual(m["price"], 1335.4)
        self.assertEqual(m["pct"], 0.83)
        self.assertEqual(news.to_local(m["time"]).strftime("%H:%M"), "15:29")
        quiet = dict(m, pct=1.2)
        self.assertNotIn("MOVING", news.render_moves([quiet])[0])
        self.assertIn("MOVING", news.render_moves([quiet], move_pct=1.0)[0])
        with self.assertRaises(news.NewsError):
            news.parse_chart(b'{"chart": {"result": null}}', "ZZZZ")
        code, out, _ = run(["--tickers", "RELIANCE", "--hours", "400", "--dry-run"] + self.base)
        self.assertRegex(out, r"RELIANCE\s+Rs 1,335\.40 \+0\.83% vs yesterday's close Rs 1,324\.40 at 15:29 IST")
        # no chart file offline: no move line, no error note
        code, out, _ = run(["--tickers", "ADANIENT", "--hours", "400", "--dry-run"] + self.base)
        self.assertNotIn("vs yesterday's close", out)
        self.assertNotIn("Yahoo", out)

    def test_state_forgets_after_30_days(self):
        state = {"seen": {"old": "2026-08-01T00:00:00+00:00"}}
        now = news.parse_time(NOW)
        news.remember([], state, now)
        self.assertNotIn("old", state["seen"])
        self.assertEqual(state["last_check"], now.isoformat())


class IndiaClockAndSymbols(unittest.TestCase):
    def test_ist_clock(self):
        self.assertEqual((news.MARKET, news.TZ_LABEL, news.CUR, news.SUFFIX), ("NSE", "IST", "Rs ", ".NS"))
        utc = datetime.datetime(2026, 11, 11, 3, 50, tzinfo=UTC)   # 09:20 IST
        self.assertEqual(news.to_local(utc).strftime("%H:%M"), "09:20")
        self.assertEqual(news.local_to_utc(datetime.datetime(2026, 11, 11, 15, 31)),
                         datetime.datetime(2026, 11, 11, 10, 1))
        self.assertEqual(news.to_local(datetime.datetime(2026, 7, 1, 0, 0, tzinfo=UTC)).hour, 5)  # no daylight time
        self.assertEqual(news.stamp(utc), "2026-11-11 09:20 IST")

    def test_us_mode_keeps_the_new_york_clock(self):
        utc = datetime.datetime(2026, 10, 19, 14, 15, tzinfo=UTC)
        self.assertEqual(us_news.to_local(utc).hour, 10)
        self.assertTrue(us_news.stamp(utc).endswith("New York"))
        self.assertEqual(us_news.render_moves([{"ticker": "AAPL", "price": 10.0, "prev_close": 10.0,
                                                "pct": 0.0, "time": None}])[0][:12], "AAPL   $10.0")

    def test_ysym_and_symbols(self):
        self.assertEqual(news.ysym("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(news.ysym("m&m"), "M&M.NS")
        self.assertEqual(news.ysym("BAJAJ-AUTO"), "BAJAJ-AUTO.NS")
        self.assertEqual(news.ysym("^NSEI"), "^NSEI")
        self.assertEqual(news.ysym("TCS.BO"), "TCS.BO")
        self.assertEqual(news.plain("m&m.ns"), "M&M")
        self.assertEqual(news.plain("bajaj-auto"), "BAJAJ-AUTO")

    def test_yahoo_url_is_encoded(self):
        urls = []

        class Spy(news.Fetcher):
            def get(self, url, name, nse=False):
                urls.append(url)
                raise news.NewsError("offline: no file " + name)

        news.collect_moves(Spy(offline="x"), {"M&M": None})
        self.assertIn("/chart/M%26M.NS?", urls[0])

    def test_symbols_with_and_and_dash_are_matched(self):
        pats = news.mention_patterns({"M&M": "Mahindra & Mahindra Limited", "BAJAJ-AUTO": "Bajaj Auto Limited"})
        self.assertTrue(pats["M&M"].search("M&M Share Price Highlights"))
        self.assertTrue(pats["M&M"].search("Mahindra & Mahindra gains"))
        self.assertFalse(pats["M&M"].search("M&MFIN slips"))
        self.assertTrue(pats["BAJAJ-AUTO"].search("Why BAJAJ-AUTO is up"))
        self.assertTrue(pats["BAJAJ-AUTO"].search("Bajaj Auto sales rise"))

    def test_symbol_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            none = os.path.join(tmp, "none.json")
            code, out, err = run(["--tickers", "bajaj-auto", "M&M", "--offline", DIR, "--dry-run", "--no-moves",
                                  "--hours", "400", "--now", NOW, "--portfolio", none, "--watchlist", none,
                                  "--plan", none])
            self.assertIn("M&M", out)
            self.assertIn("BAJAJ-AUTO", out)  # a symbol with no data is named in a note, never guessed
            self.assertIn("no data from", out)


if __name__ == "__main__":
    unittest.main()
