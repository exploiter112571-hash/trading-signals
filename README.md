# trading-signals

Monitor-and-alert pipeline for Gulf/Hormuz geopolitical risk. **This does not place trades.** It scores current conditions on a 0-100 scale and sends a Telegram alert when the score crosses a threshold; a human decides whether and how to act.

## Components

- **`poller.py`** — runs every 15 minutes via cron. Fetches:
  - Polymarket (Iran/Hormuz/oil/OPEC/Israel/nuclear-related markets) → `odds` table
  - A local [Osiris](https://github.com/aiacos/osiris) instance's `/api/flights` (Gulf/Hormuz bounding box aircraft count) → `jets` table
  - Osiris `/api/gdelt` (conflict-related events in the same bounding box) → `gdelt` table
  - Osiris fetches are best-effort: if Osiris is down, the failure is logged and skipped without affecting the Polymarket fetch.

- **`scorer.py`** — runs immediately after `poller.py` in the same cron invocation. Reads the latest rows from `signals.db` and computes a composite 0-100 score:
  - Prediction-market 24h delta (up to 35 pts)
  - Gulf jet count vs 7-day average (up to 25 pts)
  - GDELT conflict events vs 7-day average (up to 20 pts)
  - VIX level, fetched fresh via yfinance (up to 20 pts)

  Every run is logged to the `signals` table (`ts`, `score`, `components` as JSON). If score >= 60, sends a Telegram message with the full breakdown.

## Data

`signals.db` (SQLite, gitignored — not checked in) holds four tables: `odds`, `jets`, `gdelt`, `signals`.

## Setup

Requires a `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` in a `.env` file (path configurable via `EWS_ENV_PATH` in `scorer.py`) for alert delivery. Neither script has any credentials hardcoded.

## Cron

```
*/15 * * * * python3 poller.py >> poller.log 2>&1 && python3 scorer.py >> scorer.log 2>&1
```
