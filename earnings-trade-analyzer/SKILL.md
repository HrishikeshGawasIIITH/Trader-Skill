---
name: earnings-trade-analyzer
description: Analyze Nifty 500 stocks that reported quarterly results in the last few days with a 5-factor score (Gap Size, Pre-Earnings Trend, Volume Trend, MA200 Position, MA50 Position). Scores each stock 0-100 and gives an A/B/C/D grade. Use for results-day trade analysis, post-results momentum scans, results gap scoring or the best recent reactions on NSE.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# Earnings Trade Analyzer - Post-Earnings 5-Factor Scoring

Analyze Nifty 500 stocks that recently reported results using a 5-factor weighted scoring system to identify the strongest earnings reactions for potential momentum trades.

## When to Use

- User asks for post-earnings trade analysis or earnings gap screening
- User wants to find the best recent earnings reactions
- User requests earnings momentum scoring or grading
- User asks about post-results drift (PEAD) candidates

## Prerequisites

- No API key. Prices come from free Yahoo chart data. The results calendar and index lists come from NSE.
- Python standard library only.
- Only symbols in the Nifty 500 lists are scored. The free source has no market cap.

## Workflow

### Step 1: Run the Earnings Trade Analyzer

Execute the analyzer script:

```bash
# Default: last 2 days of earnings, top 20 results
python3 earnings-trade-analyzer/scripts/analyze_earnings_trades.py --output-dir reports/

# Custom lookback and market cap filter
python3 earnings-trade-analyzer/scripts/analyze_earnings_trades.py \
  --lookback-days 5 \
  --top 30 \
  --output-dir reports/

# Deterministic anchor date (IST); the window is anchored on the
# IST calendar date, not the runner's local clock. For reproducible runs/tests.
python3 earnings-trade-analyzer/scripts/analyze_earnings_trades.py \
  --as-of 2026-09-15 \
  --output-dir reports/

# With entry quality filter
python3 earnings-trade-analyzer/scripts/analyze_earnings_trades.py \
  --apply-entry-filter \
  --output-dir reports/
```

#### Empty windows and failed runs

A clean empty calendar over a window with at least one NSE session exits 1 with `ZERO_RESULT_REASON=earnings_calendar_empty_with_market_sessions`. If the session calendar cannot classify the window, it exits 1 with `ZERO_RESULT_REASON=market_calendar_unavailable`. Budget exhaustion during profile fetching exits 1 with `ZERO_RESULT_REASON=profiles_budget_exhausted`. Treat each as a failed run to retry, not a quiet day. Only a clean empty calendar over a window with no sessions exits 0 as `ZERO_RESULT_REASON=no_earnings_rows`.

If the scored run cannot finish, retry once with a larger `--max-api-calls`. If it still fails, say so. Do not invent grades.

**No-candidate output:** the analyzer may print `Candidates after filtering: 0` and write no JSON file. Then do not run PEAD Mode B from a missing file. Say that no scored JSON was produced.

The calendar window is inclusive and uses the IST date from `--as-of` (or the current IST date). Today's results are often filed after the close, so the next-session gap is not yet known. Use `--lookback-days 2` or more for scored gaps.

`--lookback-days 0` is valid and queries exactly the single IST as-of date. A non-empty response whose rows lack a `symbol` exits 0 with `ZERO_RESULT_REASON=no_earnings_rows`.

### Step 2: Review Results

1. Read the generated JSON and Markdown reports
2. Load `references/scoring_methodology.md` for scoring interpretation context
3. Focus on Grade A and B stocks for actionable setups

### Step 3: Present Analysis

For each top candidate, present:
- Composite score and letter grade (A/B/C/D)
- Earnings gap size and direction
- Pre-earnings 20-day trend
- Volume ratio (20-day vs 60-day average)
- Position relative to 200-day and 50-day moving averages
- Weakest and strongest scoring components

### Step 4: Provide Actionable Guidance

Based on grades:
- **Grade A (85+):** Strong earnings reaction with institutional accumulation - consider entry
- **Grade B (70-84):** Good earnings reaction worth monitoring - wait for pullback or confirmation
- **Grade C (55-69):** Mixed signals - use caution, additional analysis needed
- **Grade D (<55):** Weak setup - avoid or wait for better conditions

## Output

- `earnings_trade_analyzer_YYYY-MM-DD_HHMMSS.json` - Structured results with schema_version "1.0"
- `earnings_trade_analyzer_YYYY-MM-DD_HHMMSS.md` - Human-readable report with tables

### Unknown earnings timing

The NSE calendar gives no bmo/amc session, so rows report `earnings_timing: "unknown"` and the gap calculation assumes the
AMC window as a fallback. Both reports surface `timing_unknown_count` out of
`timing_candidates_total` so this assumption stays visible rather than
blending unnoticed into the scores.

## Resources

- `references/scoring_methodology.md` - 5-factor scoring system, grade thresholds, and entry quality filter rules

## India defaults

- Entry filter (`--apply-entry-filter`) drops prices below Rs 100 and gap of 10% or more with a score of 85 or more. The rules come from a US backtest and are not tuned for NSE.
- `--min-market-cap` is in rupees, default 0 (off). It applies only when a profile has a market cap.
- Market cap in reports shows Rs crore when known, otherwise N/A.

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
