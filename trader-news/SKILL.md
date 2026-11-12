---
name: trader-news
description: >-
  News Monitor for NSE stocks. Tracks breaking news on every stock you watch.
  It reads NSE exchange filings first (results, board meetings, acquisitions,
  credit ratings, insider trading, dividends, resignations, fund raising, order
  wins), then headlines from Google News and the main market publishers. It
  also shows how far each stock is from yesterday's close. It prints only what
  is new since the last check, newest first, in IST. Each item gets tags and
  never repeats. Use when the user says "any news on RELIANCE", "why is this
  moving", "what's the news on my watchlist", "morning briefing", "pre-market
  news", "monitor the news", "did anything break", "check the filings", or
  after /trader-scanner finds setups.
argument-hint: "[symbols]"
---

# trader-news

A chart can look perfect and still be about to gap on a results date, a
trading halt or a regulator order. Before a setup becomes a trade, this skill
reads the feeds that carry those first. It tells you only what is new. It also
prints how far each stock has moved today, so a headline and a move sit side
by side.

Tool in this folder (standard library Python, no keys):

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                         # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS M&M --hours 12
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-filings --json
```

## Secrets

Never open, print, copy or edit ~/.trader/angel.env, any .env file, or ~/.trader/angel_session.json. This skill needs no keys.

## What it reads and writes

| file / feed | what |
| --- | --- |
| `--tickers`, else `trader/watchlist.json` | the scanner's hits (trader-scanner) |
| `trader/plan.json` | the trade you are planning (trader-exit) |
| `trader/portfolio.json` | what you hold (trader-broker records fills there) |
| NSE RSS feeds | announcements, financial results, board meetings, corporate actions, insider trading |
| NSE announcements API | per-symbol fallback, used when the RSS feeds hold nothing for a symbol |
| Google News RSS | one search per symbol, by company name |
| Publisher RSS | Economic Times, Moneycontrol, Mint, Business Standard, BusinessLine, NDTV Profit |
| RBI and SEBI press releases, NSE FII/DII | a short market context section, not tied to one stock |
| Yahoo Finance chart endpoint | the last price against yesterday's close (unofficial, can lag) |
| `trader/cache/EQUITY_L.csv` | NSE's company list, kept for a week, used to match company names |
| `trader/state/news.json` | what has been shown (kept 30 days) |

The NSE and publisher feeds cover the whole market. The tool keeps only the
items that name your symbols or companies.

## The rules

- **Headlines are leads, not facts.** Before telling the user something
  happened, open the story or the filing and read it. Quote the source and
  link it. Never summarise a paywalled story you could not read: say so.
- **Filings beat headlines.** Filings print first. If a filing and a headline
  disagree, the filing is what the company told the exchange.
- **Every item shows its source.** If a source fails, the tool prints
  "no data from" and the source name, then carries on. Report that gap to the
  user. Never fill it with a guess.
- **Say what it touches.** Every item lists the symbols it touches and its
  tags: earnings, analyst, legal, deal, capital, people, risk, halt,
  regulatory, macro.
- **Filings marked `!` are important.** They cover financial results,
  acquisitions or mergers, credit ratings, resignations of key people, order
  wins and insolvency or default.
- **Filing categories.** Each filing maps to one or more of: financial
  results, board meeting, acquisition or merger, credit rating, insider
  trading or SAST, dividend, bonus, split or buyback, resignation of key
  people, fund raising, order win, insolvency or default.
- **MOVING** marks a stock 3 % or more from yesterday's close (`--move-pct`).
  A move with no headline is worth saying out loud too.
- **No predictions.** Report what was published and how far the price is from
  yesterday's close. Never say what the stock will do next.

## Steps

1. Run the check: `python3 "${CLAUDE_SKILL_DIR}/news.py"`. Exit code 1 means
   nothing new. `--all` shows items already seen. `--json` gives everything
   machine readable. `--dry-run` leaves the state alone.
2. Read the items that matter. Start with every `!` filing, anything tagged
   earnings, halt, legal, regulatory or risk, and every MOVING symbol.
3. Write a short brief per symbol: what happened, the source and link, the
   move, and one line on why it matters to the setup. For example, "results
   are due this week, so an overnight gap can jump past any stop".
4. Read the market context section for RBI, SEBI and FII/DII news. Mention it
   only when it bears on the trade.
5. If a story changes the picture, say so before `/trader-entry` and
   `/trader-exit`. Examples are a results date inside the trade, a halt or a
   fund raising. Never act on a headline alone.

During the session, run `/loop 15m /trader-news`. You can also schedule a task
each morning before the 9:15 IST open.

## What it never does

- Never invents or embellishes a story, a quote or a number.
- Never trades on news, and never tells the user to buy or sell because of a
  headline.
- Never hammers a server. It sends one request per feed, one search per
  symbol, and pauses between calls.

## Safety

Education and tooling, not financial advice. This skill only reads and
reports. Nothing places an order except `/trader-broker`, after `/trader-risk`
passes and the user types an explicit yes for that order.
