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


def compute_technicals(bars_newest_first):
    """Indicators from daily bars. Returns None when under 30 bars."""
    bars = [b for b in reversed(bars_newest_first) if b.get("close")]
    if len(bars) < 30:
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
    sd20 = math.sqrt(sum((x - sma20) ** 2 for x in c[-20:]) / 20)
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
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "rsi14": round(rsi(c), 1) if rsi(c) is not None else None,
        "macd": round(macd[-1], 2),
        "macd_signal": round(sig[-1], 2),
        "macd_hist": round(macd[-1] - sig[-1], 2),
        "bollinger": {"upper": round(sma20 + 2 * sd20, 2), "lower": round(sma20 - 2 * sd20, 2)},
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
    raise SystemExit(main())
