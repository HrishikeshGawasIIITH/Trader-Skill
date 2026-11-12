---
name: pead-screener
description: Screen Nifty 500 stocks that gapped up after quarterly results for Post-Earnings Announcement Drift (PEAD). Reads weekly candles to find red candle pullbacks and breakout signals. Takes the NSE results calendar (Mode A) or earnings-trade-analyzer JSON (Mode B). Use for PEAD, post-results drift, gap follow-through or weekly results momentum setups on NSE stocks.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# PEAD Screener - Post-Earnings Announcement Drift

Screen Nifty 500 stocks that gapped up after results for PEAD (Post-Earnings Announcement Drift) patterns using weekly candle analysis to detect red candle pullbacks and breakout signals.

## When to Use

- User asks for PEAD screening or post-results drift analysis
- User wants to find earnings gap-up stocks with follow-through potential
- User requests red candle breakout patterns after earnings
- User asks for weekly earnings momentum setups
- User provides earnings-trade-analyzer JSON output for further screening

## Prerequisites

- No API key. Prices come from free Yahoo chart data. The results calendar and index lists come from NSE.
- Python standard library only.
- For Mode B: earnings-trade-analyzer JSON output file with schema_version "1.0"

## Workflow

### Step 1: Prepare and Execute Screening

Run the PEAD screener script in one of two modes:

**Mode A (NSE results calendar):**
```bash
# Default: last 14 days of earnings, 5-week monitoring window
python3 pead-screener/scripts/screen_pead.py --output-dir reports/

# Custom parameters
python3 pead-screener/scripts/screen_pead.py \
  --lookback-days 21 \
  --watch-weeks 6 \
  --min-gap 5.0 \
  --output-dir reports/
```

**Mode B (earnings-trade-analyzer JSON input):**
```bash
# From earnings-trade-analyzer output
python3 pead-screener/scripts/screen_pead.py \
  --candidates-json reports/earnings_trade_analyzer_YYYY-MM-DD_HHMMSS.json \
  --min-grade B \
  --output-dir reports/
```

Mode A keeps only symbols that appear in the Nifty 500 lists. Results rows carry no before/after-market flag, so timing is `unknown` and the gap uses the next session open. Market cap is not available from the free source. `--min-market-cap` (rupees, default 0) applies only when a profile supplies one.

### Step 2: Review Results

1. Read the generated JSON and Markdown reports
2. Load `references/pead_strategy.md` for PEAD theory and pattern context
3. Load `references/entry_exit_rules.md` for trade management rules

### Step 3: Present Analysis

For each candidate, present:
- Stage classification (MONITORING, SIGNAL_READY, BREAKOUT, EXPIRED)
- Weekly candle pattern details (red candle location, breakout status)
- Composite score and rating
- Trade setup: entry, stop-loss, target, risk/reward ratio
- Liquidity metrics (ADV20, average volume)

### Step 4: Provide Actionable Guidance

Based on stages and ratings:
- **BREAKOUT + Strong Setup (85+):** High-conviction PEAD trade, full position size
- **BREAKOUT + Good Setup (70-84):** Solid PEAD setup, standard position size
- **SIGNAL_READY:** Red candle formed, set alert for breakout above red candle high
- **MONITORING:** Post-earnings, no red candle yet, add to watchlist
- **EXPIRED:** Beyond monitoring window, remove from watchlist

## Output

- `pead_screener_YYYY-MM-DD_HHMMSS.json` - Structured results with stage classification
- `pead_screener_YYYY-MM-DD_HHMMSS.md` - Human-readable report grouped by stage

### Unknown earnings timing

The NSE calendar does not give a bmo/amc session; every row carries `earnings_timing: "unknown"` in Mode A (unless Mode B input says otherwise) and the price gap
calculation assumes the AMC window as a fallback. The Mode A report shows
`timing_unknown_count` out of `timing_candidates_total` so this assumption
stays visible (Mode B reports `n/a` since timing is inherited from the input
JSON). `timing_candidates_total` is the post-budget-trim population that was
actually analyzed, not the raw earnings-calendar row count.

## Resources

- `references/pead_strategy.md` - PEAD theory and weekly candle approach
- `references/entry_exit_rules.md` - Entry, exit, and position sizing rules

## India defaults

- Liquidity check: 20-day average traded value of at least Rs 10 crore, average volume of at least 500,000 shares, price of at least Rs 50.
- Report prices are in rupees (Rs).

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
