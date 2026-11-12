---
name: position-sizer
description: Calculate risk-based position sizes for long NSE stock trades in whole shares. Supports fixed fractional, ATR-based and Kelly sizing, sector concentration limits, and F&O lot rounding (quantity in multiples of --lot-size). Use when the user asks how many shares to buy, risk per trade, Kelly sizing, ATR sizing, or how many lots of a futures or options contract.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# Position Sizer

## Overview

Calculate the optimal number of shares to buy for a long stock trade based on risk management principles. Supports three sizing methods:

- **Fixed Fractional**: Risk a fixed percentage of account equity per trade (default: 1%)
- **ATR-Based**: Use Average True Range to set volatility-adjusted stop distances
- **Kelly Criterion**: Calculate mathematically optimal risk allocation from historical win/loss statistics

All methods apply portfolio constraints (max position %, max sector %) and output a final recommended share count with full risk breakdown. Output is whole shares in rupees. NSE has no fractional shares. For F&O pass `--lot-size` and the quantity rounds down to a whole number of lots.

## When to Use

- User asks "how many shares should I buy?"
- User wants to calculate position size for a specific trade setup
- User mentions risk per trade, stop-loss sizing, or portfolio allocation
- User asks about Kelly Criterion or ATR-based position sizing
- User asks how many lots of an F&O contract fit the risk budget
- User wants to check if a position fits within portfolio concentration limits

## Prerequisites

- No API keys required
- Python 3.9+ with standard library only

## Workflow

### Step 1: Gather Trade Parameters

Collect from the user:
- **Required**: Account size (total equity)
- **Mode A (Fixed Fractional)**: Entry price, stop price, risk percentage (default 1%)
- **Mode B (ATR-Based)**: Entry price, ATR value, ATR multiplier (default 2.0x), risk percentage
- **Mode C (Kelly Criterion)**: Win rate, average win, average loss; optionally entry and stop for share calculation
- **Stop constraint**: `--stop` must be positive and below `--entry`
- **Optional constraints**: Max position % of account, max sector %, current sector exposure
- **Optional lot size**: F&O lot size with `--lot-size N`. Quantity is a multiple of N

If the user gives a ticker but no prices, ask for entry and stop. The user may also take them from a screener report or `trader-exit`.

### Step 2: Execute Position Sizer Script

Run the position sizing calculation:

```bash
# Fixed Fractional (most common)
python3 position-sizer/scripts/position_sizer.py \
  --account-size 1000000 \
  --entry 1550 \
  --stop 1485 \
  --risk-pct 1.0 \
  --output-dir reports/

# F&O lot rounding (lot of 75): 200 shares of risk room becomes 150 (2 lots)
python3 position-sizer/scripts/position_sizer.py \
  --account-size 10000000 \
  --entry 2500 \
  --stop 2450 \
  --risk-pct 1.0 \
  --lot-size 75 \
  --output-dir reports/

# ATR-Based
python3 position-sizer/scripts/position_sizer.py \
  --account-size 1000000 \
  --entry 1550 \
  --atr 32 \
  --atr-multiplier 2.0 \
  --risk-pct 1.0 \
  --output-dir reports/

# Kelly Criterion (budget mode - no entry)
python3 position-sizer/scripts/position_sizer.py \
  --account-size 1000000 \
  --win-rate 0.55 \
  --avg-win 2.5 \
  --avg-loss 1.0 \
  --output-dir reports/

# Kelly Criterion (shares mode - with entry/stop)
python3 position-sizer/scripts/position_sizer.py \
  --account-size 1000000 \
  --entry 1550 \
  --stop 1485 \
  --win-rate 0.55 \
  --avg-win 2.5 \
  --avg-loss 1.0 \
  --output-dir reports/
```

### Step 3: Load Methodology Reference

Read `references/sizing_methodologies.md` to provide context on the chosen method, risk guidelines, and portfolio constraint best practices.

### Step 4: Calculate Multiple Scenarios

If the user has not specified a single method, run multiple scenarios for comparison:
- Fixed Fractional at 0.5%, 1.0%, and 1.5% risk
- ATR-based at 1.5x, 2.0x, and 3.0x multipliers
- Present a comparison table showing shares, position value, and rupee risk for each

### Step 5: Apply Portfolio Constraints and Determine Final Size

Add constraints if the user has portfolio context:

```bash
python3 position-sizer/scripts/position_sizer.py \
  --account-size 1000000 \
  --entry 1550 \
  --stop 1485 \
  --risk-pct 1.0 \
  --max-position-pct 10 \
  --max-sector-pct 30 \
  --current-sector-exposure 22 \
  --output-dir reports/
```

Explain which constraint is binding and why it limits the position.

### Step 6: Generate Position Report

Present the final recommendation including:
- Method used and rationale
- Exact share count and position value
- Rupee risk and percentage of account
- Stop-loss price
- Any binding constraints
- Risk management reminders (portfolio heat, loss-cutting discipline)
- Reminders: brokerage, STT and other charges, slippage, margin limits for F&O, and intraday square-off times

## Output Format

All money fields are in rupees. Fields named `*_dollars` or `dollar_risk` hold rupee values (names kept for compatibility with other reports).

With `--lot-size`, `final_recommended_shares` is a multiple of the lot size, `final_lots` gives the lot count, and `constraints_applied` has a `lot_size` entry. The binding constraint is `lot_size` when only rounding reduced the size.

In risk-percentage mode (no Kelly inputs), when both `--stop` and `--atr` are supplied, the shares and `final_risk_*` figures follow the ATR-based method; the explicit `--stop` is ignored for risk reporting and the ATR-derived stop appears in `parameters.stop_price`. In Kelly shares mode the stop (or entry price) drives shares and risk instead, and ATR inputs are ignored. Risk and percentage round half-up.

### JSON Report

```json
{
  "schema_version": "1.0",
  "mode": "shares",
  "parameters": {
    "entry_price": 1550.0,
    "account_size": 100000,
    "stop_price": 1485.0,
    "risk_pct": 1.0
  },
  "calculations": {
    "fixed_fractional": {
      "method": "fixed_fractional",
      "shares": 153,
      "risk_per_share": 65.0,
      "dollar_risk": 1000.0,
      "stop_price": 1485.0
    },
    "atr_based": null,
    "kelly": null
  },
  "constraints_applied": [],
  "final_recommended_shares": 153,
  "final_position_value": 23715.0,
  "final_risk_dollars": 994.50,
  "final_risk_pct": 0.99,
  "binding_constraint": null
}
```

### Markdown Report

Generated automatically alongside the JSON report. Contains:
- Parameters summary
- Calculation details for the active method
- Constraints analysis (if any)
- Final recommendation with shares, value, and risk

Reports are saved to `reports/` with filenames `position_sizer_YYYY-MM-DD_HHMMSS.json` and `.md`.

## Resources

- `references/sizing_methodologies.md`: Comprehensive guide to Fixed Fractional, ATR-based, and Kelly Criterion methods with examples, comparison table, and risk management principles
- `scripts/position_sizer.py`: Main calculation script (CLI interface)

## Key Principles

1. **Survival first**: Position sizing is about surviving losing streaks, not maximizing winners
2. **The 1% rule**: Default to 1% risk per trade; never exceed 2% without exceptional reason
3. **Whole shares or whole lots**: NSE has no fractional shares. F&O quantity is a multiple of the lot size
4. **Floor, never round up**: Shares floor to an integer and lots floor to whole lots, so risk and concentration budgets are not exceeded
5. **Strictest constraint wins**: When multiple limits apply, the tightest one determines final size
6. **Half Kelly**: Never use full Kelly in practice; half Kelly captures 75% of growth with far less risk
7. **Portfolio heat**: Total open risk should not exceed 6-8% of account equity
8. **Intraday rules are broker-specific**: Intraday (MIS) positions square off at the broker's cutoff. Check margin and cutoff times before sizing intraday trades.
9. **Asymmetry of losses**: A 50% loss requires a 100% gain to recover; size accordingly

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
