#!/usr/bin/env python3
"""
Market Top Detector - Main Orchestrator

Integrates O'Neil (Distribution Days), Minervini (Leading Stock Deterioration)
and Defensive Sector Rotation to assess heuristic market top risk for India.

Data (no API keys): Nifty 50 (^NSEI), an equal-weight Nifty Midcap 150 composite,
India VIX (^INDIAVIX), NSE sectoral indices and breadth computed from the
Nifty 500 (percent above 50DMA and 200DMA).

Usage:
    python3 market_top_detector.py
    python3 market_top_detector.py --put-call 0.9 --put-call-date 2026-11-10
    python3 market_top_detector.py --max-symbols 20   # quick test

Output:
    - JSON: market_top_YYYY-MM-DD_HHMMSS.json
    - Markdown: market_top_YYYY-MM-DD_HHMMSS.md
"""

import argparse
import glob
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import breadth_engine
from calculators.breadth_calculator import calculate_breadth_divergence
from calculators.defensive_rotation_calculator import (
    DEFENSIVE_ETFS,
    OFFENSIVE_ETFS,
    calculate_defensive_rotation,
)
from calculators.distribution_day_calculator import calculate_distribution_days
from calculators.index_technical_calculator import calculate_index_technical
from calculators.leading_stock_calculator import (
    LEADING_ETFS,
    calculate_leading_stock_health,
    select_dynamic_basket,
)
from calculators.sentiment_calculator import calculate_sentiment
from historical_comparator import compare_to_historical
from index_data import build_midcap_composite, drop_incomplete_bar
from report_generator import generate_json_report, generate_markdown_report
from scenario_engine import generate_scenarios
from scorer import calculate_composite_score, detect_follow_through_day

IST = timezone(timedelta(hours=5, minutes=30))


def _iso_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("must be zero-padded YYYY-MM-DD")
    return parsed


def parse_arguments(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        description="Market Top Detector - O'Neil/Minervini/Defensive Rotation (India)"
    )

    # Optional manual inputs (breadth is computed automatically)
    parser.add_argument(
        "--breadth-200dma",
        type=float,
        default=None,
        help="Percent of Nifty 500 stocks above 200DMA (e.g., 62.26)",
    )
    parser.add_argument(
        "--breadth-50dma",
        type=float,
        default=None,
        help="Percent of Nifty 500 stocks above 50DMA (e.g., 55.0)",
    )
    parser.add_argument(
        "--put-call", type=float, default=None, help="Nifty put/call ratio (PCR) (e.g., 0.67)"
    )
    parser.add_argument(
        "--vix-term",
        choices=["steep_contango", "contango", "flat", "backwardation"],
        default=None,
        help="India VIX term structure state",
    )
    parser.add_argument(
        "--margin-debt-yoy",
        type=float,
        default=None,
        help="Margin debt year-over-year change percent (e.g., 36.0)",
    )

    # Data freshness dates
    parser.add_argument(
        "--breadth-200dma-date", default=None, help="Date of breadth 200DMA data (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--breadth-50dma-date", default=None, help="Date of breadth 50DMA data (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--put-call-date", default=None, help="Date of put/call ratio data (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--margin-debt-date", default=None, help="Date of margin debt data (YYYY-MM-DD)"
    )

    # Additional context (not scored, but included in report)
    parser.add_argument(
        "--context",
        nargs="*",
        default=[],
        help="Additional context items in 'key=value' format (e.g., 'Consumer Confidence=57.3')",
    )

    # Breadth computation control
    parser.add_argument(
        "--no-auto-breadth",
        action="store_true",
        help="Skip computing breadth from prices (use --breadth-200dma / --breadth-50dma)",
    )
    parser.add_argument("--universe", default="nifty500", help="Breadth universe (default: nifty500)")
    parser.add_argument("--max-symbols", type=int, default=None, help="Use only the first N symbols")
    parser.add_argument("--cache", default=None, help="Breadth cache (default: trader/cache/breadth.json)")
    parser.add_argument("--refresh", action="store_true", help="Ignore the breadth cache")

    # Leading stock basket mode
    parser.add_argument(
        "--static-basket",
        action="store_true",
        help="Use the static NSE sector-index basket instead of Midcap 150 leaders",
    )

    # Output
    parser.add_argument("--output-dir", default="reports/", help="Output directory for reports")
    parser.add_argument(
        "--as-of",
        type=_iso_date,
        default=None,
        help=(
            "Evaluation date (YYYY-MM-DD). Historical live replay is rejected because "
            "the quote provider is not point-in-time."
        ),
    )

    return parser.parse_args(argv)


def compute_data_freshness(date_args: dict, as_of_date: Optional[date] = None) -> dict:
    """
    Compute data freshness factors for CLI input dates.

    Uses business days instead of calendar days so that Friday data
    remains fresh on Monday. Future dates are treated as anomalous input.

    Args:
        date_args: Dict with keys like 'breadth_200dma_date', 'breadth_50dma_date',
                   'put_call_date', 'margin_debt_date' -> YYYY-MM-DD strings.

    Returns:
        Dict with per-input freshness info and overall_confidence (min of all factors).
    """
    from datetime import date as dateclass

    from utils import count_business_days

    freshness_map = {
        "breadth_200dma_date": "breadth_200dma",
        "breadth_50dma_date": "breadth_50dma",
        "put_call_date": "put_call",
        "margin_debt_date": "margin_debt",
    }

    result = {}
    factors = []
    today = as_of_date or dateclass.today()

    for arg_key, label in freshness_map.items():
        date_str = date_args.get(arg_key)
        if not date_str:
            continue
        try:
            d = dateclass.fromisoformat(date_str)
        except (ValueError, TypeError):
            result[label] = {"date": date_str, "age_days": None, "factor": 0.70}
            factors.append(0.70)
            continue

        # Reject future dates as input anomaly
        if d > today:
            result[label] = {"date": date_str, "age_days": None, "factor": 0.70}
            factors.append(0.70)
            continue

        biz_days = count_business_days(d, today)

        if biz_days <= 1:
            factor = 1.0
        elif biz_days <= 3:
            factor = 0.95
        elif biz_days <= 7:
            factor = 0.85
        else:
            factor = 0.70

        result[label] = {"date": date_str, "age_days": biz_days, "factor": factor}
        factors.append(factor)

    result["overall_confidence"] = min(factors) if factors else 1.0
    return result


def _load_previous_report(output_dir: str) -> Optional[dict]:
    """
    Load the most recent market_top_*.json from output_dir.

    Files are named market_top_YYYY-MM-DD_HHMMSS.json, so lexicographic
    sorting gives chronological order.
    """
    pattern = os.path.join(output_dir, "market_top_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _compute_deltas(current_scores: dict[str, float], previous_report: Optional[dict]) -> dict:
    """
    Compute delta between current and previous component scores.

    Returns:
        Dict with per-component delta info and composite delta.
        If no previous report, direction is 'first_run' for all.
    """
    component_keys = [
        "distribution_days",
        "leading_stocks",
        "defensive_rotation",
        "breadth_divergence",
        "index_technical",
        "sentiment",
    ]
    deltas = {}

    if previous_report is None:
        for key in component_keys:
            deltas[key] = {"delta": 0, "direction": "first_run"}
        return {
            "components": deltas,
            "composite_delta": 0,
            "composite_direction": "first_run",
            "previous_date": None,
        }

    prev_components = previous_report.get("components", {})
    prev_composite = previous_report.get("composite", {}).get("composite_score", 0)

    for key in component_keys:
        prev_score = prev_components.get(key, {}).get("score", 0)
        curr_score = current_scores.get(key, 0)
        delta = curr_score - prev_score
        if abs(delta) <= 3:
            direction = "stable"
        elif delta > 0:
            direction = "worsening"
        else:
            direction = "improving"
        deltas[key] = {"delta": round(delta, 1), "direction": direction, "previous": prev_score}

    prev_date = previous_report.get("metadata", {}).get("generated_at", None)

    return {
        "components": deltas,
        "composite_delta": 0,  # Will be filled after composite calc
        "composite_direction": "first_run",
        "previous_date": prev_date,
        "previous_composite": prev_composite,
    }


def _history_on_or_before(rows: list[dict], as_of_date: date) -> list[dict]:
    """Reject future bars at the consumer boundary; preserve provider order."""
    filtered = []
    for row in rows:
        try:
            row_date = date.fromisoformat(str(row.get("date", ""))[:10])
        except (TypeError, ValueError):
            continue
        if row_date <= as_of_date:
            filtered.append(row)
    return filtered


def _batch_histories_on_or_before(
    histories: dict[str, list[dict]], as_of_date: date
) -> dict[str, list[dict]]:
    """Apply the PIT ceiling to every symbol and discard empty histories."""
    return {
        symbol: filtered
        for symbol, rows in histories.items()
        if (filtered := _history_on_or_before(rows, as_of_date))
    }


def _future_dated_scored_inputs(args: argparse.Namespace, as_of_date: date) -> list[str]:
    """Return scored CLI fields whose declared source date exceeds as-of."""
    pairs = (
        ("breadth_200dma", "breadth_200dma_date"),
        ("breadth_50dma", "breadth_50dma_date"),
        ("put_call", "put_call_date"),
        ("margin_debt_yoy", "margin_debt_date"),
    )
    future = []
    for value_name, date_name in pairs:
        if getattr(args, value_name, None) is None:
            continue
        raw_date = getattr(args, date_name, None)
        if not raw_date:
            continue
        try:
            source_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError):
            continue
        if source_date > as_of_date:
            future.append(value_name)
    return future


def compute_breadth_from_prices(client, args, as_of_date: date) -> Optional[dict]:
    """Percent of the universe above its 200DMA and 50DMA (cached by breadth_engine)."""
    try:
        res = breadth_engine.get_breadth(
            client,
            universe=args.universe,
            max_symbols=args.max_symbols,
            cache_path=args.cache,
            refresh=args.refresh,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    snap = breadth_engine.latest_snapshot(res["agg"])
    if not snap:
        return None
    days_old = (as_of_date - date.fromisoformat(snap["date"])).days
    return {
        "value": snap["pct_above_200dma"],
        "value_50": snap["pct_above_50dma"],
        "date": snap["date"],
        "days_old": days_old,
        "is_fresh": days_old <= 5,
    }


def main(argv: Optional[list[str]] = None, client=None):
    args = parse_arguments(argv)
    live_today = datetime.now(IST).date()
    as_of_date = args.as_of or live_today
    if args.as_of is not None and as_of_date != live_today:
        print(
            "ERROR: historical --as-of requires point-in-time quote data, which the live "
            "provider does not supply; refusing a look-ahead-biased replay",
            file=sys.stderr,
        )
        return 2
    future_inputs = _future_dated_scored_inputs(args, as_of_date)
    if future_inputs:
        print(
            "ERROR: refusing future-dated scored input(s): " + ", ".join(future_inputs),
            file=sys.stderr,
        )
        return 2

    print("=" * 70)
    print("Market Top Detector - India")
    print("O'Neil (Distribution) + Minervini (Leadership) + Defensive Rotation")
    print("=" * 70)
    print()

    if client is None:
        from india_client import FMPClient

        client = FMPClient(quiet=True)
    print("india_client ready (Yahoo prices, NSE index lists)")

    # ========================================================================
    # Step 1: Fetch shared data (indices, leaders, sector indices)
    # ========================================================================
    print()
    print("Step 1: Fetching Market Data")
    print("-" * 70)

    # Nifty 50 data
    print("  Fetching Nifty 50 (^NSEI) data...", end=" ", flush=True)
    nifty50_quote_list = client.get_quote("^NSEI")
    nifty50_quote = nifty50_quote_list[0] if nifty50_quote_list else None
    nifty50_history_data = client.get_historical_prices("^NSEI", days=260)
    nifty50_history = drop_incomplete_bar(
        _history_on_or_before(
            nifty50_history_data.get("historical", []) if nifty50_history_data else [],
            as_of_date,
        )
    )
    if nifty50_quote and nifty50_history:
        print(f"OK (Rs {nifty50_quote.get('price', 0):.2f}, {len(nifty50_history)} days)")
    else:
        print("FAILED")
        print("ERROR: Cannot proceed without Nifty 50 data", file=sys.stderr)
        sys.exit(1)

    # Midcap 150 composite (equal-weight, summed volume)
    print("  Building Midcap 150 composite...", end=" ", flush=True)
    try:
        midcap_history = build_midcap_composite(
            client,
            days=260,
            max_symbols=args.max_symbols,
            reference=nifty50_history,
        )
    except Exception as exc:  # keep the Nifty 50 analysis alive
        print(f"error: {exc}", file=sys.stderr)
        midcap_history = []
    midcap_quote = (
        {
            "price": midcap_history[0]["close"],
            "yearHigh": max(b["high"] for b in midcap_history[:252]),
        }
        if midcap_history
        else None
    )
    if midcap_history:
        print(f"OK ({len(midcap_history)} days)")
    else:
        print("WARN - Midcap 150 data unavailable, using Nifty 50 only")

    # India VIX
    print("  Fetching India VIX (^INDIAVIX)...", end=" ", flush=True)
    vix_quote_list = client.get_quote("^INDIAVIX")
    vix_quote = vix_quote_list[0] if vix_quote_list else None
    vix_level = vix_quote.get("price", None) if vix_quote else None
    if vix_level:
        print(f"OK ({vix_level:.2f})")
    else:
        print("WARN - India VIX unavailable")

    # Term structure has no free source for India: manual --vix-term only.
    effective_vix_term = args.vix_term
    vix_term_auto = None

    # Leaders (dynamic: Midcap 150 constituents near highs, or static sector indices)
    if args.static_basket:
        selected_basket = list(LEADING_ETFS)
        print("  Fetching leaders (static sector-index basket)...", end=" ", flush=True)
        leading_quotes = client.get_batch_quotes(selected_basket)
        leading_historical = client.get_batch_historical(selected_basket, days=60)
    else:
        print("  Fetching Midcap 150 constituent quotes for leaders...", end=" ", flush=True)
        pool = list(client.get_universe("midcap150"))
        if args.max_symbols:
            pool = pool[: args.max_symbols]
        candidate_quotes = client.get_batch_quotes(pool)
        print(f"OK ({len(candidate_quotes)} candidates)")
        selected_basket = select_dynamic_basket(candidate_quotes, pool=pool)
        if not selected_basket:
            selected_basket = list(LEADING_ETFS)
            candidate_quotes = client.get_batch_quotes(selected_basket)
        print(f"  Selected leaders: {selected_basket}")
        leading_quotes = {s: candidate_quotes[s] for s in selected_basket if s in candidate_quotes}
        leading_historical = client.get_batch_historical(selected_basket, days=60)
    leading_historical = _batch_histories_on_or_before(leading_historical, as_of_date)
    print(f"  Leaders: {len(leading_quotes)} quotes, {len(leading_historical)} histories")

    # Sector indices (defensive and offensive)
    sector_indices = list(dict.fromkeys(DEFENSIVE_ETFS + OFFENSIVE_ETFS))
    print("  Fetching NSE sector indices...", end=" ", flush=True)
    sector_historical = _batch_histories_on_or_before(
        client.get_batch_historical(sector_indices, days=50),
        as_of_date,
    )
    print(f"OK ({len(sector_historical)} indices)")

    print()

    # ========================================================================
    # Step 2: Calculate Components
    # ========================================================================
    print("Step 2: Calculating Components")
    print("-" * 70)

    # Component 1: Distribution Days (25%)
    print("  [1/6] Distribution Day Count...", end=" ", flush=True)
    comp1 = calculate_distribution_days(nifty50_history, midcap_history)
    print(f"Score: {comp1['score']} ({comp1['signal']})")

    # Component 2: Leading Stock Health (20%)
    print("  [2/6] Leading Stock Health...", end=" ", flush=True)
    comp2 = calculate_leading_stock_health(
        leading_quotes, leading_historical, etf_list=selected_basket
    )
    print(f"Score: {comp2['score']} ({comp2['signal']})")

    # Component 3: Defensive Rotation (15%)
    print("  [3/6] Defensive Sector Rotation...", end=" ", flush=True)
    comp3 = calculate_defensive_rotation(sector_historical)
    print(f"Score: {comp3['score']} ({comp3['signal']})")

    # Compute breadth from prices unless supplied on the command line
    effective_breadth_200dma = args.breadth_200dma
    effective_breadth_50dma = args.breadth_50dma
    breadth_source = "cli"
    breadth_auto_date = None

    if not args.no_auto_breadth and (
        effective_breadth_200dma is None or effective_breadth_50dma is None
    ):
        print("  Computing breadth from prices...", end=" ", flush=True)
        auto_result = compute_breadth_from_prices(client, args, as_of_date)
        if auto_result is not None:
            if effective_breadth_200dma is None:
                effective_breadth_200dma = auto_result["value"]
                breadth_source = "auto"
                breadth_auto_date = auto_result["date"]
            if effective_breadth_50dma is None:
                effective_breadth_50dma = auto_result["value_50"]
            fresh_str = (
                "fresh" if auto_result["is_fresh"] else f"STALE ({auto_result['days_old']}d old)"
            )
            print(
                f"OK ({auto_result['value']}% above 200DMA, {auto_result['value_50']}% above 50DMA, "
                f"{auto_result['date']}, {fresh_str})"
            )
            if not auto_result["is_fresh"]:
                print(f"  WARNING: Breadth data is {auto_result['days_old']} days old")
        else:
            print("FAILED (will use neutral default)")

    # Component 4: Breadth Divergence (15%)
    print("  [4/6] Market Breadth Divergence...", end=" ", flush=True)
    # Calculate index distance from 52-week high
    nifty50_year_high = nifty50_quote.get("yearHigh", 0)
    nifty50_price = nifty50_quote.get("price", 0)
    if nifty50_year_high > 0:
        index_dist = (nifty50_price - nifty50_year_high) / nifty50_year_high * 100
    else:
        index_dist = 0

    comp4 = calculate_breadth_divergence(
        breadth_200dma=effective_breadth_200dma,
        breadth_50dma=effective_breadth_50dma,
        index_distance_from_high_pct=index_dist,
    )
    comp4["breadth_source"] = breadth_source
    if breadth_auto_date:
        comp4["breadth_auto_date"] = breadth_auto_date
    print(f"Score: {comp4['score']} ({comp4['signal']})")

    # Component 5: Index Technical (15%)
    print("  [5/6] Index Technical Condition...", end=" ", flush=True)
    comp5 = calculate_index_technical(
        nifty50_history, midcap_history, nifty50_quote=nifty50_quote, midcap_quote=midcap_quote
    )
    print(f"Score: {comp5['score']} ({comp5['signal']})")

    # Component 6: Sentiment (10%)
    print("  [6/6] Sentiment & Speculation...", end=" ", flush=True)
    comp6 = calculate_sentiment(
        vix_level=vix_level,
        put_call_ratio=args.put_call,
        vix_term_structure=effective_vix_term,
        margin_debt_yoy_pct=args.margin_debt_yoy,
    )
    print(f"Score: {comp6['score']} ({comp6['signal']})")

    print()

    # Compute data freshness
    freshness_args = {
        "breadth_200dma_date": breadth_auto_date
        if breadth_source == "auto"
        else args.breadth_200dma_date,
        "breadth_50dma_date": args.breadth_50dma_date,
        "put_call_date": args.put_call_date,
        "margin_debt_date": args.margin_debt_date,
    }
    data_freshness = compute_data_freshness(freshness_args, as_of_date=as_of_date)

    # ========================================================================
    # Step 3: Composite Score
    # ========================================================================
    print("Step 3: Calculating Composite Score")
    print("-" * 70)

    component_scores = {
        "distribution_days": comp1["score"],
        "leading_stocks": comp2["score"],
        "defensive_rotation": comp3["score"],
        "breadth_divergence": comp4["score"],
        "index_technical": comp5["score"],
        "sentiment": comp6["score"],
    }

    data_availability = {
        "distribution_days": True,  # Always available (requires S&P data to run)
        "leading_stocks": comp2.get("data_available", True),
        "defensive_rotation": comp3.get("data_available", True),
        "breadth_divergence": comp4.get("data_available", True),
        "index_technical": comp5.get("data_available", True),
        "sentiment": comp6.get("data_available", True),
    }

    composite = calculate_composite_score(component_scores, data_availability)

    print(f"  Heuristic Risk Score: {composite['composite_score']}/100")
    print("  Risk score, not an estimated event probability; budgets are policy heuristics.")
    print(f"  Risk Zone: {composite['zone']}")
    print(f"  Risk Budget: {composite['risk_budget']}")
    print(
        f"  Strongest Warning: {composite['strongest_warning']['label']} "
        f"({composite['strongest_warning']['score']})"
    )

    # Delta tracking vs previous run
    previous_report = _load_previous_report(args.output_dir)
    delta_info = _compute_deltas(component_scores, previous_report)
    # Update composite delta now that we have the composite score
    if previous_report is not None:
        prev_composite = delta_info.get("previous_composite", 0)
        comp_delta = composite["composite_score"] - prev_composite
        delta_info["composite_delta"] = round(comp_delta, 1)
        if abs(comp_delta) <= 3:
            delta_info["composite_direction"] = "stable"
        elif comp_delta > 0:
            delta_info["composite_direction"] = "worsening"
        else:
            delta_info["composite_direction"] = "improving"
        print(
            f"  vs Previous: {prev_composite} -> {composite['composite_score']} "
            f"({delta_info['composite_delta']:+.1f})"
        )
    else:
        print("  (First run - no comparison available)")
    print()

    # ========================================================================
    # Step 4: Follow-Through Day Check
    # ========================================================================
    ftd = detect_follow_through_day(nifty50_history, composite["composite_score"])
    if ftd.get("applicable"):
        print("Step 4: Follow-Through Day Monitor")
        print("-" * 70)
        print(f"  {ftd['reason']}")
        print()

    # ========================================================================
    # Step 5: Historical Comparison & Scenarios
    # ========================================================================
    print("Step 5: Historical Comparison & Scenarios")
    print("-" * 70)

    historical_comparison = compare_to_historical(component_scores, data_availability)
    print(f"  Historical comparison: {historical_comparison['narrative']}")

    scenarios = generate_scenarios(component_scores, data_availability)
    print(f"  Generated {len(scenarios)} what-if scenarios")
    print()

    # ========================================================================
    # Step 6: Generate Reports
    # ========================================================================
    print("Step 6: Generating Reports")
    print("-" * 70)

    # Parse additional context
    additional_context = {}
    for item in args.context:
        if "=" in item:
            key, value = item.split("=", 1)
            additional_context[key.strip()] = value.strip()

    # Build full analysis
    analysis = {
        "metadata": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "as_of_date": as_of_date.isoformat(),
            "data_mode": "india_client (Yahoo + NSE) + CLI inputs",
            "api_calls": client.get_api_stats(),
            "cli_inputs": {
                "breadth_200dma": effective_breadth_200dma,
                "breadth_200dma_source": breadth_source,
                "breadth_200dma_auto_date": breadth_auto_date,
                "breadth_universe": args.universe,
                "breadth_50dma": effective_breadth_50dma,
                "put_call_ratio": args.put_call,
                "vix_term_structure": args.vix_term,
                "margin_debt_yoy_pct": args.margin_debt_yoy,
            },
            "vix_term_auto": vix_term_auto,
            "index_data": {
                "nifty50_price": nifty50_price,
                "nifty50_year_high": nifty50_year_high,
                "nifty50_distance_from_high_pct": round(index_dist, 2),
                "midcap_price": midcap_quote.get("price", 0) if midcap_quote else None,
                "vix_level": vix_level,
            },
            "data_freshness": data_freshness,
        },
        "composite": composite,
        "components": {
            "distribution_days": comp1,
            "leading_stocks": comp2,
            "defensive_rotation": comp3,
            "breadth_divergence": comp4,
            "index_technical": comp5,
            "sentiment": comp6,
        },
        "follow_through_day": ftd,
        "historical_comparison": historical_comparison,
        "scenarios": scenarios,
        "delta": delta_info,
        "additional_context": additional_context,
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_file = os.path.join(args.output_dir, f"market_top_{timestamp}.json")
    md_file = os.path.join(args.output_dir, f"market_top_{timestamp}.md")

    generate_json_report(analysis, json_file)
    generate_markdown_report(analysis, md_file)

    print()
    print("=" * 70)
    print("Market Top Detection Complete")
    print("=" * 70)
    print(f"  Heuristic Risk Score: {composite['composite_score']}/100")
    print("  Risk score, not an estimated event probability; budgets are policy heuristics.")
    print(f"  Risk Zone: {composite['zone']}")
    print(f"  Risk Budget: {composite['risk_budget']}")
    print(f"  JSON Report: {json_file}")
    print(f"  Markdown Report: {md_file}")
    print()

    stats = client.get_api_stats()
    print("Data calls:")
    print(f"  Network calls made: {stats.get('api_calls_made')}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
