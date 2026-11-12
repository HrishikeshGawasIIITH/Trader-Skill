---
name: trader-scanner
description: >-
  Chart Scanner. Scans thousands of charts for setups: opening-range
  breakouts, flags, oversold bounces. Builds the list of NSE equities (series
  EQ) from the NSE equity list, runs a pre-market scan of daily closes
  (20-day closing-high breakout, bull flag, reclaimed the 20-day average,
  oversold, oversold bounce) and an intraday opening-range breakout scan on
  5-minute bars, then writes trader/watchlist.json for trader-news and
  trader-entry. Free Yahoo data, bar by bar. Use when the user says "scan the
  market", "find me setups", "what is breaking out", "opening range
  breakouts", "scan for bull flags", "oversold stocks", "pre-market scan",
  "build my watchlist", "what should I look at today", or at the start of a
  trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads thousands of
free charts and lists the ones that match a rule. That is all it does. A scan
is a list of charts that match a rule, not a list of stocks to buy, and a
setup on a chart is not a prediction. Most people who day trade lose money;
the scanner does not change that. It only saves you from flipping through
2,000 charts by hand.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                          # -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                             # before the open -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols TCS,RELIANCE,M&M  # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                               # after 9:35 AM IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:15                    # cut the clock at 10:15 AM IST
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Flags: `--min-price 50`, `--min-turnover` (daily only, default Rs 10 crore =
100000000) and `--min-volume` (default 0), `--or-minutes 15`, `--max-confirm
200` (orb stage 2), `--now "2026-10-19 10:15"` (IST) to pin the clock,
`--offline PATH` to read saved Yahoo files, `--no-write`, `--show N`,
`--json`. Exit code 0 when the scan found something, 1 when it found nothing
or could not run (the reason is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news and trader-entry read `hits[].symbol` |
| `trader/config.json` | read by both scans: `no_entries_after` (default 14:45), `scan_min_price` (default 50), `scan_min_turnover` (default 100000000) |
| `trader/nse_holidays.json` | optional: extra NSE holidays that trader-alerts refreshes from NSE |

## The universe

`universe` downloads the NSE equity list (`EQUITY_L.csv` from
nsearchives.nseindia.com) and keeps the rows of series EQ. Other series
(BE, SM and so on) are dropped. Symbols such as M&M and BAJAJ-AUTO stay as
they are. The download needs a browser-like User-Agent, which the script
sends. If NSE refuses it, save the file by hand and run
`scan.py universe --offline EQUITY_L.csv`.

Yahoo wants `.NS` after the symbol (TCS.NS, M&M.NS). The scanner adds it for
Yahoo requests and encodes `&`. Files and output keep the plain NSE symbol.

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so about
2,000 symbols take roughly 100 requests. Liquidity comes from the spark meta:
last price at least `--min-price` (Rs 50), and price times the last
session's volume at least `--min-turnover` (Rs 10 crore). Run it before the
open or after the close: during the session the volume is the day's so far,
and today's daily bar is left out until 3:30 PM.

The setups are computed from daily closes only (spark has no highs or lows):

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

A closing-high breakout fires more often than an intraday-high one. Hits are
listed most traded first (price times volume).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 9:15,
9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute bar
to CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range. That is a necessary condition
   (the range high is at least every range close), so no breakout is lost.
2. Stage 2, each candidate: the v8 chart with real highs and lows, one
   request each. Range high = the highest high of the range bars, range low =
   the lowest low. On a strong morning most charts are candidates, so stage 2
   checks at most `--max-confirm` (200) of them, the most traded first (price
   times volume so far), and prints PARTIAL with the count it skipped.
   `--max-confirm 0` checks them all.

For a fast answer, scan the daily watchlist or a list of names you trade
(`--watchlist`, `--symbols`).

A chart is usable only when every 5-minute bar from 9:15 to the cutoff is
there; a missing bar means a halt or a thin stock. Null closes are dropped,
a bar off the 5-minute grid (the live tick) is dropped, and a bar counts only
once it is complete (start + 5 minutes). Before 9:35 AM, on a weekend or
holiday, after the close, or after `no_entries_after` (an expired setup) it
prints one plain line and writes nothing.

## Data and limits

- Yahoo's chart and spark endpoints are free, unofficial and can lag. Bars are
  5-minute bars, bar by bar, never tick by tick. query2 first, query1 on a 429
  or 5xx, one retry after a 5-second wait on a 429.
- Partial results are said as partial: "Fetched 1,980 of 2,100 charts (120
  failed or had no data)". Never round a partial scan up to "the whole market".
- The NSE holiday list for 2026 is built in. `trader/nse_holidays.json` adds
  more days.

## Steps

1. Once a week or so: `scan.py universe`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 9:35 AM IST (10:00 is the classic): `scan.py orb`. Tell the user how
   many usable charts broke their range and when, and that a later hit is
   closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news TICKER` (what is moving
   it), then `/trader-entry TICKER` (the entry bar by bar). Never pick for them.

## Example output

A scan at 10:15 AM IST:

```
Opening-range breakout scan, Mon 2026-11-09 10:15 AM IST: 15-minute range (9:15 to 9:30 AM), 5-minute bars, Yahoo.
Fetched 1,980 of 2,100 charts (120 failed or had no data); 1,900 usable; 310 candidates, 200 confirmed with real highs and lows.
  9:40 AM  TCS        Rs 3,640.00  range 3,598.00 to 3,625.00  +0.41% over
```

The numbers above only show the layout. Real output depends on the day.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data real time, and never promises that a setup works.

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
