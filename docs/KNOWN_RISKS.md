# Known flaws and risks

The main weaknesses of this system, each with the evidence that showed it and
what has been done or would be done about it.

## 1. It only runs while the home PC is awake

The whole pipeline runs in WSL on a Windows desktop. When the PC sleeps,
nothing collects, nothing scores and no alerts go out.

- **Evidence:** the sleep from 22:00 on 2026-11-11 cost about 22 hours of
  data. The scheduled US basket then fired on wake at 07:02 ET and filled
  pre-market instead of at the open (see `ibkr/trade_log.md`).
- **Mitigation so far:** a Windows login launcher that keeps WSL running
  (`deploy/start-wsl-ibgateway.vbs`), a market-hours guard in
  `ibkr/place_order.py`, and GTC stops held on IBKR's servers, so open
  positions stay protected while the PC is off.
- **Real fix:** move it to an always-on server or VPS.

## 2. It depends on a fragile chain of unofficial data sources

The jets and "GDELT" numbers don't come from official APIs. They come through
Osiris, a third-party app run locally, and Osiris scrapes community feeds.

- **Jets:** when adsb.lol quietly added a 250 NM radius limit (2026-11-10),
  Osiris dropped the 403 errors and reported 0 aircraft, and the pipeline
  didn't notice. Fixed with a local patch using four smaller map tiles
  (`deploy/osiris/osiris-local.patch`).
- **"GDELT" isn't really GDELT:** it is an RSS headline geo-mapper. It pinned
  every Iran story to one point outside the Gulf box, so that component read 0
  for weeks. Fixed by also counting headlines that name Gulf places.
- **No timestamps:** it gives no per-event times, so the count is a snapshot
  of what is live now, not a true 6-hour window.
- **Would do:** alert when a feed returns 0 or errors instead of recording it
  as a quiet reading; move to official sources where possible.

## 3. The score is uncalibrated and partly measures the wrong thing

- **Jets:** it counts *all* aircraft in the box, mostly airliners. Military
  aircraft often switch their transponders off, and ADS-B coverage over Iran
  is thin. So it measures air traffic, not a military build-up.
- **Thresholds were set by hand:** +20 points of odds movement, double the
  7-day average, VIX 12–32. None of them was tuned on data. The backtest
  (`scripts/backtest.py`) is rough, and the jets baseline has existed only
  since 2026-11-12.
- **Market signal is diluted:** it averages about 50 markets, including
  Israeli domestic-politics ones that the "israel" keyword catches. A real
  spike in one Hormuz market gets washed out.
- **Never tested in a real event:** the score has not come close to the alert
  level of 60.
- **Would do:** count military aircraft only, drop off-topic markets or
  weight by relevance, and calibrate thresholds against past events.

## Smaller risks

- **Delayed data:** VIX is a daily close from yfinance, FRED lags a few days,
  and polling every 15 minutes is slow for a fast-moving event.
- **Data collected but unused:** Kalshi (about 10 GB) and FRED are gathered but
  not used in the score.
- **No automated tests:** every bug above was found by hand during
  diagnostics.
- **Trades too small to judge:** 1-share trades mean commissions wipe out any
  P&L, so the trades can't show whether the signal works.
