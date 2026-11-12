# Minervini Breakout Entry Rules

## Entry Methodology

Mark Minervini's VCP breakout entry follows a strict sequence:

1. **Stage 2 confirmation** via Trend Template (7-10 point filter)
2. **VCP pattern** with contracting pullbacks and volume dry-up
3. **Pivot breakout** on above-average volume
4. **Tight stop** below last contraction low

## Trade Price Derivation

```
signal_entry = pivot * (1 + pivot_buffer_pct / 100)    # Buy-stop trigger
worst_entry  = pivot * (1 + max_chase_pct / 100)       # Buy-limit ceiling
stop_loss    = last_contraction_low * (1 - stop_buffer_pct / 100)
```

- **Gate and sizing use worst_entry** (worst-case fill price)
- **R-multiples displayed for both** signal and worst entries
- **Take-profit always uses worst_entry base**

## Risk Rules

- Maximum risk per trade: 8% from worst-case entry to stop
- Default account risk: 0.5% per trade
- Portfolio heat ceiling: 6% total open risk
- Never chase > 2% above pivot

## Rating-Based Sizing

| Rating Band | Score | Multiplier |
|------------|-------|------------|
| Textbook | 90+ | 1.75x |
| Strong | 80-89 | 1.0x |
| Good | 70-79 | 0.75x |
| Developing | 60-69 | 0.0x (watch only) |

## Entry Quality Checks

When confirming a breakout on 5-minute bars:

1. **close > pivot** - Bar closes above the pivot level
2. **close_loc >= 0.60** - Close in upper 60% of bar range
3. **RVOL >= 1.5** - Time-of-day relative volume above threshold
4. **chase <= 2%** - Price not more than 2% above pivot

## Order Proposal

The planner writes one bracket limit proposal per actionable plan in `trader/orders.json` shape:

- `type` is `limit` at `worst_entry`. This is the highest price the plan accepts.
- `stop_loss_stop_price` is the stop. `take_profit_limit_price` is the target.
- `exchange` is NSE. `product` is `delivery` or `intraday`. `time_in_force` is `day`.
- Send the proposal only after the entry quality checks pass on live bars.
- Stop must be at least one tick (Rs 0.05) below the entry limit.
- `trader-risk` checks the proposal against the user's limits. `trader-broker` places it.
