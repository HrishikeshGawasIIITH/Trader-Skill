#!/usr/bin/env python3
"""Index data helpers for NSE (stdlib only).

- drop_incomplete_bar: Yahoo often returns today's bar with volume 0 before the
  data is final. Such a bar would break volume rules, so it is dropped.
- build_midcap_composite: an equal-weight Nifty Midcap 150 composite built from
  the constituents' prices (price relatives) with summed volume. NSE index
  series on Yahoo carry no volume for the midcap index, so this stands in.

All histories are newest first (same order as india_client).
"""

from __future__ import annotations


def drop_incomplete_bar(history: list[dict]) -> list[dict]:
    """Drop a newest bar with zero volume when the previous bar has volume."""
    if len(history) > 1 and not history[0].get("volume") and history[1].get("volume"):
        return history[1:]
    return history


def build_midcap_composite(
    client,
    days: int = 80,
    universe: str = "midcap150",
    max_symbols: int | None = None,
    reference: list[dict] | None = None,
    progress=None,
) -> list[dict]:
    """Equal-weight composite of the universe, newest first, base 1000.

    Stocks need bars on at least 90% of the window dates; gaps are filled from the previous bar.
    `reference` (newest first) sets the dates; default is the ^NSEI history.
    """
    if reference is None:
        data = client.get_historical_prices("^NSEI", days=days)
        reference = drop_incomplete_bar((data or {}).get("historical") or [])
    dates = [b["date"] for b in reference[:days]]
    if not dates:
        return []
    wanted = set(dates)
    symbols = list(client.get_universe(universe))
    if max_symbols:
        symbols = symbols[:max_symbols]
    per_stock = []
    for i, sym in enumerate(symbols):
        data = client.get_historical_prices(sym, days=max(days + 5, 120))
        raw = {b["date"]: b for b in ((data or {}).get("historical") or [])}
        bars = {d: raw[d] for d in dates if d in raw}
        if len(bars) >= 0.9 * len(dates):
            # fill a missing date from the previous available bar (volume 0)
            prev = None
            for d in reversed(dates):  # oldest first
                if d in bars:
                    prev = bars[d]
                elif prev is not None:
                    bars[d] = dict(prev, volume=0)
            if all(d in bars for d in dates):
                per_stock.append(bars)
        if progress and (i + 1) % 50 == 0:
            progress(f"  composite: {i + 1}/{len(symbols)} symbols")
    if not per_stock:
        return []
    first = dates[-1]
    out = []
    for d in dates:
        row = {"date": d, "volume": 0}
        for field in ("open", "high", "low", "close"):
            vals = []
            for bars in per_stock:
                ref = bars[first]["close"]
                if ref:
                    vals.append(bars[d][field] / ref)
            row[field] = 1000.0 * sum(vals) / len(vals) if vals else None
        row["volume"] = sum(int(bars[d].get("volume") or 0) for bars in per_stock)
        row["adjClose"] = row["close"]
        out.append(row)
    return out
