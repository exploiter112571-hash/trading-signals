# Paper Trading Log

| Date | Symbol | Side | Size | Entry Price | Avg Cost (incl. commission) | Stop (GTC) | Account | Notes |
|---|---|---|---|---|---|---|---|---|
| 2026-09-09 | XLE | BUY | 1 share | $65.25 | — | none at entry; backfilled 2026-09-14 as STP SELL @ $62.61 (orderId 8), later cancelled as orphaned when this position was closed by the test-fill below — see backfill section | DUQ874622 (paper) | First trade — breaks the seal. Closed 2026-09-14, see below. |
| 2026-09-09 | USO | BUY | 1 share | $148.87 | $149.87 | $142.38 (orderId 10) | DUQ874622 (paper) | Automated via place_order.py |
| 2026-09-14 | XLE | SELL | 1 share | $66.12 | — | N/A — closing trade, no remaining position to protect; orphaned the orderId 8 stop above, cancelled during same-session cleanup | DUQ874622 (paper) | Accidental test fill while validating --stop enforcement (used SELL on an existing long instead of a fresh symbol) — closed the original XLE position. Cleaned up immediately, see below. |
| 2026-09-14 | XLE | BUY | 1 share | $66.17 | $66.8317 | $62.86 (orderId 14) | DUQ874622 (paper) | Position re-established via place_order.py --stop 5 after cleanup |
| 2026-09-16 | XOM | BUY | 1 share | $168.89 | $169.89 | $160.45 (orderId 20) | DUQ874622 (paper) | score 5.01 — Polymarket: no 24h data yet, Gulf jets 0 (vs 7d avg 9.88, below baseline), GDELT 0 (flat vs avg 0.0), VIX 17.01. Quiet/baseline reading, not an escalation signal. |
| 2026-09-16 | CVX | BUY | 1 share | $217.55 | $218.55 | $206.67 (orderId 25) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | COP | BUY | 1 share | $141.85 | $142.85 | $134.76 (orderId 30) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | SLB | BUY | 1 share | $54.45 | $54.9945 | $51.73 (orderId 35) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | OXY | BUY | 1 share | $63.50 | $64.135 | $60.32 (orderId 40) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | HAL | BUY | 1 share | $35.89 | $36.2489 | $34.10 (orderId 45) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | VLO | BUY | 1 share | $399.09 | $400.09 | $379.14 (orderId 50) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | MPC | BUY | 1 share | $413.00 | $414.00 | $392.35 (orderId 55) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | BNO | BUY | 1 share | $63.40 | $64.034 | $60.23 (orderId 60) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-16 | UNG | BUY | 1 share | $10.47 | $10.5747 | $9.95 (orderId 65) | DUQ874622 (paper) | score 5.01 — same breakdown as XOM above (same scoring snapshot) |
| 2026-09-17 | EOG | BUY | 1 share | $147.79 | $148.79 | $140.40 (orderId 70) | DUQ874622 (paper) | score 30.18 — Gulf jets 45 vs 7d avg 15.68 (+187%, capped at max 25pts), Polymarket +0.56pp avg 24h across 24 markets (0.98pts), GDELT flat 0 vs 0, VIX 16.2 (4.2pts). Real elevated reading (jets maxed out), not baseline. |
| 2026-09-17 | DVN | BUY | 1 share | $48.72 | $49.2072 | $46.28 (orderId 75) | DUQ874622 (paper) | score 30.18 — same breakdown as EOG above (same scoring snapshot) |
| 2026-09-17 | KMI | BUY | 1 share | $31.44 | $31.7544 | $29.87 (orderId 80) | DUQ874622 (paper) | score 30.18 — same breakdown as EOG above (same scoring snapshot) |
| 2026-09-17 | WMB | BUY | 1 share | $71.50 | $72.215 | $67.92 (orderId 85) | DUQ874622 (paper) | score 30.18 — same breakdown as EOG above (same scoring snapshot) |
| 2026-09-17 | BKR | BUY | 1 share | $56.55 | $57.1155 | $53.72 (orderId 90) | DUQ874622 (paper) | score 30.18 — same breakdown as EOG above (same scoring snapshot) |
| 2026-09-17 | FANG | BUY | 1 share | $197.00 | $198.00 | $187.15 (orderId 95) | DUQ874622 (paper) | score 30.18 — same breakdown as EOG above (same scoring snapshot) |
| 2026-09-17 | PSX | BUY | 1 share | $269.12 | $270.12 | $255.66 (orderId 100) | DUQ874622 (paper) | score 30.18 — same breakdown as EOG above (same scoring snapshot) |

## 2026-09-14 — stop-loss backfill + structural fix

Both open positions (XLE, USO) had no stop-loss protection. Added GTC stop-sell orders at 5% below cost basis:

- USO: STP SELL 1 @ 142.38, GTC (orderId 10)
- XLE: STP SELL 1 @ 62.61, GTC (orderId 8) — later superseded, see below

Note: an initial attempt defaulted to TIF=DAY (IBKR account preset overrides unless TIF is explicitly set), which would have expired the stop at end of trading day. Caught and replaced with explicit GTC orders.

**`place_order.py` rewritten**: `--stop PERCENT` is now a required argument (argparse `required=True`) — the script refuses to run without it. On fill, it automatically computes and places a GTC protective stop at that percentage from the fill price. There is no code path to an unprotected position through this script anymore.

**Testing mistake + cleanup**: while validating the new mandatory-stop behavior, ran `place_order.py XLE 1 SELL --stop 5` as a test — this closed the existing XLE long (1 share) instead of opening a fresh test position, and left two orphaned stop orders (the original protective SELL stop with nothing left to protect, plus a new BUY stop meant for a short position that was never actually open). Caught immediately via a positions+orders audit, cancelled both orphaned orders, and re-bought 1 share of XLE through the now-fixed script (`--stop 5`) to restore the position with proper protection. Final state verified clean: exactly 2 positions (XLE, USO), exactly one GTC stop order each.

## 2026-09-16 — 10-trade batch, cited from live pipeline data

Requested: every trade_log.md row cites its reason from real pipeline data (`~/pipeline/scorer.py` / `signals.db`), no entry without `--stop`. Pulled the live score before placing anything:

```
Score: 5.01/100
  market_delta: no 24h-old pair available yet (points: 0)
  jets:  latest=0, 7d avg=9.88, pct_above_avg=-1.0 (points: 0)
  gdelt: latest=0, 7d avg=0.0 (points: 0)
  vix:   17.01 (points: 5.01)
```

**This is a quiet/flat reading, not an escalation signal** — every component is at or below baseline. Flagged this mismatch against the example format ("score 64...") before proceeding; user confirmed placing the trades anyway as honest low-signal/control trades rather than waiting for a real signal or fabricating one. All 10 rows above cite this exact snapshot since they were placed in the same session/decision point — re-running the scorer 10 times in a row would've just repeated the same underlying jets/gdelt values (unchanged since the last 15-min cron poll) with cosmetic VIX noise, not genuine new signal.

Basket: 10 distinct energy/oil-sector names (XOM, CVX, COP, SLB, OXY, HAL, VLO, MPC, BNO, UNG), 1 share each, all via `place_order.py --stop 5`. One transient IBKR connectivity blip during the XOM order (Error 1100/1102, auto-reconnected) — still filled correctly. Independently verified afterward via a fresh `ib_insync` positions+orders query (not just trusting the script's own printed output): all 10 positions present at exactly 1 share, all 10 with exactly one GTC stop order each, pre-existing XLE/USO positions and stops untouched. 12 total positions, 12 total open stop orders, no orphans, no duplicates.

## 2026-09-17 — discrepancy found: COP and OXY vanished from the account

Re-verifying positions the next day (in the course of a new request) surfaced that **COP and OXY are gone with zero trace**, despite both being independently confirmed present (1 share each, with a live GTC stop) immediately after the 2026-09-16 batch above.

Checked exhaustively before concluding this: current positions (`ib.positions()`), all open orders (`reqAllOpenOrders`), completed orders including cancelled (`reqCompletedOrders(apiOnly=False)`), full execution history (`reqExecutions`), and portfolio (`ib.portfolio()`, which retains closed lots with realized P&L). **All five checks show no record of COP or OXY ever existing** — not filled, not stopped out, not cancelled. Account identity confirmed unchanged (`DUQ874622`, consistent NLV), so this isn't an account switch.

For contrast, SLB's stop *did* trigger properly in the same window and shows a completely normal, clean audit trail (`SLB SLD 1.0 @ 51.73`, appears correctly in completed orders) — so the stop-loss mechanism itself is not implicated. This looks like a genuine irregularity specific to COP and OXY in the IBKR paper environment (or this IBC/Gateway build), not a bug in `place_order.py` or a client-side scripting error I can point to directly.

**Confirmed-real positions as of 2026-09-17**: XOM, CVX, HAL, VLO, MPC, BNO, UNG, XLE, USO (9 positions, all with intact GTC stops). COP and OXY are struck from the effective position count; the 2026-09-16 rows above are left as-written (accurate to what was true at the time) rather than edited, with this section as the correction of record.

## 2026-09-17 — 7-trade batch, real elevated score (not baseline)

Live score pulled before placing anything:

```
Score: 30.18/100
  market_delta: +0.0056 avg 24h delta across 24 markets (points: 0.98)
  jets:  latest=45, 7d avg=15.68, pct_above_avg=+1.87 (points: 25, capped/maxed)
  gdelt: latest=0, 7d avg=0.0 (points: 0)
  vix:   16.2 (points: 4.2)
```

Unlike the 2026-09-16 batch (flat/quiet, score 5.01), this is a **real elevated reading** — Gulf jets at +187% above the 7-day baseline, maxing out that component's point cap. Still below the 60 alert threshold, but a genuine signal, not a control/baseline trade.

Basket: 7 new energy/oil names not overlapping any current holding — EOG, DVN, KMI, WMB, BKR, FANG, PSX (spanning E&P, midstream/pipelines, oilfield services, refining), 1 share each, all via `place_order.py --stop 5`.

Given the unexplained disappearance of COP/OXY discovered earlier in this same session, every fill was independently re-verified via a fresh `ib_insync` positions + `reqAllOpenOrders` query before being logged here (not just trusting the script's own printed FILLED output). All 7 confirmed: each at exactly 1 share with exactly one GTC stop order. Account-wide total after this batch: 16 positions, 16 open stop orders — exact 1:1 match, no orphans, no duplicates.

## 2026-11-11 — paper account found reset; 4-trade European energy basket

**Account reset.** Before trading, a read-only check of `DUQ874622` showed **0 positions, 0 open orders, and no history at all** — `reqExecutions`, `reqCompletedOrders(apiOnly=False)` and `portfolio()` are all empty. The 16 positions/16 stops recorded on 2026-09-17 are gone with no fills or stop-outs, consistent with an IBKR paper-account reset rather than trading activity. NLV ~$1,012,314. Earlier sections are left as written.

**Live score at decision time** (16:45 SGT run):

```
Score: 10.44/100
  market_delta: -0.0062 avg 24h delta across 27 markets (points: 0)
  jets:  latest=0, 7d avg=44.76 (points: 0)   <- feed broken, see below
  gdelt: latest=8, 7d avg=6.76, +18.3% (points: 3.67)
  vix:   18.77 (points: 6.77)
```

Quiet reading, well below the 60 threshold — these are low-signal trades placed on request, not a response to an escalation. The jets reading of 0 was a **data failure**, not a real lull: adsb.lol began rejecting radii above 250 NM (HTTP 403), so every Osiris region failed and `/api/flights` returned 0 aircraft from 2026-11-10 22:00. Fixed the same session (see `deploy/osiris/osiris-local.patch`); jets history was cleared so the 7-day baseline rebuilds on the new coverage.

**Why Europe.** Requested at ~16:50 SGT with the US market closed. London/Paris/Milan were open, so the basket is four European oil & gas majors, 1 share each, all via `place_order.py --stop 5`. A planned 9-share US basket for the 22:35 SGT open was cancelled in favour of this before it placed anything.

| Symbol | Listing | Fill | Stop (GTC, 5%) | Stop orderId |
|---|---|---|---|---|
| SHEL | LSE, GBP (quoted in pence) | 3659.9998p | 3477.0p | 39 |
| BP. | LSE, GBP (quoted in pence) | 562.0p | 533.9p | 44 |
| TTE | Euronext Paris (SBF), EUR | €79.18 | €75.22 | 49 |
| ENI | Borsa Italiana (BVME), EUR | €24.915 | €23.67 | 54 |

Fills 2026-11-11 ~16:55 SGT. (IB reported fill times as `00:55+00:00`, i.e. 8 hours behind actual UTC — a paper-environment timestamp quirk, noted rather than corrected.) `avgCost` in `positions()` includes commission (e.g. BP. £5.62 + ~£3).

**Script changes made to get here** (`place_order.py`):
1. *Safety fix:* an unfilled market order used to be left live after the 30s timeout, so it could fill later with no stop. It is now cancelled; any partial fill gets a stop sized to the filled quantity. Tested with the US market closed (XLE, 1 share): cancelled cleanly, nothing left open.
2. Added `--exchange` (primary listing) and `--currency` for non-US stocks. The first attempt direct-routed to LSE/SBF/BVME and all four were rejected by the Gateway's precautionary settings (Error 10311, "Order was discarded") — no fills. Switched to SMART routing with `primaryExchange`, after which all four filled.

Pre-trade what-if checks: SHEL, BP., TTE, ENI and RWE accepted; EQNR (Oslo) rejected — no trading permission. No market-data subscription on the paper account, so no live quotes; stops are computed from the actual fill.

**Independent verification** (fresh read-only `ib_insync` positions + `reqAllOpenOrders`, not the script's own output): 4 positions at exactly 1 share, 4 open STP SELL GTC orders, one per position at the prices above. No orphans, no duplicates.

## 2026-11-11 — 7 more European energy names (~17:05 SGT)

Requested while the 22:35 SGT US basket remains scheduled (kept, not cancelled). Score at decision time (17:00 run): **10.16/100** — market_delta 0, jets 0 (baseline rebuilding after the feed fix; latest real reading 80 aircraft), gdelt 8 vs 6.81 avg (3.5 pts), VIX 18.66 (6.66 pts). Quiet, low-signal trades.

What-if pre-checks passed for all seven below; NESTE (Helsinki) failed on a symbol mismatch (IB local symbol NEF) and was dropped as a renewables name anyway. 1 share each, `place_order.py --stop 5`, SMART-routed with primary exchange:

| Symbol | Listing | Fill | Stop (GTC) | Stop orderId |
|---|---|---|---|---|
| REP | BME Madrid, EUR | €29.27 | €27.81 | 59 |
| GALP | Euronext Lisbon, EUR | €18.865 | €17.92 | 64 |
| OMV | Vienna, EUR | €71.00 | €67.45 | 69 |
| HBR | LSE, GBP (pence) | 272.4p | **258.8p** (see below) | **93** |
| TEN | Borsa Italiana, EUR | €27.35 | €25.98 | 79 |
| SPM | Borsa Italiana, EUR | €4.343 | €4.13 | 84 |
| VK | Euronext Paris, EUR | €19.685 | €18.70 | 89 |

**Incident — HBR briefly unprotected.** The script's stop for HBR (258.78p, orderId 74) was rejected: LSE trades HBR in 0.2p increments between 200p and 500p, and the script rounded stops to 2 decimals. The independent verification caught it (11 positions, 10 stops). A valid GTC stop at 258.8p (orderId 93) was attached manually within minutes. Fixed in `place_order.py`: stops are now rounded to the instrument's IB market-rule tick, and the script exits non-zero with a loud warning if a stop isn't accepted.

**Independent verification after the fix:** 11 positions (SHEL, BP., TTE, ENI + the 7 above), 11 STP SELL GTC orders, exactly one per position. No orphans, no duplicates.

## 2026-11-12 — 9-share US energy basket (planned for 22:35 SGT on 11-11; actually placed 20:01 SGT on 11-12, pre-market)

**Timing deviation.** The basket was scheduled by a waiting script for 2026-11-11 22:35 SGT (09:35 ET, just after the US open), with the instruction to keep it and never cancel it. The host PC slept from ~22:00 SGT on 11-11 (apart from a brief wake ~01:00) until ~20:00 SGT on 11-12. The script's only condition was "now ≥ 22:35", so on wake it placed the orders immediately — at **07:02 ET, in the US pre-market**, not at the open. All nine market orders filled on **Cboe BYX** (early-session venue), so fills are pre-market prices with thinner liquidity than regular hours. The scheduler should have had a "still inside regular hours" check; any future scheduled basket needs one.

**Score at placement** (last stored run before the sleep, 2026-11-11 22:00 SGT — the pipeline had not yet run after waking):

```
Score: 9.41/100
  market_delta: -0.007 avg across 28 markets (points: 0)
  jets:  latest=103, baseline rebuilding (13/16 rows) (points: 0)
  gdelt: latest=8, 7d avg=6.95, +15.1% (points: 3.02)
  vix:   18.39 (points: 6.39)
```

Quiet reading; low-signal trades placed on request, not on a signal.

1 share each via `place_order.py --stop 5` (stops tick-rounded; US tick 0.01):

| Symbol | Fill (USD) | Stop (GTC, 5%) | Stop orderId |
|---|---|---|---|
| XOM | 167.48 | 159.11 | 100 |
| CVX | 214.80 | 204.06 | 106 |
| HAL | 33.55 | 31.87 | 112 |
| VLO | 372.58 | 353.95 | 118 |
| MPC | 405.00 | 384.75 | 124 |
| BNO | 58.64 | 55.71 | 130 |
| UNG | 10.29 | 9.78 | 136 |
| XLE | 63.64 | 60.46 | 142 |
| USO | 141.09 | 134.04 | 148 |

One transient Gateway connectivity blip during XOM (Error 1100 → 1102, "data maintained"); the order still filled normally. Execution records show the correct UTC time (12:02Z) for these fills, unlike the 8-hour-shifted timestamps on the 11-11 European fills.

**Independent verification** (fresh read-only positions + `reqAllOpenOrders`): **20 positions, 20 STP SELL GTC orders**, exactly one per position — the 11 European names from 11-11 plus these 9. No orphans, no duplicates, no other open orders. All 11 European stops survived the overnight sleep untouched (GTC stops live at IBKR, not on the host).
