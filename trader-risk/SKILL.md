---
name: trader-risk
description: >-
  Risk Manager for NSE and BSE trading. Checks every trade against your limits and stops anything
  over them, before it can reach the broker. For an intraday trade: a stop is
  required, the loss at the stop must fit your max loss per trade (measured
  from the higher of the plan's entry and a fresh price), reward:risk must
  meet your minimum, the day's total risk must fit your daily loss limit, no
  more than your trades per day, and no new entries outside your entry
  window or when the market is closed. It also keeps the basics: blocked
  symbols, order size, position cap, cash buffer, margin, short sales, F&O,
  malformed or bad bracket orders, duplicates, a daily order limit and a
  losing-streak breaker. Getting out is never blocked by a day limit. Prints
  PASS or BLOCK with the reason and records the verdicts so trader-broker only
  shows an order that passed. Use when the user says "check my order", "is this
  safe", "risk check", "does this break my rules", "can I take this trade",
  "how much have I risked today", or before /trader-broker, always.
argument-hint: "[path to orders.json]"
---

# trader-risk

The Risk Manager is the gate between a proposal and the broker. Every order
written by trader-budget or trader-broker's flatten passes through it. A
BLOCK is final for that order. It does not go to the user for a yes, and it
does not go to the broker. Most people who day trade lose money. These limits
keep each loss and each day's losses small. They do not make a trade win.

## Secrets

Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`. This skill needs no keys.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"                           # trader/ files; writes trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write                # look without recording
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-11 10:30"  # pin the clock (IST)
```

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget, or trader-broker's flatten) |
| `trader/config.json` | the limits (trader-budget ships `config.example.json`) |
| `trader/portfolio.json` | cash and holdings; if missing, a fresh account funded with the budget |
| `trader/prices.json` | a fresh price raises the entry it measures risk from; also values holdings |
| `trader/nse_holidays.json` | extra market holidays, written by `alerts.py holidays --refresh` (optional) |
| `trader/state/broker.json` | what was placed today: duplicates, trades per day, daily loss, losing streak |
| `trader/state/risk.json` | the verdicts it writes, with a fingerprint of each exact order |

## Entries and exits

An **entry** opens or adds to a position: a buy, or a sell that would go
short. An **exit** only reduces what you already hold. Getting out must
always be possible, so an exit is checked for format, asset and short sales
only. Every other rule (day limits, entry window, loss, reward:risk, blocked
list, size, duplicates) turns into a warning for an exit, never a BLOCK.

## The checks

Orders are checked in file order, as if each passed order had filled. A batch
that is fine order by order but breaks a limit together is caught.

Money limits are written as `*_inr` in the config, for example `max_order_inr`.
The code also reads the older `*_usd` names.

| check | blocks when |
| --- | --- |
| format | no symbol, side not buy or sell, both or neither of qty and notional, a notional (rupee) order that is not market + day, a limit order with no limit price; exchange not NSE, BSE, NFO or BFO; product not intraday, delivery, carryforward or margin; F&O with product delivery; carryforward on a cash order; `modify_of` that is not an order placed today; a bracket that is not whole shares, not `day` or `gtc`, or misses its stop-loss or take-profit |
| asset | a symbol that is not an NSE or BSE stock or ETF (M&M and BAJAJ-AUTO are allowed); an F&O symbol on NFO or BFO, such as `NIFTY17NOV2624000CE` or `BANKNIFTY29DEC26FUT`, while `allow_fno` is false; crypto or any symbol with a slash; an option symbol while `allow_options` is false |
| short | a sell of more than you hold (`allow_short` false). Selling an option or future that opens a position is a short too |
| blocked | (entries) the symbol is on the `blocked` list |
| size | (entries) under `min_order_inr` or over `max_order_inr` |
| position | (entries) the stock would be over `max_position_pct` of the account |
| cash | (entries) the buy would leave less than the cash buffer, or need margin |
| stop | (entries) no stop while `require_stop` is true (a bracket `stop_loss_stop_price`, or the order's plan stop); a stop on the wrong side of the entry |
| loss | (entries) qty x (entry minus stop) over `max_loss_per_trade_inr` |
| reward:risk | (entries) (target minus entry) / (entry minus stop) under `min_reward_risk` |
| daily loss | (entries) the max losses at the stops of today's entries, plus this one, over `max_daily_loss_inr` |
| trades | (entries) `max_trades_per_day` entries already placed today |
| circuit breaker | (entries) blocked after `max_consecutive_losses` losing closed trades in a row (default 3). Closed trades are counted first in, first out from the fills in `trader/state/broker.json` |
| window | (entries) before `no_entries_before` or after `no_entries_after`, or the market is closed |
| duplicate | (entries) the same symbol and side twice in one batch, or already placed today |
| daily limit | (entries) `max_orders_per_day` orders already placed today |

**Changing an open order.** A changed order names the broker order it replaces in `modify_of`. It is checked as a new order, so the other rules still apply. It does not count as a duplicate or as a new trade. The old order's max loss comes out of the daily loss, so the change is not counted twice.

**Instrument checks come later.** After this check, trader-broker's `angel.py` adds instrument checks: lot size, freeze quantity, tick size, price band, circuit band and hard caps. A PASS here does not guarantee the broker accepts the order.

How the numbers work:

- **The entry it measures from**: the limit price for a limit order. For a
  market order, the HIGHER of the plan's entry and a fresh price from
  `trader/prices.json` (under 15 minutes old). A plan written at 10:15 cannot
  understate the risk at 10:55 after the price ran up. An older price is not
  used, and it says so.
- **Daily loss** counts the full max loss of every entry placed today, win or
  lose, as trader-broker logged it. Three entries at Rs 500 max loss each use up Rs 1,500 of a Rs 2,000 day.
- **The window** is IST, worked out in the tool, never from the computer's clock zone.
  Market hours are 09:15 to 15:30 IST, Monday to Friday. There are no early closes.
  Weekends and NSE holidays are closed. Set both `no_entries_*` to null to switch the window off.
- **Holidays** come from a built-in 2026 list plus `trader/nse_holidays.json`. Run `alerts.py holidays --refresh` for the next year. A year not covered gets a warning.

Warnings do not block, but say them to the user:

- a LIVE account;
- a number sent as a number, not as a string;
- a stop that lives only in the plan, not at the broker;
- a price too old to use;
- an option order, which can lose all of its premium.

## Steps

1. If the price may have moved since the plan, refresh it first
   (trader-alerts: `alerts.py quote SBIN --write`).
2. Run `check.py`. Exit code 0 means every order passed, 1 means at least one
   was blocked.
3. Tell the user the result in plain words, order by order. Give the max loss
   at the stop, the reward:risk, and how much of today's limits it uses. For a
   BLOCK, give the reason and the fix. The fix is fewer shares, a closer stop
   from trader-exit, waiting for the window, or skipping the trade. Never change a limit yourself.
4. If the order changes in any way, run the check again. trader-broker matches
   each order to its verdict by fingerprint. An edited order is not ready until
   it passes again. A verdict from yesterday does not count today.

## Example: an SBIN buy

A limit buy of SBIN at 10:30 AM IST on Wednesday 2026-11-11, on a fresh paper account with the example config:

```
PASS  #1 buy SBIN 20 shares, entry
          entry 800.00 (the limit price), stop 790.00, target 820.00: risk 10.00 a share
          max loss Rs 200 (limit Rs 500), reward:risk 2.00 (min 1)
          today before this: 0 of 3 trades, Rs 0 of Rs 2,000 daily loss

1 passed, 0 blocked at 2026-11-11 10:30 IST.
```

Sixty shares put the loss over the limit:

```
BLOCK #1 buy SBIN 60 shares, entry
          entry 800.00 (the limit price), stop 790.00, target 820.00: risk 10.00 a share
          max loss Rs 600 (limit Rs 500), reward:risk 2.00 (min 1)
          today before this: 0 of 3 trades, Rs 0 of Rs 2,000 daily loss
        - loss: 60 shares x 10.00 risk a share = Rs 600 at the stop, over your Rs 500 max loss per trade
```

Fewer shares fix the loss check. Order size and cash are checked too. A sell that closes the position passes after the entry window closes, because it is an exit.

## Rules

- A PASS only means the order is allowed to be shown to the user. It is not a yes.
- Every number comes from the config, the order, the portfolio, the prices or the broker log.
- Free price feeds are unofficial and can lag. The broker's price is the one that fills. A stop can fill worse than its price in a fast market.

## What it never does

It never places an order, never edits an order to make it pass, never
loosens a limit, never blocks a sell that only gets the user out, and never
treats a PASS as the user's yes.

## Safety

- This is not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold. trader-risk passed that exact order today. The user typed an explicit yes for that one order in the chat. The user approved the order command's prompt once, because the tool is set to ask first. Never set the order tool to always allow.
- F&O follows `allow_fno`. Short selling and margin need `allow_short` and `allow_margin` in the config, and the user's confirmation.
- Broker keys live in environment variables or the broker's own setup file, never in the chat.
