#!/usr/bin/env python3
"""Free India market data client (Yahoo chart API + NSE public files).

Drop-in replacement for the paid price client used by the screeners.
Standard library only. No keys. Class name stays FMPClient so skill code
changes only its import line (IndiaClient is an alias).

Return shapes:
  get_historical_prices -> {"symbol", "historical": [{date, open, high, low,
      close, adjClose, volume}, ...]}  newest first, or None
  get_quote             -> list of quote dicts
  get_batch_quotes      -> {symbol: quote}
  get_batch_historical  -> {symbol: historical list, newest first}
  get_universe          -> list of NSE symbols
  get_company_profiles  -> {symbol: {companyName, industry, sector}}
  get_earnings_calendar -> [{symbol, date, purpose, company}]
"""

import csv
import http.cookiejar
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Optional

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/130.0 Safari/537.36"
)
YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
NSE_HOME = "https://www.nseindia.com/"
NSE_EVENT_URL = "https://www.nseindia.com/api/event-calendar"
NSE_BOARD_URL = "https://www.nseindia.com/api/corporate-board-meetings"
NSE_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
UNIVERSE_URLS = {
    "nifty50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    "midcap150": "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "smallcap250": "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
}
IST = timezone(timedelta(hours=5, minutes=30))


class ApiCallBudgetExceeded(RuntimeError):
    """Raised when max_api_calls network calls have been used."""


def to_yahoo_symbol(symbol: str) -> str:
    """RELIANCE -> RELIANCE.NS. Index symbols (^NSEI) and .NS names pass through."""
    s = str(symbol).strip()
    if s.startswith("^") or s.endswith(".NS") or s.endswith(".BO"):
        return s
    return s + ".NS"


def _num(value):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


class FMPClient:
    """Yahoo + NSE client with rate limiting, one 429 retry and a per-run cache."""

    RATE_LIMIT_DELAY = 0.3
    INDIA_EXCHANGES = ("NSE",)
    US_EXCHANGES = INDIA_EXCHANGES  # name kept for drop-in compatibility

    def __init__(self, api_key=None, opener=None, sleep=None, max_api_calls=None,
                 rate_delay=None, quiet=False, **kw):
        self.api_key = None  # no key is ever needed
        if opener is None:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._opener = opener
        self._sleep = sleep or time.sleep
        self.max_api_calls = max_api_calls
        self.rate_delay = self.RATE_LIMIT_DELAY if rate_delay is None else rate_delay
        self.quiet = quiet
        self.cache = {}
        self.api_calls_made = 0
        self.rate_limit_reached = False
        self._last_yahoo = 0.0
        self._nse_ready = False
        self._last_error = None

    # ---- transport -------------------------------------------------------
    def _log(self, msg):
        if not self.quiet:
            print(msg, file=sys.stderr)

    def _fetch(self, url, headers=None, yahoo=False):
        """Return response text or None. Retries once after 2 s on HTTP 429."""
        if self.max_api_calls is not None and self.api_calls_made >= self.max_api_calls:
            raise ApiCallBudgetExceeded(f"max_api_calls={self.max_api_calls} reached")
        hdrs = {"User-Agent": USER_AGENT}
        if headers:
            hdrs.update(headers)
        for attempt in (0, 1):
            if yahoo:
                wait = self.rate_delay - (time.time() - self._last_yahoo)
                if wait > 0:
                    self._sleep(wait)
            req = urllib.request.Request(url, headers=hdrs)
            try:
                self.api_calls_made += 1
                resp = self._opener.open(req, timeout=30)
                body = resp.read()
                if yahoo:
                    self._last_yahoo = time.time()
                if isinstance(body, bytes):
                    body = body.decode("utf-8-sig", errors="replace")
                return body
            except urllib.error.HTTPError as e:
                if yahoo:
                    self._last_yahoo = time.time()
                if e.code == 429 and attempt == 0:
                    self._sleep(2)
                    continue
                self._last_error = f"HTTP {e.code}"
                return None
            except (urllib.error.URLError, OSError, ValueError) as e:
                self._last_error = f"request error: {e}"
                return None
        return None

    def _yahoo_chart(self, symbol, rng="2y"):
        """Raw Yahoo chart result dict (first result) or None. Cached."""
        ysym = to_yahoo_symbol(symbol)
        key = ("chart", ysym, rng)
        if key in self.cache:
            return self.cache[key]
        result = None
        for host in YAHOO_HOSTS:
            url = (f"https://{host}/v8/finance/chart/{urllib.parse.quote(ysym, safe='')}"
                   f"?range={rng}&interval=1d")
            body = self._fetch(url, yahoo=True)
            if not body:
                continue
            try:
                data = json.loads(body)
                res = data["chart"]["result"]
                if res:
                    result = res[0]
                    break
            except (ValueError, KeyError, TypeError):
                continue
        if result is None:
            self._log(f"WARN: no Yahoo data for {symbol} ({self._last_error})")
        self.cache[key] = result
        return result

    @staticmethod
    def _parse_bars(result):
        """Chart result -> bar list newest first."""
        try:
            ts = result.get("timestamp") or []
            q = result["indicators"]["quote"][0]
            adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
            offset = int(result.get("meta", {}).get("gmtoffset", 19800))
        except (KeyError, IndexError, TypeError, AttributeError):
            return []
        tz = timezone(timedelta(seconds=offset))
        bars = []
        for i, t in enumerate(ts):
            try:
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            except (IndexError, KeyError, TypeError):
                continue
            if None in (o, h, l, c):
                continue
            vol = q.get("volume", [None] * len(ts))[i]
            a = adj[i] if adj and i < len(adj) and adj[i] is not None else c
            d = datetime.fromtimestamp(t, tz).date().isoformat()
            bars.append({"date": d, "open": float(o), "high": float(h), "low": float(l),
                         "close": float(c), "adjClose": float(a),
                         "volume": int(vol) if vol is not None else 0})
        bars.reverse()
        return bars

    @staticmethod
    def _range_for(days):
        if days <= 480:
            return "2y"
        if days <= 1200:
            return "5y"
        return "10y"

    # ---- prices ----------------------------------------------------------
    def get_historical_prices(self, symbol, days=365):
        key = ("prices", symbol, days)
        if key in self.cache:
            return self.cache[key]
        res = self._yahoo_chart(symbol, self._range_for(days))
        data = None
        if res:
            bars = self._parse_bars(res)
            if bars:
                data = {"symbol": symbol, "historical": bars[:days]}
        self.cache[key] = data
        return data

    def get_batch_historical(self, symbols, days=365):
        out = {}
        for s in symbols:
            d = self.get_historical_prices(s, days=days)
            if d and d.get("historical"):
                out[s] = d["historical"]
        return out

    def calculate_sma(self, prices, period):
        if not prices:
            return 0.0
        if len(prices) < period:
            return sum(prices) / len(prices)
        return sum(prices[:period]) / period

    # ---- quotes ----------------------------------------------------------
    def _quote_one(self, symbol):
        res = self._yahoo_chart(symbol, "2y")
        if not res:
            return None
        bars = self._parse_bars(res)
        if not bars:
            return None
        meta = res.get("meta", {})
        last = bars[0]
        price = _num(meta.get("regularMarketPrice"))
        if price is None:
            price = last["close"]
        rmt = meta.get("regularMarketTime")
        traded_day = (datetime.fromtimestamp(rmt, IST).date().isoformat()
                      if isinstance(rmt, (int, float)) else last["date"])
        if last["date"] == traded_day and len(bars) > 1:
            prev = bars[1]["close"]
        else:
            prev = last["close"]
        change = price - prev
        pct = (change / prev * 100.0) if prev else 0.0
        year = bars[:252]
        vols = [b["volume"] for b in bars[:50] if b["volume"]]
        return {
            "symbol": symbol,
            "name": meta.get("longName") or meta.get("shortName") or symbol,
            "price": price,
            "previousClose": prev,
            "change": change,
            "changesPercentage": pct,
            "open": last["open"],
            "dayHigh": _num(meta.get("regularMarketDayHigh")) or last["high"],
            "dayLow": _num(meta.get("regularMarketDayLow")) or last["low"],
            "yearHigh": max(b["high"] for b in year),
            "yearLow": min(b["low"] for b in year),
            "volume": _num(meta.get("regularMarketVolume")) or last["volume"],
            "avgVolume": (sum(vols) / len(vols)) if vols else 0,
            "marketCap": None,
            "exchange": "NSE",
        }

    def get_quote(self, symbols):
        if isinstance(symbols, str):
            symbols = [s for s in symbols.split(",") if s.strip()]
        out = []
        for s in symbols:
            s = s.strip()
            key = ("quote", s)
            if key not in self.cache:
                self.cache[key] = self._quote_one(s)
            if self.cache[key]:
                out.append(self.cache[key])
        return out or None

    def get_batch_quotes(self, symbols):
        out = {}
        for q in self.get_quote(list(symbols)) or []:
            out[q["symbol"]] = q
        return out

    # ---- universe and profiles ------------------------------------------
    def get_universe_rows(self, name="nifty500"):
        """Rows of the NSE index CSV: Company Name, Industry, Symbol, Series, ISIN Code."""
        name = (name or "nifty500").lower()
        url = UNIVERSE_URLS.get(name)
        if url is None:
            raise ValueError(f"unknown universe '{name}'. Use one of {sorted(UNIVERSE_URLS)}")
        key = ("universe", name)
        if key not in self.cache:
            body = self._fetch(url)
            rows = []
            if body:
                rows = [r for r in csv.DictReader(io.StringIO(body)) if r.get("Symbol")]
            self.cache[key] = rows
        return self.cache[key]

    def get_universe(self, name="nifty500"):
        return [r["Symbol"].strip() for r in self.get_universe_rows(name)]

    def get_company_profiles(self, symbols):
        """Profiles from the NSE index CSVs (industry doubles as sector)."""
        wanted = set(symbols)
        out = {}
        for uni in ("nifty500", "smallcap250", "midcap150", "nifty50"):
            if not wanted - set(out):
                break
            for r in self.get_universe_rows(uni):
                sym = r["Symbol"].strip()
                if sym in wanted and sym not in out:
                    ind = (r.get("Industry") or "").strip()
                    out[sym] = {"companyName": (r.get("Company Name") or sym).strip(),
                                "industry": ind, "sector": ind}
        return out

    # ---- NSE JSON --------------------------------------------------------
    def _nse_json(self, url):
        if not self._nse_ready:
            self._fetch(NSE_HOME)
            self._nse_ready = True
        body = self._fetch(url, headers={"Referer": NSE_HOME, "Accept": "application/json"})
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None

    @staticmethod
    def _parse_nse_date(text):
        for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(text).strip(), fmt).date()
            except ValueError:
                continue
        return None

    def get_earnings_calendar(self, from_date=None, to_date=None, results_only=True):
        """NSE results meetings between two dates (YYYY-MM-DD strings or date objects).

        Past and current meetings come from the NSE board-meetings API. The
        upcoming event calendar adds meetings that are not yet filed there.
        """
        lo = self._as_date(from_date) or date.today() - timedelta(days=14)
        hi = self._as_date(to_date) or date.today() + timedelta(days=14)
        seen = {}

        def add(symbol, d, purpose, desc, company):
            if not symbol or d is None or d < lo or d > hi:
                return
            text = (str(purpose or "") + " " + str(desc or "")).lower()
            if results_only and "result" not in text:
                return
            seen.setdefault((symbol, d.isoformat()), {
                "symbol": symbol, "date": d.isoformat(),
                "purpose": str(purpose or ""), "company": company or symbol})

        url = (f"{NSE_BOARD_URL}?index=equities&from_date={lo.strftime('%d-%m-%Y')}"
               f"&to_date={hi.strftime('%d-%m-%Y')}")
        rows = self._nse_json(url)
        for ev in rows if isinstance(rows, list) else []:
            add(ev.get("bm_symbol"), self._parse_nse_date(ev.get("bm_date")),
                ev.get("bm_purpose"), ev.get("bm_desc"), ev.get("sm_name"))
        rows = self._nse_json(NSE_EVENT_URL)
        for ev in rows if isinstance(rows, list) else []:
            add(ev.get("symbol"), self._parse_nse_date(ev.get("date")),
                ev.get("purpose"), ev.get("bm_desc"), ev.get("company"))
        return sorted(seen.values(), key=lambda e: (e["date"], e["symbol"]))

    def get_trading_holidays(self):
        """Sorted ISO dates of NSE cash-market trading holidays (current year)."""
        data = self._nse_json(NSE_HOLIDAY_URL)
        out = set()
        if isinstance(data, dict):
            for row in data.get("CM") or []:
                d = self._parse_nse_date(row.get("tradingDate"))
                if d:
                    out.add(d.isoformat())
        return sorted(out)

    @staticmethod
    def _as_date(v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    def get_api_stats(self):
        remaining = (max(0, self.max_api_calls - self.api_calls_made)
                     if self.max_api_calls is not None else 10 ** 9)
        return {"api_calls_made": self.api_calls_made, "source": "yahoo+nse",
                "cache_entries": len(self.cache), "rate_limit_reached": self.rate_limit_reached,
                "max_api_calls": self.max_api_calls, "budget_remaining": remaining}


IndiaClient = FMPClient
