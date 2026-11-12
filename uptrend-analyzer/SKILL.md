---
name: uptrend-analyzer
description: Diagnoses Indian market breadth from uptrend ratios computed for the Nifty 500 and 11 sectors. Gives a 0-100 score from 5 components (breadth, sector participation, rotation, momentum, history) with exposure guidance. No API key. Use when asked about breadth, uptrend ratios, or whether the market supports equity exposure.
---

# Uptrend Analyzer Skill

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Purpose

Diagnose breadth with the share of stocks in an uptrend, overall and per sector.
The script computes the ratio from Nifty 500 prices and gives a 0-100 composite score (higher is healthier) with exposure guidance.

The uptrend ratio needs the stock to meet all of these:
- close above SMA20 and SMA200, and SMA50 above SMA200
- close more than 30% above the 52-week low
- close above the close 20 sessions ago
- base filters: close at least Rs 50, 50-day average volume at least 100,000

NSE industries map to the 11 sector names used in the scoring (for example Information Technology to Technology, Power to Utilities).

## When to Use This Skill

- "Is market breadth healthy?" or "How broad is the rally?"
- Uptrend ratios across sectors
- Market participation and exposure guidance

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access to Yahoo (prices) and NSE (index lists)
- No API keys

## Difference from Market Top Detector

| Aspect | Uptrend Analyzer | Market Top Detector |
|--------|-----------------|-------------------|
| Score direction | Higher = healthier | Higher = riskier |
| Data | Computed breadth | Index prices and breadth |
| Focus | Breadth participation | Top formation risk |
| API key | Not required | Not required |

---

## Execution Workflow

### Phase 1: Run the script

```bash
python3 scripts/uptrend_analyzer.py --output-dir reports/
python3 scripts/uptrend_analyzer.py --universe nifty50 --max-symbols 5   # quick test
python3 scripts/uptrend_analyzer.py --refresh                            # ignore the cache
```

The first Nifty 500 run takes 3 to 5 minutes. The result is cached in `trader/cache/breadth.json`, shared with market-breadth-analyzer. Later runs on the same session date are fast.

The script will:
1. Compute uptrend ratios for the universe (or read the cache)
2. Calculate 5 component scores
3. Write the composite score and reports

### Phase 2: Present results

- Composite score and zone
- Exposure guidance (Full, Normal, Reduced, Defensive, Preservation)
- Sector heatmap with strongest and weakest sectors
- Key momentum and rotation signals

---

## 5-Component Scoring System

| # | Component | Weight | Key Signal |
|---|-----------|--------|------------|
| 1 | Market Breadth (Overall) | **30%** | Ratio level + trend direction |
| 2 | Sector Participation | **25%** | Uptrend sector count + ratio spread |
| 3 | Sector Rotation | **15%** | Cyclical vs Defensive balance |
| 4 | Momentum | **20%** | Slope direction + acceleration |
| 5 | Historical Context | **10%** | Percentile rank in history |

## Scoring Zones

| Score | Zone | Exposure Guidance |
|-------|------|-------------------|
| 80-100 | Strong Bull | Full Exposure (100%) |
| 60-79 | Bull | Normal Exposure (80-100%) |
| 40-59 | Neutral | Reduced Exposure (60-80%) |
| 20-39 | Cautious | Defensive (30-60%) |
| 0-19 | Bear | Capital Preservation (0-30%) |

### 7-Level Zone Detail

Each scoring zone is further divided into sub-zones for finer-grained assessment:

| Score | Zone Detail | Color |
|-------|-------------|-------|
| 80-100 | Strong Bull | Green |
| 70-79 | Bull-Upper | Light Green |
| 60-69 | Bull-Lower | Light Green |
| 40-59 | Neutral | Yellow |
| 30-39 | Cautious-Upper | Orange |
| 20-29 | Cautious-Lower | Orange |
| 0-19 | Bear | Red |

### Warning System

Active warnings trigger exposure penalties that tighten guidance even when the composite score is high:

| Warning | Condition | Penalty |
|---------|-----------|---------|
| **Late Cycle** | Commodity avg > both Cyclical and Defensive | -5 |
| **High Spread** | Max-min sector ratio spread > 40pp | -3 |
| **Divergence** | Intra-group std > 8pp, spread > 20pp, or trend dissenters | -3 |

Penalties stack (max -10) + multi-warning discount (+1 when ≥2 active). Applied after composite scoring.

### Momentum Smoothing

Slope values are smoothed using EMA(3) (Exponential Moving Average, span=3) before scoring. Acceleration is calculated by comparing the recent 10-point average vs prior 10-point average of smoothed slopes (10v10 window), with fallback to 5v5 when fewer than 20 data points are available.

### Historical Confidence Indicator

The Historical Context component includes a confidence assessment based on:
- **Sample size:** Number of historical data points available
- **Regime coverage:** Proportion of distinct market regimes (bull/bear/neutral) observed
- **Recency:** How recent the latest data point is

Confidence levels: High, Medium, Low.

---

## Data

No API keys. Prices come from Yahoo and constituents from NSE index lists through `scripts/india_client.py`.

## Output Files

- JSON: `uptrend_analysis_YYYY-MM-DD_HHMMSS.json`
- Markdown: `uptrend_analysis_YYYY-MM-DD_HHMMSS.md`

## Reference Documents

### `references/uptrend_methodology.md`
- Uptrend Ratio definition and thresholds
- 5-component scoring methodology
- Sector classification (Cyclical/Defensive/Commodity)
- Historical calibration notes

### When to Load References
- **First use:** Load `uptrend_methodology.md` for full framework understanding
- **Regular execution:** References not needed - script handles scoring

## Same-run provenance

Pass `--run-id daily-20261110-unique` to every market-regime script in one run.
JSON includes a `data_provenance` block with the data date, UTC retrieval time, source and run ID.
The time zone is Asia/Kolkata. Adjustment, point-in-time, survivorship and corporate-action flags are false.
Missing or malformed primary dates stop report generation.

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
