---
name: market-top-detector
description: Assesses heuristic market top risk for the Indian market using Nifty 50 distribution days, leading-stock deterioration in the Nifty Midcap 150, defensive sector rotation, computed breadth and India VIX. Gives a 0-100 composite score with a risk zone. No API key. Use for market top risk, distribution days, leadership breakdown or when to cut equity exposure. Targets 2-8 week timing for 10-20% corrections.
---

# Market Top Detector Skill

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Purpose

Assess heuristic market top risk using a 6-component scoring system (0-100). Integrates three market risk methodologies:

1. **O'Neil** - Distribution Day accumulation (institutional selling)
2. **Minervini** - Leading stock deterioration pattern
3. **Defensive sector rotation** - capital moving from growth to defensive sectors

This skill focuses on **tactical 2-8 week timing signals** that precede 10-20% market corrections.

## Score interpretation

Treat the 0-100 composite as a **heuristic risk score**, not an estimated event
probability. A score of 70 does not mean a 70% chance of a top. Risk-budget
percentages are policy heuristics, not measured outcome frequencies.
Historical patterns are retrospective estimates, not point-in-time evidence.
Report **no comparable episode** when any component is unavailable/invalid or
nearest-pattern weighted RMS exceeds 15 points. This tolerance is a predeclared
heuristic, not an empirically validated similarity threshold.
Follow [the point-in-time evaluation protocol](references/point_in_time_evaluation.md)
before making calibration claims. No measured calibration results are supplied.

## When to Use This Skill

- "Is the market topping?" or "Are we near a top?"
- Distribution days accumulating on the Nifty
- Defensive sectors (FMCG, Pharma) outperforming growth sectors
- Leading stocks breaking down while the indices hold
- Timing to reduce equity exposure
- Correction risk for the next 2-8 weeks

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access to Yahoo (prices) and NSE (index lists)
- No API keys

Breadth is computed from Nifty 500 prices and cached in `trader/cache/breadth.json`.
Put/Call ratio, VIX term structure and margin debt have no free Indian feed. They are optional manual inputs.

---

## Execution Workflow

### Phase 1: Optional manual inputs

These have no free Indian feed. Skip them when you do not have them. Data should be from the last 3 business days.

```
1. [OPTIONAL] Nifty Put/Call ratio (PCR)
   Valid range: 0.30-1.50
   Source: NSE option chain (index options). Record the data date.

2. [OPTIONAL] India VIX term structure
   Values: steep_contango / contango / flat / backwardation
   Only if you track VIX futures yourself.

3. [OPTIONAL] Margin funding data (YoY %)
   Record the reporting month. Usually lagged 1-2 months.
```

Breadth (percent above 200DMA and 50DMA) is computed from prices automatically.
Override with `--breadth-200dma` and `--breadth-50dma`. Skip the computation with `--no-auto-breadth`.

### Phase 2: Run the script

```bash
python3 scripts/market_top_detector.py \
  --put-call [VALUE] --put-call-date [YYYY-MM-DD] \
  --vix-term [steep_contango|contango|flat|backwardation] \
  --margin-debt-yoy [VALUE] --margin-debt-date [YYYY-MM-DD] \
  --output-dir reports/ \
  --context "FII net flow=[VALUE]" "Nifty PE=[VALUE]"

# Quick test with a small universe
python3 scripts/market_top_detector.py --max-symbols 20 --output-dir reports/
```

The script will:
1. Fetch Nifty 50 (`^NSEI`) quote and history, India VIX (`^INDIAVIX`)
2. Build an equal-weight Nifty Midcap 150 composite (price relatives, summed volume)
3. Pick leaders: the Midcap 150 stocks closest to their 52-week highs
4. Fetch sector indices: defensive (FMCG, Pharma, Energy) and offensive (IT, Media, Auto, Midcap 150)
5. Compute breadth from Nifty 500 prices (cached)
6. Calculate all 6 components and write the composite score and reports

The first run fetches about 650 symbols (5 to 8 minutes). Later runs on the same session date reuse the breadth cache.
A trailing bar with zero volume is dropped.

### Phase 3: Present Results

Present the generated Markdown report to the user, highlighting:
- Composite score and risk zone
- Data freshness warnings (if any data older than 3 days)
- Strongest warning signal (highest component score)
- Historical comparison (closest past top pattern)
- What-if scenarios (sensitivity to key changes)
- Recommended actions based on risk zone
- Follow-Through Day status (if applicable)
- Delta vs previous run (if prior report exists)

---

## 6-Component Scoring System

| # | Component | Weight | Data Source | Key Signal |
|---|-----------|--------|-------------|------------|
| 1 | Distribution Day Count | **25%** | Nifty 50 + Midcap 150 composite | Institutional selling in last 25 trading days |
| 2 | Leading Stock Health | **20%** | Midcap 150 leaders | Leader deterioration |
| 3 | Defensive Sector Rotation | **15%** | NSE sector indices | Defensive vs growth relative performance |
| 4 | Market Breadth Divergence | **15%** | Computed from Nifty 500 | 200DMA and 50DMA breadth vs index level |
| 5 | Index Technical Condition | **15%** | Nifty 50 + Midcap 150 composite | MA structure, failed rallies, lower highs |
| 6 | Sentiment & Speculation | **10%** | India VIX + manual | India VIX, Put/Call, term structure |

## Risk Zone Mapping

| Score | Zone | Risk Budget | Action |
|-------|------|-------------|--------|
| 0-20 | Green (Normal) | 100% | Normal operations |
| 21-40 | Yellow (Early Warning) | 80-90% | Tighten stops, reduce new entries |
| 41-60 | Orange (Elevated Risk) | 60-75% | Profit-taking on weak positions |
| 61-80 | Red (High Risk) | 40-55% | Aggressive profit-taking |
| 81-100 | Critical (Very High Risk) | 20-35% | Maximum defense, hedging |

---

## Calendar and Replay

Freshness counts weekdays. NSE trading holidays are not subtracted. `--as-of YYYY-MM-DD` is accepted for
the live evaluation date (IST). A historical live replay fails closed because the quote data is not point-in-time.

## Keys

None needed.

## Output Files

- JSON: `market_top_YYYY-MM-DD_HHMMSS.json`
- Markdown: `market_top_YYYY-MM-DD_HHMMSS.md`

## Reference Documents

### `references/market_top_methodology.md`
- Full methodology with O'Neil, Minervini and defensive rotation frameworks
- Component scoring details and thresholds
- Historical validation notes

### `references/distribution_day_guide.md`
- Detailed O'Neil Distribution Day rules
- Stalling day identification
- Follow-Through Day (FTD) mechanics

### `references/historical_tops.md`
- Four reference top patterns (blow-off, slow crisis, fast sell-off, rate-hike)
- Heuristic component estimates for each pattern

### When to Load References
- **First use:** Load `market_top_methodology.md` for full framework understanding
- **Distribution day questions:** Load `distribution_day_guide.md`
- **Pattern comparison:** Load `historical_tops.md`
- **Regular execution:** References not needed - script handles scoring

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
