# Black-Scholes Methodology Reference

## Overview

The Black-Scholes model is the foundation for theoretical options pricing in this skill. This document provides the mathematical framework and interpretation guidance.

## Black-Scholes Formula

### Call Option Price
```
C = S × e^(-qT) × N(d₁) - K × e^(-rT) × N(d₂)
```

### Put Option Price
```
P = K × e^(-rT) × N(-d₂) - S × e^(-qT) × N(-d₁)
```

### Parameters
| Symbol | Description | Typical Range |
|--------|-------------|---------------|
| S | Current stock price | Market price |
| K | Strike price | User selected |
| T | Time to expiration (years) | 0.01 - 2.0 |
| r | Risk-free rate | 0.06 - 0.07 (default 0.065) |
| σ | Volatility | 0.10 - 1.00 |
| q | Dividend yield | 0.00 - 0.05 |

### d₁ and d₂ Calculations
```
d₁ = [ln(S/K) + (r - q + σ²/2) × T] / (σ × √T)
d₂ = d₁ - σ × √T
```

## The Greeks

### Delta (Δ)
- **Definition**: Price change per Rs 1 move in underlying
- **Call**: 0 to +1 (positive, bullish)
- **Put**: -1 to 0 (negative, bearish)
- **ATM options**: ~0.50 (call) or ~-0.50 (put)

### Gamma (Γ)
- **Definition**: Rate of change of delta
- **Always positive** for long options
- **Highest at ATM**, decreases as option moves ITM/OTM
- **Increases** as expiration approaches

### Theta (Θ)
- **Definition**: Daily time decay (Rs per day)
- **Negative** for long options (lose value daily)
- **Positive** for short options (collect decay)
- **Accelerates** in final 30 days

### Vega (ν)
- **Definition**: Price change per 1% IV move
- **Always positive** for long options
- **Highest at ATM**
- **Critical** for earnings plays

### Rho (ρ)
- **Definition**: Price change per 1% rate change
- **Positive** for calls, **negative** for puts
- **Small impact** in short-dated options

## Historical vs Implied Volatility

| Metric | Description | Source |
|--------|-------------|--------|
| HV (Historical) | Past price movement | Calculated from prices |
| IV (Implied) | Market expectation | Derived from option prices |

### IV-HV Relationship
- **IV > HV**: Options expensive → consider selling premium
- **IV < HV**: Options cheap → consider buying
- **IV ≈ HV**: Fairly priced

### IV Percentile Interpretation
| Percentile | Interpretation | Strategy Bias |
|------------|----------------|---------------|
| >80% | Very high IV | Sell premium |
| 50-80% | Elevated IV | Neutral/sell |
| 20-50% | Normal IV | Direction-based |
| <20% | Low IV | Buy premium |

## Model Limitations

### Assumptions (Not Always True)
1. **Constant volatility** - IV changes constantly
2. **European exercise** - NSE index options are European. Check the style of any other contract
3. **No transaction costs** - Commissions and slippage exist
4. **Continuous trading** - Gaps and halts occur
5. **Log-normal distribution** - Fat tails exist in practice

### When Model Underperforms
- Deep ITM options when early exercise is allowed (not the case for NSE index options)
- Near expiration with high gamma
- Earnings/events (IV regime change)
- Low liquidity options (wide bid-ask)

## Practical Adjustments

### Exercise style
- NSE index options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) are European. Black-Scholes applies directly.
- For other contracts, note "European pricing approximation" if early exercise is possible

### Dividend Handling
- Include dividend yield (q) in calculations
- For discrete dividends: subtract PV from stock price
- Ex-dividend dates move stock prices. Index dividend yield is small (about 1%)

## Strategy Selection Framework

### By Market Outlook
| Outlook | Delta Target | Strategies |
|---------|--------------|------------|
| Bullish | +0.3 to +0.7 | Long call, bull spread, covered call |
| Bearish | -0.3 to -0.7 | Long put, bear spread, protective put |
| Neutral | -0.1 to +0.1 | Iron condor, straddle, butterfly |

### By Volatility View
| IV View | Vega Target | Strategies |
|---------|-------------|------------|
| IV rising | Positive | Long straddle, long strangle |
| IV falling | Negative | Iron condor, short straddle |
| IV neutral | Near zero | Spreads, collars |

## Position Sizing Guidelines

### Risk-Based Sizing
```
Max Lots = (Account Risk in Rs) / (Max Loss per Lot)
```

### Portfolio Greeks Limits
| Greek | Conservative | Moderate | Aggressive |
|-------|--------------|----------|------------|
| Delta | ±10 | ±25 | ±50 |
| Theta | +Rs 500/day | +Rs 1,500/day | +Rs 3,000/day |
| Vega | +-Rs 2,000 | +-Rs 5,000 | +-Rs 10,000 |

## References

- Black, F. & Scholes, M. (1973). "The Pricing of Options and Corporate Liabilities"
- Hull, J.C. "Options, Futures, and Other Derivatives"
- NSE options contract specifications: https://www.nseindia.com
