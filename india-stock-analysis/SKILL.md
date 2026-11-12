---
name: india-stock-analysis
description: Analyzes NSE-listed stocks. Builds a data pack (price, technical indicators, NSE announcements, corporate actions, results dates) with a script, then applies fundamental, technical, comparison and report frameworks. Use for "analyze RELIANCE", "compare TCS vs INFY", technical levels, valuation questions or a full report on an Indian stock.
---

# India Stock Analysis

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Overview

Analyze NSE stocks with four modes: basic info, fundamental, technical and a comprehensive report. Compare two or more stocks side by side.
Amounts are in rupees (`Rs 1,250`). Large figures use Rs crore. Times are IST. The NSE session runs 09:15-15:30.

## Data Sources

Run the data pack script first:

```bash
python3 scripts/stock_snapshot.py RELIANCE
python3 scripts/stock_snapshot.py TCS INFY --json
python3 scripts/stock_snapshot.py HDFCBANK --announcements 15
```

It reads, with no keys:
1. **Price and quote:** Yahoo through `scripts/india_client.py` (NSE symbols such as `RELIANCE`, `M&M`)
2. **Technicals:** SMA20/50/200, RSI14, MACD, Bollinger, ATR, 52-week range, returns, volume trend, support and resistance
3. **NSE corporate announcements:** results, board outcomes, investor meets, filings
4. **NSE corporate actions:** dividends, splits, bonus, rights, with ex-dates
5. **Results dates:** NSE board meeting calendar
6. **Industry:** from the NSE index lists

**Fundamentals are not scraped.** Revenue, profit, margins and debt are not in the pack. Use these routes:
- Read the financial results filing linked in the announcements (the `file` URL).
- Ask the user to paste key figures from the exchange filing or their own data source.
- State plainly which numbers are missing. Never invent them.

Always state the date of the data. Say when an announcement is older than one quarter.

## Analysis Types

1. **Basic Stock Info** - quick overview with key metrics
2. **Fundamental Analysis** - business, financials, valuation (needs user-supplied figures)
3. **Technical Analysis** - trend, indicators, levels
4. **Comprehensive Investment Report** - all of the above

## Analysis Workflows

### 1. Basic Stock Information

1. Run the data pack.
2. Present: company and industry, price and day change, 52-week range, returns, trend, recent announcements and any upcoming results date.

### 2. Fundamental Analysis

1. Run the data pack. Read the latest results filing if present.
2. Read `references/fundamental-analysis.md` for the framework and `references/financial-metrics.md` for formulas.
3. Assess business quality, profitability trends, cash flow quality, balance sheet strength, growth and valuation (P/E, P/B, EV/EBITDA versus history and peers).
4. India checks: promoter holding and pledging, related-party dealings, auditor remarks, contingent liabilities, dividend history from corporate actions.
5. List risks and red flags. Mark each missing input.
6. Write the output with `references/report-template.md`.

### 3. Technical Analysis

1. Use the technicals in the pack. Read `references/technical-analysis.md`.
2. Identify the trend, support and resistance, indicator signals (RSI above 70 or below 30, MACD cross, Bollinger squeeze) and volume confirmation.
3. Give key levels, a stop-loss reference (for example 1.5 to 2 times ATR), and short and medium-term outlook.
4. Note corporate actions: an ex-date gap can look like a price drop.

### 4. Comprehensive Investment Report

1. Combine the data pack, fundamental and technical work.
2. Read `references/report-template.md`.
3. Give bull and bear cases, a rating, a target range with timeframe, conviction and an entry plan.
4. Include: executive summary, company overview, thesis, fundamentals, technicals, valuation, risks, catalysts and conclusion.
5. Send sizing to trader-risk. Never place orders from this skill.

## Stock Comparison

1. Run the data pack for every symbol (`stock_snapshot.py TCS INFY`).
2. Read both fundamental references.
3. Build side-by-side tables: business model, valuation, growth, profitability, balance sheet, technical position.
4. State where each stock is stronger, with numbers.
5. Follow "Comparison Report Structure" in `references/report-template.md`.

## Output Guidelines

- Tables for metrics and comparisons. Bold key findings.
- Include data sources and dates.
- Show bull and bear views. State assumptions and gaps.
- Currency: `Rs`, with crore for large amounts.
- Objective tone. Support each claim with data.

## Reference Files

- `references/technical-analysis.md` - indicators, patterns, levels
- `references/fundamental-analysis.md` - business quality, financial health, valuation, red flags
- `references/financial-metrics.md` - formulas for key ratios
- `references/report-template.md` - report and comparison structure

## Example Queries

- "Quick overview of HDFCBANK"
- "Analyze Infosys financials" (provide the results figures)
- "Technical analysis of TATAMOTORS"
- "Complete analysis of RELIANCE"
- "Compare TCS vs INFY"

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
