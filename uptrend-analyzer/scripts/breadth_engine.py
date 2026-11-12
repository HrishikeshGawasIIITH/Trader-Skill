#!/usr/bin/env python3
"""Breadth engine: market breadth computed from stock prices (stdlib only).

Replaces the upstream CSV dashboards, which do not exist for India. For a
universe (default Nifty 500) it computes, for every trading day:

  - percent of stocks above their 50-day average
  - percent of stocks above their 200-day average
  - percent of stocks in an "uptrend" (overall and per sector)

Uptrend definition (upstream rules, rupee-adjusted):
  close > SMA20, close > SMA200, SMA50 > SMA200,
  close more than 30% above the 52-week low, close above its close 20 sessions ago.
  Base filters: close >= Rs 50 and 50-day average volume >= 100,000 shares.

From the 200-day breadth it derives the same detail columns the scoring code
expects: 8-day and 200-day EMA, 200MA trend with hysteresis, peaks, troughs and
a bearish signal. Results are cached in trader/cache/breadth.json (current
working folder, or TRADER_DIR) so repeat runs are fast.

This file is copied into each skill that needs it. Do not import across skills.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

CACHE_VERSION = 2
MIN_PRICE = 50.0
MIN_AVG_VOLUME = 100_000
UPTREND_MIN_BARS = 252  # needs a 52-week window

# NSE industry (from the index CSV) -> the 11 sector names the scoring code uses.
INDUSTRY_TO_SECTOR = {
    "information technology": "Technology",
    "automobile and auto components": "Consumer Cyclical",
    "consumer durables": "Consumer Cyclical",
    "consumer services": "Consumer Cyclical",
    "textiles": "Consumer Cyclical",
    "telecommunication": "Communication Services",
    "media entertainment & publication": "Communication Services",
    "financial services": "Financial",
    "capital goods": "Industrials",
    "construction": "Industrials",
    "services": "Industrials",
    "diversified": "Industrials",
    "power": "Utilities",
    "fast moving consumer goods": "Consumer Defensive",
    "healthcare": "Healthcare",
    "realty": "Real Estate",
    "oil gas & consumable fuels": "Energy",
    "metals & mining": "Basic Materials",
    "chemicals": "Basic Materials",
    "construction materials": "Basic Materials",
    "forest materials": "Basic Materials",
}

SECTOR_TO_WORKSHEET = {
    "Basic Materials": "sec_basicmaterials",
    "Communication Services": "sec_communicationservices",
    "Consumer Cyclical": "sec_consumercyclical",
    "Consumer Defensive": "sec_consumerdefensive",
    "Energy": "sec_energy",
    "Financial": "sec_financial",
    "Healthcare": "sec_healthcare",
    "Industrials": "sec_industrials",
    "Real Estate": "sec_realestate",
    "Technology": "sec_technology",
    "Utilities": "sec_utilities",
}


def industry_to_sector(industry: str | None) -> str | None:
    return INDUSTRY_TO_SECTOR.get((industry or "").strip().lower())


# ---------------------------------------------------------------------------
# Small numeric helpers (replace numpy / scipy)
# ---------------------------------------------------------------------------


def ema(values: list[float], span: int) -> list[float]:
    """Exponential moving average, adjust=False (same as pandas ewm)."""
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def sma_series(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total / window
    return out


def find_peaks(x: list[float], distance: int = 1, prominence: float | None = None) -> list[int]:
    """Local maxima with minimum distance and prominence (like scipy.signal.find_peaks)."""
    n = len(x)
    cands = []
    i = 1
    while i < n - 1:
        if x[i - 1] < x[i]:
            j = i
            while j + 1 < n and x[j + 1] == x[i]:
                j += 1
            if j + 1 < n and x[j + 1] < x[i]:
                cands.append((i + j) // 2)
            i = j + 1
        else:
            i += 1
    if prominence is not None:
        kept = []
        for p in cands:
            left_min = x[p]
            k = p - 1
            while k >= 0 and x[k] <= x[p]:
                left_min = min(left_min, x[k])
                k -= 1
            right_min = x[p]
            k = p + 1
            while k < n and x[k] <= x[p]:
                right_min = min(right_min, x[k])
                k += 1
            if x[p] - max(left_min, right_min) >= prominence:
                kept.append(p)
        cands = kept
    if distance > 1 and cands:
        order = sorted(range(len(cands)), key=lambda k: x[cands[k]], reverse=True)
        keep = [True] * len(cands)
        for k in order:
            if not keep[k]:
                continue
            m = k - 1
            while m >= 0 and cands[k] - cands[m] < distance:
                keep[m] = False
                m -= 1
            m = k + 1
            while m < len(cands) and cands[m] - cands[k] < distance:
                keep[m] = False
                m += 1
        cands = [c for c, kp in zip(cands, keep) if kp]
    return cands


# ---------------------------------------------------------------------------
# Per-stock flags
# ---------------------------------------------------------------------------


def stock_flags(bars_newest_first: list[dict]) -> dict[str, tuple[bool, bool, bool | None]]:
    """Return {date: (above50, above200, uptrend)} for one stock.

    uptrend is None when the day does not pass the base filters or lacks a
    52-week window. above50 and above200 need 200 bars of history.
    """
    bars = [b for b in reversed(bars_newest_first) if b.get("close") is not None]
    closes = [float(b["close"]) for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]
    n = len(closes)
    if n < 200:
        return {}
    s20 = sma_series(closes, 20)
    s50 = sma_series(closes, 50)
    s200 = sma_series(closes, 200)
    v50 = sma_series(vols, 50)
    out: dict[str, tuple[bool, bool, bool | None]] = {}
    for i in range(199, n):
        c = closes[i]
        above50 = c > s50[i]
        above200 = c > s200[i]
        up: bool | None = None
        if i >= UPTREND_MIN_BARS - 1 and c >= MIN_PRICE and (v50[i] or 0) >= MIN_AVG_VOLUME:
            lo = min(closes[i - 251 : i + 1])
            up = bool(
                c > s20[i]
                and c > s200[i]
                and s50[i] > s200[i]
                and c > 1.3 * lo
                and c > closes[i - 20]
            )
        out[bars[i]["date"]] = (above50, above200, up)
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(
    histories: dict[str, list[dict]],
    sectors: dict[str, str | None],
    benchmark: list[dict] | None,
) -> list[dict]:
    """Daily aggregate rows, oldest first."""
    days: dict[str, dict] = {}
    for sym, bars in histories.items():
        sector = sectors.get(sym)
        for d, (a50, a200, up) in stock_flags(bars).items():
            r = days.setdefault(
                d, {"date": d, "n": 0, "a50": 0, "a200": 0, "up_n": 0, "up": 0, "sec": {}}
            )
            r["n"] += 1
            r["a50"] += int(a50)
            r["a200"] += int(a200)
            if up is not None:
                r["up_n"] += 1
                r["up"] += int(up)
                if sector:
                    s = r["sec"].setdefault(sector, [0, 0])
                    s[0] += int(up)
                    s[1] += 1
    bench = {b["date"]: float(b["close"]) for b in (benchmark or []) if b.get("close") is not None}
    rows = []
    last_price = None
    for d in sorted(days):
        r = days[d]
        if r["n"] < 5:
            continue
        price = bench.get(d, last_price)
        if price is None:
            continue
        last_price = price
        r["price"] = price
        rows.append(r)
    return rows


# ---------------------------------------------------------------------------
# Derived columns (match the detail-row schema the scoring code expects)
# ---------------------------------------------------------------------------


def build_detail_rows(agg: list[dict]) -> list[dict]:
    """Detail rows: Date, Nifty50_Price, Breadth_Index_Raw/8MA/200MA, trend and flags."""
    if not agg:
        return []
    raw = [r["a200"] / r["n"] for r in agg]
    ma8 = ema(raw, 8)
    ma200 = ema(raw, 200)
    trend = []
    cur = 1
    for i, v in enumerate(ma200):
        if i > 0:
            diff = v - ma200[i - 1]
            if diff > 0.001:
                cur = 1
            elif diff < -0.001:
                cur = -1
        trend.append(cur)
    peaks = set(find_peaks(ma200, distance=50, prominence=0.015))
    troughs = set(find_peaks([-v for v in ma200], distance=50, prominence=0.015))
    ext = {
        i
        for i in find_peaks([-v for v in ma8], prominence=0.02)
        if ma8[i] < 0.4
    }
    # Bearish signal: the 8MA crossed below the 200MA within the last 10 sessions
    # and is still below it while the 200MA trend is falling.
    cross_idx = None
    bearish = []
    for i in range(len(raw)):
        if i > 0 and ma8[i - 1] >= ma200[i - 1] and ma8[i] < ma200[i]:
            cross_idx = i
        if ma8[i] >= ma200[i]:
            cross_idx = None
        bearish.append(cross_idx is not None and i - cross_idx <= 10 and trend[i] == -1)
    rows = []
    for i, r in enumerate(agg):
        rows.append(
            {
                "Date": r["date"],
                "Nifty50_Price": r["price"],
                "Breadth_Index_Raw": raw[i],
                "Breadth_Index_200MA": ma200[i],
                "Breadth_Index_8MA": ma8[i],
                "Breadth_200MA_Trend": trend[i],
                "Bearish_Signal": bearish[i],
                "Is_Peak": i in peaks,
                "Is_Trough": i in troughs,
                "Is_Trough_8MA_Below_04": i in ext,
            }
        )
    return rows


def build_summary(detail: list[dict]) -> dict[str, str]:
    peaks = [r["Breadth_Index_200MA"] for r in detail if r["Is_Peak"]]
    troughs = [r["Breadth_Index_8MA"] for r in detail if r["Is_Trough_8MA_Below_04"]]
    out = {
        "Average Peaks (200MA)": f"{sum(peaks) / len(peaks):.4f}" if peaks else "",
        "Average Troughs (8MA < 0.4)": f"{sum(troughs) / len(troughs):.4f}" if troughs else "",
        "Peak Count": str(len(peaks)),
        "Trough Count": str(len([r for r in detail if r["Is_Trough"]])),
    }
    if detail:
        out["Analysis Period"] = f"{detail[0]['Date']} to {detail[-1]['Date']}"
    return {k: v for k, v in out.items() if v != ""}


def build_timeseries(agg: list[dict]) -> list[dict]:
    """Uptrend-ratio rows: worksheet, date, count, total, ratio, ma_10, slope, trend."""
    series: dict[str, list[tuple[str, int, int]]] = {"all": []}
    for r in agg:
        if r["up_n"] > 0:
            series["all"].append((r["date"], r["up"], r["up_n"]))
        for sector, (cnt, tot) in r["sec"].items():
            ws = SECTOR_TO_WORKSHEET.get(sector)
            if ws and tot > 0:
                series.setdefault(ws, []).append((r["date"], cnt, tot))
    out = []
    for ws, pts in series.items():
        ratios = [c / t for _, c, t in pts]
        ma10 = sma_series(ratios, 10)
        prev = None
        for (d, c, t), ratio, m in zip(pts, ratios, ma10):
            slope = (m - prev) if (m is not None and prev is not None) else None
            if m is not None:
                prev = m
            out.append(
                {
                    "worksheet": ws,
                    "date": d,
                    "count": c,
                    "total": t,
                    "ratio": ratio,
                    "ma_10": m,
                    "slope": slope,
                    "trend": "up" if (slope is not None and slope > 0) else "down",
                }
            )
    out.sort(key=lambda r: (r["worksheet"], r["date"]))
    return out


# ---------------------------------------------------------------------------
# Cache and entry point
# ---------------------------------------------------------------------------


def default_cache_path() -> str:
    base = os.environ.get("TRADER_DIR") or os.path.join(os.getcwd(), "trader")
    return os.path.join(base, "cache", "breadth.json")


def _load_cache(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
            return data
    except (OSError, ValueError):
        pass
    return {"version": CACHE_VERSION, "universes": {}}


def _save_cache(path: str, data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass


def latest_market_date(client) -> str | None:
    data = client.get_historical_prices("^NSEI", days=30)
    hist = (data or {}).get("historical") or []
    return hist[0]["date"] if hist else None


def get_breadth(
    client,
    universe: str = "nifty500",
    max_symbols: int | None = None,
    cache_path: str | None = None,
    refresh: bool = False,
    days: int = 1250,
    progress=None,
) -> dict:
    """Return {"agg", "detail", "summary", "timeseries", "meta"} for the universe.

    A cached result is reused when its last date equals the latest NSE session
    date (read from ^NSEI), so repeat runs make one network call.
    """
    cache_path = cache_path or default_cache_path()
    key = f"{universe}:{max_symbols or 'all'}"
    cache = _load_cache(cache_path)
    latest = latest_market_date(client)
    entry = cache["universes"].get(key)
    if entry and not refresh and latest and entry.get("last_date") == latest:
        agg = entry["agg"]
        meta = dict(entry["meta"], from_cache=True)
    else:
        symbols = list(client.get_universe(universe))
        if max_symbols:
            symbols = symbols[:max_symbols]
        profiles = client.get_company_profiles(symbols) or {}
        sectors = {s: industry_to_sector((profiles.get(s) or {}).get("industry")) for s in symbols}
        histories = {}
        for i, s in enumerate(symbols):
            d = client.get_historical_prices(s, days=days)
            if d and d.get("historical"):
                histories[s] = d["historical"]
            if progress and (i + 1) % 50 == 0:
                progress(f"  fetched {i + 1}/{len(symbols)} symbols")
        bench = (client.get_historical_prices("^NSEI", days=days) or {}).get("historical") or []
        agg = aggregate(histories, sectors, bench)
        meta = {
            "universe": universe,
            "symbols_requested": len(symbols),
            "symbols_with_data": len(histories),
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": False,
        }
        if agg:
            cache["universes"][key] = {"last_date": agg[-1]["date"], "agg": agg, "meta": meta}
            _save_cache(cache_path, cache)
    detail = build_detail_rows(agg)
    return {
        "agg": agg,
        "detail": detail,
        "summary": build_summary(detail),
        "timeseries": build_timeseries(agg),
        "meta": meta,
    }


def latest_snapshot(agg: list[dict]) -> dict:
    """Latest percent above 50DMA, 200DMA and in uptrend."""
    if not agg:
        return {}
    r = agg[-1]
    return {
        "date": r["date"],
        "stocks": r["n"],
        "pct_above_50dma": round(100.0 * r["a50"] / r["n"], 1),
        "pct_above_200dma": round(100.0 * r["a200"] / r["n"], 1),
        "pct_uptrend": round(100.0 * r["up"] / r["up_n"], 1) if r["up_n"] else None,
    }


if __name__ == "__main__":  # quick manual check
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from india_client import FMPClient

    res = get_breadth(FMPClient(), "nifty50", max_symbols=10, progress=print)
    print(latest_snapshot(res["agg"]), math.isfinite(1.0))
