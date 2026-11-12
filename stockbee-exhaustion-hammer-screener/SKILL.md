---
name: stockbee-exhaustion-hammer-screener
description: Screen Nifty 500 stocks for Stockbee-style selling exhaustion hammer setups. Uses prior momentum, pullback depth, undercut and reclaim, lower-wick geometry, close location, volume, liquidity gates and risk distance scoring. Use for exhaustion setups, hammer reversals, undercut reclaim or near-close reversal candidates on NSE stocks.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# Stockbee Exhaustion Hammer Screener

Screen NSE equities (default universe: Nifty 500) for Stockbee-style selling-exhaustion hammer candidates. The skill is a candidate-generation and setup-quality workflow, not a signal service or an auto-execution system.

## When to Use

- User asks for Stockbee-style exhaustion setup screening
- User wants near-close hammer / long lower-wick reversal candidates
- User wants to scan strong, liquid stocks that pulled back and may be seeing selling exhaustion
- User wants undercut/reclaim candidates before the close or after the close
- User provides a symbol list, universe file, or historical / provisional OHLCV JSON for screening
- User wants candidate outputs to feed into `position-sizer` and then `trader-risk`

## Prerequisites

- No API key. Prices come from free Yahoo chart data. Index lists come from NSE.
- Python standard library only.
- Offline path: provide `--prices-json` containing daily OHLCV bars by symbol. For the intended near-close use case, the latest bar should be a provisional current-day bar captured near the close.
- Optional `--profiles-json` can add quality metadata such as `marketCap`, `mutualFundHolders`, `institutionalHolders`, or `institutionalOwnershipPct`.
- Run only after the market-regime workflow allows new swing risk, or mark output as manual-review-only.

## Workflow

### Step 1: Choose Input Mode

Use one of three modes:

**Mode A: Index universe scan (default nifty500)**
```bash
python3 stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py \
  --universe-name nifty500 \
  --max-symbols 500 \
  --market-gate allowed \
  --output-dir reports/
```

**Mode B: Explicit symbols**
```bash
python3 stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py \
  --symbols RELIANCE TATAMOTORS "M&M" INFY \
  --market-gate allowed \
  --output-dir reports/
```

**Mode C: Offline / near-close OHLCV JSON**
```bash
python3 stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py \
  --prices-json data/near_close_daily_ohlcv.json \
  --profiles-json data/quality_profiles.json \
  --market-gate allowed \
  --output-dir reports/
```

For a best-effort near-close run, use the quote override. It reuses the price download and depends on how fresh the Yahoo quote is:

```bash
python3 stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py \
  --universe-name nifty500 \
  --use-quote-latest \
  --max-api-calls 1200 \
  --market-gate allowed \
  --output-dir reports/
```

### Step 2: Run the Screening Pass

The script detects these setup families:

- **Selling exhaustion hammer:** long lower wick, small body, strong close-location, and recovery from the day low
- **Undercut/reclaim hammer:** current low undercuts the prior short-term low and the near-close price reclaims that level
- **Prior momentum pullback:** recent high formed within the configured lookback, followed by a controlled pullback rather than a long-term downtrend
- **High-quality / liquid context:** price, volume, 20-day average traded value, market-cap metadata, and optional holder metadata

It then scores setup quality using:

- Quality / liquidity
- Prior momentum
- Pullback and selling-exhaustion context
- Hammer candle geometry
- Risk distance to the day low plus buffer
- Market gate alignment

### Step 3: Review Output

Read the generated JSON and Markdown reports. For each candidate, present:

- Trigger type and all matched tags
- Pullback depth from recent high and days since that high
- Undercut/reclaim status and short-term prior low
- Hammer geometry: lower wick, body, upper wick, close location, recovery from low
- Volume ratios, average traded value, and quality metadata
- Entry reference, stop reference, and risk percentage to stop
- Setup score, rating, state, and reject reasons
- Suggested downstream action

### Step 4: Send Survivors to Trade Planning

Use the output conservatively:

- **A / A- candidates:** validate chart manually, check results and news risk, then send to `position-sizer`
- **B candidates:** manual review or next-day hammer-high confirmation
- **Watch candidates:** keep on watchlist / model book; wait for follow-through or tighter risk
- **Rejected candidates:** retain for post-analysis, not for execution

## Output

- `stockbee_exhaustion_hammer_YYYY-MM-DD_HHMMSS.json` - Structured candidate list, metadata, thresholds, score components, and rejects
- `stockbee_exhaustion_hammer_YYYY-MM-DD_HHMMSS.md` - Human-readable report grouped by rating/state

## Resources

- `references/exhaustion_hammer_methodology.md` - Stockbee-style method summary and implementation boundaries
- `references/scoring_system.md` - Component weights, state thresholds, and failure filters
- `references/near_close_operations.md` - Near-close operational checklist and scheduling notes

## Defaults for India

- Minimum price: Rs 100 (`--min-price`). Minimum volume: 100,000 shares (`--min-volume`).
- Minimum 20-day average traded value: Rs 10 crore (`--min-avg-dollar-volume`, in rupees).
- Market cap floor: Rs 10,000 crore (`--min-market-cap`). It applies only when `--profiles-json` supplies a market cap. The free source has none.
- Session is 09:15-15:30 IST. The near-close scan runs around 15:28 IST.

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
