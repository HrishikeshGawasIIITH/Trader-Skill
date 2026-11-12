"""
FTD Detector - Main Orchestrator

Detects Follow-Through Day (FTD) signals for market bottom confirmation
using William O'Neil's methodology with dual-index tracking:
Nifty 50 (^NSEI) and an equal-weight Nifty Midcap 150 composite.
Data comes from india_client (Yahoo, NSE index lists). No API key.

Usage:
    python3 ftd_detector.py
    python3 ftd_detector.py --max-symbols 20 --output-dir reports/

Output:
    - JSON: ftd_detector_YYYY-MM-DD_HHMMSS.json
    - Markdown: ftd_detector_YYYY-MM-DD_HHMMSS.md
"""

import argparse
import os
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from index_data import build_midcap_composite, drop_incomplete_bar
from post_ftd_monitor import assess_post_ftd_health
from rally_tracker import get_market_state
from report_generator import generate_json_report, generate_markdown_report


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="FTD Detector - Follow-Through Day Bottom Confirmation (NSE)"
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory for reports (default: current directory)",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Use only the first N Midcap 150 constituents for the composite",
    )
    return parser.parse_args(argv)


def main(argv=None, client=None):
    args = parse_arguments(argv)

    print("=" * 70)
    print("FTD Detector - Follow-Through Day Bottom Confirmation")
    print("O'Neil Rally Attempt + FTD State Machine (Nifty 50 + Midcap 150)")
    print("=" * 70)
    print()

    if client is None:
        from india_client import FMPClient

        client = FMPClient(quiet=True)
    print("india_client ready (Yahoo prices, NSE index lists)")

    # ========================================================================
    # Step 1: Fetch Market Data
    # ========================================================================
    print()
    print("Step 1: Fetching Market Data")
    print("-" * 70)

    # Nifty 50 history (60 trading days)
    print("  Fetching Nifty 50 (^NSEI) history...", end=" ", flush=True)
    nifty50_history_data = client.get_historical_prices("^NSEI", days=80)
    nifty50_history = drop_incomplete_bar(
        nifty50_history_data.get("historical", []) if nifty50_history_data else []
    )
    if nifty50_history:
        print(f"OK ({len(nifty50_history)} days)")
    else:
        print("FAILED")
        print("ERROR: Cannot proceed without Nifty 50 data", file=sys.stderr)
        sys.exit(1)

    # Midcap 150 composite (60 trading days)
    print("  Building Midcap 150 composite...", end=" ", flush=True)
    try:
        midcap_history = build_midcap_composite(
            client,
            days=80,
            max_symbols=args.max_symbols,
            reference=nifty50_history,
        )
    except Exception as exc:  # network problems must not stop the Nifty 50 analysis
        print(f"error: {exc}", file=sys.stderr)
        midcap_history = []
    if midcap_history:
        print(f"OK ({len(midcap_history)} days)")
    else:
        print("WARN - Midcap 150 data unavailable, using Nifty 50 only")

    # Nifty 50 quote (for current price)
    print("  Fetching Nifty 50 quote...", end=" ", flush=True)
    nifty50_quote_list = client.get_quote("^NSEI")
    nifty50_quote = nifty50_quote_list[0] if nifty50_quote_list else None
    if nifty50_quote and nifty50_quote.get("price"):
        print(f"OK (Rs {nifty50_quote.get('price', 0):.2f})")
    else:
        nifty50_quote = None
        print("WARN - Using historical close as current price")
    midcap_quote = None

    print()

    # ========================================================================
    # Step 2: Run State Machine (Rally Tracker)
    # ========================================================================
    print("Step 2: Analyzing Market State")
    print("-" * 70)

    market_state = get_market_state(nifty50_history, midcap_history)

    nifty50_state = market_state["nifty50"]["state"]
    midcap_state = market_state["midcap"]["state"]
    combined = market_state["combined_state"]

    print(f"  Nifty 50 State: {nifty50_state}")
    print(f"  Midcap 150 State:  {midcap_state}")
    print(f"  Combined:      {combined}")

    # Print swing low info if found
    for label, idx_data in [("Nifty 50", market_state["nifty50"]), ("Midcap 150", market_state["midcap"])]:
        swing = idx_data.get("swing_low")
        if swing:
            print(
                f"  {label} Swing Low: {swing['swing_low_date']} "
                f"(Rs {swing['swing_low_price']:.2f}, "
                f"{swing['decline_pct']:.1f}% decline)"
            )
        rally = idx_data.get("rally_attempt")
        if rally and rally.get("day1_date"):
            print(f"  {label} Rally Day 1: {rally['day1_date']} (Day {rally['current_day_count']})")

    print()

    # ========================================================================
    # Step 3: Post-FTD Health Assessment
    # ========================================================================
    print("Step 3: Post-FTD Health Assessment")
    print("-" * 70)

    # Convert to chronological for post-FTD analysis
    nifty50_chrono = list(reversed(nifty50_history))
    midcap_chrono = list(reversed(midcap_history)) if midcap_history else []

    market_state = assess_post_ftd_health(market_state, nifty50_chrono, midcap_chrono)

    quality = market_state.get("quality_score", {})
    print(f"  Quality Score: {quality.get('total_score', 0)}/100")
    print(f"  Signal: {quality.get('signal', 'N/A')}")
    print(f"  Guidance: {quality.get('guidance', 'N/A')}")
    print(f"  Exposure Range: {quality.get('exposure_range', 'N/A')}")

    # Power trend
    pt = market_state.get("power_trend", {})
    if pt:
        print(
            f"  Power Trend: {'YES' if pt.get('power_trend') else 'No'} "
            f"({pt.get('conditions_met', 0)}/3 conditions)"
        )

    # Post-FTD distribution
    dist = market_state.get("post_ftd_distribution", {})
    if dist:
        print(
            f"  Post-FTD Distribution Days: {dist.get('distribution_count', 0)} "
            f"(monitored {dist.get('days_monitored', 0)} days)"
        )

    # Invalidation
    inv = market_state.get("ftd_invalidation", {})
    if inv and inv.get("invalidated"):
        print(
            f"  FTD INVALIDATED on {inv.get('invalidation_date')} "
            f"({inv.get('days_after_ftd')} days after FTD)"
        )

    print()

    # ========================================================================
    # Step 4: Generate Reports
    # ========================================================================
    print("Step 4: Generating Reports")
    print("-" * 70)

    analysis = {
        "metadata": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "api_calls": client.get_api_stats(),
            "data_source": "india_client (Yahoo prices, NSE index lists)",
            "index_prices": {
                "nifty50": nifty50_quote.get("price", 0)
                if nifty50_quote
                else (nifty50_history[0].get("close", 0) if nifty50_history else None),
                "midcap": midcap_quote.get("price", 0)
                if midcap_quote
                else (midcap_history[0].get("close", 0) if midcap_history else None),
            },
        },
        "market_state": {
            "combined_state": market_state["combined_state"],
            "dual_confirmation": market_state["dual_confirmation"],
            "ftd_index": market_state.get("ftd_index"),
        },
        "nifty50": _serialize_index(market_state["nifty50"]),
        "midcap": _serialize_index(market_state["midcap"]),
        "quality_score": quality,
        "post_ftd_distribution": market_state.get("post_ftd_distribution", {}),
        "ftd_invalidation": market_state.get("ftd_invalidation", {}),
        "power_trend": market_state.get("power_trend", {}),
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_file = os.path.join(args.output_dir, f"ftd_detector_{timestamp}.json")
    md_file = os.path.join(args.output_dir, f"ftd_detector_{timestamp}.md")

    generate_json_report(analysis, json_file)
    generate_markdown_report(analysis, md_file)

    print()
    print("=" * 70)
    print("FTD Detection Complete")
    print("=" * 70)
    print(f"  Combined State: {market_state['combined_state']}")
    print(f"  Quality Score: {quality.get('total_score', 0)}/100 ({quality.get('signal', 'N/A')})")
    print(f"  JSON Report: {json_file}")
    print(f"  Markdown Report: {md_file}")
    print()

    stats = client.get_api_stats()
    print("Data calls:")
    print(f"  Network calls made: {stats.get('api_calls_made')}")
    print()


def _serialize_index(idx_data: dict) -> dict:
    """Serialize index analysis for JSON output, removing large rally_days lists."""
    result = {
        "state": idx_data.get("state"),
        "current_price": idx_data.get("current_price"),
        "lookback_high": idx_data.get("lookback_high"),
        "correction_depth_pct": idx_data.get("correction_depth_pct"),
    }

    swing = idx_data.get("swing_low")
    if swing:
        result["swing_low"] = {
            "date": swing.get("swing_low_date"),
            "price": swing.get("swing_low_price"),
            "decline_pct": swing.get("decline_pct"),
            "down_days": swing.get("down_days"),
            "recent_high_date": swing.get("recent_high_date"),
            "recent_high_price": swing.get("recent_high_price"),
        }

    rally = idx_data.get("rally_attempt")
    if rally:
        result["rally_attempt"] = {
            "day1_date": rally.get("day1_date"),
            "current_day_count": rally.get("current_day_count"),
            "invalidated": rally.get("invalidated"),
            "invalidation_reason": rally.get("invalidation_reason"),
        }

    ftd = idx_data.get("ftd")
    if ftd:
        result["ftd"] = {
            "ftd_detected": ftd.get("ftd_detected"),
            "ftd_date": ftd.get("ftd_date"),
            "ftd_day_number": ftd.get("ftd_day_number"),
            "ftd_low": ftd.get("ftd_low"),
            "gain_pct": ftd.get("gain_pct"),
            "gain_tier": ftd.get("gain_tier"),
            "volume_above_avg": ftd.get("volume_above_avg"),
        }

    return result


if __name__ == "__main__":
    main()
