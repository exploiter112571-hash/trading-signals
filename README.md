# trading-signals

Monitor-and-alert pipeline for Gulf/Hormuz geopolitical risk. **This does not place trades.** It scores current conditions on a 0-100 scale and sends a Telegram alert when the score crosses a threshold; a human decides whether and how to act.

## Components

- **`poller.py`** — runs every 15 minutes via cron. Fetches:
  - Polymarket (Iran/Hormuz/oil/OPEC/Israel/nuclear-related markets, whole-word keyword match over the top 500 open markets by 24h volume, fetched as 5 pages of 100 — ~50 tracked markets) → `odds` table
  - A local [Osiris](https://github.com/aiacos/osiris) instance's `/api/flights` (Gulf/Hormuz bounding box aircraft count) → `jets` table
  - Osiris `/api/gdelt` (conflict-related events in the same bounding box) → `gdelt` table
  - Osiris fetches are best-effort: if Osiris is down, the failure is logged and skipped without affecting the Polymarket fetch.

- **`scorer.py`** — runs immediately after `poller.py` in the same cron invocation. Reads the latest rows from `signals.db` and computes a composite 0-100 score:
  - Prediction-market 24h delta (up to 35 pts)
  - Gulf jet count vs 7-day average (up to 25 pts)
  - GDELT conflict events vs 7-day average (up to 20 pts)
  - VIX level, fetched fresh via yfinance (up to 20 pts)

  Every run is logged to the `signals` table (`ts`, `score`, `components` as JSON). If score >= 60, sends a Telegram message with the full breakdown.

- **`news.py`** — every 15 minutes (:05/:20/:35/:50). Pulls headlines from Google News (one Hormuz/Gulf/Iran/Brent query), BBC Middle East, Al Jazeera and OilPrice.com RSS, scores each title by weighted keywords (Hormuz, tanker, IRGC, missile, Brent, …) and keeps relevant ones in the `news` table (30 days). Context only; not part of the score.

- **`stock_picks.py`** — hourly (:25). A rule-based screen, **not investment advice and never places orders**. Combines the score regime (calm < 30 ≤ elevated < 60 ≤ high) and its 24h trend with each ticker's momentum (5d/20d return, close vs 50-day SMA, via yfinance) over a fixed watchlist:
  - *beneficiaries* of Gulf risk (XLE, XOM, CVX, OXY, tankers FRO/DHT/INSW/STNG, defense LMT/RTX/NOC/LHX, GLD) → `LONG-WATCH` when risk is elevated or rising and momentum confirms
  - *exposed* names (JETS, DAL, UAL, CCL, RCL) → `AVOID` while risk is elevated or rising, `HEDGE-WATCH` if also below the 50-day SMA
  - everything else `NEUTRAL`. Each run is written to `stock_picks` with a one-line rationale; edit `UNIVERSE` to change the watchlist.

- **`dashboard/`** — read-only web UI (standard library only) on `127.0.0.1:8050`: score and components, score history with the alert line, stock picks, Polymarket odds with 24h change, news, and data freshness. Works on a phone; reach it remotely through Tailscale, see [docs/PHONE_ACCESS.md](docs/PHONE_ACCESS.md).

## Data

`signals.db` (SQLite, gitignored — not checked in) holds the core tables `odds`, `jets`, `gdelt`, `signals`, plus `gdelt_v2`, `mil_jets`, `gnss` (shadow sources), `news` and `stock_picks`.

## Setup

Requires a `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` in a `.env` file (path configurable via `EWS_ENV_PATH` in `scorer.py`) for alert delivery. Neither script has any credentials hardcoded.

## Cron

```
*/15 * * * * python3 poller.py >> poller.log 2>&1 && python3 scorer.py >> scorer.log 2>&1
5,20,35,50 * * * * python3 news.py >> news.log 2>&1
25 * * * * python3 stock_picks.py >> stock_picks.log 2>&1
```

## ibkr/ — paper trading execution (manual, not automated)

Scripts that touch the IB Gateway paper trading API directly. **Trades are never placed automatically by this pipeline** — every trade in `trade_log.md` was placed manually via `place_order.py`, in response to an explicit decision each time, usually informed by (but never auto-triggered by) the score above.

- **`balance.py`** — connects to IB Gateway (port 4002, paper) and prints net liquidation value.
- **`place_order.py`** — places a market order and *requires* a `--stop PERCENT` argument; refuses to run without it. On fill, automatically attaches a GTC (good-til-canceled) protective stop at that percentage from the fill price. There is no code path to an unprotected position through this script. It also refuses (exit 2) to place outside the exchange's regular session, read from IB's `liquidHours` (override with `--allow-outside-rth`), so a delayed or woken scheduler can't fill pre-market.
- **`trade_log.md`** — running journal of every paper trade, including entry price, stop price/order ID, and the live score/component breakdown that motivated it at the time. Also documents two real incidents transparently: a testing mistake that briefly left orphaned stop orders (caught and fixed same-session), and an unexplained IBKR paper-environment anomaly where two positions (COP, OXY) vanished with zero trace despite being independently verified present shortly after being filled.

## scripts/ — standalone data collectors and one-off analysis

Independent scripts, most running on their own cron/systemd schedule, that either feed data other pipeline components read or were used for ad-hoc analysis:

- **`macro_fetch.py`** — hourly cron (incremental: re-fetches from the last stored day, so missed runs while the PC sleeps are backfilled on the next waking hour). Pulls VIX/S&P/gold/Treasury yields via yfinance, plus 2Y Treasury yield and ICE BofA High Yield credit spread via the FRED API (key read from `~/.fred_api_key`, never hardcoded) into `macro.db`.
- **`polymarket_odds.py`** — 15-min cron. Separate, older Polymarket keyword tracker (Iran/oil/Hormuz) into `polymarket_odds.db`, paired with `alerts.py`.
- **`alerts.py`** — runs after `polymarket_odds.py` in the same cron line; simple threshold-based console/log alert (not Telegram) over the odds it just fetched.
- **`opensky_poller.py`**, **`kalshi_poller.py`**, **`polymarket_poller.py`** — continuous background pollers (run as systemd user services, not cron) building long-running historical datasets of global aircraft state vectors, Kalshi markets, and the full Polymarket market catalog respectively. Independent of the Gulf/Hormuz-specific `poller.py`/`scorer.py` above.
- **`geo_risk_score.py`** — earlier, standalone version of the composite scoring idea (global OpenSky airborne count + Polymarket delta + VIX), superseded by `scorer.py`'s more targeted Gulf/Hormuz-bbox + Osiris-based approach but kept for reference.

## Data sources and what uses them

Snapshot as of 2026-11-11. Only the first group feeds the score; several collectors store data that nothing reads yet.

| Source | Collector | Store | Size / coverage | Used by |
|---|---|---|---|---|
| Polymarket — Gulf/oil/Iran/Israel markets | `poller.py` (15 min) | `signals.db` `odds` | ~50 markets | `scorer.py` (market-delta component) |
| Osiris `/api/flights` (adsb.lol) | `poller.py` | `signals.db` `jets` | Gulf bbox aircraft count | `scorer.py` (jets) |
| Osiris `/api/gdelt` (news RSS) | `poller.py` | `signals.db` `gdelt` | Gulf conflict headlines | `scorer.py` (gdelt) |
| VIX (yfinance, live) | `scorer.py` | — | — | `scorer.py` (vix) |
| Polymarket keyword search (iran/oil/hormuz) | `scripts/polymarket_odds.py` (15 min) | `~/polymarket_odds.db` | ~270 open markets | `scripts/alerts.py` (log-only alerts) |
| Polymarket full catalog | `scripts/polymarket_poller.py` (hourly, systemd) | `~/polymarket_markets.db` | ~195k markets/snapshot, 2.7 GB | nothing yet |
| Kalshi full catalog | `scripts/kalshi_poller.py` (systemd) | `~/kalshi_markets.db` | ~173k markets/snapshot, 8.2 GB; mostly elections/sports, little Gulf/oil coverage | nothing yet |
| OpenSky global state vectors | `scripts/opensky_poller.py` (systemd) | `~/opensky_states.db` | global aircraft | `geo_risk_score.py` (legacy) only |
| yfinance: VIX, S&P 500, gold, 10Y/30Y yields | `scripts/macro_fetch.py` (hourly) | `~/macro.db` `prices` | daily bars | nothing yet |
| FRED: `DGS2` (2Y Treasury), `BAMLH0A0HYM2` (HY credit spread) | `scripts/macro_fetch.py` (hourly; key in `~/.fred_api_key`, 0600) | `~/macro.db` `fred_series` | DGS2 since 1976, HY OAS since 2023; ~1–2 day publication lag | nothing yet |

**IBKR is not connected to any of these.** Only `ibkr/place_order.py` and `ibkr/balance.py` talk to IB Gateway (paper, port 4002), and neither is run by cron or systemd. Every trade is a manual decision; the score informs it but never triggers it. Executions placed by `place_order.py` show `clientId=4` in IB's execution records.

Known gaps / candidate improvements: the Israel next-PM markets match the "israel" keyword but are domestic politics, diluting the market-delta component; Kalshi and FRED (e.g. the HY credit spread as a second stress gauge beside VIX) are collected but unused; collection pauses whenever the host PC sleeps (GTC stops live at IBKR and are unaffected).

## data/ — CSV snapshot of collected data

`./export_data.sh` exports the pipeline's data to `data/` (timestamp in `data/EXPORTED_AT`): composite scores with full component breakdown (`scores.csv`), Gulf jet counts, GDELT event counts, the pipeline's Polymarket odds, the standalone Polymarket odds history, macro prices and FRED series. The live `.db` files stay out of git; the Kalshi (~10 GB) and Polymarket market dumps (~3 GB) are far above GitHub's 100 MB file limit and are not exported. Snapshots are only as fresh as the last export + commit.

**God's Eye View + direct OSINT sources:** the God's Eye View app runs locally as a service (http://localhost:4173, `deploy/systemd/gods-eye-view.service`) for a live visual of the Gulf. The poller reads its GPS-integrity data (`gnss`) and also stores real GDELT 2.0 events (`gdelt_v2`) and adsb.lol military aircraft (`mil_jets`); the scorer logs all three as shadow components that don't count toward the score yet. In a fresh clone run `python3 poller.py --backfill-gdelt 7` for the GDELT baseline. Details and further sources (incl. awesome-osint): [docs/OSINT_SOURCES.md](docs/OSINT_SOURCES.md).

**Fresh clone:** `signals.db` is gitignored, so a new checkout starts empty: market_delta has no 24h-old odds and jets/gdelt have no 7-day baseline. Run `python3 import_data.py` once to seed `signals.db` from `data/` (pure Python, no `sqlite3` CLI needed; safe to re-run). The baselines then work right away. market_delta pairs odds 24–30 h old, so it only benefits if the snapshot was exported within that window; otherwise it fills in after a day of polling.

See [`docs/CODE_WALKTHROUGH.md`](docs/CODE_WALKTHROUGH.md) for a function-by-function explanation of `poller.py` and `scorer.py`.
See [`docs/DEVELOPMENT_HISTORY.md`](docs/DEVELOPMENT_HISTORY.md) for how the repo evolved commit by commit.
See [`docs/KNOWN_RISKS.md`](docs/KNOWN_RISKS.md) for the system's known flaws and risks.

## deploy/ — machine setup (cron, services, log rotation, Osiris patch)

Templates for the configuration that lives outside the repo, so the whole setup can be rebuilt on any Linux/WSL machine. Nothing in the repo names a specific user or home directory.

### Running on another machine

```bash
git clone https://github.com/exploiter112571-hash/trading-signals.git && cd trading-signals
python3 -m venv ~/.venv && ~/.venv/bin/pip install requests yfinance
python3 import_data.py                 # seed signals.db from the data/ snapshot
~/.venv/bin/python poller.py --backfill-gdelt 7
cp .env.example .env                   # optional: Telegram bot token + channel
deploy/install.sh                      # fill in this machine's paths into deploy/build/ (review)
deploy/install.sh --apply              # install crontab, logrotate, systemd units
```

Paths are resolved at run time, so the repo can live anywhere:

- `poller.py`, `scorer.py`, `scripts/backtest.py`: `signals.db` next to the code, or `$SIGNALS_DB`.
- `scripts/*` collectors: `.db`/`.log` files in `$PIPELINE_DATA_DIR` (default: your home directory).
- Telegram: `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHANNEL` from the environment, else this repo's `.env`, else `~/ews/.env`.
- `deploy/install.sh` fills `@PIPELINE_DIR@`, `@DATA_DIR@`, `@PYTHON@` (default `~/.venv/bin/python`), `@NODE@` (the `node` on PATH; Node 24) and `@HOME@` into the templates. Override any with env vars, e.g. `PYTHON=/usr/bin/python3 deploy/install.sh`.

Optional services need their own setup first: Osiris (`~/osiris-src`, see the patch below), God's Eye View (`~/gods-eye-view`, see [docs/OSINT_SOURCES.md](docs/OSINT_SOURCES.md)) and IB Gateway (`~/ibc`).

### Files

- **`install.sh`** — renders the templates below for this machine into `deploy/build/` (gitignored); `--apply` installs them (backs up the current crontab first). Services are installed but not enabled.
- **`systemd/ibgateway.service`** — runs IB Gateway headless via IBC (`~/ibc`, not in git: its config holds broker login).
- **`crontab.txt`** — crontab template: 15-min `poller.py`→`scorer.py` and `polymarket_odds.py`→`alerts.py`, 15-min `news.py` (:05/:20/:35/:50), hourly `stock_picks.py` (:25), hourly `macro_fetch.py` (:17), hourly logrotate (:40).
- **`systemd/*.service`** — user services for Osiris (`next start -p 3000`, Node 24), God's Eye View (Vite, port 4173), the dashboard (`dashboard.service`, 127.0.0.1:8050) and the three continuous pollers. After `install.sh --apply`: `systemctl --user enable --now <name>`.
- **`logrotate/pipeline.conf`** — weekly or >10 MB rotation (8 kept, compressed, copytruncate) for the collector and pipeline logs; run by the crontab line above with a user state file.
- **`start-wsl-ibgateway.vbs`** — Windows login launcher (copy into `shell:startup`). Starts the Ubuntu WSL distro hidden and holds it open with `sleep infinity`, so systemd (linger on) brings up cron, IB Gateway, Osiris and the pollers without a terminal open and WSL never idle-shuts-down. It cannot prevent Windows itself from sleeping.
- **`osiris/osiris-local.patch`** — local changes to the [Osiris](https://github.com/aiacos/osiris) checkout: Gulf/Hormuz place names in the `/api/gdelt` geo-dictionary (without these, Gulf stories never reach the poller) and, on `/api/flights`, a User-Agent plus a 250 NM radius cap (adsb.lol's limit; larger radii now return 403 and the feed silently went to 0 aircraft on 2026-11-10) and four Gulf/Hormuz tiles covering the jets bounding box. Apply with `git -C ~/osiris-src apply deploy/osiris/osiris-local.patch`, then `npx next build` and restart `osiris.service`.

Not included on purpose: databases and logs (local data), `.env`/API keys, and the IBC/IB Gateway config (contains broker credentials).

The templates run the collectors straight from `scripts/`. On the original machine, cron/systemd still run older copies from `~/`; there, keep them in sync when editing, or switch over with `deploy/install.sh --apply`.
