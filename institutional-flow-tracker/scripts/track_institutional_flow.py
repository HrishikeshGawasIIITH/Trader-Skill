#!/usr/bin/env python3
"""Institutional flow tracker for India (FII/DII flows and NSE bulk/block deals).

Usage:
    python3 track_institutional_flow.py flows
    python3 track_institutional_flow.py deals --min-value-cr 5 --top 10
    python3 track_institutional_flow.py stock RELIANCE
    python3 track_institutional_flow.py flows --json --output-dir reports/

No API keys. Data comes from NSE public endpoints (see nse_flows.py).
This is analysis, not financial advice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nse_flows as nf


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------


def gather_flows(session, history_path: str, save: bool = True) -> dict:
    """Fetch today's FII/DII row, append to the history file, summarize."""
    day = nf.parse_fii_dii(session.get_json(nf.FII_DII_URL))
    history = nf.load_history(history_path)
    updated = nf.append_day(history, day)
    if save and day:
        nf.save_history(history_path, updated)
    summary = nf.summarize_flows(updated)
    summary["fetched_today"] = day is not None
    return summary


def gather_deals(session) -> list[dict]:
    bulk = nf.parse_deals(session.get_text(nf.BULK_URL), "bulk")
    block = nf.parse_deals(session.get_text(nf.BLOCK_URL), "block")
    return bulk + block


def price_context(client, symbol: str) -> dict | None:
    """1-week, 1-month return and position vs the 50-day average."""
    try:
        data = client.get_historical_prices(symbol, days=120)
    except Exception:
        return None
    closes = [b["close"] for b in ((data or {}).get("historical") or []) if b.get("close")]
    if len(closes) < 22:
        return None
    sma50 = sum(closes[:50]) / 50 if len(closes) >= 50 else None
    return {
        "last": round(closes[0], 2),
        "ret_1w_pct": round((closes[0] / closes[5] - 1) * 100, 2),
        "ret_1m_pct": round((closes[0] / closes[21] - 1) * 100, 2),
        "above_50dma": (closes[0] > sma50) if sma50 else None,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _cr(v) -> str:
    return f"Rs {v:,.0f} cr"


def format_flows(s: dict) -> str:
    lines = ["# FII / DII Flows (NSE cash market)", ""]
    latest = s.get("latest")
    if not latest:
        return "\n".join(lines + ["No flow data available."])
    if not s.get("fetched_today"):
        lines += ["> WARNING: today's NSE flow data could not be fetched. Showing saved history.", ""]
    lines += [
        f"Latest session: {latest['date']}",
        f"- FII/FPI: buy {_cr(latest['fii']['buy'])}, sell {_cr(latest['fii']['sell'])}, net {_cr(latest['fii']['net'])}",
        f"- DII: buy {_cr(latest['dii']['buy'])}, sell {_cr(latest['dii']['sell'])}, net {_cr(latest['dii']['net'])}",
        "",
        "| Window | Sessions | FII net | DII net |",
        "|--------|----------|---------|---------|",
    ]
    for n, w in s["windows"].items():
        lines.append(f"| {n} days | {w['sessions']} | {_cr(w['fii_net'])} | {_cr(w['dii_net'])} |")
    lines += ["", f"Regime (last 5 sessions): **{s['regime']}**", ""]
    if s["sessions"] < 20:
        lines.append(
            f"Note: only {s['sessions']} sessions are saved. Windows fill as you run this daily."
        )
    return "\n".join(lines)


def _deal_table(title, rows) -> list[str]:
    if not rows:
        return [f"## {title}", "", "None.", ""]
    out = [f"## {title}", "", "| Symbol | Buy | Sell | Net | Deals | Institutional clients |", "|---|---|---|---|---|---|"]
    for r in rows:
        clients = ", ".join(r["institutional_clients"][:2]) or "-"
        out.append(
            f"| {r['symbol']} | {_cr(r['buy_cr'])} | {_cr(r['sell_cr'])} | {_cr(r['net_cr'])} | {r['deals']} | {clients} |"
        )
    return out + [""]


def format_deals(s: dict, total: int) -> str:
    lines = ["# NSE Bulk and Block Deals", "", f"Deals read: {total}. Symbols after filter: {s['symbols']}.", ""]
    lines += _deal_table("Top net accumulation", s["accumulation"])
    lines += _deal_table("Top net distribution", s["distribution"])
    lines.append("Client type is a name-based guess. Bulk deals are reported for the latest session only.")
    return "\n".join(lines)


def format_stock(symbol: str, deals: list[dict], ctx: dict | None, flows: dict | None) -> str:
    lines = [f"# Institutional activity: {symbol}", ""]
    mine = [d for d in deals if d["symbol"].upper() == symbol.upper()]
    if mine:
        lines += ["| Kind | Date | Client | Type | Side | Quantity | Price | Value |", "|---|---|---|---|---|---|---|---|"]
        for d in mine:
            lines.append(
                f"| {d['kind']} | {d['date']} | {d['client']} | {d['client_type']} | {d['side']} | "
                f"{d['quantity']:,.0f} | Rs {d['price']:,.2f} | {_cr(d['value'] / nf.CRORE)} |"
            )
        net = sum(d["value"] if d["side"] == "BUY" else -d["value"] for d in mine) / nf.CRORE
        lines += ["", f"Net deal value: {_cr(net)} ({'accumulation' if net > 0 else 'distribution' if net < 0 else 'flat'})"]
    else:
        lines.append("No bulk or block deals for this symbol in the latest files.")
    if ctx:
        above = {True: "above", False: "below", None: "n/a vs"}[ctx["above_50dma"]]
        lines += [
            "",
            f"Price: Rs {ctx['last']:,.2f}, 1 week {ctx['ret_1w_pct']:+.1f}%, 1 month {ctx['ret_1m_pct']:+.1f}%, {above} 50-day average.",
        ]
    if flows and flows.get("latest"):
        lines += ["", f"Market flow regime (5 sessions): {flows['regime']}."]
    lines += ["", "A deal shows one session of trading. It is not proof of long-term holding."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_arguments(argv=None):
    p = argparse.ArgumentParser(description="FII/DII flows and NSE bulk/block deals")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--output-dir", default=None, help="Also save the output here")
    p.add_argument("--history", default=None, help="FII/DII history file (default trader/cache/fii_dii.json)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("flows", help="FII/DII daily flows and rolling totals")
    d = sub.add_parser("deals", help="Bulk and block deals ranked by net value")
    d.add_argument("--min-value-cr", type=float, default=1.0)
    d.add_argument("--top", type=int, default=10)
    s = sub.add_parser("stock", help="Deals and price context for one symbol")
    s.add_argument("symbol")
    return p.parse_args(argv)


def run(args, session=None, client=None) -> str:
    session = session or nf.NseSession()
    history_path = args.history or nf.default_history_path()
    if args.command == "flows":
        summary = gather_flows(session, history_path)
        return json.dumps(summary, indent=2) if args.json else format_flows(summary)
    if args.command == "deals":
        deals = gather_deals(session)
        summary = nf.summarize_deals(deals, args.min_value_cr, args.top)
        summary["deals_read"] = len(deals)
        return json.dumps(summary, indent=2) if args.json else format_deals(summary, len(deals))
    # stock
    deals = gather_deals(session)
    if client is None:
        from india_client import FMPClient

        client = FMPClient(quiet=True)
    ctx = price_context(client, args.symbol)
    flows = gather_flows(session, history_path)
    if args.json:
        mine = [d for d in deals if d["symbol"].upper() == args.symbol.upper()]
        return json.dumps({"symbol": args.symbol, "deals": mine, "price": ctx, "flows_regime": flows["regime"]}, indent=2)
    return format_stock(args.symbol, deals, ctx, flows)


def main(argv=None):
    args = parse_arguments(argv)
    out = run(args)
    print(out)
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        ext = "json" if args.json else "md"
        path = os.path.join(args.output_dir, f"institutional_flow_{args.command}_{date.today().isoformat()}.{ext}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"Saved to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
