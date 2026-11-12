# Market Top Detection Methodology

## Overview

This framework integrates three approaches to market top detection, each targeting different aspects of institutional behavior that precede significant market declines (10-20% corrections).

## The Three Pillars

### Pillar 1: O'Neil - Distribution Day Accumulation

**Source:** William O'Neil, "How to Make Money in Stocks"

**Core Concept:** Institutional investors (mutual funds, hedge funds, pensions) cannot sell their large positions in a single day. Their selling creates a distinctive pattern: the index declines on higher-than-previous-day volume. When these "distribution days" accumulate, it signals that smart money is systematically exiting.

**Distribution Day Definition:**
- Index declines >= 0.2% from previous close
- Volume is higher than previous day's volume
- Both conditions must be met simultaneously

**Stalling Day Definition:**
- Volume increases from previous day
- But price gain is minimal (< 0.1%)
- Indicates institutional selling into strength
- Counted at half weight (0.5 distribution days)

**25-Day Window:**
- Distribution days expire after 25 trading days
- Only the rolling 25-day count matters
- This prevents old events from distorting current assessment

**O'Neil's Warning Thresholds:**
- 4-5 distribution days in 25 trading days = "market under pressure"
- 6+ distribution days = "distribution is heavy, protect capital"
- Combined with stalling days for full picture

### Pillar 2: Minervini - Leading Stock Deterioration

**Source:** Mark Minervini, "Trade Like a Stock Market Wizard" / "Think & Trade Like a Champion"

**Core Concept:** Market tops do not appear suddenly. They develop through a process where leading stocks - the strongest performers of the previous rally - begin breaking down before the major indices. This is because institutional investors sell their biggest winners first to lock in profits.

**Key Observation:** In the early stage of a bear market, some leading stocks appear to resist the downtrend. They keep rising while the rest of the market weakens.

**Detection Method (India):**
- Default (dynamic): the 10 Nifty Midcap 150 constituents closest to their 52-week high
- Static option (`--static-basket`): NSE growth and cyclical indices (Nifty IT, Auto, Financial Services, Bank, Infrastructure, Metal, Realty, PSU Bank)

**Deterioration Signals per leader:**
1. Distance from 52-week high (>10% = concerning, >25% = bear territory)
2. Price below 50-day moving average
3. Price below 200-day moving average
4. Formation of lower highs pattern

**Amplification Rule:** When 60%+ of leaders show deterioration, the signal is amplified by 1.3x. This reflects the systemic nature of leadership breakdown.

### Pillar 3: Defensive Sector Rotation

**Core Concept:** Before a market top, capital flows from offensive/growth sectors into defensive sectors. Institutions turn defensive while they keep their equity allocation. It is an early warning signal.

**Defensive indices (Safety Seekers):**
- Nifty FMCG (consumer staples, recession-resistant demand)
- Nifty Pharma (healthcare, non-discretionary spending)
- Nifty Energy (utilities proxy; there is no standalone utilities index)

**Offensive indices (Growth/Risk):**
- Nifty IT (growth-dependent)
- Nifty Media (communication services, ad-spend sensitive)
- Nifty Auto (consumer discretionary, economically sensitive)
- Nifty Midcap 150 (broad growth proxy)

**Signal:** When defensive sectors outperform offensive sectors over a 20-day rolling period, capital is flowing defensively. A relative performance spread of +3% or more is a strong warning signal.

---

## Supplementary Components

### Component 4: Market Breadth Divergence

**Concept:** When the index makes new highs but fewer stocks participate, the rally is narrowing and vulnerable. This "divergence" between index price and market breadth is a classic top signal.

**Key Metric:** Percentage of Nifty 500 stocks above their 200-day moving average (computed from prices).
- Healthy market: >70% of stocks above 200DMA
- Warning zone: 50-70% with index near highs
- Critical: <50% with index at highs

**Important Nuance:** Breadth divergence is most meaningful when the index is near its 52-week high (within -5%). If the index has already corrected significantly, weak breadth is expected and less informative.

### Component 5: Index Technical Condition

**Moving Average Structure:**
- Healthy: Price > 21 EMA > 50 EMA > 200 SMA
- Deteriorating: Any of these relationships inverting
- Bearish: Price below all major moving averages

**Pattern Recognition:**
- Failed Rally: Price bounces but fails to exceed recent peak
- Lower Highs: Sequential swing highs declining
- Gap Downs on Volume: Institutional panic selling

### Component 6: Sentiment & Speculation

**India VIX (Fear Index):**
- <12: Extreme complacency (warning)
- 12-16: Low volatility (mild warning)
- 16-20: Normal
- >25: Fear elevated (top less likely, correction may be underway)

**Put/Call Ratio:**
- <0.60: Extreme call buying (maximum complacency)
- 0.60-0.70: Elevated optimism
- 0.70-0.80: Mildly bullish
- >0.80: Healthy caution

**India VIX Term Structure:**
- Steep Contango: Market expects calm (complacency signal)
- Backwardation: Hedging demand elevated (fear present)

---

## Follow-Through Day (FTD) Monitor

O'Neil's concept for bottom confirmation, relevant when composite score > 40:

1. **Rally Attempt Day:** First day the index closes up after a decline
2. **Counting begins:** Day 1 of potential new uptrend
3. **Follow-Through Day:** On days 4-7 of rally attempt, a strong gain (1.5%+) on higher volume than previous day
4. **Significance:** "The most powerful uptrends usually begin with a Follow-Through Day on day 4-7"

**False FTD Rate:** Approximately 25% of FTDs fail. Multiple FTDs increase confidence.

---

## Scoring Philosophy

### Why Weighted Composite?

No single indicator perfectly predicts market tops. Each pillar captures a different dimension:
- Distribution Days: Direct measurement of institutional selling
- Leading Stocks: Quality of market leadership
- Defensive Rotation: Institutional positioning shift
- Breadth: Market participation health
- Technicals: Price structure integrity
- Sentiment: Psychological extremes

### Weight Rationale

- **Distribution Days (25%):** Most direct measure of institutional behavior
- **Leading Stocks (20%):** Minervini's strongest conviction signal
- **Defensive Rotation (15%):** Capital flow into defensive sectors
- **Breadth (15%):** Classic confirmation signal
- **Technicals (15%):** Structural integrity check
- **Sentiment (10%):** Context and extremes (less reliable alone)

### Heuristic Design Targets

The heuristic scoring was designed around the following illustrative targets; these are not measured calibration results:
- A "normal" healthy market scores 10-20
- An "early warning" market scores 25-40
- A market in the "initial to middle stage of top formation" scores 40-55
- A clear top formation scores 60-80
- A completed top with breakdown scores 80+
