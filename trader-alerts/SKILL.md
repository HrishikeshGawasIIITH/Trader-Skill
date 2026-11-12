---
name: trader-alerts
description: >-
  Price Alerts. Rings when a price, a stop or the opening bell hits. Turns
  the trade plan into three alerts in one go (the stop, the target and "flat
  by close" at your flat-by time), plus above / below / stop / target levels,
  percent moves from the previous close, any time of day, and the NSE
  opening bell, each ringing once so you are not spammed. Knows NSE hours
  and the 2026 trading holidays, refreshes the holiday list from nseindia.com,
  works out IST itself, fetches free delayed quotes (Yahoo chart JSON) one
  ticker at a time, and writes trader/prices.json for sizing and the risk
  check. Use when the user says "alert me when", "tell me if RELIANCE hits",
  "watch my stop", "watch my trade", "remind me to close by 3:00", "is the
  market open", "when does the market open", "get me a price", "refresh the
  holidays", or right after /trader-exit writes a plan.
argument-hint: "[ticker] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a bracket order the stop-loss and the
take-profit already sit at the broker and do the work. The alerts tell the
user what happened and when it is time to be flat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE open or closed, next open
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat by close from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TATASTEEL --stop 158.30
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TATASTEEL --target 170.40
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --at 15:00 --label "flat by close" --before-close
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol KOTAKBANK --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # exit 0 = something rang
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE --write         # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write       # portfolio + plan tickers
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-plan-stop
python3 "${CLAUDE_SKILL_DIR}/alerts.py" holidays                       # the NSE holiday table in use
python3 "${CLAUDE_SKILL_DIR}/alerts.py" holidays --refresh             # fetch it from nseindia.com
```

`--now "2026-11-11 15:00"` pins the clock (IST). `--offline DIR` reads saved
quote files instead of the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | the tickers held, for `quote --holdings` |
| `trader/nse_holidays.json` | the NSE holidays from `holidays --refresh`; the trader scripts read it |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the IST clock passed `at` ("15:00") on a trading day | once per trading day |
| `opening_bell` | the NSE is open | once per trading day |

A rule with `"date"` is watched on that IST date only. `--from-plan` rules
carry the plan's date, so yesterday's stop never rings today. A `time` rule
with `"before_close": true` moves up with a shortened session. NSE has no
early closes in the built-in table, so it rings at the time you set.

## Quotes

- `yahoo` (default): `query2.finance.yahoo.com/v8/finance/chart/<TICKER>.NS`,
  an unofficial free JSON endpoint. It sends one request per ticker, half a
  second apart. On a 429 it waits and tries once more. On a 429 or a 5xx
  after that it tries `query1`. It identifies itself as `trader-skill/1.0`.
- Symbols are plain NSE names (`RELIANCE`, `M&M`, `BAJAJ-AUTO`). The tool adds
  `.NS` for Yahoo. Index symbols start with `^` (`^NSEI`). A symbol with a
  dot, like `500325.BO`, is sent as it is.
- Free quotes are unofficial, delayed and can lag. They are fine for alerts
  and for checking a size, not for timing an order. The broker's price is the
  one that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If Yahoo is down, read the price from the broker connector and write it into
  `trader/prices.json` as `{"as_of": "...Z", "prices": {"RELIANCE": 1456.10}}`.

## The NSE clock

The regular session runs 9:15 to 15:30 IST, Monday to Friday. IST is UTC+5:30
all year, so there is no daylight saving. The built-in 2026 holidays come from
the NSE equity-segment holiday API:

- Jan 15, Jan 26, Feb 15, Mar 3, Mar 21, Mar 26, Mar 31, Apr 3, Apr 14,
  May 1, May 28, Jun 26, Aug 15, Sep 14, Oct 2, Oct 20, Nov 8, Nov 10,
  Nov 24, Dec 25.

Run `holidays --refresh` once a quarter, and whenever the clock says the
list is unknown. It opens nseindia.com for cookies, then reads the holiday
API and saves `trader/nse_holidays.json`. NSE blocks some networks. If the
refresh fails, check the dates on nseindia.com and edit that file by hand as
`{"2027-01-26": "Republic Day"}`.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a scheduled
   task or `/loop`. Each run fetches only the tickers in today's rules and
   rings each alert once. A check reads the latest delayed quote. It is not a
   live feed, and a price can pass a level between two checks.
3. Tell the user what rang in one line each. A stop or target alert means the
   bracket order has probably filled: check the open position and record the
   fill with trader-broker. "Flat by close" means close anything still open:
   trader-broker `flatten`, then trader-risk, then the user's yes. Never act
   for them.

## Example (illustrative numbers)

RELIANCE on Wednesday 2026-11-11: entry Rs 1451.20 at 9:35 AM, stop 1442.25,
target 1469.10, flat by 15:00. `add --from-plan` writes `reliance-plan-stop`,
`reliance-plan-target` and `reliance-flat-by` for that day. A `check` at 10:53
reads a quote of Rs 1456.10, between the stop and the target:

```
NSE OPEN (2026-11-11 10:53 IST, regular session).
Nothing hit. 3 rule(s) watched today, RELIANCE Rs 1456.10.
```

At 3:00 PM:

```
ALERT Flat by close: it is 15:00 IST (set for 15:00), the market closes at 15:30. If RELIANCE is still
open, close it: trader-broker flatten --symbol RELIANCE builds the sell ticket, then trader-risk and your yes.
```

It rings once. The next morning the plan's three alerts are no longer
watched. With `add --opening-bell`, the bell rings at 9:15.

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a quote as live. Free quotes are delayed and unofficial.
- Confirm every new rule back to the user: ticker, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a quote is
live, and never predicts where a price is going.

## Safety

- This is not financial advice. A PASS is a rules check. It is not a recommendation.
- Paper mode is the default (`"paper": true`). Only the user turns on live mode.
- Only trader-broker places an order. It needs three gates: a trader-risk PASS for that exact order today,
  the user's typed yes for that one order, and the user's approval of the `angel.py place` command prompt.
- Never approve a command prompt for the user. Never retry a failed order on your own.
- No option selling, futures or short selling unless the config allows it and the user confirms.

## Secrets

- Never open, read, print, copy, search or edit `~/.trader/angel.env`.
- Never open `~/.trader/angel_session.json` or any `.env` file.
- Never print environment variables. Never ask the user to paste a key, MPIN or TOTP secret into the chat.
- To check the Angel One setup, run `python trader-broker/angel.py doctor`. It shows only "present" or "missing".
