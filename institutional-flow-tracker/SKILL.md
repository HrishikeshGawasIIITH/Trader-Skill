---
name: institutional-flow-tracker
description: Tracks institutional money in Indian stocks using NSE FII/DII daily cash flows and bulk and block deals. Shows rolling FII and DII totals, a flow regime, and the stocks with the largest net deal buying or selling. No API key. Use when asked about FII or DII buying and selling, smart money, bulk or block deals, or institutional activity in a stock.
---

# Institutional Flow Tracker

## Secrets
Never open, print, copy or edit `~/.trader/angel.env`, any `.env` file, or `~/.trader/angel_session.json`.
This skill needs no keys. If a step seems to need a secret, stop and ask the user.

## Overview

Institutions move Indian markets. This skill reads two free NSE sources.

- **FII/DII flows:** daily net buying and selling in the cash market, in Rs crore.
- **Bulk and block deals:** large trades with the client name, side, quantity and price.

It replaces quarterly 13F ownership data, which does not exist for India. Flows here are daily and short-term.

## When to Use This Skill

- "Are FIIs buying or selling?" or "Is DII supporting the market?"
- Which stocks had large bulk or block deals today
- Whether mutual funds or insurers bought a stock you hold
- Context for market-top-detector or market-breadth-analyzer readings

Do not use it for long-term ownership trends. Check shareholding patterns on NSE for those.

## Prerequisites

- Python 3.9 or newer, standard library only
- Internet access to nseindia.com and nsearchives.nseindia.com
- No API keys

## Running the Script

```bash
# FII/DII flows with 5, 10 and 20 session totals
python3 scripts/track_institutional_flow.py flows

# Bulk and block deals ranked by net value
python3 scripts/track_institutional_flow.py deals --min-value-cr 5 --top 10

# One stock: its deals, price context and market flow regime
python3 scripts/track_institutional_flow.py stock RELIANCE

# JSON output and saved file
python3 scripts/track_institutional_flow.py flows --json --output-dir reports/
```

The FII/DII endpoint returns only the latest session. Each run adds the day to `trader/cache/fii_dii.json`.
Windows of 5, 10 and 20 sessions fill as you run the script daily. Set `TRADER_DIR` to move the cache.
NSE needs a browser-like session. The script handles the cookie step. If NSE blocks a request, wait and retry.

## Workflow

1. Run `flows` after the close (NSE publishes the numbers in the evening). Read the regime line.
2. Run `deals` to find stocks with large institutional net buying or selling.
3. Run `stock SYMBOL` to check a stock you hold or plan to buy.
4. Read `references/interpretation_framework.md` before drawing conclusions.

## Output

- Latest session FII and DII buy, sell and net in Rs crore
- Rolling net totals and a regime: broad buying, broad selling, DII absorbing FII selling, FII buying while DII books profits
- Top net accumulation and distribution by symbol, with institutional client names
- Per-stock deal table and price context (1 week, 1 month, position versus the 50-day average)

## Limits

- Cash-market flows only. Derivative positions are not included.
- Bulk deals cover trades above 0.5% of listed shares. Block deals are large negotiated trades.
- Client type is guessed from the name. Treat it as a hint.
- A deal is one trade. It does not show the holder's later behavior.

---

This is analysis, not financial advice. Orders go only through trader-risk and trader-broker.
