---
name: earnings-calendar
description: List upcoming quarterly results announcements for Nifty 500 companies from the NSE results calendar. Groups them by date and index tier (Nifty 50, Midcap 150, Smallcap 250) in a markdown report. Use when the user asks which NSE companies report results this week, wants a results calendar, or needs a weekly results review.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# Earnings Calendar (NSE)

## Overview

This skill lists which Nifty 500 companies hold board meetings to approve quarterly results over a date range. It reads the free NSE board meeting filings and the NSE event calendar. It then tags each company with its index tier and writes a markdown report.

Key points:
- No API key. Python standard library only.
- NSE gives the meeting date, not the time of day. Every row is "time not announced".
- The free source has no market cap or analyst estimates. Index tiers replace market cap bands.
- Dates and times are IST. The NSE session runs 09:15-15:30.

## Workflow

### Step 1: Get the date range

Use today's date from the environment. The default range is the next 7 days. Write dates as YYYY-MM-DD.

```
Today: 2026-11-11
Start: 2026-11-12
End:   2026-11-18
```

### Step 2: Fetch the calendar

```bash
python3 earnings-calendar/scripts/fetch_earnings_nse.py 2026-11-12 2026-11-18 > earnings_data.json
```

Options:
- `--universe nifty50|nifty500|midcap150|smallcap250`. Default is `nifty500`.

JSON goes to stdout. Progress goes to stderr. Each row has `symbol`, `companyName`, `date`, `timing`, `index`, `purpose`, `sector`, `industry` and `exchange`.

An empty list means no Nifty 500 results meetings in the range. A non-zero exit means NSE could not be reached. Retry once, then tell the user.

### Step 3: Generate the report

```bash
python3 earnings-calendar/scripts/generate_report.py earnings_data.json reports/earnings_calendar_2026-11-12.md
```

Leave out the output path to print to stdout.

### Step 4: Review and present

Read the report. Present these points:
- Total companies reporting and the split by index tier.
- The peak day.
- The largest companies reporting (Nifty 50 first).
- The sector mix.

Add short notes where useful:
- Results are often filed after the close or before the open. Plan for a gap at the next open.
- Board meeting dates can move. Check the NSE announcement before acting.
- "Board Meeting Intimation" rows are notices of a future meeting. The meeting date is the `date` field.

### Step 5: Save the report

Save to `reports/earnings_calendar_<start-date>.md`. Create the folder if needed.

## Resources

- `scripts/fetch_earnings_nse.py` - fetch and filter the NSE results calendar
- `scripts/generate_report.py` - build the markdown report from the JSON
- `scripts/india_client.py` - free Yahoo and NSE data client
- `assets/earnings_report_template.md` - report layout reference

Related skills: `earnings-trade-analyzer` scores the stocks after they report. `pead-screener` follows the drift.

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
