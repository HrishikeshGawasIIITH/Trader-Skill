#!/usr/bin/env python3
"""Sector rotation analysis for the Indian market.

Computes the uptrend ratio of each of 11 sectors from Nifty 500 stock prices
(breadth_engine + india_client, cached in trader/cache/breadth.json), then
produces sector rankings, risk-regime scoring, overbought/oversold flags and
market-cycle phase estimation. Also reports the price performance of the NSE
sectoral indices (Nifty IT, Auto, Pharma, FMCG, Metal, Realty, Energy, Bank...).

Dependencies: stdlib only (urllib via india_client, csv, json, argparse, dataclasses).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import breadth_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Verified Yahoo symbols for NSE sectoral indices: (label, symbol, sector name used below)
SECTOR_INDEX_SYMBOLS = [
    ("Nifty IT", "^CNXIT", "Technology"),
    ("Nifty Auto", "^CNXAUTO", "Consumer Cyclical"),
    ("Nifty FMCG", "^CNXFMCG", "Consumer Defensive"),
    ("Nifty Pharma", "^CNXPHARMA", "Healthcare"),
    ("Nifty Financial Services", "NIFTY_FIN_SERVICE.NS", "Financial"),
    ("Nifty Bank", "^NSEBANK", "Financial"),
    ("Nifty PSU Bank", "^CNXPSUBANK", "Financial"),
    ("Nifty Metal", "^CNXMETAL", "Basic Materials"),
    ("Nifty Realty", "^CNXREALTY", "Real Estate"),
    ("Nifty Energy", "^CNXENERGY", "Energy"),
    ("Nifty Infrastructure", "^CNXINFRA", "Industrials"),
    ("Nifty Media", "^CNXMEDIA", "Communication Services"),
]

# Sector classification - aligned with uptrend-analyzer's
# sector_rotation_calculator.py (L31-47).
CYCLICAL_SECTORS = [
    "Technology",
    "Consumer Cyclical",
    "Communication Services",
    "Financial",
    "Industrials",
]
DEFENSIVE_SECTORS = [
    "Utilities",
    "Consumer Defensive",
    "Healthcare",
    "Real Estate",
]
COMMODITY_SECTORS = [
    "Energy",
    "Basic Materials",
]

# Overbought / oversold thresholds (uptrend ratio scale).
OVERBOUGHT_THRESHOLD = 0.37
OVERSOLD_THRESHOLD = 0.097

# Freshness: warn if data is older than this many days.
FRESHNESS_MAX_DAYS = 5

# Cycle phase definitions: which sectors lead/lag in each phase.
CYCLE_PHASES = {
    "early": {
        "leaders": ["Technology", "Consumer Cyclical", "Industrials", "Financial"],
        "laggards": ["Utilities", "Consumer Defensive", "Healthcare"],
    },
    "mid": {
        "leaders": ["Technology", "Industrials", "Consumer Cyclical", "Energy"],
        "laggards": ["Utilities", "Consumer Defensive"],
    },
    "late": {
        "leaders": ["Energy", "Basic Materials", "Healthcare"],
        "laggards": ["Technology", "Consumer Cyclical", "Industrials"],
    },
    "recession": {
        "leaders": ["Utilities", "Consumer Defensive", "Healthcare"],
        "laggards": ["Technology", "Consumer Cyclical", "Industrials", "Financial"],
    },
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class SectorData:
    """Parsed sector row."""

    sector: str
    ratio: float
    ma_10: float | None
    trend: str
    slope: float | None
    status: str


# ---------------------------------------------------------------------------
# CSV Fetching
# ---------------------------------------------------------------------------


# Required columns for sector_summary.csv validation.
REQUIRED_COLUMNS = {"Sector", "Ratio"}
EXPECTED_COLUMNS = {"Sector", "Ratio", "10MA", "Trend", "Slope", "Status"}


def validate_columns(raw_rows: list[dict]) -> None:
    """Validate that required columns exist in CSV data.

    Raises ValueError if required columns are missing.
    Prints a warning if optional expected columns are missing.
    """
    if not raw_rows:
        return
    actual = set(raw_rows[0].keys())
    missing_required = REQUIRED_COLUMNS - actual
    if missing_required:
        raise ValueError(f"Missing required columns: {sorted(missing_required)}")
    missing_optional = EXPECTED_COLUMNS - REQUIRED_COLUMNS - actual
    if missing_optional:
        print(
            f"WARNING: Missing optional columns: {sorted(missing_optional)}",
            file=sys.stderr,
        )


def parse_sector_rows(raw_rows: list[dict]) -> list[SectorData]:
    """Convert raw CSV dicts to SectorData, skipping invalid rows."""
    result: list[SectorData] = []
    for row in raw_rows:
        sector = row.get("Sector", "").strip()
        if not sector:
            continue
        ratio_str = row.get("Ratio", "").strip()
        if not ratio_str:
            continue
        try:
            ratio = float(ratio_str)
        except ValueError:
            continue

        ma_10 = _safe_float(row.get("10MA", ""))
        slope = _safe_float(row.get("Slope", ""))
        trend = row.get("Trend", "").strip()
        status = row.get("Status", "").strip()

        result.append(SectorData(sector, ratio, ma_10, trend, slope, status))
    return result


def check_freshness(latest_date: str | None) -> dict | None:
    """Check data freshness from the latest breadth date (YYYY-MM-DD).

    Returns dict with 'date', 'is_fresh', 'warning' or None when no date is known.
    """
    if not latest_date:
        return None
    try:
        max_date = datetime.strptime(latest_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    days_old = (date.today() - max_date).days
    is_fresh = days_old <= FRESHNESS_MAX_DAYS
    warning = None if is_fresh else f"Data is {days_old} days old (latest: {latest_date})"
    return {"date": latest_date, "is_fresh": is_fresh, "warning": warning}


def compute_sector_rows(client, universe="nifty500", max_symbols=None, cache_path=None,
                        refresh=False, progress=None) -> tuple[list[dict], str | None]:
    """Compute sector summary rows (same columns as the old CSV) and the latest date."""
    res = breadth_engine.get_breadth(
        client, universe=universe, max_symbols=max_symbols, cache_path=cache_path,
        refresh=refresh, progress=progress,
    )
    latest: dict[str, dict] = {}
    for row in res["timeseries"]:
        ws = row["worksheet"]
        if ws == "all":
            continue
        if ws not in latest or row["date"] > latest[ws]["date"]:
            latest[ws] = row
    display = {ws: sector for sector, ws in breadth_engine.SECTOR_TO_WORKSHEET.items()}
    rows = []
    for ws, r in latest.items():
        ratio = r["ratio"]
        status = "Overbought" if ratio > OVERBOUGHT_THRESHOLD else (
            "Oversold" if ratio < OVERSOLD_THRESHOLD else "Normal")
        rows.append({
            "Sector": display.get(ws, ws),
            "Ratio": str(ratio),
            "10MA": "" if r["ma_10"] is None else str(r["ma_10"]),
            "Trend": r["trend"].capitalize(),
            "Slope": "" if r["slope"] is None else str(r["slope"]),
            "Status": status,
        })
    latest_date = res["agg"][-1]["date"] if res["agg"] else None
    return rows, latest_date


def index_performance(client) -> list[dict]:
    """1-week, 1-month, 3-month return and position vs 50-day average for NSE sectoral indices."""
    out = []
    for label, symbol, sector in SECTOR_INDEX_SYMBOLS:
        try:
            data = client.get_historical_prices(symbol, days=120)
        except Exception:
            data = None
        hist = (data or {}).get("historical") or []
        closes = [h["close"] for h in hist if h.get("close") is not None]  # newest first
        if len(closes) < 22:
            out.append({"index": label, "symbol": symbol, "sector": sector, "available": False})
            continue

        def ret(n):
            return round((closes[0] / closes[n] - 1) * 100, 2) if len(closes) > n else None

        sma50 = sum(closes[:50]) / 50 if len(closes) >= 50 else None
        out.append({
            "index": label, "symbol": symbol, "sector": sector, "available": True,
            "last": round(closes[0], 2), "ret_1w_pct": ret(5), "ret_1m_pct": ret(21),
            "ret_3m_pct": ret(63),
            "above_50dma": (closes[0] > sma50) if sma50 else None,
        })
    return out


# ---------------------------------------------------------------------------
# Analysis Functions
# ---------------------------------------------------------------------------


def rank_sectors(sectors: list[SectorData]) -> list[dict]:
    """Rank sectors by ratio descending."""
    sorted_sectors = sorted(sectors, key=lambda s: s.ratio, reverse=True)
    return [
        {
            "rank": i + 1,
            "sector": s.sector,
            "ratio": s.ratio,
            "ratio_pct": round(s.ratio * 100, 1),
            "trend": s.trend,
            "slope": s.slope,
            "status": s.status,
        }
        for i, s in enumerate(sorted_sectors)
    ]


def analyze_groups(sectors: list[SectorData]) -> dict:
    """Analyze cyclical/defensive/commodity groups and determine risk regime."""
    sector_map = {s.sector: s for s in sectors}

    cyclical_ratios = _get_group_ratios(sector_map, CYCLICAL_SECTORS)
    defensive_ratios = _get_group_ratios(sector_map, DEFENSIVE_SECTORS)
    commodity_ratios = _get_group_ratios(sector_map, COMMODITY_SECTORS)

    cyclical_avg = _avg(cyclical_ratios) if cyclical_ratios else None
    defensive_avg = _avg(defensive_ratios) if defensive_ratios else None
    commodity_avg = _avg(commodity_ratios) if commodity_ratios else None

    if cyclical_avg is None or defensive_avg is None:
        return {
            "cyclical_avg": cyclical_avg,
            "defensive_avg": defensive_avg,
            "commodity_avg": commodity_avg,
            "difference": None,
            "score": 50,
            "regime": "incomplete data",
            "late_cycle_flag": False,
            "divergence_flag": False,
        }

    difference = cyclical_avg - defensive_avg
    base_score = _difference_to_score(difference)

    # Commodity adjustment
    late_cycle_flag = False
    commodity_penalty = 0
    if commodity_avg is not None:
        if commodity_avg > cyclical_avg and commodity_avg > defensive_avg:
            late_cycle_flag = True
            excess = commodity_avg - max(cyclical_avg, defensive_avg)
            commodity_penalty = -10 if excess > 0.10 else -5

    # Divergence detection
    divergence_result = _calculate_group_divergence(sector_map)
    divergence_penalty = divergence_result.get("divergence_penalty", 0)

    score = round(min(100, max(0, base_score + commodity_penalty + divergence_penalty)))
    regime = _score_to_regime(score)

    return {
        "cyclical_avg": round(cyclical_avg, 4),
        "cyclical_avg_pct": round(cyclical_avg * 100, 1),
        "defensive_avg": round(defensive_avg, 4),
        "defensive_avg_pct": round(defensive_avg * 100, 1),
        "commodity_avg": round(commodity_avg, 4) if commodity_avg is not None else None,
        "commodity_avg_pct": round(commodity_avg * 100, 1) if commodity_avg is not None else None,
        "difference": round(difference, 4),
        "difference_pct": round(difference * 100, 1),
        "score": score,
        "regime": regime,
        "late_cycle_flag": late_cycle_flag,
        "commodity_penalty": commodity_penalty,
        "divergence_flag": divergence_result.get("divergence_flag", False),
        "divergence_penalty": divergence_penalty,
    }


def identify_overbought_oversold(
    sectors: list[SectorData],
) -> tuple[list[dict], list[dict]]:
    """Identify overbought (ratio > 0.37) and oversold (ratio < 0.097) sectors."""
    overbought: list[dict] = []
    oversold: list[dict] = []
    for s in sectors:
        if s.ratio > OVERBOUGHT_THRESHOLD:
            overbought.append(
                {"sector": s.sector, "ratio": s.ratio, "ratio_pct": round(s.ratio * 100, 1)}
            )
        elif s.ratio < OVERSOLD_THRESHOLD:
            oversold.append(
                {"sector": s.sector, "ratio": s.ratio, "ratio_pct": round(s.ratio * 100, 1)}
            )
    return overbought, oversold


def analyze_trends(sectors: list[SectorData]) -> dict:
    """Analyze trend distribution across sectors."""
    up = [s.sector for s in sectors if s.trend.lower() == "up"]
    down = [s.sector for s in sectors if s.trend.lower() == "down"]
    return {
        "uptrend_count": len(up),
        "downtrend_count": len(down),
        "uptrend_sectors": up,
        "downtrend_sectors": down,
    }


def estimate_cycle_phase(sectors: list[SectorData]) -> dict:
    """Estimate market cycle phase based on sector performance patterns.

    Scoring per phase:
      - Leader match in top ranks: weight 0.4
      - Laggard match in bottom ranks: weight 0.3
      - Trend direction alignment: weight 0.3
    """
    if not sectors:
        return {"phase": "unknown", "confidence": "low", "scores": {}, "evidence": []}

    sorted_by_ratio = sorted(sectors, key=lambda s: s.ratio, reverse=True)
    n = len(sorted_by_ratio)
    top_half = {s.sector for s in sorted_by_ratio[: n // 2 + 1]}
    bottom_half = {s.sector for s in sorted_by_ratio[n // 2 :]}
    trend_map = {s.sector: s.trend.lower() for s in sectors}

    scores: dict[str, float] = {}
    evidence: list[str] = []

    for phase_name, phase_def in CYCLE_PHASES.items():
        leaders = phase_def["leaders"]
        laggards = phase_def["laggards"]

        # Leader match: how many expected leaders are in top half
        leader_hits = sum(1 for s in leaders if s in top_half)
        leader_score = leader_hits / len(leaders) if leaders else 0

        # Laggard match: how many expected laggards are in bottom half
        laggard_hits = sum(1 for s in laggards if s in bottom_half)
        laggard_score = laggard_hits / len(laggards) if laggards else 0

        # Trend alignment: leaders trending up, laggards trending down
        trend_hits = 0
        trend_total = 0
        for s in leaders:
            if s in trend_map:
                trend_total += 1
                if trend_map[s] == "up":
                    trend_hits += 1
        for s in laggards:
            if s in trend_map:
                trend_total += 1
                if trend_map[s] == "down":
                    trend_hits += 1
        trend_score = trend_hits / trend_total if trend_total else 0

        total = leader_score * 0.4 + laggard_score * 0.3 + trend_score * 0.3
        scores[phase_name] = round(total * 100, 1)

    # Determine best phase
    sorted_phases = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_phase = sorted_phases[0][0]
    best_score = sorted_phases[0][1]
    second_score = sorted_phases[1][1] if len(sorted_phases) > 1 else 0

    gap = best_score - second_score
    if gap > 20:
        confidence = "high"
    elif gap > 10:
        confidence = "moderate"
    else:
        confidence = "low"

    # Build evidence
    phase_def = CYCLE_PHASES[best_phase]
    matched_leaders = [s for s in phase_def["leaders"] if s in top_half]
    matched_laggards = [s for s in phase_def["laggards"] if s in bottom_half]
    if matched_leaders:
        evidence.append(f"Leaders in top ranks: {', '.join(matched_leaders)}")
    if matched_laggards:
        evidence.append(f"Laggards in bottom ranks: {', '.join(matched_laggards)}")

    return {
        "phase": best_phase,
        "confidence": confidence,
        "scores": scores,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------


def format_human(
    ranking: list[dict],
    groups: dict,
    overbought: list[dict],
    oversold: list[dict],
    trends: dict,
    cycle: dict,
    freshness: dict | None,
    index_perf: list[dict] | None = None,
) -> str:
    """Format analysis results as human-readable markdown."""
    lines: list[str] = []
    lines.append(f"# Sector Rotation Analysis - {date.today().isoformat()}")
    lines.append("")

    # Freshness warning
    if freshness:
        if freshness.get("warning"):
            lines.append(f"> **WARNING**: {freshness['warning']}")
            lines.append("")
        else:
            lines.append(f"> Data as of: {freshness['date']}")
            lines.append("")

    # Risk Regime
    lines.append("## Risk Regime")
    lines.append("")
    regime = groups.get("regime", "N/A").upper()
    score = groups.get("score", "N/A")
    lines.append(f"**{regime}** (score: {score}/100)")
    lines.append("")
    if groups.get("cyclical_avg") is not None:
        lines.append(f"- Cyclical avg: {groups['cyclical_avg_pct']}%")
        lines.append(f"- Defensive avg: {groups['defensive_avg_pct']}%")
        lines.append(f"- Difference: {groups['difference_pct']}pp")
        if groups.get("commodity_avg") is not None:
            lines.append(f"- Commodity avg: {groups['commodity_avg_pct']}%")
        if groups.get("late_cycle_flag"):
            lines.append(
                "- **Late Cycle Flag**: Commodity sectors leading both cyclical and defensive"
            )
        if groups.get("divergence_flag"):
            lines.append("- **Divergence Flag**: High intra-group spread detected")
    lines.append("")

    # Cycle Phase
    lines.append("## Cycle Phase Estimate")
    lines.append("")
    phase = cycle.get("phase", "unknown").replace("_", " ").title()
    conf = cycle.get("confidence", "N/A")
    lines.append(f"**{phase}** (confidence: {conf})")
    lines.append("")
    if cycle.get("scores"):
        for p, s in sorted(cycle["scores"].items(), key=lambda x: x[1], reverse=True):
            marker = " <-" if p == cycle["phase"] else ""
            lines.append(f"- {p.title()}: {s}{marker}")
    lines.append("")
    if cycle.get("evidence"):
        lines.append("Evidence:")
        for e in cycle["evidence"]:
            lines.append(f"- {e}")
        lines.append("")

    # Sector Ranking
    lines.append("## Sector Ranking (by uptrend ratio)")
    lines.append("")
    lines.append("| Rank | Sector | Ratio | Trend | Status |")
    lines.append("|------|--------|-------|-------|--------|")
    for r in ranking:
        lines.append(
            f"| {r['rank']} | {r['sector']} | {r['ratio_pct']}% | {r['trend']} | {r['status']} |"
        )
    lines.append("")

    # Trends
    lines.append("## Trend Summary")
    lines.append("")
    lines.append(f"- Uptrending: {trends['uptrend_count']} sectors")
    lines.append(f"- Downtrending: {trends['downtrend_count']} sectors")
    lines.append("")

    # Overbought / Oversold
    if overbought or oversold:
        lines.append("## Overbought / Oversold")
        lines.append("")
        if overbought:
            lines.append("**Overbought** (ratio > 37%):")
            for s in overbought:
                lines.append(f"- {s['sector']}: {s['ratio_pct']}%")
        if oversold:
            lines.append("**Oversold** (ratio < 9.7%):")
            for s in oversold:
                lines.append(f"- {s['sector']}: {s['ratio_pct']}%")
        lines.append("")

    # NSE sectoral index performance
    if index_perf:
        lines.append("## NSE Sectoral Index Performance")
        lines.append("")
        lines.append("| Index | Sector | 1W | 1M | 3M | Above 50DMA |")
        lines.append("|-------|--------|----|----|----|-------------|")
        for p in index_perf:
            if not p.get("available"):
                lines.append(f"| {p['index']} | {p['sector']} | n/a | n/a | n/a | n/a |")
                continue
            above = {True: "yes", False: "no", None: "n/a"}[p.get("above_50dma")]
            lines.append(
                f"| {p['index']} | {p['sector']} | {_pct(p['ret_1w_pct'])} | "
                f"{_pct(p['ret_1m_pct'])} | {_pct(p['ret_3m_pct'])} | {above} |"
            )
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated: {datetime.now().isoformat(timespec='seconds')}*")
    lines.append("*This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.*")
    return "\n".join(lines)


def format_json(
    ranking: list[dict],
    groups: dict,
    overbought: list[dict],
    oversold: list[dict],
    trends: dict,
    cycle: dict,
    freshness: dict | None,
    index_perf: list[dict] | None = None,
) -> str:
    """Format analysis results as JSON."""
    data = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "date": date.today().isoformat(),
            "freshness": freshness,
        },
        "groups": groups,
        "cycle_phase": cycle,
        "ranking": ranking,
        "overbought": overbought,
        "oversold": oversold,
        "trends": trends,
        "sector_indices": index_perf or [],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _safe_float(value: str) -> float | None:
    """Parse float, return None on failure."""
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def _avg(values: list[float]) -> float:
    """Simple average."""
    return sum(values) / len(values)


def _get_group_ratios(sector_map: dict[str, SectorData], sector_names: list[str]) -> list[float]:
    """Extract ratios for a group of sectors."""
    ratios: list[float] = []
    for name in sector_names:
        sector = sector_map.get(name)
        if sector is not None:
            ratios.append(sector.ratio)
    return ratios


def _difference_to_score(diff: float) -> float:
    """Map cyclical-defensive difference to score (0-100).

    Aligned with sector_rotation_calculator.py L171-189.
    """
    if diff > 0.15:
        return min(100, 90 + (diff - 0.15) / 0.10 * 10)
    elif diff > 0.05:
        return 70 + (diff - 0.05) / 0.10 * 19
    elif diff > -0.05:
        return 45 + (diff + 0.05) / 0.10 * 24
    elif diff > -0.15:
        return 20 + (diff + 0.15) / 0.10 * 24
    else:
        return max(0, 19 + (diff + 0.15) / 0.10 * 19)


def _score_to_regime(score: int) -> str:
    """Map score to risk regime label."""
    if score >= 90:
        return "strong risk-on"
    elif score >= 70:
        return "risk-on"
    elif score >= 45:
        return "balanced"
    elif score >= 20:
        return "defensive tilt"
    else:
        return "strong risk-off"


def _calculate_group_divergence(sector_map: dict[str, SectorData]) -> dict:
    """Detect intra-group divergence.

    Aligned with sector_rotation_calculator.py L209-232.
    """
    cyclical_div = _analyze_group(sector_map, CYCLICAL_SECTORS)
    defensive_div = _analyze_group(sector_map, DEFENSIVE_SECTORS)

    flag = cyclical_div["flagged"] or defensive_div["flagged"]
    penalty = -5 if flag else 0

    return {
        "divergence_flag": flag,
        "divergence_penalty": penalty,
        "cyclical_divergence": cyclical_div,
        "defensive_divergence": defensive_div,
    }


def _analyze_group(sector_map: dict[str, SectorData], sector_names: list[str]) -> dict:
    """Analyze divergence within a sector group."""
    ratios: list[float] = []
    trends: list[str] = []
    names_with_data: list[str] = []

    for name in sector_names:
        sector = sector_map.get(name)
        if sector is not None:
            ratios.append(sector.ratio)
            trends.append(sector.trend.lower())
            names_with_data.append(name)

    if len(ratios) < 2:
        return {
            "flagged": False,
            "std_dev": None,
            "spread": None,
            "outliers": [],
            "trend_dissenters": [],
        }

    mean = sum(ratios) / len(ratios)
    variance = sum((r - mean) ** 2 for r in ratios) / len(ratios)
    std_dev = math.sqrt(variance)
    spread = max(ratios) - min(ratios)

    # Outlier detection
    outliers: list[dict] = []
    for name, ratio in zip(names_with_data, ratios):
        if abs(ratio - mean) > 1.5 * std_dev and std_dev > 0:
            outliers.append({"sector": name, "ratio": ratio, "deviation": round(ratio - mean, 4)})

    # Trend dissenter detection
    trend_dissenters: list[dict] = []
    if trends:
        up_count = sum(1 for t in trends if t == "up")
        down_count = sum(1 for t in trends if t == "down")
        majority = "up" if up_count >= down_count else "down"

        for name, trend in zip(names_with_data, trends):
            if trend and trend != majority:
                trend_dissenters.append({"sector": name, "trend": trend, "majority": majority})

    flagged = std_dev > 0.08 or spread > 0.20 or len(trend_dissenters) > 0

    return {
        "flagged": flagged,
        "std_dev": round(std_dev, 4),
        "spread": round(spread, 4),
        "outliers": outliers,
        "trend_dissenters": trend_dissenters,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None, client=None) -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Sector rotation analysis for NSE sectors")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--output-dir", default="reports/", help="Output directory (default: reports/)"
    )
    parser.add_argument("--save", action="store_true", help="Save output to file")
    parser.add_argument("--universe", default="nifty500", help="nifty50, nifty500, midcap150, smallcap250")
    parser.add_argument("--max-symbols", type=int, default=None, help="Use only the first N symbols")
    parser.add_argument("--cache", default=None, help="Cache file (default: trader/cache/breadth.json)")
    parser.add_argument("--refresh", action="store_true", help="Ignore the cache and recompute")
    parser.add_argument("--no-index", action="store_true", help="Skip NSE sectoral index performance")
    args = parser.parse_args(argv)

    if client is None:
        from india_client import FMPClient

        client = FMPClient(quiet=True)

    # 1. Compute sector uptrend ratios
    print("Computing sector uptrend ratios...", file=sys.stderr)
    raw_rows, latest_date = compute_sector_rows(
        client, args.universe, args.max_symbols, args.cache, args.refresh,
        progress=lambda m: print(m, file=sys.stderr),
    )
    freshness = check_freshness(latest_date)
    if freshness is None:
        print("WARNING: Could not check data freshness (continuing)", file=sys.stderr)
    elif freshness.get("warning"):
        print(f"WARNING: {freshness['warning']}", file=sys.stderr)
    else:
        print(f"Data is fresh (latest: {freshness['date']})", file=sys.stderr)

    try:
        validate_columns(raw_rows)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    sectors = parse_sector_rows(raw_rows)

    if not sectors:
        print("ERROR: No valid sector data found", file=sys.stderr)
        raise SystemExit(1)

    print(f"Parsed {len(sectors)} sectors", file=sys.stderr)

    # 2. Analyze
    ranking = rank_sectors(sectors)
    groups = analyze_groups(sectors)
    overbought, oversold = identify_overbought_oversold(sectors)
    trends = analyze_trends(sectors)
    cycle = estimate_cycle_phase(sectors)
    index_perf = None if args.no_index else index_performance(client)

    # 3. Format output
    fmt = format_json if args.json else format_human
    output = fmt(ranking, groups, overbought, oversold, trends, cycle, freshness, index_perf)
    print(output)

    # 4. Save to file
    if args.save:
        os.makedirs(args.output_dir, exist_ok=True)
        ext = ".json" if args.json else ".md"
        filename = f"sector_rotation_{date.today().isoformat()}{ext}"
        filepath = os.path.join(args.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Saved to {filepath}", file=sys.stderr)


if __name__ == "__main__":
    main()
