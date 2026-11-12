# Near-Close Operations

The intended production cadence is relative to the market close rather than a fixed wall-clock time.

## Suggested Routine

| Time | Action |
|---|---|
| Close - 15 min | Optional broad scan to see whether many names are forming lower-wick reversals |
| Close - 5 min | Refresh candidates and remove names with weak close-location or wide risk |
| Close - 2 min | Run final scan, review top candidates manually, and decide whether any deserve a small planned entry |
| Close + 1 min | Save final report and ingest studyable examples into the model book |

## Example Commands

Offline/provisional OHLCV feed:

```bash
python3 stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py \
  --prices-json data/near_close_daily_ohlcv.json \
  --profiles-json data/quality_profiles.json \
  --market-gate allowed \
  --output-dir reports/
```

Quote override path:

```bash
python3 stockbee-exhaustion-hammer-screener/scripts/screen_exhaustion_hammer.py \
  --universe-name nifty500 \
  --use-quote-latest \
  --max-symbols 500 \
  --max-api-calls 1200 \
  --market-gate allowed \
  --output-dir reports/
```

## Scheduling Note

If scheduling this scan, use an exchange calendar and run at `market_close - 2 minutes`. For NSE this is about 15:28 IST. Do not hard-code it without handling special sessions and market holidays.

## Handling Half Days

On early-close days, either:

- Run at the adjusted close minus two minutes, or
- Disable near-close actionability and use the output for study only.
