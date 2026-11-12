---
name: ftd-detector
description: Detects Follow-Through Day (FTD) signals that confirm a market bottom, using William O'Neil's method on Indian indices. Tracks Nifty 50 and an equal-weight Nifty Midcap 150 composite with a state machine for rally attempt, FTD qualification and post-FTD health. No API key. Use for market bottom signals, rally attempts or re-entry timing after a correction. Complements market-top-detector.
---

# FTD Detector Skill

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Purpose

Detect Follow-Through Day signals that confirm a market bottom. The score runs 0 to 100 with exposure guidance for re-entry after a correction.

- Market Top Detector is defensive. It detects distribution, rotation and deterioration.
- FTD Detector is offensive. It detects rally attempts and bottom confirmation.

## When to Use This Skill

- "Is the market bottoming?" or "Is it safe to buy again?"
- A correction of 3% or more and the user wants re-entry timing
- Follow-Through Days or rally attempts
- Whether a recent bounce is sustainable
- Raising equity exposure after a correction

## Difference from Market Top Detector

| Aspect | FTD Detector | Market Top Detector |
|--------|-------------|-------------------|
| Focus | Bottom confirmation (offensive) | Top detection (defensive) |
| Trigger | Correction (3%+ decline) | Market at or near highs |
| Signal | Rally attempt, FTD, re-entry | Distribution, deterioration, exit |
| Score | 0-100 FTD quality | 0-100 top probability |
| Action | When to raise exposure | When to cut exposure |

---

## Execution Workflow

### Phase 1: Run the script

```bash
python3 scripts/ftd_detector.py --output-dir reports/
python3 scripts/ftd_detector.py --max-symbols 20   # quick test with a small composite
```

The script will:
1. Fetch Nifty 50 (`^NSEI`) history (60+ sessions) and the current quote
2. Build an equal-weight Nifty Midcap 150 composite from its constituents (price relatives, summed volume)
3. Run the dual-index state machine (correction, rally, FTD detection)
4. Assess post-FTD health (distribution days, invalidation, power trend)
5. Calculate the quality score (0-100)
6. Write JSON and Markdown reports

A trailing bar with zero volume (today's unfinished bar) is dropped before analysis.
The first run fetches about 150 stocks (under a minute). Prices come from Yahoo through `scripts/india_client.py`.

### Phase 2: Present results

- Current market state (correction, rally attempt, FTD confirmed and so on)
- Quality score and signal strength
- Recommended exposure level
- Key watch levels (swing low, FTD day low)
- Post-FTD health (distribution days, power trend)

### Phase 3: Contextual guidance

**If FTD confirmed (score 60+):**
- Look at leading stocks in proper bases
- Size positions with trader-risk and set stops

**If rally attempt (Day 1-3):**
- Be patient and do not buy ahead of the FTD
- Build watchlists

**If no correction:**
- FTD analysis does not apply in an uptrend
- Use Market Top Detector for defensive signals

---

## State Machine

```
NO_SIGNAL → CORRECTION → RALLY_ATTEMPT → FTD_WINDOW → FTD_CONFIRMED
                ↑              ↓               ↓              ↓
                └── RALLY_FAILED ←─────────────┘     FTD_INVALIDATED
```

| State | Definition |
|-------|-----------|
| NO_SIGNAL | Uptrend, no qualifying correction |
| CORRECTION | 3%+ decline with 3+ down days |
| RALLY_ATTEMPT | Day 1-3 of rally from swing low |
| FTD_WINDOW | Day 4-10, waiting for qualifying FTD |
| FTD_CONFIRMED | Valid FTD signal detected |
| RALLY_FAILED | Rally broke below swing low |
| FTD_INVALIDATED | Close below FTD day's low |

## Quality Score (0-100)

| Score | Signal | Exposure |
|-------|--------|----------|
| 80-100 | Strong FTD | 75-100% |
| 60-79 | Moderate FTD | 50-75% |
| 40-59 | Weak FTD | 25-50% |
| <40 | No FTD / Failed | 0-25% |

---

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access to Yahoo (prices) and NSE (index lists)
- No API keys

## Output Files

- JSON: `ftd_detector_YYYY-MM-DD_HHMMSS.json`
- Markdown: `ftd_detector_YYYY-MM-DD_HHMMSS.md`

## Reference Documents

### `references/ftd_methodology.md`
- O'Neil's FTD rules in detail
- Rally attempt mechanics and day counting
- How to study past FTDs on Indian data

### `references/post_ftd_guide.md`
- Post-FTD distribution day failure rates
- Power Trend definition and conditions
- Success vs failure pattern comparison

### When to Load References
- **First use:** Load `references/ftd_methodology.md` for full understanding
- **Post-FTD questions:** Load `references/post_ftd_guide.md`
- **Regular execution:** References not needed - script handles analysis

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
