#!/usr/bin/env python3
"""News monitor for trader-news. Standard library only.

Watches NSE filings and headlines for the stocks you watch or hold and
prints only what is new since the last check, with how far each stock has
moved today and a flag on anything that touches your symbols. Filings come
first, then headlines, each newest first.

    python3 news.py                                  # watchlist + plan + portfolio symbols
    python3 news.py --tickers RELIANCE TCS M&M
    python3 news.py --tickers RELIANCE --all --hours 72   # everything in the last 3 days, seen or not
    python3 news.py --no-filings                     # headlines only
    python3 news.py --no-moves                       # skip the price line per symbol
    python3 news.py --no-context                     # skip the RBI, SEBI and FII/DII section

Your symbols, when --tickers is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json.

Sources:
  - Exchange filings (ranked first). NSE's RSS feeds: announcements, financial
    results, board meetings, corporate actions and insider trading. They cover
    every company, so the tool keeps only the companies you watch (matched by
    name, from NSE's EQUITY_L.csv, cached in trader/cache/). A symbol with no
    item in those feeds falls back to NSE's per-symbol announcements API.
    Each filing is mapped to a category: financial results, board meeting,
    acquisition or merger, credit rating, insider trading or SAST, dividend,
    bonus or split, resignation of key people, fund raising, order win.
  - Headlines. Google News RSS searched by company name, plus the market feeds
    of Economic Times, Moneycontrol, Mint, Business Standard, BusinessLine and
    NDTV Profit. The market feeds are filtered by your symbols and names.
  - Market context: the latest RBI and SEBI press releases and NSE's FII/DII
    figures. They are not tied to a symbol.
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close.

Every item shows its source. When a source fails the tool prints "no data from
<source>" and carries on. It never guesses.

Times print in IST. State: trader/state/news.json remembers what you have seen
(30 days), so an item shows once. Offline: --offline DIR reads the feed files
(nse-announcements.xml, nse-results.xml, nse-board.xml, nse-actions.xml,
nse-insider.xml, google-<SYMBOL>.xml, et-markets.xml, et-stocks.xml, mc-*.xml,
mint.xml, bs.xml, bl.xml, ndtv.xml, rbi.xml, sebi.xml, fiidii.json,
api-<SYMBOL>.json, chart-<SYMBOL>.json, EQUITY_L.csv) from DIR. The tests use it.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""

import argparse
import csv
import datetime as _dt
import email.utils
import gzip
import hashlib
import html
import http.cookiejar
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

MARKET = "NSE"
TZ_LABEL = "IST"
IST_OFFSET = 5.5          # India Standard Time is UTC+5:30, no daylight time
CUR = "Rs "
SUFFIX = ".NS"            # Yahoo Finance symbol suffix for NSE (".BO" for BSE)

CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
GOOGLE = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
NSE_HOME = "https://www.nseindia.com/"
NSE_API = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=%s"
FIIDII = "https://www.nseindia.com/api/fiidiiTradeReact"
EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BROWSER_UA = "Mozilla/5.0 (compatible; trader-skill/1.0)"
KEEP_DAYS = 30
CACHE_DAYS = 7  # how long the NSE company list is kept in trader/cache/
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving

# (key, url, offline file, source name)
NSE_FEEDS = [
    ("ann", "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
     "nse-announcements.xml", "NSE announcements"),
    ("results", "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
     "nse-results.xml", "NSE financial results"),
    ("board", "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",
     "nse-board.xml", "NSE board meetings"),
    ("actions", "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
     "nse-actions.xml", "NSE corporate actions"),
    ("insider", "https://nsearchives.nseindia.com/content/RSS/Insider_Trading.xml",
     "nse-insider.xml", "NSE insider trading"),
]
PUBLISHERS = [
    ("https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "et-markets.xml", "ET Markets"),
    ("https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms", "et-stocks.xml", "ET Stocks"),
    ("https://www.moneycontrol.com/rss/marketreports.xml", "mc-reports.xml", "Moneycontrol reports"),
    ("https://www.moneycontrol.com/rss/buzzingstocks.xml", "mc-buzzing.xml", "Moneycontrol buzzing stocks"),
    ("https://www.moneycontrol.com/rss/results.xml", "mc-results.xml", "Moneycontrol results"),
    ("https://www.livemint.com/rss/markets", "mint.xml", "Mint"),
    ("https://www.business-standard.com/rss/markets-106.rss", "bs.xml", "Business Standard"),
    ("https://www.thehindubusinessline.com/markets/feeder/default.rss", "bl.xml", "BusinessLine"),
    ("https://feeds.feedburner.com/ndtvprofit-latest", "ndtv.xml", "NDTV Profit"),
]
CONTEXT_FEEDS = [
    ("https://www.rbi.org.in/pressreleases_rss.xml", "rbi.xml", "RBI"),
    ("https://www.sebi.gov.in/sebirss.xml", "sebi.xml", "SEBI"),
]

# SEBI LODR filing subjects, grouped into the categories this tool reports.
SUBJECTS = {
    "results": "financial results", "board": "board meeting",
    "deal": "acquisition or merger", "rating": "credit rating",
    "insider": "insider trading or SAST", "dividend": "dividend, bonus, split or buyback",
    "resign": "resignation or change of key people", "funding": "fund raising",
    "orders": "order win", "insolvency": "insolvency or default",
}
SUBJECT_PATTERNS = [
    ("results", r"financial results?|quarterly results?|\bresults\b|limited review"),
    ("board", r"outcome of board|board meeting"),
    ("deal", r"(?<!substantial )acquisition|\bacquire|merger|amalgamation|scheme of arrangement|"
             r"demerger|slump sale|sale or disposal|divestment"),
    ("rating", r"credit rating|\bCRISIL\b|\bICRA\b|CARE Ratings|India Ratings|\brating (?:revision|withdrawal|assigned)"),
    ("insider", r"insider trading|\bPIT\b|\bSAST\b|takeover regulation|substantial acq|"
                r"Reg\.?\s?(?:7|29|31)\b"),
    ("dividend", r"dividend|\bbonus\b|stock split|sub-?division|book closure|buy-?back"),
    ("resign", r"resign|cessation|change in director|key managerial|\bKMP\b|senior management|"
               r"\bappointment\b|managing director"),
    ("funding", r"fund[- ]?raising|preferential|\bQIP\b|rights issue|allotment of (?:equity shares|securities)|"
                r"non-convertible|debenture|\bwarrants\b|raising of funds"),
    ("orders", r"work order|purchase order|orders? (?:worth|of|from|received|win)|receipt of order|"
               r"bagging|letter of award|awarded|bags? order|secures? order|wins? order"),
    ("insolvency", r"insolvency|\bCIRP\b|\bNCLT\b|winding up|\bdefault|bankrupt|liquidat"),
]
IMPORTANT_ITEMS = {"results", "deal", "rating", "resign", "orders", "insolvency"}
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bQ[1-4]\b|\bnet profit\b|\bPAT\b|\bguidance\b|\bEBITDA\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\bbrokerage\b|\boutperform\b|"
                r"\bunderperform\b|\binitiates coverage\b"),
    ("legal", r"\blawsuit\b|\bsued\b|\bprobe\b|\binvestigation\b|\bSEBI order\b|\bNCLT\b|\bCCI\b|\bcourt\b|\bED raid"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b|\bstake sale\b|\bblock deal\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\bbonus\b|\bstock split\b|\brights issue\b|\bQIP\b|\bIPO\b|\bOFS\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist|\bhack|\bbreach\b|\boutage\b|\bfraud\b|\bpledge"),
    ("halt", r"\bhalt(?:s|ed)?\b|\bcircuit\b|\bASM\b|\bGSM\b|\btrading (?:pause|suspen)"),
    ("regulatory", r"\bUSFDA\b|\bFDA\b|\bapproval\b|\bapproves\b|\bclinical\b|\bSEBI\b|\bCCI\b|\bDGCA\b"),
    ("macro", r"\bRBI\b|\brepo\b|\bMPC\b|\bCPI\b|\binflation\b|\bGDP\b|\bFIIs?\b|\bFPIs?\b|\bcrude\b|\brupee\b|\bfutures\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

def market_offset(utc):
    return IST_OFFSET


def to_local(utc):
    return utc.replace(tzinfo=None) + _dt.timedelta(hours=market_offset(utc))


def local_to_utc(local):
    return local - _dt.timedelta(hours=market_offset(local))


def ysym(sym):
    s = sym.upper()
    return s if s.startswith("^") or "." in s else s + SUFFIX


def plain(sym):
    """RELIANCE.NS -> RELIANCE. Files, output and keys use the plain NSE symbol."""
    return re.sub(r"\.(NS|BO)$", "", sym.strip().upper())


def stamp(utc):
    return to_local(utc).strftime("%Y-%m-%d %H:%M") + " " + TZ_LABEL


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{symbol: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[plain(sym)] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(plain(pl["symbol"]), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[plain(sym)] = p.get("name") or out.get(plain(sym))
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.15):
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._nse = None

    def _read(self, opener, url, headers):
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers=headers)
        try:
            with (opener.open(req, timeout=30) if opener else urllib.request.urlopen(req, timeout=30)) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url, exc.reason))

    def get(self, url, name, nse=False):
        """nse=True: NSE's website API, which needs the cookies its home page sets."""
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        if not nse:
            return self._read(None, url, {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip"})
        if self._nse is None:
            self._nse = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            try:
                self._read(self._nse, NSE_HOME, {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip"})
            except NewsError:
                pass  # the home page can answer 403 and still set the cookie the API needs
        return self._read(self._nse, url, {"User-Agent": BROWSER_UA, "Accept": "application/json",
                                           "Referer": NSE_HOME, "Accept-Encoding": "gzip"})


def norm_name(name):
    s = html.unescape(name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(w for w in s.split() if w not in ("limited", "ltd"))


def short_name(name):
    return re.sub(r"\s+(?:Limited|Ltd\.?)$", "", (name or "").strip(), flags=re.I)


def equity_names(fetcher, cache="trader/cache"):
    """{SYMBOL: company name} from NSE's EQUITY_L.csv, kept a week in trader/cache/."""
    path = os.path.join(cache, "EQUITY_L.csv") if cache and not fetcher.offline else None
    data = None
    if path and os.path.isfile(path) and time.time() - os.path.getmtime(path) < CACHE_DAYS * 86400:
        with open(path, "rb") as fh:
            data = fh.read()
    if data is None:
        try:
            data = fetcher.get(EQUITY_URL, "EQUITY_L.csv")
        except NewsError:
            if not (path and os.path.isfile(path)):
                raise
            with open(path, "rb") as fh:  # a stale list beats none
                data = fh.read()
        else:
            if path:
                try:
                    os.makedirs(cache, exist_ok=True)
                    with open(path, "wb") as fh:
                        fh.write(data)
                except OSError:
                    pass
    out = {}
    for row in csv.reader(io.StringIO(data.decode("utf-8-sig", "replace"))):
        if len(row) >= 2 and row[0].strip() and row[0].strip().upper() != "SYMBOL":
            out[row[0].strip().upper()] = row[1].strip()
    if not out:
        raise NewsError("the NSE company list is empty")
    return out


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def _clean(value):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(value or "")).split())


TIME_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y")


def parse_time(value):
    """RFC 822 (RSS), ISO 8601 (Atom) or NSE's 11-Nov-2026 20:18:42 (IST) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in TIME_FORMATS:  # NSE writes India time with no zone
        try:
            local = _dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return local_to_utc(local).replace(tzinfo=_dt.timezone.utc)
    value = re.sub(r"^(\d{1,2} [A-Za-z]{3}),", lambda m: m.group(1), value)  # SEBI: "11 Nov, 2026 +0530"
    try:
        return _dt.datetime.strptime(value, "%d %b %Y %z").astimezone(_dt.timezone.utc)
    except ValueError:
        pass
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def classify(text):
    """The filing categories a subject or text falls under, in a fixed order."""
    return [code for code, rx in SUBJECT_PATTERNS if re.search(rx, text or "", re.I)]


def parse_rss(data, ticker, source="Google News"):
    """Headline RSS (Google News or a publisher) -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (source, exc))
    out = []
    for it in root.iter("item"):
        title = _clean(_text(it, "title"))
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        pub = _clean(_text(it, "source"))
        if pub and title.endswith(" - " + pub):
            title = title[:-len(pub) - 3]
        out.append({"id": "rss:" + guid, "source": ("%s via %s" % (pub, source)) if pub else source,
                    "kind": "headline", "ticker": ticker, "title": title,
                    "summary": _clean(_text(it, "description")),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def _fields(desc):
    out = {}
    for part in (desc or "").split("|"):
        k, _, v = part.partition(":")
        out[k.strip().upper()] = v.strip()
    return out


def _filing(key, source, ticker, company, title, summary, items, link, when, form="", generic_link=False):
    ident = hashlib.sha1(("%s|%s|%s|%s|%s" % (key, company, summary, link, when)).encode("utf-8")).hexdigest()[:16]
    return {"id": "nse:%s:%s" % (key, ident), "source": source, "kind": "filing", "form": form,
            "ticker": ticker, "company": company, "title": title, "summary": summary,
            "items": items, "important": bool(set(items) & IMPORTANT_ITEMS),
            "link": link, "link_unique": not generic_link, "time": parse_time(when)}


def parse_nse_rss(data, feed):
    """One NSE RSS feed -> filing items. The ticker is filled in later, from the company name."""
    key, _url, _name, source = feed
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("%s is not valid XML: %s" % (source, exc))
    out = []
    for it in root.iter("item"):
        company = _clean(_text(it, "title"))
        desc = _clean(_text(it, "description"))
        link = _text(it, "link")
        when = _text(it, "pubDate")
        if key == "ann":
            text, _, subject = desc.partition("|SUBJECT:")
            subject = subject.strip() or text.strip()[:120]
            title, items, form = "%s: %s" % (company, subject), classify(subject + " " + text), subject
        elif key == "results":
            f = _fields(desc)
            title = "%s: financial results for %s (%s, %s, period ended %s)" % (
                company, f.get("RELATING TO", "the period"), f.get("AUDITED/UNAUDITED", "status unknown").lower(),
                f.get("CONSOLIDATED/NON-CONSOLIDATED", "basis unknown").lower(),
                f.get("PERIOD ENDED", "date unknown"))
            items, form = ["results"], "Financial results"
        elif key == "board":
            title = "%s: board meeting, %s" % (company, desc.replace(" |", ";")[:140])
            items, form = ["board"], "Board meeting"
        elif key == "actions":
            company = re.sub(r"\s+-\s+Ex-Date:.*$", "", company)
            f = _fields(desc)
            purpose = f.get("PURPOSE", desc)
            title = "%s: %s (record date %s)" % (company, purpose.lower(), f.get("RECORD DATE", "unknown"))
            items, form = classify(purpose) or ["dividend"], "Corporate action"
        else:
            title = "%s: insider trading disclosure" % company
            items, form = ["insider"], "Insider trading"
        out.append(_filing(key, source, "", company, title, desc, items, link, when, form,
                           generic_link=key in ("results", "actions")))
    return out


def parse_nse_api(data, ticker):
    """NSE's per-symbol announcements JSON -> filing items, newest first."""
    try:
        rows = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        if not isinstance(rows, list):
            raise ValueError("not a list")
    except ValueError:
        raise NewsError("NSE API for %s is not usable" % ticker)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        desc = _clean(r.get("desc"))
        text = _clean(r.get("attchmntText"))
        company = r.get("sm_name") or ticker
        out.append(_filing("api", "NSE API", ticker, company, "%s: %s" % (company, desc),
                           text[:400], classify(desc + " " + text), r.get("attchmntFile") or "",
                           r.get("an_dt") or "", desc))
        out[-1]["id"] = "nse:api:%s" % (r.get("seq_id") or out[-1]["id"])
    out.sort(key=lambda i: i["time"] or _dt.datetime.min.replace(tzinfo=_dt.timezone.utc), reverse=True)
    return out


def parse_fiidii(data):
    """NSE's FII/DII JSON -> market context items."""
    try:
        rows = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        out = []
        for r in rows:
            net = float(str(r["netValue"]).replace(",", ""))
            out.append({"source": "NSE FII/DII", "title": "%s net %s %s%s crore (bought %s, sold %s)" % (
                r["category"], "buying" if net >= 0 else "selling", CUR, "{:,.2f}".format(abs(net)),
                "{:,.2f}".format(float(str(r["buyValue"]).replace(",", ""))),
                "{:,.2f}".format(float(str(r["sellValue"]).replace(",", "")))),
                "link": "https://www.nseindia.com/reports/fii-dii", "time": parse_time(r.get("date"))})
        return out
    except (ValueError, KeyError, TypeError):
        raise NewsError("FII/DII data is not usable")


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        sym = urllib.parse.quote(ysym(t), safe="")
        try:
            try:
                data = fetcher.get(CHART % ("query2", sym), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", sym), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("no data from Yahoo Finance price for %s: %s" % (t, exc))
    return out


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\bNSE\s*:\s*%s(?![A-Za-z0-9&-])" % re.escape(t)]
        if len(t) >= 3:
            alts.append(r"(?<![A-Za-z0-9&-])%s(?![A-Za-z0-9&-])" % re.escape(t))
        short = short_name(name)
        if short and len(short) >= 4:
            alts.append(r"(?i:\b%s\b)" % re.escape(short).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    """Which of your symbols each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "filing" and "results" in it.get("items", []) and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"] if it.get("link_unique", True) else "",
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def _market_wide(items, watch):
    """Keep what a market-wide feed says about your symbols; the first one named is the ticker."""
    pats = mention_patterns(watch)
    out = []
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        hit = sorted(t for t, rx in pats.items() if rx.search(hay))
        if hit:
            it["ticker"] = hit[0]
            out.append(it)
    return out


def collect(fetcher, watch, state, filings=True, count=10, errors=None, names=None, counts=None, api=True):
    """Filings first, then headlines. `names` is {symbol: company} from the NSE list."""
    errors = [] if errors is None else errors
    counts = {} if counts is None else counts
    names = names or {}
    full = {t: watch.get(t) or names.get(t) for t in watch}
    items = []

    def add(source, found):
        counts[source] = counts.get(source, 0) + len(found)
        items.extend(found)

    if filings:
        rev = {norm_name(n): t for t, n in full.items() if n}
        covered = set()
        for feed in NSE_FEEDS:
            counts.setdefault(feed[3], 0)
            try:
                found = parse_nse_rss(fetcher.get(feed[1], feed[2]), feed)
            except NewsError as exc:
                errors.append("no data from %s: %s" % (feed[3], exc))
                continue
            kept = []
            for it in found:
                t = rev.get(norm_name(it["company"]))
                if t:
                    it["ticker"] = t
                    kept.append(it)
            covered.update(it["ticker"] for it in kept)
            add(feed[3], kept)
        counts.setdefault("NSE API", 0)
        for t in sorted(watch):
            if t in covered or not api:
                continue
            try:
                add("NSE API", parse_nse_api(fetcher.get(NSE_API % urllib.parse.quote(t, safe=""),
                                                         "api-%s.json" % t, nse=True), t)[:count])
            except NewsError as exc:
                errors.append("no data from NSE API for %s: %s" % (t, exc))
    for t in sorted(watch):
        counts.setdefault("Google News", 0)
        query = urllib.parse.quote_plus("%s share" % (short_name(full[t]) or t))
        try:
            add("Google News", parse_rss(fetcher.get(GOOGLE % query, "google-%s.xml" % t), t, "Google News"))
        except NewsError as exc:
            errors.append("no data from Google News for %s: %s" % (t, exc))
    for url, fname, source in PUBLISHERS:
        counts.setdefault(source, 0)
        try:
            add(source, _market_wide(parse_rss(fetcher.get(url, fname), "", source), full))
        except NewsError as exc:
            errors.append("no data from %s: %s" % (source, exc))
    return items


def collect_context(fetcher, errors=None, limit=5):
    """Latest RBI and SEBI press releases and FII/DII figures. Not tied to a symbol."""
    errors = [] if errors is None else errors
    out = []
    for url, fname, source in CONTEXT_FEEDS:
        try:
            found = parse_rss(fetcher.get(url, fname), "", source)[:limit]
        except NewsError as exc:
            errors.append("no data from %s: %s" % (source, exc))
            continue
        out += [{"source": source, "title": it["title"], "link": it["link"], "time": it["time"]}
                for it in found]
    try:
        out += parse_fiidii(fetcher.get(FIIDII, "fiidii.json", nse=True))
    except NewsError as exc:
        errors.append("no data from NSE FII/DII: %s" % exc)
    return out


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all. Filings first."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["kind"] == "filing", i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    mark = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), mark)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = mark


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s %s" % (to_local(m["time"]).strftime("%H:%M"), TZ_LABEL)) if m.get("time") else ""
        out.append("%-6s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], CUR + "{:,.2f}".format(m["price"]), m["pct"],
            CUR + "{:,.2f}".format(m["prev_close"]), when, flag))
    return out


def render_context(context):
    if not context:
        return []
    out = ["Market context (not tied to one stock):"]
    for c in context:
        when = stamp(c["time"]) if c.get("time") else "time unknown"
        title = c["title"] if len(c["title"]) <= 150 else c["title"][:147] + "..."
        out.append("  %s  %-12s %s" % (when, c["source"], title))
        out.append("      " + c["link"])
    out.append("")
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT, context=None, counts=None):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    out += render_context(context or [])
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = stamp(it["time"]) if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-11s %-20s %s" % (mark, when, who, it["source"], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    if counts:
        out.append("Items found per source: " + ", ".join("%s %d" % (k, v) for k, v in counts.items()) + ".")
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. "
               "Not financial advice." % stamp(now))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="NSE symbols; default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--cache", default="trader/cache", help="where the NSE company list is kept")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-filings", "--no-sec", dest="no_filings", action="store_true", help="headlines only")
    ap.add_argument("--no-api", action="store_true", help="skip NSE's per-symbol fallback")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per symbol")
    ap.add_argument("--no-context", action="store_true", help="skip the RBI, SEBI and FII/DII section")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {plain(t): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no tickers. Pass --tickers, or run /trader-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    counts = {}
    fetcher = Fetcher(offline=args.offline)
    try:
        names = equity_names(fetcher, args.cache)
    except NewsError as exc:
        names = {}
        errors.append("no data from NSE company list: %s" % exc)
    items = collect(fetcher, watch, state, filings=not args.no_filings, errors=errors,
                    names=names, counts=counts, api=not args.no_api)
    full = {t: watch[t] or names.get(t) for t in watch}
    items = dedupe(tag(items, full))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    context = [] if args.no_context else collect_context(fetcher, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        ctx = [dict(c, time=c["time"].isoformat() if c.get("time") else None) for c in context]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "context": ctx,
                          "items": _json_ready(shown), "sources": counts, "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct, context, counts))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    import sys as _sys
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
