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

## ibkr/ — paper trading execution (manual, not automated)

Scripts that touch the IB Gateway paper trading API directly. **Trades are never placed automatically by this pipeline** — every trade in `trade_log.md` was placed manually via `place_order.py`, in response to an explicit decision each time, usually informed by (but never auto-triggered by) the score above.

- **`balance.py`** — connects to IB Gateway (port 4002, paper) and prints net liquidation value.
- **`place_order.py`** — places a market order and *requires* a `--stop PERCENT` argument; refuses to run without it. On fill, automatically attaches a GTC (good-til-canceled) protective stop at that percentage from the fill price. There is no code path to an unprotected position through this script.
- **`trade_log.md`** — running journal of every paper trade, including entry price, stop price/order ID, and the live score/component breakdown that motivated it at the time. Also documents two real incidents transparently: a testing mistake that briefly left orphaned stop orders (caught and fixed same-session), and an unexplained IBKR paper-environment anomaly where two positions (COP, OXY) vanished with zero trace despite being independently verified present shortly after being filled.

## scripts/ — standalone data collectors and one-off analysis

Independent scripts, most running on their own cron/systemd schedule, that either feed data other pipeline components read or were used for ad-hoc analysis:

- **`macro_fetch.py`** — hourly cron (incremental: re-fetches from the last stored day, so missed runs while the PC sleeps are backfilled on the next waking hour). Pulls VIX/S&P/gold/Treasury yields via yfinance, plus 2Y Treasury yield and ICE BofA High Yield credit spread via the FRED API (key read from `~/.fred_api_key`, never hardcoded) into `macro.db`.
- **`polymarket_odds.py`** — 15-min cron. Separate, older Polymarket keyword tracker (Iran/oil/Hormuz) into `polymarket_odds.db`, paired with `alerts.py`.
- **`alerts.py`** — runs after `polymarket_odds.py` in the same cron line; simple threshold-based console/log alert (not Telegram) over the odds it just fetched.
- **`opensky_poller.py`**, **`kalshi_poller.py`**, **`polymarket_poller.py`** — continuous background pollers (run as systemd user services, not cron) building long-running historical datasets of global aircraft state vectors, Kalshi markets, and the full Polymarket market catalog respectively. Independent of the Gulf/Hormuz-specific `poller.py`/`scorer.py` above.
- **`geo_risk_score.py`** — earlier, standalone version of the composite scoring idea (global OpenSky airborne count + Polymarket delta + VIX), superseded by `scorer.py`'s more targeted Gulf/Hormuz-bbox + Osiris-based approach but kept for reference.
