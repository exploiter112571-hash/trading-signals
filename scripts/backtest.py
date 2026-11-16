#!/usr/bin/env python3
"""Rough backtest of the Gulf/Hormuz scoring pipeline (scorer.py) against
signals.db. Answers: over the pipeline's actual run history, how often
would the composite score have crossed the alert threshold (60), and what
did the score distribution look like?

Two separate replays, because they have different levels of rigor:

1. REPLAY OF STORED `signals` ROWS (ground truth)
   Every row in `signals` is the actual output of a real scorer.py run at
   that moment -- not reconstructed, not point-in-time-adjusted. This is
   the most honest number but is limited to the ~119 runs that actually
   happened, which has a large gap in it (Osiris was down ~2026-09-18 to
   2026-11-09, so jets/gdelt contributed 0 for most of this window -- see
   prior audit note). Treat this as "what the live system actually said",
   not "what a correctly-functioning system would have said".

2. DENSE REPLAY OF THE MARKET-DELTA COMPONENT ALONE, across every distinct
   poll timestamp in `odds` (1987 rows / ~129 distinct timestamps, full
   ~55-day span). This component is the only one in scorer.py whose query
   is actually point-in-time correct as written (it filters `ts <= now_ts`
   for both the "now" and "24h-ago" lookups), so replaying it at historical
   timestamps doesn't leak future data. jets/gdelt/vix are deliberately
   NOT replayed this way:
     - compute_vs_baseline_component() in scorer.py grabs the single latest
       row in the table unconditionally (no `ts <= now_ts` filter) -- fine
       for live use (now_ts IS always ~now) but would leak future data if
       reused for historical replay without first patching that filter.
     - VIX is fetched live from yfinance each run; no historical VIX series
       is stored anywhere in this pipeline, so there is nothing to replay.
   So part 2 is explicitly a one-component-out-of-four lower bound on how
   often the full score would have crossed 60, not an attempt at the full
   historical score.

Run: python3 scripts/backtest.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scorer import (  # noqa: E402
    ALERT_THRESHOLD,
    DELTA_WINDOW_SECONDS,
    MARKET_DELTA_MAX_POINTS,
    compute_market_delta_component,
    DB_PATH,  # signals.db next to scorer.py, or $SIGNALS_DB
)


def replay_stored_signals(conn):
    rows = conn.execute("SELECT ts, score FROM signals ORDER BY ts").fetchall()
    print("=== Part 1: replay of stored `signals` rows (actual live runs) ===")
    print(f"{len(rows)} runs logged")
    if not rows:
        print("(no rows)")
        return

    scores = [r[1] for r in rows]
    buckets = [0, 20, 40, 60, 80, 100]
    print(f"min={min(scores):.2f}  max={max(scores):.2f}  "
          f"avg={sum(scores)/len(scores):.2f}")
    for lo, hi in zip(buckets[:-1], buckets[1:]):
        n = sum(1 for s in scores if lo <= s < hi)
        print(f"  [{lo:3d}-{hi:3d}): {n}")
    n_alert = sum(1 for s in scores if s >= ALERT_THRESHOLD)
    print(f"Runs that would have alerted (score >= {ALERT_THRESHOLD}): {n_alert} / {len(rows)}")
    if n_alert == 0:
        print("-> threshold never crossed in the live history we have on record.")


def replay_market_delta_only(conn):
    print()
    print("=== Part 2: dense replay of market-delta component only ===")
    distinct_ts = [r[0] for r in conn.execute("SELECT DISTINCT ts FROM odds ORDER BY ts")]
    print(f"{len(distinct_ts)} distinct poll timestamps in `odds` "
          f"(span: full history, not just live scorer.py runs)")

    results = []
    for ts in distinct_ts:
        comp = compute_market_delta_component(conn, ts)
        results.append((ts, comp["points"]))

    with_data = [p for _, p in results if p is not None]
    n_full = sum(1 for p in with_data if p >= MARKET_DELTA_MAX_POINTS)
    n_nonzero = sum(1 for p in with_data if p > 0)
    n_zero = sum(1 for p in with_data if p == 0)
    print(f"Timestamps with a usable 24h-old comparison pair: {len(with_data)} / {len(distinct_ts)}")
    print(f"  points > 0 (sentiment improving): {n_nonzero}")
    print(f"  points = 0 (flat/falling, clamped): {n_zero}")
    print(f"  at full {MARKET_DELTA_MAX_POINTS} pts (delta >= +20pp/24h): {n_full}")
    print(f"NOTE: {MARKET_DELTA_MAX_POINTS}/100 possible points max from this component alone "
          f"(35), so this alone can never cross the {ALERT_THRESHOLD}-point alert threshold -- "
          "it's a lower-bound signal check, not a full backtest.")


def main():
    conn = sqlite3.connect(DB_PATH)
    replay_stored_signals(conn)
    replay_market_delta_only(conn)
    conn.close()


if __name__ == "__main__":
    main()
