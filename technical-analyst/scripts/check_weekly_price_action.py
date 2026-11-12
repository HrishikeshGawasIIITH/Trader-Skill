#!/usr/bin/env python3
"""Weekly price-action confirmation for an NSE stock or index.

Fetches daily bars with india_client (Yahoo chart data, no keys), resamples
to completed weeks and runs the pure checks in weekly_price_action.py:
weekly key reversal, failed extreme, failed breakout and a continuation veto.
You supply the crowd direction (CROWDED_LONG or CROWDED_SHORT).

Usage:
    python check_weekly_price_action.py --symbol RELIANCE --direction CROWDED_LONG
    python check_weekly_price_action.py --symbol ^NSEI --direction CROWDED_SHORT --as-of 2026-11-10

Fails closed to INSUFFICIENT_DATA (exit 0, report written) when the data is
missing or too short.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from weekly_price_action import (
    EXTREME_LOOKBACK_WEEKS_DEFAULT,
    MIN_WEEKS_DEFAULT,
    SIGNAL_RECENCY_WEEKS_DEFAULT,
    SWING_LOOKBACK_WEEKS_DEFAULT,
    build_sorted_daily_series,
    run_weekly_price_action,
)

SKILL_NAME = "technical-analyst"
SCHEMA_VERSION = "2.0"
WEEKS_FETCH_BUFFER = 10


def _make_client():
    from india_client import FMPClient

    return FMPClient()


def fetch_price_series(client, symbol: str, weeks_needed: int, as_of: str) -> dict[str, Any]:
    """Fetch daily bars through the client. Bars after as_of are dropped."""
    days = int(weeks_needed * 7 + 14)
    try:
        data = client.get_historical_prices(symbol, days=days)
    except Exception as exc:  # network errors must not crash the run
        return {"error": f"fetch_failed: {exc}", "daily_bars": []}
    rows = (data or {}).get("historical") or []
    bars = [b for b in build_sorted_daily_series(rows) if b["date"] <= as_of]
    if not bars:
        return {"error": "no_price_source", "daily_bars": []}
    return {"error": None, "daily_bars": bars}


def build_run_context(
    price_symbol,
    as_of,
    swing_lookback_weeks,
    extreme_lookback_weeks,
    signal_recency_weeks,
    min_weeks,
) -> dict[str, Any]:
    return {
        "price_symbol": price_symbol,
        "price_source": "yahoo",
        "as_of": as_of,
        "lookbacks": {"swing_weeks": swing_lookback_weeks, "extreme_weeks": extreme_lookback_weeks},
        "recency": {"signal_recency_weeks": signal_recency_weeks},
        "min_weeks": min_weeks,
        "schema_version": SCHEMA_VERSION,
    }


# --- Report assembly -----------------------------------------------------


def generate_json_report(output: dict[str, Any], output_path: str) -> None:
    Path(output_path).write_text(json.dumps(output, indent=2, sort_keys=False), encoding="utf-8")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def generate_markdown_report(output: dict[str, Any], output_path: str) -> None:
    run_context = output.get("run_context", {})
    checks = output.get("checks") or {}
    swing_levels = output.get("swing_levels") or {}

    lines = [
        "# Weekly Price-Action Confirmation Report",
        "",
        f"Symbol: {output.get('symbol')}",
        f"Direction: `{output.get('direction')}`  (mode: {output.get('mode')})",
        f"As-of date: {run_context.get('as_of')}",
        f"Price source: `{run_context.get('price_symbol')}` ({run_context.get('price_source')})",
        "",
        "## Verdict",
        "",
        f"**{output.get('verdict')}** (confidence: {output.get('confidence')})",
        f"Reason: `{output.get('verdict_reason')}`",
        f"Weekly bars used: {output.get('weekly_bars_used')}",
        f"Last completed week: {output.get('last_completed_week')}",
        "",
        "## Checks",
        "",
        "| Check | Triggered | Week of | Detail |",
        "|---|---|---|---|",
    ]
    for name in ("weekly_key_reversal", "failed_extreme", "failed_breakout"):
        c = checks.get(name) or {}
        lines.append(
            f"| {name} | {c.get('triggered')} | {c.get('week_of') or 'n/a'} | {c.get('detail', '')} |"
        )
    cont = checks.get("continuation") or {}
    lines.append(
        f"| continuation (new closing extreme with crowd) | {cont.get('new_closing_extreme_with_crowd')} "
        f"| {cont.get('week_of') or 'n/a'} | veto check |"
    )

    lines += ["", "## Swing Levels", ""]
    if swing_levels:
        nsh = swing_levels.get("nearest_swing_high") or {}
        nsl = swing_levels.get("nearest_swing_low") or {}
        lines += [
            f"- Nearest swing high: Rs {_fmt(nsh.get('price'))} (week of {nsh.get('week_of')}, "
            f"fallback={nsh.get('fallback')})",
            f"- Nearest swing low: Rs {_fmt(nsl.get('price'))} (week of {nsl.get('week_of')}, "
            f"fallback={nsl.get('fallback')})",
            f"- Stop reference: Rs {_fmt(swing_levels.get('stop_reference'))}",
        ]
    else:
        lines.append("Not computed (insufficient data).")

    lines += [
        "",
        "## Methodology",
        "",
        "The verdict combines three weekly price-action checks (weekly key "
        "reversal, failed extreme, failed breakout) and a continuation veto. See "
        "`references/contrarian-confirmation-checklist.md` for the definitions. "
        "This is analysis, not financial advice. Orders go only through "
        "trader-risk and trader-broker.",
        "",
    ]

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


# --- CLI -----------------------------------------------------------------


def _min_weeks_type(value: str) -> int:
    try:
        ivalue = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--min-weeks must be an integer, got {value!r}") from exc
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"--min-weeks must be >= 1, got {ivalue}")
    return ivalue


def parse_arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Weekly price-action confirmation for an NSE stock or index"
    )
    parser.add_argument("--symbol", required=True, help="NSE symbol (RELIANCE) or index (^NSEI)")
    parser.add_argument("--direction", required=True, choices=["CROWDED_LONG", "CROWDED_SHORT"])
    parser.add_argument("--as-of", default=date.today().strftime("%Y-%m-%d"))
    parser.add_argument("--swing-lookback-weeks", type=int, default=SWING_LOOKBACK_WEEKS_DEFAULT)
    parser.add_argument(
        "--extreme-lookback-weeks", type=int, default=EXTREME_LOOKBACK_WEEKS_DEFAULT
    )
    parser.add_argument("--signal-recency-weeks", type=int, default=SIGNAL_RECENCY_WEEKS_DEFAULT)
    parser.add_argument("--min-weeks", type=_min_weeks_type, default=MIN_WEEKS_DEFAULT)
    parser.add_argument("--output-dir", default="reports/")
    parser.add_argument("--format", choices=["json", "md", "both"], default="both")
    return parser.parse_args(argv)


def _insufficient_data_output(symbol, direction, reason, run_context) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": direction,
        "mode": "data",
        "verdict": "INSUFFICIENT_DATA",
        "confidence": "MEDIUM",
        "verdict_reason": reason,
        "checks": None,
        "swing_levels": None,
        "weekly_bars_used": 0,
        "last_completed_week": None,
        "handoff": {
            "price_action": {
                "verdict": "INSUFFICIENT_DATA",
                "confidence": "MEDIUM",
                "stop_reference": None,
                "report_path": None,
            }
        },
        "run_context": run_context,
    }


def run(args, client=None) -> dict[str, Any]:
    symbol = args.symbol if args.symbol.startswith("^") else args.symbol.upper()
    os.makedirs(args.output_dir, exist_ok=True)
    safe = symbol.replace("^", "").replace("&", "_")
    json_path = os.path.join(args.output_dir, f"ta_confirmation_{safe}_{args.as_of}.json")
    md_path = os.path.join(args.output_dir, f"ta_confirmation_{safe}_{args.as_of}.md")
    ctx = build_run_context(
        symbol,
        args.as_of,
        args.swing_lookback_weeks,
        args.extreme_lookback_weeks,
        args.signal_recency_weeks,
        args.min_weeks,
    )
    weeks_needed = (
        max(args.extreme_lookback_weeks, args.min_weeks)
        + args.signal_recency_weeks
        + WEEKS_FETCH_BUFFER
    )
    client = client or _make_client()
    price = fetch_price_series(client, symbol, weeks_needed, args.as_of)
    if price["error"]:
        output = _insufficient_data_output(symbol, args.direction, "no_price_source", ctx)
    else:
        result = run_weekly_price_action(
            price["daily_bars"],
            args.direction,
            args.as_of,
            swing_lookback_weeks=args.swing_lookback_weeks,
            extreme_lookback_weeks=args.extreme_lookback_weeks,
            signal_recency_weeks=args.signal_recency_weeks,
            min_weeks=args.min_weeks,
        )
        stop = result["swing_levels"]["stop_reference"] if result["swing_levels"] else None
        output = {
            "symbol": symbol,
            "direction": args.direction,
            "mode": "data",
            "verdict": result["verdict"],
            "confidence": result["confidence"],
            "verdict_reason": result["verdict_reason"],
            "checks": result["checks"],
            "swing_levels": result["swing_levels"],
            "weekly_bars_used": result["weekly_bars_used"],
            "last_completed_week": result["last_completed_week"],
            "handoff": {
                "price_action": {
                    "verdict": result["verdict"],
                    "confidence": result["confidence"],
                    "stop_reference": stop,
                    "report_path": None,
                }
            },
            "run_context": ctx,
        }
    output["handoff"]["price_action"]["report_path"] = json_path
    if args.format in ("json", "both"):
        generate_json_report(output, json_path)
    if args.format in ("md", "both"):
        generate_markdown_report(output, md_path)
    return output


def main() -> None:
    args = parse_arguments()
    output = run(args)
    print(
        f"{output['symbol']}: {output['verdict']} "
        f"(confidence: {output['confidence']}, reason: {output['verdict_reason']})"
    )
    print(f"Report saved to {args.output_dir}")


if __name__ == "__main__":
    main()
