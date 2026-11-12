---
name: sector-analyst
description: Analyzes sector rotation in the Indian market. Computes uptrend ratios for 11 sectors from Nifty 500 stocks, adds NSE sectoral index performance, ranks sectors, scores cyclical versus defensive risk regime, flags overbought and oversold sectors and estimates the market cycle phase. No API key. Optional chart images add detail.
---

# Sector Analyst

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Overview

This skill analyzes sector rotation and market cycle position for NSE stocks.
It computes the uptrend ratio of each sector, ranks sectors, scores cyclical versus defensive balance,
flags overbought and oversold sectors and estimates the cycle phase.
It also reports 1-week, 1-month and 3-month performance of NSE sectoral indices.
Chart images can add industry-level detail.

## When to Use This Skill

- Sector rotation analysis (no chart images needed)
- Cyclical versus defensive positioning
- Which sectors are overbought or oversold
- Market cycle phase estimation
- Sector performance charts for extra detail

Example requests:
- "Run a sector rotation analysis"
- "Which sectors are leading, cyclical or defensive?"
- "Are any sectors overbought right now?"
- "What phase of the market cycle are we in?"

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access to Yahoo (prices) and NSE (index lists)
- No API keys
- Optional: sector performance chart images

## Data Source

- Sector uptrend ratios: computed from Nifty 500 stock prices by `scripts/breadth_engine.py`. NSE industries map to 11 sector names. Cached in `trader/cache/breadth.json`, shared with market-breadth-analyzer and uptrend-analyzer.
- NSE sectoral indices (Yahoo symbols): Nifty IT `^CNXIT`, Auto `^CNXAUTO`, FMCG `^CNXFMCG`, Pharma `^CNXPHARMA`, Financial Services `NIFTY_FIN_SERVICE.NS`, Bank `^NSEBANK`, PSU Bank `^CNXPSUBANK`, Metal `^CNXMETAL`, Realty `^CNXREALTY`, Energy `^CNXENERGY`, Infrastructure `^CNXINFRA`, Media `^CNXMEDIA`.

## Running the Script

```bash
# Default: compute ratios, print a readable analysis
python3 scripts/analyze_sector_rotation.py

# JSON output
python3 scripts/analyze_sector_rotation.py --json

# Save to file
python3 scripts/analyze_sector_rotation.py --save --output-dir reports/

# Quick test with a small universe
python3 scripts/analyze_sector_rotation.py --universe nifty50 --max-symbols 5
```

The first Nifty 500 run takes 3 to 5 minutes. Later runs on the same session date use the cache.

## Analysis Workflow

Follow this structured workflow:

### Step 1: Data Collection

1. Run the analysis script: `python3 scripts/analyze_sector_rotation.py`
2. Extract from the output:
   - Sector ranking by uptrend ratio
   - Risk regime (cyclical vs defensive) and score
   - Overbought/oversold sectors
   - Cycle phase estimate and confidence level
3. If a data freshness warning appears, note it in the analysis

### Step 2: Market Cycle Assessment

Use the script's cycle phase estimate as a starting point:
- Read `references/sector_rotation.md` to access market cycle and sector rotation frameworks
- Compare the script's quantitative findings against expected patterns for each cycle phase:
  - Early Cycle Recovery
  - Mid Cycle Expansion
  - Late Cycle
  - Recession
- Add qualitative interpretation informed by the knowledge base

If chart images are provided, use them to supplement with industry-level detail:
- Extract industry-level performance data from chart images
- Compare 1-week vs 1-month performance for trend consistency
- Note specific industries showing strength or weakness within sectors

### Step 3: Current Situation Analysis

Synthesize observations into an objective assessment:
- State which market cycle phase current performance most closely resembles
- Highlight supporting evidence (which sectors/industries confirm this view)
- Note any contradictory signals or unusual patterns
- Assess confidence level based on consistency of signals

Use data-driven language and specific references to performance figures.

### Step 4: Scenario Development

Based on sector rotation principles and current positioning, develop 2-4 potential scenarios for the next phase:

For each scenario:
- Describe the market cycle transition
- Identify which sectors would likely outperform
- Identify which sectors would likely underperform
- Specify the catalysts or conditions that would confirm this scenario
- Assign a probability (see Probability Assessment Framework in sector_rotation.md)

Scenarios should range from most likely (highest probability) to alternative/contrarian scenarios.

### Step 5: Output Generation

Create a structured Markdown document with the following sections:

**Required Sections:**
1. **Executive Summary**: 2-3 sentence overview of key findings
2. **Current Situation**: Detailed analysis of current performance patterns and market cycle positioning
3. **Supporting Evidence**: Specific sector and industry performance data supporting the cycle assessment
4. **Scenario Analysis**: 2-4 scenarios with descriptions and probability assignments
5. **Recommended Positioning**: Strategic and tactical positioning recommendations based on scenario probabilities
6. **Key Risks**: Notable risks or contradictory signals to monitor

## Output Format

Save analysis results as a Markdown file with naming convention: `sector_analysis_YYYY-MM-DD.md`

Use this structure:

```markdown
# Sector Performance Analysis - [Date]

## Executive Summary

[2-3 sentences summarizing key findings]

## Current Situation

### Market Cycle Assessment
[Which cycle phase and why]

### Performance Patterns Observed

#### 1-Week Performance
[Analysis of recent performance]

#### 1-Month Performance
[Analysis of medium-term trends]

#### Sector-Level Analysis
[Detailed breakdown by sector]

#### Industry-Level Analysis
[Notable industry-specific observations]

## Supporting Evidence

### Confirming Signals
- [List data points supporting cycle assessment]

### Contradictory Signals
- [List any conflicting indicators]

## Scenario Analysis

### Scenario 1: [Name] (Probability: XX%)
**Description**: [What happens]
**Outperformers**: [Sectors/industries]
**Underperformers**: [Sectors/industries]
**Catalysts**: [What would confirm this scenario]

### Scenario 2: [Name] (Probability: XX%)
[Repeat structure]

[Additional scenarios as appropriate]

## Recommended Positioning

### Strategic Positioning (Medium-term)
[Sector allocation recommendations]

### Tactical Positioning (Short-term)
[Specific adjustments or opportunities]

## Key Risks and Monitoring Points

[What to watch that could invalidate the analysis]

---
*Analysis Date: [Date]*
*Data Period: [Timeframe of charts analyzed]*
```

## Key Analysis Principles

When conducting analysis:

1. **Objectivity First**: Let the data guide conclusions, not preconceptions
2. **Probabilistic Thinking**: Express uncertainty through probability ranges
3. **Multiple Timeframes**: Compare 1-week and 1-month data for trend confirmation
4. **Relative Performance**: Focus on relative strength, not absolute returns
5. **Breadth Matters**: Broad-based moves are more significant than isolated movements
6. **No Absolutes**: Markets rarely follow textbook patterns exactly
7. **Historical Context**: Reference typical rotation patterns but acknowledge uniqueness

## Probability Guidelines

Apply these probability ranges based on evidence strength:

- **70-85%**: Strong evidence with multiple confirming signals across sectors and timeframes
- **50-70%**: Moderate evidence with some confirming signals but mixed indicators
- **30-50%**: Weak evidence with limited or conflicting signals
- **15-30%**: Speculative scenario contrary to current indicators but possible

Total probabilities across all scenarios should sum to approximately 100%.

## Resources

### scripts/
- `analyze_sector_rotation.py` - Computes sector ratios, rankings, risk regime, overbought and oversold flags, cycle phase and index performance. No API key.
- `breadth_engine.py` - Computes breadth from stock prices and manages the cache.
- `india_client.py` - Yahoo and NSE data client.

### references/
- `sector_rotation.md` - Market cycle phases, typical sector patterns, probability framework and India notes

## Important Notes

- All analysis and output are in English
- Reference the sector rotation knowledge base for each analysis
- Maintain objectivity and avoid confirmation bias
- Update probabilities if new data arrives
- Chart images are optional. The computed data is the primary input
- The sector classification matches uptrend-analyzer

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
