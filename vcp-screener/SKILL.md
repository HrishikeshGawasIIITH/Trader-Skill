---
name: vcp-screener
description: Screen Nifty 500 stocks for the Minervini Volatility Contraction Pattern (VCP). Finds Stage 2 uptrend stocks with tight bases near a breakout pivot. A single-ticker history mode lists past VCPs with forward outcomes. Use for VCP scans, tight base setups, Stage 2 momentum scans, or a VCP study of one NSE stock such as TATAMOTORS.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# VCP Screener - Minervini Volatility Contraction Pattern

Screen Nifty 500 stocks for Mark Minervini's Volatility Contraction Pattern (VCP), identifying Stage 2 uptrend stocks with contracting volatility near breakout pivot points.

## When to Use

- User asks for VCP screening or Minervini-style setups
- User wants to find tight base / volatility contraction patterns
- User requests Stage 2 momentum stock scanning
- User asks for breakout candidates with defined risk
- User asks "find every historical VCP in <TICKER>" or wants to study one ticker's
  past VCP setups with forward outcomes (`--history --ticker SYM`)

## Prerequisites

- No API key. Data comes from free Yahoo chart prices and NSE index lists.
- Python standard library only.
- The client pauses 0.3 seconds between calls. A full Nifty 500 run takes several minutes.
- Prices are in rupees (Rs). Relative strength is measured against the Nifty 50 (`^NSEI`).

## Workflow

### Step 1: Prepare and Execute Screening

Run the VCP screener script:

```bash
# Default: Nifty 500, top 100 candidates
python3 vcp-screener/scripts/screen_vcp.py --output-dir reports/

# Another index: nifty50, midcap150, smallcap250
python3 vcp-screener/scripts/screen_vcp.py --universe-name nifty50 --output-dir reports/

# Custom symbols
python3 vcp-screener/scripts/screen_vcp.py --universe RELIANCE TCS INFY HDFCBANK --output-dir reports/

# Analyze every stock that passes the pre-filter
python3 vcp-screener/scripts/screen_vcp.py --full-universe --output-dir reports/
```

### Strict Mode (Minervini pure setup)

Only return stocks with `valid_vcp=True` AND `execution_state` in `(Pre-breakout, Breakout)`:

```bash
python3 vcp-screener/scripts/screen_vcp.py --strict --output-dir reports/
```

### Historical single-ticker mode

Walk one ticker's multi-year history, detect every VCP that ever formed, and
attach forward-outcome stats (breakout / stop-hit / timeout, days-to-outcome,
max gain, max loss) per detection. Useful for pattern study and backtesting
context — not a real-time screener.

```bash
# Default: scan ~5 years (1260 trading days), 5-day stride, 60-day outcome window
python3 vcp-screener/scripts/screen_vcp.py \
  --history --ticker TATAMOTORS --output-dir reports/

# Custom scan length: 750 trading days (~3 years), 90-day outcome window
python3 vcp-screener/scripts/screen_vcp.py \
  --history 750 --ticker RELIANCE \
  --stride-days 5 --outcome-days 90 \
  --output-dir reports/

# Long scan: 10 years (2520 trading days)
python3 vcp-screener/scripts/screen_vcp.py \
  --history 2520 --ticker HDFCBANK --output-dir reports/
```

Outputs (timestamped):
- `vcp_history_<SYM>_<YYYY-MM-DD_HHMMSS>.json` — timeline of detections with full
  analyzer payload + `forward_outcome` per detection + summary stats.
- `vcp_history_<SYM>_<YYYY-MM-DD_HHMMSS>.md` — human-readable timeline.

Mode-specific flags:

| Parameter | Default | Range | Effect |
|-----------|---------|-------|--------|
| `--history [DAYS]` | (off) / 1260 if bare | 100-5040 | Enable historical mode; optionally specify trading-day scan window (requires `--ticker`) |
| `--ticker SYM` | — | — | Ticker to scan |
| `--stride-days` | 5 | 1-60 | Trading-day step between as-of cursor positions |
| `--outcome-days` | 60 | 5-252 | Forward window evaluated per detection |

Notes:
- Two data calls per scan (ticker and Nifty 50 history), not 100+ like the
  cross-sectional pipeline.
- Market cap is not available from the free source. Reports show N/A.
- `marketCap` and absolute RS percentile reflect the ticker in isolation,
  not against the live screening universe — use this report for pattern
  study, not portfolio sizing.
- Detections are deduplicated by `(T1_high_date, last_low_date, pivot)` so
  the same VCP isn't reported repeatedly as the cursor ages.

### Advanced Tuning (for backtesting)

Adjust VCP detection parameters for research and backtesting:

```bash
python3 vcp-screener/scripts/screen_vcp.py \
  --min-contractions 3 \
  --t1-depth-min 12.0 \
  --breakout-volume-ratio 2.0 \
  --trend-min-score 90 \
  --atr-multiplier 1.5 \
  --output-dir reports/
```

| Parameter | Default | Range | Effect |
|-----------|---------|-------|--------|
| `--min-contractions` | 2 | 2-4 | Higher = fewer but higher-quality patterns |
| `--t1-depth-min` | 10.0% | 1-50 | Higher = excludes shallow first corrections |
| `--breakout-volume-ratio` | 1.5x | 0.5-10 | Higher = stricter volume confirmation |
| `--trend-min-score` | 85 | 0-100 | Higher = stricter Stage 2 filter |
| `--atr-multiplier` | 1.5 | 0.5-5 | Lower = more sensitive swing detection |
| `--contraction-ratio` | 0.70 | 0.1-1 | Lower = requires tighter contractions |
| `--min-contraction-days` | 5 | 1-30 | Higher = longer minimum contraction |
| `--lookback-days` | 120 | 30-365 | Longer = finds older patterns |
| `--max-sma200-extension` | 50.0% | — | SMA200 distance threshold for Overextended state and penalty |
| `--wide-and-loose-threshold` | 15.0% | — | Final contraction depth above which wide-and-loose flag triggers |
| `--strict` | off | — | Minervini strict mode: only Pre-breakout or Breakout with valid VCP |

### Step 2: Review Results

1. Read the generated JSON and Markdown reports
2. Load `references/vcp_methodology.md` for pattern interpretation context
3. Load `references/scoring_system.md` for score threshold guidance

### Step 3: Present Analysis

For each top candidate, present:
- **Quality** (`composite_score` / rating) — how well-formed is the VCP pattern?
- **Execution State** (`execution_state`) — is it buyable now? (Pre-breakout / Breakout = actionable)
- **Pattern Type** (`pattern_type`) — Textbook VCP / VCP-adjacent / Post-breakout / Extended Leader / Damaged
- `★` marker if a State Cap was applied (raw score was downgraded)
- Contraction details (T1/T2/T3 depths and ratios)
- Trade setup: pivot price, stop-loss, risk percentage
- Volume dry-up ratio and breakout_volume_score
- Relative strength rank

### Step 4: Provide Actionable Guidance

**By Execution State (primary filter):**
- **Pre-breakout / Breakout:** Pattern is in the active entry window — apply rating-based sizing
- **Early-post-breakout:** Breakout underway but above ideal entry — reduced size or wait for pullback
- **Extended / Overextended:** Trade missed — add to watchlist for next base
- **Damaged / Invalid:** Setup invalidated — do not enter

**By Rating (secondary, after state confirms actionability):**
- **Textbook VCP (90+):** Buy at pivot with aggressive sizing (1.5-2x)
- **Strong VCP (80-89):** Buy at pivot with standard sizing (1x)
- **Good VCP (70-79):** Buy on volume confirmation above pivot (0.75x)
- **Developing (60-69):** Add to watchlist, wait for tighter contraction
- **Weak/No VCP (<60):** Monitor only or skip

## 3-Phase Pipeline

1. **Pre-Filter** - Quote-based screening (price above Rs 50, average volume above 100,000, 52-week position)
2. **Trend Template** - 7-point Stage 2 filter with 260-day histories
3. **VCP Detection** - Pattern analysis, scoring, report generation (no additional data calls)

## Output

- `vcp_screener_YYYY-MM-DD_HHMMSS.json` - Structured results
- `vcp_screener_YYYY-MM-DD_HHMMSS.md` - Human-readable report

## Resources

- `references/vcp_methodology.md` - VCP theory and Trend Template explanation
- `references/scoring_system.md` - Scoring thresholds and component weights

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
