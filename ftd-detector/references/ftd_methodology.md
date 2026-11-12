# Follow-Through Day (FTD) Methodology

## Overview

The Follow-Through Day (FTD) is William O'Neil's market timing signal for confirming a new uptrend after a correction. It is the **single most important signal** for re-entering the market after a decline. Without an FTD, no new bull market or sustained rally has ever begun (per IBD historical analysis).

**Key Insight:** FTD is a necessary but not sufficient condition. Historically, approximately 25% of FTDs lead to sustained uptrends. The remaining 75% fail, which is why quality scoring and post-FTD monitoring are critical.

---

## Step 1: Identify the Correction

### Qualifying Correction
A correction must meet these criteria before FTD analysis begins:

- **Decline magnitude:** Index closes 3% or more below its recent high
- **Duration:** At least 3 down days during the decline
- **Index scope:** Nifty 50 and/or Midcap 150 Composite (either suffices)

### Swing Low Definition
The swing low is the lowest closing price during the correction that becomes the reference point for the rally attempt:

- Must be preceded by 3%+ decline from a recent high (within 40 trading days)
- Must have at least 3 down days between the high and the low
- Must be a local minimum (adjacent days have higher closes)
- Multiple swing lows can occur; use the most recent qualifying one

**Important:** The swing low is determined by *closing price*, not intraday low.

---

## Step 2: Rally Attempt (Day 1-3)

### Day 1 Detection
Day 1 marks the beginning of a rally attempt. It occurs on the **first qualifying up day** after the swing low:

**Primary criterion:** Close > Previous day's close (up day)

**Alternative criterion:** Close in the top 50% of the day's price range
- Formula: (Close - Low) / (High - Low) >= 0.50
- This captures days where the market recovers significantly from intraday lows even if it doesn't close above the prior day's close

### Day 2-3 Integrity Check
For the rally attempt to remain valid through Day 2-3:

- **Close must not breach Day 1's intraday low** (not the close, the *low*)
- This is a strict rule; even a single day closing below Day 1's low invalidates the attempt
- Day 2 and Day 3 do NOT need to be up days; they just cannot close below Day 1's low

### Rally Invalidation (Reset)
The rally attempt resets completely if:

1. **Any day's close falls below the swing low price** → Start over from new potential swing low
2. **Day 2 or Day 3 closes below Day 1's intraday low** → Wait for new Day 1

When a rally resets, the new lower price may become the new swing low, and the cycle begins again.

---

## Step 3: FTD Window (Day 4-10)

### FTD Qualification Criteria
A Follow-Through Day must satisfy ALL of these conditions:

1. **Day 4-10** of the rally attempt (Day 4-7 is the prime window; Day 8-10 still valid)
2. **Price gain >= 1.25%** (minimum threshold)
   - 1.25-1.49%: Minimum qualifying gain
   - 1.50-1.99%: Recommended gain (higher reliability)
   - 2.00%+: Strong signal
3. **Volume > previous day's volume** (mandatory)
   - This confirms institutional participation
   - Volume does not need to exceed the 50-day average, though it's a positive if it does

### Day Counting Rules
- Day 1 = first qualifying up day after swing low
- Day 2, 3, etc. = every subsequent trading day (regardless of whether it's up or down)
- Days count continues as long as the rally is not invalidated
- The FTD itself must be an up day meeting the gain and volume requirements

### Prime vs Late Window

**Day 4-7 (Prime):**
- Historically higher success rate
- Base quality score: 60 points
- Institutional buyers are more likely to have conviction

**Day 8-10 (Late):**
- Still valid but statistically weaker
- Base quality score: 50 points
- May indicate hesitant institutional buying

**After Day 10:**
- No longer qualifies as a traditional FTD
- Rally without FTD by Day 10 is a warning sign
- May still develop into an uptrend but reliability drops significantly

---

## Step 4: Dual-Index Confirmation

### Single-Index FTD
An FTD on either the Nifty 50 or Midcap 150 is sufficient to trigger the signal. The signal is actionable on a single-index confirmation.

### Dual-Index FTD
When both Nifty 50 and Midcap 150 produce FTDs (within a few days of each other):
- Significantly higher reliability
- Quality score bonus: +15 points
- Indicates broader institutional conviction
- Both growth and value participants are buying

### Index Discrepancy
When one index confirms FTD but the other is still in rally attempt or correction:
- FTD is still valid from the confirming index
- Monitor the lagging index for convergence or divergence
- Divergence (one fails while other holds) is a cautionary signal

---

## Quality Score Framework

### Score Components (0-100)

| Factor | Criteria | Points |
|--------|----------|--------|
| **Base (FTD Day)** | Day 4-7 | 60 |
| | Day 8-10 | 50 |
| **Price Gain** | >= 2.0% | +15 |
| | >= 1.5% | +10 |
| | >= 1.25% | +5 |
| **Volume vs 50-day Avg** | Above average | +10 |
| | Below average | +0 |
| **Dual Index Confirm** | Both Nifty 50 + Midcap 150 | +15 |
| | Single index | +0 |
| **Post-FTD Health** | No distribution (5 days) | +10 |
| | Distribution Day 4-5 | -5 |
| | Distribution Day 3 | -15 |
| | Distribution Day 1-2 | -30 |

### Interpretation

| Score | Signal | Recommended Exposure |
|-------|--------|---------------------|
| 80-100 | Strong FTD | 75-100% equity |
| 60-79 | Moderate FTD | 50-75% equity |
| 40-59 | Weak FTD | 25-50% equity |
| < 40 | No FTD / Failed | 0-25% equity |

---

## Studying Past FTDs

The rules were first described on US indices. To see how they behave on Indian data, find a past low and read the state machine output:

- Pick a swing low on the Nifty 50 (for example the March 2020 low or the June 2022 low).
- Run the detector with data ending a few weeks after that low.
- Check the day count, the gain on the FTD day, the volume rule and the distribution days that follow.

Patterns seen across markets:
- Day 4-7 FTDs with a gain of 1.5% or more on rising volume work best.
- Several failed rally attempts often come before a successful one.
- An FTD in a hostile environment (rising rates, heavy foreign selling) fails more often. Check FII/DII flows.

---

## Common Mistakes

1. **Buying before FTD confirmation:** Acting on Day 1-3 before FTD is confirmed
2. **Ignoring volume:** A large gain without volume increase is NOT an FTD
3. **Counting wrong:** Including non-trading days or resetting day count incorrectly
4. **Single vs. dual index:** Treating a single-index FTD as equivalent to a Nifty 50 plus Midcap 150 confirmation
5. **Ignoring post-FTD distribution:** Not monitoring for early distribution days
6. **FTD ≠ all clear:** Treating FTD as guarantee rather than probability shift
