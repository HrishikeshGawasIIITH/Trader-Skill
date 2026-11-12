#!/usr/bin/env python3
"""
Earnings Calendar Report Generator

Generates formatted markdown reports from earnings data JSON.

Usage:
    # Output to stdout
    python generate_report.py earnings_data.json

    # Output to file
    python generate_report.py earnings_data.json earnings_calendar.md

    # Help
    python generate_report.py --help
"""

import json
import sys
from collections import defaultdict
from datetime import datetime


def load_earnings_data(filepath: str) -> list[dict]:
    """
    Load earnings data from JSON file

    Args:
        filepath: Path to JSON file

    Returns:
        List of earnings announcements
    """
    try:
        with open(filepath) as f:
            content = f.read()

            # Handle case where file has progress messages before JSON.
            # Try a direct parse first; only fall back to locating the array
            # if the file has a non-JSON preamble. A preamble may itself
            # contain "[" (e.g. "[INFO] ..."), so scan each candidate "["
            # and keep the first one that decodes to valid JSON rather than
            # blindly slicing from the first bracket.
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                data = None
                search_start = 0
                while True:
                    bracket = content.find("[", search_start)
                    if bracket == -1:
                        raise
                    try:
                        data, _ = decoder.raw_decode(content[bracket:])
                        break
                    except json.JSONDecodeError:
                        search_start = bracket + 1

            if not isinstance(data, list):
                print("ERROR: JSON file must contain an array of earnings data", file=sys.stderr)
                sys.exit(1)

            return data

    except FileNotFoundError:
        print(f"ERROR: File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error reading file: {e}", file=sys.stderr)
        sys.exit(1)


def group_by_date(earnings: list[dict]) -> dict:
    """
    Group earnings by date and timing

    Args:
        earnings: List of earnings announcements

    Returns:
        Dictionary grouped by date and timing
    """
    by_date = defaultdict(lambda: {"BMO": [], "AMC": [], "TAS": []})

    for stock in earnings:
        date = stock.get("date")
        timing = stock.get("timing") or "TAS"
        if timing not in ("BMO", "AMC", "TAS"):
            timing = "TAS"

        if date:
            by_date[date][timing].append(stock)

    return by_date


def calculate_summary_stats(earnings: list[dict]) -> dict:
    """
    Calculate summary statistics

    Args:
        earnings: List of earnings announcements

    Returns:
        Dictionary with summary statistics
    """
    total = len(earnings)
    large_cap = sum(1 for s in earnings if s.get("index") == "Nifty 50")
    mid_cap = sum(1 for s in earnings if s.get("index") == "Midcap 150")
    small_cap = total - large_cap - mid_cap

    # Sector distribution
    sectors = defaultdict(int)
    for stock in earnings:
        sector = stock.get("sector", "N/A")
        sectors[sector] += 1

    # Peak day
    by_date = group_by_date(earnings)
    if by_date:
        peak = max(by_date.items(), key=lambda x: sum(len(v) for v in x[1].values()))
        peak_date, peak_data = peak
        peak_count = sum(len(v) for v in peak_data.values())
    else:
        peak_date, peak_count = None, 0

    return {
        "total": total,
        "large_cap": large_cap,
        "mid_cap": mid_cap,
        "small_cap": small_cap,
        "sectors": dict(sectors),
        "peak_date": peak_date,
        "peak_count": peak_count,
    }


def get_day_name(date_str: str) -> str:
    """
    Convert date string to full day name

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        Formatted day name (e.g., "Monday, November 03, 2025")
    """
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%A, %B %d, %Y")


def generate_report(earnings: list[dict]) -> str:
    """
    Generate markdown earnings calendar report

    Args:
        earnings: List of earnings announcements

    Returns:
        Formatted markdown report
    """
    if not earnings:
        return "# Results Calendar\n\nNo results data available.\n"

    # Calculate statistics
    stats = calculate_summary_stats(earnings)
    by_date = group_by_date(earnings)

    # Get date range
    dates = sorted(by_date.keys())
    if dates:
        start_date = datetime.strptime(dates[0], "%Y-%m-%d")
        end_date = datetime.strptime(dates[-1], "%Y-%m-%d")
        date_range = f"{start_date.strftime('%B %d')} to {end_date.strftime('%B %d, %Y')}"
    else:
        date_range = "Unknown"

    # Top 5 by index tier (Nifty 50 first)
    tier_rank = {"Nifty 50": 0, "Midcap 150": 1, "Smallcap 250": 2}
    top5 = sorted(
        earnings, key=lambda x: (tier_rank.get(x.get("index"), 3), x.get("symbol") or "")
    )[:5]

    # Peak day label (may be absent if no records had a usable date)
    peak_day = get_day_name(stats["peak_date"]).split(",")[0] if stats["peak_date"] else "N/A"

    # Generate report
    report = f"""# Upcoming Results Calendar - {date_range}

**Report Generated**: {datetime.now().strftime("%B %d, %Y")}
**Data Source**: NSE results calendar (Nifty 500 companies)
**Total Companies**: {stats["total"]}

---

## Executive Summary

- **Total Companies Reporting**: {stats["total"]}
- **Nifty 50**: {stats["large_cap"]}
- **Nifty Midcap 150**: {stats["mid_cap"]}
- **Nifty Smallcap 250**: {stats["small_cap"]}
- **Peak Day**: {peak_day} ({stats["peak_count"]} companies)

---

"""

    # Generate day-by-day sections
    for date in dates:
        day_name = get_day_name(date)
        report += f"## {day_name}\n\n"

        timing_labels = {
            "BMO": "Before Market Open (BMO)",
            "AMC": "After Market Close (AMC)",
            "TAS": "Time Not Announced",
        }

        for timing in ["BMO", "AMC", "TAS"]:
            stocks = by_date[date][timing]
            # NSE gives no time of day, so skip empty BMO and AMC blocks.
            if not stocks and timing != "TAS":
                continue

            report += f"### {timing_labels[timing]}\n\n"

            if not stocks:
                report += "*No results announcements*\n\n"
            else:
                report += "| Symbol | Company | Index | Sector |\n"
                report += "|--------|---------|-------|--------|\n"

                display_stocks = sorted(
                    stocks,
                    key=lambda x: (tier_rank.get(x.get("index"), 3), x.get("symbol") or ""),
                )[:60]

                for stock in display_stocks:
                    ticker = stock.get("symbol", "N/A")
                    company = (stock.get("companyName") or "N/A")[:35]
                    index_name = stock.get("index") or "N/A"
                    sector = (stock.get("sector") or "N/A")[:30]
                    report += f"| {ticker} | {company} | {index_name} | {sector} |\n"

                if len(stocks) > 60:
                    report += f"\n*Showing first 60 of {len(stocks)} companies by index tier*\n"

                report += "\n"

        report += "---\n\n"

    # Key observations
    report += "## Key Observations\n\n### Largest Companies Reporting\n"
    for i, stock in enumerate(top5, 1):
        date_str = datetime.strptime(stock["date"], "%Y-%m-%d").strftime("%a")
        company = stock.get("companyName", stock.get("symbol"))
        ticker = stock.get("symbol", "N/A")
        index_name = stock.get("index", "N/A")
        timing = stock.get("timing", "TAS")
        report += f"{i}. {company} ({ticker}) - {index_name} - {date_str} {timing}\n"

    report += "\n### Sector Distribution\n"
    top_sectors = sorted(stats["sectors"].items(), key=lambda x: x[1], reverse=True)[:5]
    for sector, count in top_sectors:
        report += f"- **{sector}**: {count} companies\n"

    report += f"""
### Trading Considerations
- **Peak Day**: {peak_day} with {stats["peak_count"]} results announcements
- **Session**: NSE trades 09:15-15:30 IST. Most results are filed after the close or before the open.
- **Gap risk**: Plan for the next session open. Do not hold size through results without a reason.

---

## Data Notes

- **Index tiers**: Nifty 50 (large), Nifty Midcap 150 (mid), Nifty Smallcap 250 (small).
  The free source has no market cap, so tiers replace market cap bands.

- **Filter Criteria**: Companies in the Nifty 500 list with a board meeting for results in the period.

- **Data Source**: NSE board meeting filings and the NSE event calendar.

- **Timing**: NSE gives the meeting date, not the time of day. All rows are listed as time not announced.

- **Data Freshness**: Meeting dates can change. Check the company announcement on NSE before acting.

- **Estimates**: EPS and revenue estimates are not available from the free source.

---

*Report generated from NSE public data. Always verify results dates through the exchange announcement.*
"""

    return report


def print_usage():
    """Print usage instructions"""
    print("Usage:", file=sys.stderr)
    print("  python generate_report.py INPUT_JSON [OUTPUT_FILE]", file=sys.stderr)
    print("", file=sys.stderr)
    print("Arguments:", file=sys.stderr)
    print("  INPUT_JSON   Path to earnings data JSON file (required)", file=sys.stderr)
    print(
        "  OUTPUT_FILE  Path to output markdown file (optional, defaults to stdout)",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("Examples:", file=sys.stderr)
    print("  python generate_report.py earnings_data.json", file=sys.stderr)
    print("  python generate_report.py earnings_data.json earnings_calendar.md", file=sys.stderr)
    print("", file=sys.stderr)
    print("Input JSON format:", file=sys.stderr)
    print(
        "  Array of results objects with fields: symbol, companyName, date, timing,",
        file=sys.stderr,
    )
    print(
        "  index, sector, industry, purpose", file=sys.stderr
    )


def main():
    """Main execution"""
    # Check for help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help", "help"]:
        print_usage()
        sys.exit(0)

    # Validate arguments
    if len(sys.argv) < 2:
        print("ERROR: Missing required argument", file=sys.stderr)
        print("", file=sys.stderr)
        print_usage()
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Loading earnings data from: {input_file}", file=sys.stderr)
    earnings = load_earnings_data(input_file)
    print(f"OK: loaded {len(earnings)} companies", file=sys.stderr)

    print("Generating markdown report...", file=sys.stderr)
    report = generate_report(earnings)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"OK: report saved to: {output_file}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
