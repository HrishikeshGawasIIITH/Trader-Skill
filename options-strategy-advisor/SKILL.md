---
name: options-strategy-advisor
description: Options strategy analysis for NSE index and stock options. Prices with Black-Scholes (European style), computes Greeks, simulates strategy profit and loss per lot, and gives risk management guidance. Reads lot sizes from the NSE F&O file. Use for covered calls, protective puts, spreads, straddles, iron condors, results-season plays and options risk questions. Educational, theoretical pricing.
---

# Options Strategy Advisor

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Overview

This skill explains and simulates options strategies with theoretical prices. It needs no options-data subscription.

**Core capabilities:**
- **Black-Scholes pricing** and Greeks (stdlib only, `scripts/black_scholes.py`)
- **Strategy simulation:** profit and loss per lot for the main strategies
- **Results-season strategies:** pre-results volatility plays (use the earnings-calendar skill for dates)
- **Risk management:** position sizing, Greeks exposure, maximum loss and profit

**India specifics:**
- NSE index options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) are **European-style**. Black-Scholes applies directly.
- Contracts trade in **lots**. Lot sizes come from `https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv` and change often. Always read the current file.
- Default **risk-free rate is 6.5%** (India 91-day T-bill). The user can override it.
- Prices are in rupees. Write amounts as `Rs 1,250`.
- Index options settle in cash. Check your broker for the settlement rules of stock options.

**Data sources (no keys):**
- Spot and history: `scripts/india_client.py` (Yahoo)
- Lot sizes: NSE F&O lot file
- Implied volatility: user input from the broker option chain. If it is missing, use historical volatility.

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access for spot, history and lot sizes (optional if you type the inputs)

## Quick Start

```bash
# Price one strike with lot size and Greeks
python3 scripts/black_scholes.py --symbol NIFTY --spot 24500 --strike 24600 --days 14 --iv 14

# Fetch spot and 30-day historical volatility
python3 scripts/black_scholes.py --symbol RELIANCE --strike 1500 --days 21 --live

# Override the risk-free rate (percent)
python3 scripts/black_scholes.py --symbol NIFTY --spot 24500 --strike 24600 --days 14 --iv 14 --rate 6.8
```

Library use:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from black_scholes import OptionPricer, fetch_lot_sizes, lot_size

pricer = OptionPricer(S=24500, K=24600, T=14 / 365, r=0.065, sigma=0.14)
greeks = pricer.get_all_greeks("call")
lots = fetch_lot_sizes()
print(greeks["price"], lot_size("NIFTY", lots))
```

`T` is in years. Rates, volatility and dividend yield are annual decimals. The model assumes constant volatility and rates.

## When to Use This Skill

- "What is a covered call?" or "How does an iron condor work?"
- "What is my maximum profit on a Nifty bull call spread?"
- "What is my delta exposure?"
- "Should I buy a straddle before results?"
- "Covered call or protective put for downside protection?"
- "How many lots should I trade?"
- "Is implied volatility high right now?"

## Supported Strategies

### Income
1. **Covered Call** - own the stock, sell a call
2. **Cash-Secured Put** - sell a put with cash set aside
3. **Poor Man's Covered Call** - long-dated deep ITM call plus a short near-term call

### Protection
4. **Protective Put** - own the stock, buy a put
5. **Collar** - own the stock, sell a call, buy a put

### Directional
6. **Bull Call Spread** - buy a lower call, sell a higher call
7. **Bull Put Spread** - sell a higher put, buy a lower put
8. **Bear Call Spread** - sell a lower call, buy a higher call
9. **Bear Put Spread** - buy a higher put, sell a lower put

### Volatility
10. **Long Straddle** - buy ATM call and put
11. **Long Strangle** - buy OTM call and put
12. **Short Straddle** - sell ATM call and put (unlimited risk)
13. **Short Strangle** - sell OTM call and put

### Range-bound
14. **Iron Condor** - bull put spread plus bear call spread
15. **Iron Butterfly** - sell ATM straddle, buy OTM strangle

### Advanced
16. **Calendar Spread** - sell near, buy far
17. **Diagonal Spread** - calendar with different strikes
18. **Ratio Spread** - unbalanced legs

## Analysis Workflow

### Step 1: Gather inputs

**Required from the user:** underlying (NIFTY, BANKNIFTY or a stock), strategy, strikes, expiry (days), number of lots.
**Optional:** implied volatility (default: 30-day historical volatility), risk-free rate (default 6.5%), dividend yield (default 0).
**Fetched:** spot, history and the lot size.

Example input:
```
Underlying: NIFTY
Strategy: Bull Call Spread
Long strike: 24500, Short strike: 24700
Expiry: 14 days
Lots: 1 (lot size 65 from the NSE file)
IV: 14%
```

### Step 2: Historical volatility (if IV is not given)

```python
from black_scholes import fetch_historical_prices_for_hv, calculate_historical_volatility

closes = fetch_historical_prices_for_hv("NIFTY", days=90)   # oldest first
hv = calculate_historical_volatility(closes, window=30)     # annualized
```

Tell the user: "HV = 13.2%. Use the IV from your broker option chain for better accuracy." India VIX (`^INDIAVIX`) is the market's 30-day implied volatility for Nifty. It is a good IV input for Nifty options.

### Step 3: Price each leg

European model:
```
Call = S * N(d1) - K * e^(-rT) * N(d2)
Put  = K * e^(-rT) * N(-d2) - S * N(-d1)
d1 = [ln(S/K) + (r + sigma^2/2) * T] / (sigma * sqrt(T))
d2 = d1 - sigma * sqrt(T)
```
`OptionPricer` implements this with `math.erf` for the normal CDF. Dividends enter as a continuous yield `q`.

Example, NIFTY 24,500, 14 days, IV 14%, rate 6.5%:

| Strike | Call | Put |
|--------|------|-----|
| 24,300 | Rs 416.8 | Rs 156.3 |
| 24,500 | Rs 299.3 | Rs 238.3 |
| 24,700 | Rs 205.2 | Rs 343.6 |

Note: market prices differ because of the bid-ask spread and the volatility skew.

### Step 4: Greeks

| Greek | Meaning | Example (one NIFTY lot of 65) |
|-------|---------|-------------------------------|
| **Delta** | Exposure to spot | 0.54 means Rs 35 gain per Rs 1 rise |
| **Gamma** | Delta change per Rs 1 | 0.00059 |
| **Theta** | Decay per calendar day | -Rs 11.8 per unit, about -Rs 769 per lot per day |
| **Vega** | Per 1% change in IV | Rs 19.0 per unit, about Rs 1,237 per lot |
| **Rho** | Per 1% change in rate | Rs 5.0 per unit |

Sum Greeks across legs, with a sign for long (+) and short (-). Multiply by the lot size and the number of lots.

### Step 5: Simulate profit and loss

Generate a spot range (for example +-10% for Nifty, +-30% for a stock). For each price at expiry:
```python
def pnl(legs, spot_at_expiry, lot_size, lots):
    total = 0.0
    for leg in legs:
        intrinsic = max(0, spot_at_expiry - leg.strike) if leg.type == "call" else max(0, leg.strike - spot_at_expiry)
        total += (intrinsic - leg.premium) if leg.position == "long" else (leg.premium - intrinsic)
    return total * lot_size * lots
```

Key metrics: maximum profit, maximum loss, breakevens, risk/reward, rough probability of profit.

Example, Bull Call Spread 24,500/24,700 (1 lot of 65):
```
Net debit: 299.3 - 205.2 = Rs 94.1 per unit = Rs 6,117 per lot
Max profit: (200 - 94.1) x 65 = Rs 6,884 at 24,700 and above
Max loss: Rs 6,117 at 24,500 and below
Breakeven: 24,594
Risk/Reward: 1 : 1.1
```

Add brokerage, STT and exchange charges. They matter for small spreads. Check the current STT rules for options exercised at expiry.

### Step 6: ASCII P/L diagram

Plot P/L against spot, mark breakevens and the current spot:
```
P/L (Rs)
 +6,884 |                    ________
        |                  /
      0 |----------------*------------ spot
        |              /
 -6,117 |_____________/
        24,500   24,594   24,700
```

### Step 7: Strategy-specific guidance

**Covered Call** (stock ABC at Rs 1,000, lot 500, sell the 1,050 call for Rs 12.2, 30 days, IV 25%)
```
Max profit: (50 + 12.2) x 500 = Rs 31,100 if ABC closes at 1,050 or above
Max loss: large (the stock falls); the premium cushions Rs 12.2 per share
Breakeven: Rs 987.8
Greeks per lot: delta falls from 500 to about 358; theta +Rs 225/day
Assignment: stock options on NSE settle physically. Plan for delivery if ABC > 1,050 at expiry.
Use when: neutral to mildly bullish, you accept selling at 1,050
Exit: buy back the call on a strong rally, let it expire if ABC stays below 1,050, roll to keep the shares
```

**Protective Put** (own 1 lot ABC at Rs 1,000, buy the 950 put for Rs 8.5)
```
Max loss: (50 + 8.5) x 500 = Rs 29,250
Breakeven: Rs 1,008.5
Net delta: about 0.80 per share
Use when: you hold the stock and fear a short-term drop, or results are near
Cost: the premium is insurance; it decays if the stock rises
```

**Iron Condor** (NIFTY 24,500, 14 days, IV 14%, 1 lot of 65)
```
Sell 24000 put at 74.0, buy 23900 put at 55.7, sell 25000 call at 106.0, buy 25100 call at 82.9
Net credit: 41.4 per unit = Rs 2,691 per lot
Max profit: Rs 2,691 if Nifty stays between 24,000 and 25,000
Max loss: (100 - 41.4) x 65 = Rs 3,809
Breakevens: 23,959 and 25,041
Greeks: delta near 0, theta positive, vega negative (short volatility)
Use when: you expect a range and implied volatility is high
Rules: close at 50% of the credit; cut the loss at 2x the credit; roll the tested side
```

**Long Straddle** (NIFTY 24,500 call + put, 14 days)
```
Cost: 299.3 + 238.3 = Rs 537.6 per unit = Rs 34,944 per lot
Breakevens: 23,962 and 25,038 (a move of about 2.2%)
Use when: you expect a larger move than the market implies (events, results)
Risk: theta and a fall in IV hurt the position every day
```

### Step 8: Results-season strategies

For a stock with results in the next 1-2 weeks, get the date from the earnings-calendar skill (NSE board meeting calendar).

- **Long straddle or strangle:** profits if the move beats what the options price in. IV usually falls after results (IV crush).
- **Iron condor or short strangle:** profits if the move is smaller than priced. Gaps beyond the wings lose the maximum.
- **Compare the implied move** (straddle price / spot) with the stock's past results-day moves.

Avoid buying options with high IV when you expect a normal move. Avoid short strangles without defined risk.

### Step 9: Risk management

**Position sizing (lots):**
```
Account: Rs 5,00,000, risk per trade 2% = Rs 10,000
Iron condor max loss per lot: Rs 3,809 -> 2 lots (Rs 7,618)
Bull call spread debit per lot: Rs 6,117 -> 1 lot
```
Final sizing goes through trader-risk. Orders go through trader-broker only.

**Portfolio Greeks:** keep net delta small relative to capital, prefer positive theta only with defined risk, and watch net vega when India VIX moves.

**Exit rules:**
- Covered call: take 50-75% of maximum profit; roll at 7-10 days to expiry
- Spreads: close at 50% of maximum profit; cut a loss at 2x the debit; avoid the last week (gamma risk)
- Iron condor: close at 50% of the credit; cut when one side is tested
- Straddle or strangle: close after the event

**Expiry mechanics:** index options are cash-settled and European. Weekly and monthly expiry days differ by index. Confirm the current expiry day, lot size and margin with your broker.

## Output Format

Save the analysis as `options_analysis_[SYMBOL]_[Strategy]_[YYYY-MM-DD].md`.

```markdown
# Options Strategy Analysis: [Strategy Name]

**Underlying:** [SYMBOL]  **Spot:** Rs [price]
**Expiry:** [date] ([DTE] days)  **Lots:** [n] (lot size [size])
**IV used:** [x]%  **Risk-free rate:** [r]%

## Legs
| Leg | Type | Strike | Price | Position | Lots |

## Profit and Loss
Max profit, max loss, breakevens, risk/reward (all in Rs per lot and total)

## P/L Diagram

## Greeks (position)
Delta, gamma, theta per day, vega per 1% IV, rho

## Risk
Maximum risk, margin note, expiry and settlement notes

## Trade Management
Entry, profit taking, stop loss, adjustments

## Suitability
When to use, when to avoid
```

## Key Principles

**Black-Scholes limits:**
1. Constant volatility. Real IV changes and has a skew.
2. No transaction costs. STT, brokerage and exchange fees are real.
3. European exercise. This fits NSE index options. Check the style for other contracts.
4. Continuous trading and a smooth price path. Gaps (budget day, results) break this.

**Real versus theoretical:** the bid-ask spread raises the real cost. Far OTM and far-month strikes can be illiquid. Treat the theoretical price as a mid-market guide.

**Historical versus implied volatility:**
- IV above HV: options look expensive (consider selling premium with defined risk)
- IV below HV: options look cheap (consider buying)
- India VIX above 20 is high for recent years. Below 12 is low. Check the one-year range before judging.

**IV percentile:** compare the current IV with a one-year series of 30-day HV values (or the India VIX history from `^INDIAVIX`). Above the 75th percentile favors selling premium. Below the 25th favors buying.

## Integration with Other Skills

- **earnings-calendar:** results dates and days to results
- **technical-analyst:** support and resistance for strike selection
- **market-top-detector, ftd-detector:** market risk context for protective or bullish structures
- **trader-risk:** final position sizing
- **trader-broker:** the only path for orders

## Troubleshooting

- **IV not available:** use HV and say so. Ask the user for the broker IV or use India VIX for Nifty.
- **Lot size not found:** the symbol may not be in F&O. Check the NSE file.
- **Negative or zero price:** check strike versus spot and the days to expiry.
- **Greeks look wrong:** check T (years), sigma (decimal) and r (decimal).
- **Strategy too complex:** break it into legs and sum the results.

## Resources

- `references/black_scholes_methodology.md` - formulas, Greeks and interpretation
- `scripts/black_scholes.py` - pricing engine, Greeks, lot sizes, CLI
- `scripts/india_client.py` - Yahoo and NSE data client

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
