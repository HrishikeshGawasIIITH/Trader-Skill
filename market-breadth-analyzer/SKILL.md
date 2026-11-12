---
name: market-breadth-analyzer
description: Measures breadth of the Indian market (Nifty 500 by default) and gives a 0-100 health score from 6 components. Breadth is computed from stock prices, cached daily, no API key. Use when asked about market breadth, participation, whether a rally is broad, or general market health.
---

# Market Breadth Analyzer Skill

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Purpose

Score market breadth from 0 to 100 using 6 components. 100 means broad participation. 0 means critical weakness.
Breadth is computed from the universe's own stock prices: percent above the 50-day and 200-day averages, and percent in an uptrend.

## When to Use This Skill

- "Is the rally broad-based?" or "How healthy is Indian market breadth?"
- Participation rate and advance-decline health
- Whether the market is narrowing
- Equity exposure guidance based on breadth

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access to Yahoo (prices) and NSE (index constituents)
- No API keys

## Execution Workflow

### Phase 1: Run the script

```bash
python3 scripts/market_breadth_analyzer.py --output-dir reports/
python3 scripts/market_breadth_analyzer.py --universe nifty50 --max-symbols 5   # quick test
python3 scripts/market_breadth_analyzer.py --refresh                            # ignore the cache
```

The first run for Nifty 500 fetches about 500 symbols (3 to 5 minutes). Later runs on the same session date read `trader/cache/breadth.json` and finish in seconds.
The cache sits in the current folder under `trader/cache/`. Set `TRADER_DIR` to move it.

The script will:
1. Compute daily breadth for the universe (or read the cache)
2. Warn if the latest data is older than 5 days
3. Score the 6 components, with weight redistribution when a component lacks data
4. Write the composite score and zone, with score history and trend
5. Write JSON and Markdown reports

### Phase 2: Present results

- Composite score and health zone
- Strongest and weakest components
- Recommended equity exposure
- Universe snapshot: percent above 50DMA, above 200DMA, in uptrend
- Any freshness warning

## 6-Component Scoring System

| # | Component | Weight | Key Signal |
|---|-----------|--------|------------|
| 1 | Breadth Level & Trend | **25%** | Current 8MA level + 200MA trend direction + 8MA direction modifier |
| 2 | 8MA vs 200MA Crossover | **20%** | Momentum via MA gap and direction |
| 3 | Peak/Trough Cycle | **20%** | Position in breadth cycle |
| 4 | Bearish Signal | **15%** | Backtested bearish signal flag |
| 5 | Historical Percentile | **10%** | Current vs full history distribution |
| 6 | Nifty 50 Divergence | **10%** | Multi-window (20d + 60d) price vs breadth divergence |

**Weight Redistribution:** If any component lacks sufficient data (e.g., no peak/trough markers detected), it is excluded and its weight is proportionally redistributed among the remaining components. The report shows both original and effective weights.

**Score History:** Composite scores are persisted across runs (keyed by data date). The report includes a trend summary (improving/deteriorating/stable) when multiple observations are available.

## Health Zone Mapping (100 = Healthy)

| Score | Zone | Equity Exposure | Action |
|-------|------|-----------------|--------|
| 80-100 | Strong | 90-100% | Full position, growth/momentum favored |
| 60-79 | Healthy | 75-90% | Normal operations |
| 40-59 | Neutral | 60-75% | Selective positioning, tighten stops |
| 20-39 | Weakening | 40-60% | Profit-taking, raise cash |
| 0-19 | Critical | 25-40% | Capital preservation, watch for trough |

---

## Data Source

`scripts/breadth_engine.py` builds one row per session:
- `Breadth_Index_Raw`: share of stocks above their 200-day average (0 to 1)
- `Breadth_Index_8MA` and `Breadth_Index_200MA`: 8-day and 200-day EMA of the raw value
- `Breadth_200MA_Trend`: 1 when the 200MA rises, -1 when it falls (hysteresis 0.001)
- `Is_Peak`, `Is_Trough`, `Is_Trough_8MA_Below_04`: turning points
- `Bearish_Signal`: the 8MA crossed below the 200MA within 10 sessions while the 200MA trend is down
- `Nifty50_Price`: Nifty 50 close (^NSEI)

Uptrend rule (percent in uptrend): close above SMA20 and SMA200, SMA50 above SMA200,
close more than 30% above the 52-week low, and close above the close 20 sessions ago.
Base filters: close of at least Rs 50 and 50-day average volume of at least 100,000.

## Output Files

- JSON: `market_breadth_YYYY-MM-DD_HHMMSS.json`
- Markdown: `market_breadth_YYYY-MM-DD_HHMMSS.md`
- History: `market_breadth_history.json` (persists across runs, max 20 entries)

## Reference Documents

### `references/breadth_analysis_methodology.md`
- Full methodology with component scoring details
- Threshold explanations and zone definitions
- Historical context and interpretation guide

### When to Load References
- **First use:** Load methodology reference for framework understanding
- **Regular execution:** References not needed - script handles scoring

## Same-run provenance

Pass `--run-id daily-20261110-unique` to every market-regime script in one run.
JSON includes a `data_provenance` block with the primary data date, UTC retrieval time, source and run ID.
The time zone is Asia/Kolkata. Adjustment, point-in-time, survivorship and corporate-action flags are false.
A missing or malformed primary date stops report generation.

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
