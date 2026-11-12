#!/usr/bin/env python3
"""Data pack for one or more NSE stocks (stdlib only, no keys).

Gathers price history and quote (india_client), computes technical indicators,
and reads NSE corporate announcements and corporate actions.
No fundamentals scraping: use announcements (results filings) and ask the user
for financial figures.

Usage:
    python3 stock_snapshot.py RELIANCE
    python3 stock_snapshot.py RELIANCE TCS --json
    python3 stock_snapshot.py HDFCBANK --announcements 15
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
NSE_HOME = "https://www.nseindia.com/"
ANNOUNCE_URL = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={s}"
ACTIONS_URL = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={s}"
HOLDING_URL = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={s}"
PLEDGE_URL = "https://www.nseindia.com/api/corporate-pledgedata?index=equities&symbol={s}"
RESULT_WORDS = ("financial result", "outcome of board meeting")


class NseSession:
    """NSE JSON fetcher with the cookie warm-up the API needs."""

    def __init__(self, opener=None):
        if opener is None:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._opener = opener
        self._ready = False

    def _get(self, url, headers=None):
        h = {"User-Agent": UA}
        h.update(headers or {})
        for attempt in (0, 1):
            try:
                body = self._opener.open(urllib.request.Request(url, headers=h), timeout=30).read()
                return body.decode("utf-8-sig", errors="replace") if isinstance(body, bytes) else body
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt == 0:
                    time.sleep(2)
                    continue
                return None
            except (urllib.error.URLError, OSError, ValueError):
                return None
        return None

    def get_json(self, url):
        if not self._ready:
            self._get(NSE_HOME)
            self._ready = True
        body = self._get(url, {"Referer": NSE_HOME, "Accept": "application/json"})
        try:
            return json.loads(body) if body else None
        except ValueError:
            return None


def _iso(text):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Technicals (bars newest first)
# ---------------------------------------------------------------------------


def _sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def _ema_series(v, n):
    a, out = 2.0 / (n + 1), [v[0]]
    for x in v[1:]:
        out.append(a * x + (1 - a) * out[-1])
    return out


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _pct(v):
    try:
        return round(float(str(v).strip()), 2)
    except (TypeError, ValueError):
        return None


def parse_holding(data, quarters=4):
    """NSE shareholding master -> [{date, promoter_pct, public_pct}], newest first."""
    rows = data if isinstance(data, list) else []
    out = []
    for r in rows[:quarters]:
        if isinstance(r, dict):
            out.append({"date": r.get("date"), "promoter_pct": _pct(r.get("pr_and_prgrp")),
                        "public_pct": _pct(r.get("public_val"))})
    return out


def parse_pledge(data):
    """NSE pledge data -> {as_of, promoter_pct, pledged_pct_of_promoter, pledged_pct_of_total} or None.
    An empty answer means NSE has no pledge disclosure for the stock."""
    rows = (data or {}).get("data") if isinstance(data, dict) else None
    if not rows or not isinstance(rows[0], dict):
        return None
    r = rows[0]
    return {"as_of": r.get("shp"), "promoter_pct": _pct(r.get("percPromoterHolding")),
            "pledged_pct_of_promoter": _pct(r.get("percPromoterShares")),
            "pledged_pct_of_total": _pct(r.get("percTotShares"))}


def results_filings(announcements):
    """The announcements that carry quarterly results (read the PDF for the figures)."""
    return [a for a in announcements
            if any(w in (a.get("category", "") + " " + a.get("text", "")).lower() for w in RESULT_WORDS)]


def compute_technicals(bars_newest_first):
    """Indicators from daily bars. Returns None when under 15 bars.
    A short history (a recent listing) gives the indicators it can; the rest are None."""
    bars = [b for b in reversed(bars_newest_first) if b.get("close")]
    if len(bars) < 15:
        return None
    c = [b["close"] for b in bars]
    h = [b["high"] for b in bars]
    lo = [b["low"] for b in bars]
    vol = [b.get("volume") or 0 for b in bars]
    last = c[-1]

    def ret(n):
        return round((last / c[-1 - n] - 1) * 100, 2) if len(c) > n else None

    ema12, ema26 = _ema_series(c, 12), _ema_series(c, 26)
    macd = [a - b for a, b in zip(ema12, ema26)]
    sig = _ema_series(macd, 9)
    sma20 = _sma(c, 20)
    sd20 = math.sqrt(sum((x - sma20) ** 2 for x in c[-20:]) / 20) if sma20 else None
    trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]
    atr = sum(trs[-14:]) / 14 if len(trs) >= 14 else None
    yr = bars[-252:]
    hi52, lo52 = max(b["high"] for b in yr), min(b["low"] for b in yr)
    sma50, sma200 = _sma(c, 50), _sma(c, 200)
    v20 = sum(vol[-20:]) / 20 if vol else 0
    v50 = sum(vol[-50:]) / min(50, len(vol)) if vol else 0
    rec = bars[-60:]
    supports = sorted({round(min(b["low"] for b in rec[i : i + 5]), 2) for i in range(0, len(rec) - 4, 5)})
    resist = sorted({round(max(b["high"] for b in rec[i : i + 5]), 2) for i in range(0, len(rec) - 4, 5)})
    if sma50 and sma200:
        trend = "uptrend" if last > sma50 > sma200 else "downtrend" if last < sma50 < sma200 else "sideways/mixed"
    else:
        trend = "uptrend" if sma50 and last > sma50 else "mixed"
    return {
        "last": round(last, 2),
        "date": bars[-1]["date"],
        "returns_pct": {"1w": ret(5), "1m": ret(21), "3m": ret(63), "6m": ret(126), "12m": ret(252)},
        "history_days": len(bars),
        "sma20": round(sma20, 2) if sma20 else None,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "rsi14": round(rsi(c), 1) if rsi(c) is not None else None,
        "macd": round(macd[-1], 2),
        "macd_signal": round(sig[-1], 2),
        "macd_hist": round(macd[-1] - sig[-1], 2),
        "bollinger": ({"upper": round(sma20 + 2 * sd20, 2), "lower": round(sma20 - 2 * sd20, 2)}
                      if sma20 else {"upper": None, "lower": None}),
        "atr14": round(atr, 2) if atr else None,
        "high_52w": round(hi52, 2),
        "low_52w": round(lo52, 2),
        "from_52w_high_pct": round((last / hi52 - 1) * 100, 1),
        "volume_20d_vs_50d": round(v20 / v50, 2) if v50 else None,
        "support_levels": supports[:3],
        "resistance_levels": resist[-3:],
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# NSE announcements and actions
# ---------------------------------------------------------------------------


def parse_announcements(payload, limit=10):
    if not isinstance(payload, list):
        return []
    out = []
    for r in payload[:limit]:
        if isinstance(r, dict):
            out.append(
                {
                    "date": _iso(r.get("an_dt")),
                    "category": r.get("desc"),
                    "text": (r.get("attchmntText") or "").strip()[:300],
                    "file": r.get("attchmntFile"),
                }
            )
    return out


def parse_actions(payload, limit=12):
    if not isinstance(payload, list):
        return []
    out = []
    for r in payload[:limit]:
        if isinstance(r, dict):
            out.append({"ex_date": _iso(r.get("exDate")), "record_date": _iso(r.get("recDate")), "subject": r.get("subject")})
    return out


def build_pack(symbol, client, session, announcements=10):
    sym = symbol.upper()
    pack = {"symbol": sym}
    try:
        data = client.get_historical_prices(sym, days=300)
    except Exception:
        data = None
    pack["technicals"] = compute_technicals((data or {}).get("historical") or [])
    try:
        q = client.get_quote(sym)
    except Exception:
        q = None
    pack["quote"] = (q or [None])[0]
    try:
        prof = client.get_company_profiles([sym]).get(sym)
    except Exception:
        prof = None
    pack["profile"] = prof
    try:
        cal = client.get_earnings_calendar() or []
    except Exception:
        cal = []
    pack["upcoming_events"] = [e for e in cal if str(e.get("symbol", "")).upper() == sym][:3]
    pack["announcements"] = parse_announcements(session.get_json(ANNOUNCE_URL.format(s=urllib.parse.quote(sym))), announcements)
    pack["corporate_actions"] = parse_actions(session.get_json(ACTIONS_URL.format(s=urllib.parse.quote(sym))))
    pack["shareholding"] = parse_holding(session.get_json(HOLDING_URL.format(s=urllib.parse.quote(sym))))
    pledge_raw = session.get_json(PLEDGE_URL.format(s=urllib.parse.quote(sym)))
    pack["pledge"] = parse_pledge(pledge_raw)
    pack["pledge_checked"] = pledge_raw is not None
    pack["results_filings"] = results_filings(pack["announcements"])
    return pack


def format_pack(p):
    lines = [f"# {p['symbol']} data pack", ""]
    prof = p.get("profile") or {}
    if prof:
        lines.append(f"{prof.get('companyName', p['symbol'])} | industry: {prof.get('industry', 'n/a')}")
    q = p.get("quote")
    if q:
        lines.append(f"Price Rs {q['price']:,.2f} ({q.get('changesPercentage', 0):+.2f}% today), 52w range Rs {q['yearLow']:,.2f} - Rs {q['yearHigh']:,.2f}")
    t = p.get("technicals")
    lines += ["", "## Technicals"]
    if not t:
        lines.append("Not enough price history.")
    else:
        r = t["returns_pct"]
        if t.get("history_days", 999) < 200:
            lines.append(f"- Short history: {t['history_days']} trading days. Indicators that need more days show None.")
        lines += [
            f"- Trend: {t['trend']}; last Rs {t['last']:,.2f} on {t['date']}",
            f"- Returns: 1w {r['1w']}%, 1m {r['1m']}%, 3m {r['3m']}%, 6m {r['6m']}%, 12m {r['12m']}%",
            f"- SMA20 {t['sma20']}, SMA50 {t['sma50']}, SMA200 {t['sma200']}",
            f"- RSI14 {t['rsi14']}; MACD {t['macd']} vs signal {t['macd_signal']} (hist {t['macd_hist']})",
            f"- Bollinger {t['bollinger']['lower']} - {t['bollinger']['upper']}; ATR14 {t['atr14']}",
            f"- 52w high Rs {t['high_52w']} ({t['from_52w_high_pct']}% away), low Rs {t['low_52w']}",
            f"- Volume 20d vs 50d: {t['volume_20d_vs_50d']}",
            f"- Support {t['support_levels']}, resistance {t['resistance_levels']}",
        ]
    lines += ["", "## Upcoming events (NSE board meeting calendar)"]
    lines += [f"- {e.get('date')}: {e.get('purpose')}" for e in p["upcoming_events"]] or ["- None listed"]
    lines += ["", "## Recent announcements"]
    lines += [f"- {a['date']} [{a['category']}] {a['text'][:160]}" for a in p["announcements"]] or ["- None fetched"]
    lines += ["", "## Promoter holding and pledge (NSE)"]
    sh = p.get("shareholding") or []
    if sh:
        lines.append("- Promoter holding: " + ", ".join(
            "%s %s%%" % (r["date"], r["promoter_pct"]) for r in sh))
    else:
        lines.append("- Promoter holding: not fetched")
    pl = p.get("pledge")
    if pl:
        lines.append("- Pledge (%s): %s%% of promoter shares, %s%% of all shares" % (
            pl["as_of"], pl["pledged_pct_of_promoter"], pl["pledged_pct_of_total"]))
    elif p.get("pledge_checked"):
        lines.append("- Pledge: no pledge disclosure at NSE")
    else:
        lines.append("- Pledge: not fetched")
    lines += ["", "## Results filings (open the PDF for revenue, profit and margins)"]
    lines += [f"- {a['date']} {a['text'][:120]} {a.get('file') or ''}".rstrip()
              for a in p.get("results_filings") or []] or ["- None in the recent announcements"]
    lines += ["", "## Corporate actions"]
    lines += [f"- ex-date {a['ex_date']}: {a['subject']}" for a in p["corporate_actions"]] or ["- None fetched"]
    lines += ["", "Fundamentals are not scraped. Use results filings above or figures the user supplies.",
              "This is analysis, not financial advice."]
    return "\n".join(lines)


def main(argv=None, client=None, session=None):
    ap = argparse.ArgumentParser(description="NSE stock data pack")
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--announcements", type=int, default=10)
    a = ap.parse_args(argv)
    if client is None:
        from india_client import FMPClient

        client = FMPClient(quiet=True)
    session = session or NseSession()
    packs = [build_pack(s, client, session, a.announcements) for s in a.symbols]
    print(json.dumps(packs, indent=2, default=str) if a.json else "\n\n".join(format_pack(p) for p in packs))
    return 0


if __name__ == "__main__":
    import sys as _sys
    if hasattr(_sys.stdout, "reconfigure"):
        _sys.stdout.reconfigure(errors="replace")
    raise SystemExit(main())
