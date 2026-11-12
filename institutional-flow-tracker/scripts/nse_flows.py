#!/usr/bin/env python3
"""NSE institutional flow data (stdlib only, no keys).

Sources:
  FII/DII daily cash-market flows  https://www.nseindia.com/api/fiidiiTradeReact
  Bulk deals                       https://nsearchives.nseindia.com/content/equities/bulk.csv
  Block deals                      https://nsearchives.nseindia.com/content/equities/block.csv

The FII/DII endpoint returns only the latest session, so each run appends the
day to a local history file (trader/cache/fii_dii.json) to build 5/10/20-day
totals over time.
"""

from __future__ import annotations

import csv
import http.cookiejar
import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/130.0 Safari/537.36"
)
NSE_HOME = "https://www.nseindia.com/"
FII_DII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
BULK_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
CRORE = 1e7
MATERIAL_NET_CR = 2000.0  # Rs crore over the window that counts as a real net flow


class NseSession:
    """Small NSE fetcher: cookie warm-up for the JSON API, plain GET for archives."""

    def __init__(self, opener=None, sleep=None):
        if opener is None:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._opener = opener
        self._sleep = sleep or time.sleep
        self._ready = False

    def _get(self, url, headers=None):
        hdrs = {"User-Agent": USER_AGENT}
        hdrs.update(headers or {})
        for attempt in (0, 1):
            try:
                resp = self._opener.open(urllib.request.Request(url, headers=hdrs), timeout=30)
                body = resp.read()
                return body.decode("utf-8-sig", errors="replace") if isinstance(body, bytes) else body
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt == 0:
                    self._sleep(2)
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
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError:
            return None

    def get_text(self, url):
        return self._get(url)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _iso(text):
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_fii_dii(payload) -> dict | None:
    """Rows [{category, date, buyValue, sellValue, netValue}] -> {date, fii, dii} in Rs crore."""
    if not isinstance(payload, list):
        return None
    out = {"date": None, "fii": None, "dii": None}
    for row in payload:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category", "")).upper()
        buy, sell = _num(row.get("buyValue")), _num(row.get("sellValue"))
        net = _num(row.get("netValue"))
        if net is None and buy is not None and sell is not None:
            net = buy - sell
        if buy is None or sell is None or net is None:
            continue
        entry = {"buy": buy, "sell": sell, "net": net}
        iso = _iso(row.get("date"))
        if iso:
            out["date"] = iso
        if cat.startswith("FII") or cat.startswith("FPI"):
            out["fii"] = entry
        elif cat.startswith("DII"):
            out["dii"] = entry
    if out["date"] is None or out["fii"] is None or out["dii"] is None:
        return None
    return out


def parse_deals(csv_text: str, kind: str) -> list[dict]:
    """Bulk or block deals CSV -> list of deal dicts. Values are in Rs."""
    if not csv_text:
        return []
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    if reader.fieldnames:
        reader.fieldnames = [(n or "").strip() for n in reader.fieldnames]
    deals = []
    for row in reader:
        qty = _num(row.get("Quantity Traded"))
        price = _num(row.get("Trade Price / Wght. Avg. Price"))
        side = (row.get("Buy/Sell") or "").strip().upper()
        symbol = (row.get("Symbol") or "").strip()
        if not symbol or qty is None or price is None or side not in ("BUY", "SELL"):
            continue
        client = (row.get("Client Name") or "").strip()
        deals.append(
            {
                "kind": kind,
                "date": _iso(row.get("Date")),
                "symbol": symbol,
                "name": (row.get("Security Name") or "").strip(),
                "client": client,
                "client_type": classify_client(client),
                "side": side,
                "quantity": qty,
                "price": price,
                "value": qty * price,
            }
        )
    return deals


_CLIENT_KEYWORDS = (
    ("mutual_fund", ("MUTUAL FUND", " MF", "AMC", "ASSET MANAGEMENT")),
    ("insurance", ("INSURANCE", "LIFE ", "LIC ", "ASSURANCE")),
    ("foreign", ("FPI", "FII", "SINGAPORE", "MAURITIUS", "LUXEMBOURG", "IRELAND", "CAYMAN", "LTD - ODI", "OFFSHORE", "INTERNATIONAL", "GLOBAL")),
    ("bank_or_nbfc", ("BANK", "FINANCE", "FINANCIAL")),
)


def classify_client(name: str) -> str:
    """Rough bucket from the client name. A heuristic, not an official category."""
    upper = f" {name.upper()} "
    for label, words in _CLIENT_KEYWORDS:
        if any(w in upper for w in words):
            return label
    return "other"


# ---------------------------------------------------------------------------
# History and summaries
# ---------------------------------------------------------------------------


def default_history_path() -> str:
    base = os.environ.get("TRADER_DIR") or os.path.join(os.getcwd(), "trader")
    return os.path.join(base, "cache", "fii_dii.json")


def load_history(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return sorted(
                (r for r in data if isinstance(r, dict) and r.get("date")), key=lambda r: r["date"]
            )
    except (OSError, ValueError):
        pass
    return []


def append_day(history: list[dict], day: dict | None) -> list[dict]:
    """Add or replace one day (keyed by date). Returns a new sorted list."""
    rows = {r["date"]: r for r in history}
    if day:
        rows[day["date"]] = day
    return [rows[d] for d in sorted(rows)]


def save_history(path: str, history: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history[-250:], f, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass


def summarize_flows(history: list[dict], windows=(5, 10, 20)) -> dict:
    """Net FII and DII flow (Rs crore) over the last N recorded sessions, plus a regime label."""
    out = {"sessions": len(history), "latest": history[-1] if history else None, "windows": {}}
    for n in windows:
        rows = history[-n:]
        out["windows"][str(n)] = {
            "sessions": len(rows),
            "fii_net": round(sum(r["fii"]["net"] for r in rows), 2),
            "dii_net": round(sum(r["dii"]["net"] for r in rows), 2),
        }
    ref = out["windows"].get("5") or {"fii_net": 0.0, "dii_net": 0.0, "sessions": 0}
    out["regime"] = classify_regime(ref["fii_net"], ref["dii_net"]) if ref["sessions"] else "no data"
    return out


def classify_regime(fii_net: float, dii_net: float, material: float = MATERIAL_NET_CR) -> str:
    fii = 1 if fii_net > material else (-1 if fii_net < -material else 0)
    dii = 1 if dii_net > material else (-1 if dii_net < -material else 0)
    if fii > 0 and dii > 0:
        return "broad buying (FII and DII both net buyers)"
    if fii < 0 and dii < 0:
        return "broad selling (FII and DII both net sellers)"
    if fii < 0 and dii > 0:
        return "DII absorbing FII selling"
    if fii > 0 and dii < 0:
        return "FII buying while DII books profits"
    if fii == 0 and dii == 0:
        return "no material net flow"
    return "FII net flow is small" if fii == 0 else "DII net flow is small"


def summarize_deals(deals: list[dict], min_value_cr: float = 0.0, top: int = 10) -> dict:
    """Net deal value per symbol (Rs crore), split into top accumulation and distribution."""
    per: dict[str, dict] = {}
    for d in deals:
        s = per.setdefault(
            d["symbol"], {"symbol": d["symbol"], "name": d["name"], "buy": 0.0, "sell": 0.0, "deals": 0, "institutions": set()}
        )
        s["buy" if d["side"] == "BUY" else "sell"] += d["value"]
        s["deals"] += 1
        if d["client_type"] in ("mutual_fund", "insurance", "foreign"):
            s["institutions"].add(d["client"])
    rows = []
    for s in per.values():
        net = (s["buy"] - s["sell"]) / CRORE
        gross = max(s["buy"], s["sell"]) / CRORE
        if gross < min_value_cr:
            continue
        rows.append(
            {
                "symbol": s["symbol"],
                "name": s["name"],
                "buy_cr": round(s["buy"] / CRORE, 2),
                "sell_cr": round(s["sell"] / CRORE, 2),
                "net_cr": round(net, 2),
                "deals": s["deals"],
                "institutional_clients": sorted(s["institutions"]),
            }
        )
    rows.sort(key=lambda r: r["net_cr"], reverse=True)
    accumulation = [r for r in rows if r["net_cr"] > 0][:top]
    distribution = [r for r in reversed(rows) if r["net_cr"] < 0][:top]
    return {"symbols": len(rows), "accumulation": accumulation, "distribution": distribution}
