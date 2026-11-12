#!/usr/bin/env python3
"""
Component 1: Distribution Day Count (Weight: 25%)

O'Neil's Distribution Day Rules:
- Distribution Day: Index drops >= 0.2% on higher volume than previous day
- Stalling Day: Volume increases but price gain < 0.1% (half weight)
- Days expire after 25 trading days
- Count the higher of Nifty 50 or Midcap 150

Scoring:
  6+ distribution days -> 100 (Critical)
  5 days -> 90
  4 days -> 75  (O'Neil's warning threshold)
  3 days -> 55
  2 days -> 30
  1 day  -> 15
  0 days -> 0
"""


def calculate_distribution_days(nifty50_history: list[dict], midcap_history: list[dict]) -> dict:
    """
    Calculate distribution day count for Nifty 50 and Midcap 150.

    Args:
        nifty50_history: List of daily OHLCV dicts (most recent first), at least 30 days
        midcap_history: List of daily OHLCV dicts (most recent first), at least 30 days

    Returns:
        Dict with score (0-100), distribution_days, stalling_days, details
    """
    nifty50_result = _count_distribution_days(nifty50_history, "Nifty 50")
    midcap_result = _count_distribution_days(midcap_history, "Midcap 150")

    # Use the higher (worse) effective count
    nifty50_effective = nifty50_result["distribution_days"] + 0.5 * nifty50_result["stalling_days"]
    midcap_effective = midcap_result["distribution_days"] + 0.5 * midcap_result["stalling_days"]

    if nifty50_effective >= midcap_effective:
        primary = nifty50_result
        primary_name = "Nifty 50"
    else:
        primary = midcap_result
        primary_name = "Midcap 150"

    effective_count = max(nifty50_effective, midcap_effective)
    raw_score = _score_distribution_days(effective_count)

    # Clustering analysis: check if distribution days are concentrated recently
    primary_details = primary["details"]
    clustering = _calculate_clustering_factor(primary_details)
    clustering_applied = effective_count >= 2 and clustering["factor"] > 0.5
    if clustering_applied:
        score = min(100, round(raw_score * 1.15))
    else:
        score = raw_score

    # Build signal description
    if effective_count >= 5:
        signal = "CRITICAL: Heavy distribution detected"
    elif effective_count >= 4:
        signal = "WARNING: O'Neil's threshold reached"
    elif effective_count >= 3:
        signal = "CAUTION: Moderate distribution"
    elif effective_count >= 1:
        signal = "MINOR: Some distribution present"
    else:
        signal = "CLEAR: No distribution"

    return {
        "score": score,
        "raw_score": raw_score,
        "effective_count": effective_count,
        "signal": signal,
        "clustering": clustering,
        "clustering_applied": clustering_applied,
        "primary_index": primary_name,
        "nifty50": {
            "distribution_days": nifty50_result["distribution_days"],
            "stalling_days": nifty50_result["stalling_days"],
            "effective_count": nifty50_effective,
            "details": nifty50_result["details"],
        },
        "midcap": {
            "distribution_days": midcap_result["distribution_days"],
            "stalling_days": midcap_result["stalling_days"],
            "effective_count": midcap_effective,
            "details": midcap_result["details"],
        },
    }


def _count_distribution_days(history: list[dict], index_name: str) -> dict:
    """Count distribution and stalling days in the last 25 trading days"""
    if not history or len(history) < 2:
        return {"distribution_days": 0, "stalling_days": 0, "details": []}

    # We need at least 26 days to check 25 days of change
    # history[0] = most recent, history[1] = day before, etc.
    window = min(25, len(history) - 1)  # 25 trading day window

    distribution_days = 0
    stalling_days = 0
    details = []

    for i in range(window):
        today = history[i]
        yesterday = history[i + 1]

        today_close = today.get("close", today.get("adjClose", 0))
        yesterday_close = yesterday.get("close", yesterday.get("adjClose", 0))
        today_volume = today.get("volume", 0)
        yesterday_volume = yesterday.get("volume", 0)

        if yesterday_close == 0 or yesterday_volume == 0:
            continue

        pct_change = (today_close - yesterday_close) / yesterday_close * 100
        volume_increase = today_volume > yesterday_volume

        date = today.get("date", f"day-{i}")

        # Distribution day: price drops >= 0.2% AND volume increases
        if pct_change <= -0.2 and volume_increase:
            distribution_days += 1
            details.append(
                {
                    "date": date,
                    "type": "distribution",
                    "pct_change": round(pct_change, 2),
                    "volume_change": round((today_volume / yesterday_volume - 1) * 100, 1),
                    "window_index": i,
                }
            )

        # Stalling day: volume increases but price gain < 0.1%
        elif volume_increase and 0 <= pct_change < 0.1:
            stalling_days += 1
            details.append(
                {
                    "date": date,
                    "type": "stalling",
                    "pct_change": round(pct_change, 2),
                    "volume_change": round((today_volume / yesterday_volume - 1) * 100, 1),
                    "window_index": i,
                }
            )

    return {
        "distribution_days": distribution_days,
        "stalling_days": stalling_days,
        "details": details,
    }


def _calculate_clustering_factor(details: list) -> dict:
    """
    Calculate how clustered distribution/stalling events are in recent days.

    Looks at window_index of events: index 0-4 = most recent 5 days.
    Returns factor = recent_count / total_count (0.0-1.0).
    """
    if not details:
        return {"factor": 0.0, "recent_count": 0, "total_count": 0}

    total_count = len(details)
    recent_count = sum(1 for d in details if d.get("window_index", 99) < 5)
    factor = recent_count / total_count if total_count > 0 else 0.0

    return {
        "factor": round(factor, 2),
        "recent_count": recent_count,
        "total_count": total_count,
    }


def _score_distribution_days(effective_count: float) -> int:
    """Convert effective distribution day count to 0-100 score"""
    if effective_count >= 6:
        return 100
    elif effective_count >= 5:
        return 90
    elif effective_count >= 4:
        return 75
    elif effective_count >= 3:
        return 55
    elif effective_count >= 2:
        return 30
    elif effective_count >= 1:
        return 15
    else:
        return 0
