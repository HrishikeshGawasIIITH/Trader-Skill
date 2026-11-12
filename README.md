# Trader-Skill

Trading skills for Indian markets (NSE, BSE, NFO, BFO) with an Angel One account.
The skills scan charts, read news, plan entries and exits, and check risk.
An order goes to Angel One only after you say yes to that order.
Paper mode is the default.

This is not financial advice. Most people who day trade lose money.
These tools limit each loss. They do not make a trade win.

## How the skills work together

```
market health ──> scanner / screeners ──> entry + exit plan ──> budget (size)
   breadth, sector,     trader-scanner,       trader-entry,        trader-budget,
   FTD, top, flows      vcp, momentum,        trader-exit,         position-sizer
                        hammer, PEAD          timemachine
                                                   │
news + stock analysis ─────────────────────────────┤
   trader-news, india-stock-analysis,              v
   earnings-calendar, technical-analyst      trader/orders.json
                                                   │
                                                   v
                                     trader-risk ── PASS or BLOCK
                                                   │ PASS
                                                   v
                       trader-broker: your yes ──> command prompt ──> Angel One
                                                   │
                                                   v
                                  fills, stop-loss, alerts, kill switch
```

## Skills

| group | skill | what it does |
| --- | --- | --- |
| Order path | trader-scanner | Scans NSE stocks for gaps, volume and opening-range setups |
| | trader-entry | Times an entry (opening-range breakout, level breaks) in IST |
| | trader-exit | Sets the stop, the target and the flat-by time |
| | trader-timemachine | Replays a setup over past sessions before you risk money |
| | trader-budget | Sizes the trade to your max loss and writes `trader/orders.json` |
| | trader-risk | Checks every order against your limits: PASS or BLOCK |
| | trader-broker | Sends approved orders to Angel One (paper by default) |
| | trader-alerts | Price alerts, the NSE clock and the holiday list |
| News | trader-news | NSE filings, Indian business news, FII/DII, RBI and SEBI |
| Screeners | vcp-screener | Volatility contraction patterns in the Nifty 500 |
| | stockbee-momentum-burst-screener | 4% breakouts with range expansion |
| | stockbee-exhaustion-hammer-screener | Selling-exhaustion hammer setups |
| | pead-screener | Post-results gap-ups that keep drifting |
| | earnings-trade-analyzer | Scores the reaction to quarterly results |
| | earnings-calendar | Upcoming results and board meetings from NSE |
| Planning | breakout-trade-planner | Breakout plans written as orders for trader-risk |
| | position-sizer | Risk-based size, whole shares and F&O lots |
| | backtest-expert | Checks a backtest for bias and weak edges |
| Market health | market-breadth-analyzer | Nifty 500 breadth score from 0 to 100 |
| | uptrend-analyzer | Share of stocks in an uptrend |
| | sector-analyst | Sector rotation from the NSE sectoral indices |
| | ftd-detector | Follow-through days after a Nifty correction |
| | market-top-detector | Signs of a market top (distribution, leadership, India VIX) |
| | institutional-flow-tracker | FII/DII flows and bulk and block deals |
| Analysis | technical-analyst | Chart analysis: trend, support, resistance, scenarios |
| | india-stock-analysis | One report on a stock: price, technicals, filings |
| | options-strategy-advisor | Option prices, Greeks and strategy payoffs |

## Install

Plugin install (this also loads the secret guard hook):

```
/plugin marketplace add https://github.com/HrishikeshGawasIIITH/Trader-Skill
/plugin install trader-skill@trader-skill
```

Or copy the skills:

```
git clone https://github.com/HrishikeshGawasIIITH/Trader-Skill
cd Trader-Skill
python install.py --hooks
```

To update, run `python install.py --update`. An agent can do all of this from the repo link. See [AGENTS.md](AGENTS.md).

The scripts need Python 3.8 or newer and nothing else.

## Connect Angel One

1. Turn on TOTP for your Angel One account.
2. Create an app on the SmartAPI portal and copy the API key.
3. Register your static public IP on the app. Angel One accepts API orders only from that IP.
4. Create `~/.trader/angel.env` in a text editor. The format is in [trader-broker/SKILL.md](trader-broker/SKILL.md).
5. Run `python trader-broker/angel.py doctor`, then `python trader-broker/angel.py login`.

Never paste a key into a chat. The agent never reads the secrets file.

## Safety

- Every order passes three gates: a trader-risk PASS, your typed yes, and your approval of the command prompt.
- Paper mode is the default. Live orders need `"paper": false`, `"broker": "angelone"` and `ANGEL_LIVE=1`.
- The code sets hard limits: Rs 25,000 per order, 5 orders a day, a 2% price band, circuit limits and tick size.
- Your config sets the daily limits: max loss per trade, max loss per day and trades per day.
- Trading stops for the day after 3 losses in a row.
- F&O orders must match the lot size and stay under the freeze quantity.
- Option orders must be LIMIT orders. Option selling and futures stay off until you turn them on.
- Orders go only in IST market hours on NSE trading days. No orders go from 15:15 to 15:20.
- No new F&O entries go after 14:30 on expiry day.
- `angel.py kill` cancels open orders and blocks new ones. `--flatten` also exits intraday positions.
- A hook blocks agent access to `~/.trader/angel.env`, `.env` files and the session file.
- Every Angel One call goes to the audit log `trader/state/angel_audit.jsonl`, with secrets masked.

## Data sources (all free, no keys)

| data | source |
| --- | --- |
| Orders, positions, funds, live prices, candles, option Greeks | Angel One SmartAPI |
| Instruments, lot sizes, tick sizes | Angel One scrip master |
| Daily and intraday charts, indices, India VIX | Yahoo Finance (`.NS` symbols) |
| Stock lists, index members, F&O lots, bulk and block deals | NSE archives |
| Filings, results, board meetings, insider trades | NSE RSS feeds and NSE corporate announcements |
| Results calendar, FII/DII flows, holidays | NSE website data |
| News | Google News (India), Economic Times, Moneycontrol, Mint, Business Standard, BusinessLine, NDTV Profit |
| Regulator news | RBI and SEBI RSS feeds |
| Optional analysis data | NSE MCP servers (`mcp.nseindia.in`) |

Free sources can change or fail without notice. When a source fails, the skills report the failure and show no value for it.

## Not in version 1

MCX and currency, GTT, AMO and bracket (ROBO) orders, the WebSocket live feed, the eDIS/TPIN flow for
delivery sells (v1 needs DDPI on your account), fundamental screeners, and scheduled runs.

## Tests

Run the order-path tests:

```
cd tests && python -m unittest discover -s .
```

The market health and analysis skills run with unittest. This example runs the tests for market-breadth-analyzer:

```
python -m unittest discover -s market-breadth-analyzer/scripts/tests
```

The screener, earnings, planning, position-sizer and backtest tests need pytest (`pip install pytest`):

```
cd vcp-screener/scripts && python -m pytest tests -q
```

The tests use fixtures only. They never connect to Angel One.

## License

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
