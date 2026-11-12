---
name: trader-broker
description: >-
  Order Executor for Angel One (SmartAPI). Sends approved orders for NSE, BSE
  and NFO/BFO (F&O), in paper mode by default. It sends an order only after
  three gates: a trader-risk PASS for that exact order, the user's typed yes,
  and the user's own approval of the command prompt. Shows each order as a
  plain ticket with the stop-loss and the max loss. Places the stop-loss after
  a fill, makes risk-reducing changes to open orders, converts positions
  (intraday to delivery and back), cancels orders, and has a kill switch. Use
  when the user says "place the order", "buy it", "execute", "send it to Angel
  One", "modify my order", "convert to delivery", "cancel", "flatten", "get me
  out", "kill switch", "connect Angel One", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

This skill is the only path to a real order. It is the strictest skill in the pack.
This is not financial advice. Most people who day trade lose money.

## Secrets: read this first

- Never open, print, copy, search or edit `~/.trader/angel.env`.
- Never open `~/.trader/angel_session.json` or any `.env` file.
- Never ask the user to paste a key, MPIN or TOTP secret into the chat.
- Never print environment variables. Never run `env`, `printenv` or `Get-ChildItem env:`.
- `angel.py` reads the secrets itself. It never prints them.
- To check the setup, run `angel.py doctor`. It shows only "present" or "missing" for each key.
- If a step seems to need a secret, stop and ask the user to do that step.

The plugin hook (`hooks/guard.py`) blocks these actions. These rules apply even where the hook does not run.

## The three gates

An order reaches Angel One only after three separate gates, every time, for every order:

1. **trader-risk passed this exact order today.** The match uses a fingerprint of the order.
2. **The user typed a yes for this one order.** `ticket.py approve` records the exact words.
3. **The user approved the `angel.py place` command prompt.** The hook asks for it on every order command.

`angel.py place` checks gates 1 and 2 in code again before it sends anything.
You never approve a prompt for the user. You never retry a failed order on your own.

## Hard limits in code

`angel.py` blocks an order when one of these is true. The config can lower a limit. It cannot raise one.

| check | blocks when |
| --- | --- |
| kill switch | the file `trader/STOP` exists |
| order value | qty x price is over Rs 25,000 (`angel.max_order_value`) |
| orders per day | 5 orders are already placed today (`angel.max_orders_per_day`) |
| price band | the limit price is more than 2% from a fresh last price |
| circuit band | the limit price is outside the exchange circuit limits |
| tick size | the price is not a multiple of the tick (for example 0.05) |
| market hours | outside 09:15 to 15:30 IST, on weekends and on NSE holidays |
| closing auction | 15:15 to 15:20 IST (Angel One rejects API orders then) |
| cautionary scrip | an entry in an ASM/GSM stock (live mode) |
| duplicate | the order book already has an order with the same tag |

F&O adds these checks:

| check | blocks when |
| --- | --- |
| lot size | qty is not a multiple of the lot size |
| freeze limit | qty is over the exchange freeze quantity |
| options type | an option order is not a LIMIT order |
| option selling | a sell that opens a position, unless `angel.allow_option_selling` is true and a bought hedge exists |
| futures | a futures entry, unless `angel.allow_futures` is true |
| strike distance | the strike is more than 5% from spot |
| expiry day | a new entry after 14:30 on expiry day |

Exits are never blocked by a day limit. An exit can still fail on market hours or price checks.

## Paper and live

Paper mode is the default. Live mode needs all three of these:

1. `"paper": false` in `trader/config.json`
2. `"broker": "angelone"` in `trader/config.json`
3. The environment variable `ANGEL_LIVE=1`, which the user sets in their own terminal

In paper mode, `angel.py` sends nothing to Angel One. A limit order fills at its limit price.
The user changes these settings. You never change them.

## Setup (the user does these steps)

1. Open an Angel One account. Turn on TOTP for the account.
2. Create an app on the SmartAPI portal (smartapi.angelone.in). Copy the API key.
3. Register a static public IP for the app. From 1 April 2026, Angel One accepts API orders only from that IP.
4. Create the file `~/.trader/angel.env` in a text editor. Put these lines in it:

```
ANGEL_API_KEY=your api key
ANGEL_CLIENT_CODE=your client code
ANGEL_MPIN=your 4-digit MPIN
ANGEL_TOTP_SECRET=the secret from the TOTP QR code setup
ANGEL_PUBLIC_IP=your registered static IP
```

5. Run `python angel.py doctor`. All five keys must show "present".
6. Run `python angel.py login`. The session lasts until midnight IST.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

## Commands

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                       # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"   # record the user's own words
python3 "${CLAUDE_SKILL_DIR}/angel.py" place --index 1             # gates 1 and 2, then send
python3 "${CLAUDE_SKILL_DIR}/angel.py" protect --index 1           # stop-loss after the entry fills
python3 "${CLAUDE_SKILL_DIR}/angel.py" orders                      # order book
python3 "${CLAUDE_SKILL_DIR}/angel.py" positions | funds | holdings | trades
python3 "${CLAUDE_SKILL_DIR}/angel.py" ltp SBIN TCS --write        # fresh prices for trader-risk
python3 "${CLAUDE_SKILL_DIR}/angel.py" search NIFTY --exchange NFO --expiry 17NOV2026 --strike 24000 --type CE
python3 "${CLAUDE_SKILL_DIR}/angel.py" margin --index 1            # margin for the order
python3 "${CLAUDE_SKILL_DIR}/angel.py" charges --index 1           # brokerage, STT and other charges
python3 "${CLAUDE_SKILL_DIR}/angel.py" modify --order-id ID --trigger 795   # risk-reducing changes only
python3 "${CLAUDE_SKILL_DIR}/angel.py" convert --symbol SBIN --side buy --qty 20 --from INTRADAY --to DELIVERY --reply "yes convert SBIN"
python3 "${CLAUDE_SKILL_DIR}/angel.py" cancel --order-id ID
python3 "${CLAUDE_SKILL_DIR}/angel.py" kill [--flatten]            # stop everything
python3 "${CLAUDE_SKILL_DIR}/angel.py" logout
```

## Steps for one order

1. Run `ticket.py show`. Show the user the ticket for the order, word for word.
2. If the ticket is not READY, say why. Do not continue.
3. Run `angel.py charges --index N` and `angel.py margin --index N`. Tell the user the numbers.
4. Ask the user: "Do you want me to send order N?" Wait for their answer.
5. If the answer is a yes, run `ticket.py approve --index N --reply "<their exact words>"`.
   If the answer is anything else, run `ticket.py decline --index N`. Stop.
6. Run `angel.py place --index N`. The user approves the prompt, or the order does not go.
7. Report the result exactly as the script prints it.
8. When the entry fills, run `angel.py protect --index N` to place the stop-loss.

## Changes to open orders

- `modify` makes only changes that lower risk: fewer shares, a tighter stop, or a new exit price.
- A change that adds risk is a new order. Write it to `trader/orders.json` with `"modify_of": "<order id>"`.
  Then run trader-risk, get a new yes, and run `angel.py place`. The script then modifies the open order.
- `convert` needs the user's own yes that names the symbol. Delivery needs enough cash.
- `cancel` is always allowed.

## Kill switch

`angel.py kill` writes `trader/STOP` and cancels every open order. `--flatten` also exits every open intraday position.
Only the user deletes `trader/STOP`. Never delete it yourself.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget or breakout-trade-planner) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today counts |
| `trader/state/broker.json` | every yes, no, placed, failed and filled order |
| `trader/state/angel_audit.jsonl` | every Angel One call, with secrets masked |
| `trader/state/angel_paper.json` | paper orders |
| `trader/cache/scrips.json` | the instrument list, refreshed once a day |
| `trader/portfolio.json` | cash and positions |

## Order format

Each order in `trader/orders.json` uses these fields (values as strings):

```json
{"symbol": "SBIN", "exchange": "NSE", "product": "intraday", "side": "buy", "qty": "20",
 "type": "limit", "time_in_force": "day", "limit_price": "800.00", "order_class": "bracket",
 "stop_loss_stop_price": "790.00", "take_profit_limit_price": "820.00"}
```

- `exchange`: NSE, BSE, NFO or BFO.
- `product`: intraday or delivery for cash; intraday or carryforward for F&O.
- `type`: limit, market (exits only), stop_limit or stop.
- For F&O, `symbol` is the trading symbol from `angel.py search` (for example NIFTY17NOV2624000CE), and `qty` is in units (lots x lot size).

## Errors

- `STOP: ...` means the script sent nothing, or it says what it sent. Read the whole line to the user.
- HTTP 403 means a rate limit or a wrong static IP. Stop. Ask the user to run `angel.py doctor`.
- "session token invalid or expired" means the user must run `angel.py login`.
- If the script cannot confirm an order, run `angel.py orders` before you do anything else.
