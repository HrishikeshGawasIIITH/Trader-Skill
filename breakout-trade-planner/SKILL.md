---
name: breakout-trade-planner
description: Turn VCP screener output into Minervini-style breakout trade plans for NSE stocks. Calculates worst-case risk, whole-share position size and portfolio heat. Writes bracket order proposals in trader/orders.json shape. It places nothing. trader-risk checks the proposals and trader-broker places them. Use when the user has VCP screener results and wants entry, stop and target levels with sizing.
---

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

# Breakout Trade Planner

Generate trade plans from VCP screener output following Mark Minervini's breakout methodology. Calculate position sizes using worst-case entry prices, enforce portfolio risk limits, and write order proposals in `trader/orders.json` shape. The planner places no orders. `trader-risk` checks each proposal. `trader-broker` places it.

## When to Use

- User has VCP screener JSON output and wants trade plans
- User asks for breakout entry/stop/target calculation
- User wants order proposals for VCP breakout candidates
- User needs position sizing with portfolio heat management

## Prerequisites

- VCP screener JSON output with `schema_version: "1.0"`
- No API keys required (works with local JSON files)
- Run `vcp-screener` first. Its JSON is the input.
- No external skill dependencies (position sizing is built-in)

## Workflow

### Step 1: Generate Trade Plans

Run the planner with VCP screener output:

```bash
python3 breakout-trade-planner/scripts/plan_breakout_trades.py \
  --input reports/vcp_screener_YYYY-MM-DD.json \
  --account-size 1000000 \
  --risk-pct 0.5 \
  --product delivery \
  --output-dir reports/
```

The run writes a JSON plan, a Markdown report and `orders_proposal_<time>.json`. The proposal file holds `{"orders": [...]}`. Copy it to `trader/orders.json` only when the user agrees. Then run `trader-risk`, then `trader-broker`.: Review Output

Read the generated JSON and Markdown reports. Present:

1. **Actionable Orders** — Pre-breakout candidates with order proposals
2. **Revalidation** — Breakout-state candidates needing live confirmation
3. **Watchlist** — Developing VCP candidates to monitor
4. **Rejected/Deferred/Constrained** — Candidates filtered by Gate or portfolio limits
### Step 3: Explain Trade Plans

For each actionable order, explain:
- Entry levels (signal vs worst-case) and stop-loss placement
- R-multiple targets and reward-risk ratio
- The order proposal and the entry condition to confirm first
- Portfolio risk contribution and cumulative heat
- Proposals are not broker permission. `trader-risk` applies the user's limits. `trader-broker` asks the user before any order goes out.

## Order proposal format

Each actionable plan carries `order_proposal`. Every value is a string:

```json
{"symbol": "SBIN", "exchange": "NSE", "product": "delivery", "side": "buy", "qty": "20",
 "type": "limit", "time_in_force": "day", "limit_price": "800.00", "order_class": "bracket",
 "stop_loss_stop_price": "790.00", "take_profit_limit_price": "820.00"}
```

- The entry is a limit at the worst-case entry. It is the highest price the plan accepts.
- Send the proposal only after the plan's `entry_condition` passes on live 5-minute bars (close above pivot, close in the upper part of the bar, relative volume of 1.5 or more, price within the chase limit).
- Revalidation (Breakout-state) candidates get no order proposal.
- `--product` is `delivery` (default) or `intraday`. Intraday orders must be flat by the broker's cutoff.
- Quantities are whole shares. For F&O lot sizes use `position-sizer --lot-size`.
- Prices round to the NSE tick of Rs 0.05.

## Minervini Gate (Filtering Criteria)

Candidates must pass ALL conditions:

| Condition | Pre-breakout | Breakout |
|-----------|-------------|----------|
| valid_vcp | True | True |
| rating_band | good/strong/textbook | good/strong/textbook |
| risk_pct_worst | <= 8.0% | <= 8.0% |
| breakout_volume | — | True |
| distance_from_pivot | — | <= max_chase_pct |
| current_price | — | <= worst_entry |

## CLI Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| --account-size | (required) | Account equity in rupees |
| --risk-pct | 0.5 | Base risk % per trade |
| --max-position-pct | 10.0 | Max single position % |
| --max-sector-pct | 30.0 | Max sector exposure % |
| --max-portfolio-heat-pct | 6.0 | Max total open risk % |
| --target-r-multiple | 2.0 | Take-profit R-multiple |
| --stop-buffer-pct | 1.0 | Stop buffer below contraction low |
| --max-chase-pct | 2.0 | Max chase above pivot |
| --pivot-buffer-pct | 0.1 | Pivot buffer for buy-stop trigger |
| --current-exposure-json | None | Existing portfolio exposure |
| --product | delivery | `delivery` or `intraday` for the proposals |
| --orders-out | output dir | Where to write the `{"orders": [...]}` file |
| --holidays | none | Comma-separated NSE holiday dates for the session calendar |

## Output

- `breakout_trade_plan_YYYY-MM-DD_HHMMSS.json` — Structured plans with order proposals
- `breakout_trade_plan_YYYY-MM-DD_HHMMSS.md` — Human-readable report
- `orders_proposal_YYYY-MM-DD_HHMMSS.json` — Proposals in `trader/orders.json` shape

## Session Calendar and Replay

`--as-of` accepts `YYYY-MM-DD` (00:00 IST) or an offset-bearing ISO-8601 timestamp. Plan validity uses the current not-yet-closed NSE session (09:15-15:30 IST) or the next session after the close, a weekend or a holiday. The calendar works offline and knows weekends only. Pass `--holidays 2026-11-14,2026-12-25` for exchange holidays.

## Resources

- `references/minervini_entry_rules.md` — Entry methodology and rules

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
