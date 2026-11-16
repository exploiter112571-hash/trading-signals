#!/usr/bin/env python3
"""Composite risk score combining three weighted, independently-normalized inputs:

  1. jet level    - total airborne aircraft count in the latest OpenSky poll
  2. market delta - average 24h probability change across tracked Polymarket
                     questions (odds.db)
  3. VIX level    - latest VIX close (macro.db)

Each input is min-max normalized against its own recent history (so the three
land on a comparable 0-1 scale) before being combined with WEIGHTS below.
Adjust WEIGHTS and LOOKBACK_DAYS to taste; they don't need to sum to 1 (the
final score is reported both raw and as a 0-1 fraction of max possible).
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Data directory for the .db files (default: home dir; override with PIPELINE_DATA_DIR).
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", Path.home()))

OPENSKY_DB = DATA_DIR / "opensky_states.db"
POLYMARKET_DB = DATA_DIR / "polymarket_odds.db"
MACRO_DB = DATA_DIR / "macro.db"

WEIGHTS = {"jet": 1 / 3, "delta": 1 / 3, "vix": 1 / 3}
LOOKBACK_DAYS = 14


def minmax(value, history):
    """Scale value to [0, 1] using min/max of history (clamped if out of range).
    Falls back to 0.5 if history has no spread."""
    if not history:
        return 0.5
    lo, hi = min(history), max(history)
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def get_jet_level():
    conn = sqlite3.connect(OPENSKY_DB)
    try:
        latest = conn.execute("SELECT MAX(polled_at) FROM states").fetchone()[0]
        if latest is None:
            return None, [], None
        current = conn.execute(
            "SELECT COUNT(*) FROM states WHERE polled_at = ? AND on_ground = 0",
            (latest,),
        ).fetchone()[0]

        cutoff = (
            datetime.fromisoformat(latest) - timedelta(days=LOOKBACK_DAYS)
        ).isoformat()
        history = [
            row[0]
            for row in conn.execute(
                """
                SELECT COUNT(*) FROM states
                WHERE polled_at >= ? AND on_ground = 0
                GROUP BY polled_at
                """,
                (cutoff,),
            )
        ]
        return current, history, latest
    finally:
        conn.close()


def get_market_delta():
    conn = sqlite3.connect(POLYMARKET_DB)
    try:
        now = int(datetime.now(timezone.utc).timestamp())

        def avg_delta_asof(reference_ts):
            """Average (prob as of reference_ts) - (prob ~24h before that) across
            every market that has data on both sides of the 24h gap."""
            markets = [r[0] for r in conn.execute("SELECT DISTINCT market FROM odds")]
            deltas = []
            for market in markets:
                newer = conn.execute(
                    """SELECT prob FROM odds WHERE market = ? AND ts <= ?
                       ORDER BY ts DESC LIMIT 1""",
                    (market, reference_ts),
                ).fetchone()
                older = conn.execute(
                    """SELECT prob FROM odds WHERE market = ? AND ts <= ?
                       ORDER BY ts DESC LIMIT 1""",
                    (market, reference_ts - 86400),
                ).fetchone()
                if newer and older:
                    deltas.append(newer[0] - older[0])
            return sum(deltas) / len(deltas) if deltas else None

        current = avg_delta_asof(now)

        history = []
        for days_back in range(1, LOOKBACK_DAYS + 1):
            d = avg_delta_asof(now - days_back * 86400)
            if d is not None:
                history.append(d)

        return current, history
    finally:
        conn.close()


def get_vix_level():
    conn = sqlite3.connect(MACRO_DB)
    try:
        rows = conn.execute(
            """
            SELECT date, close FROM prices
            WHERE ticker = '^VIX'
            ORDER BY date DESC LIMIT ?
            """,
            (LOOKBACK_DAYS + 1,),
        ).fetchall()
        if not rows:
            return None, [], None
        current_date, current = rows[0]
        history = [r[1] for r in rows[1:]]
        return current, history, current_date
    finally:
        conn.close()


def main():
    jet_current, jet_history, jet_asof = get_jet_level()
    delta_current, delta_history = get_market_delta()
    vix_current, vix_history, vix_asof = get_vix_level()

    components = {}

    if jet_current is not None:
        components["jet"] = (jet_current, minmax(jet_current, jet_history))
    if delta_current is not None:
        components["delta"] = (delta_current, minmax(delta_current, delta_history))
    if vix_current is not None:
        components["vix"] = (vix_current, minmax(vix_current, vix_history))

    if not components:
        print("No data available in any source DB.")
        return

    weight_sum = sum(WEIGHTS[k] for k in components)
    score = sum(WEIGHTS[k] * norm for k, (_, norm) in components.items()) / weight_sum

    print(f"Composite risk score: {score:.3f}  (0=low, 1=high)")
    print()
    if "jet" in components:
        raw, norm = components["jet"]
        print(f"  jet level    raw={raw} airborne (as of {jet_asof})  norm={norm:.3f}  weight={WEIGHTS['jet']}")
    else:
        print("  jet level    NO DATA -- opensky_states.db has nothing")
    if "delta" in components:
        raw, norm = components["delta"]
        print(f"  market delta raw={raw:+.4f} (avg 24h prob change)  norm={norm:.3f}  weight={WEIGHTS['delta']}")
    else:
        print("  market delta NO DATA -- polymarket_odds.db lacks 24h-old pairs")
    if "vix" in components:
        raw, norm = components["vix"]
        print(f"  VIX level    raw={raw:.2f} (as of {vix_asof})  norm={norm:.3f}  weight={WEIGHTS['vix']}")
    else:
        print("  VIX level    NO DATA -- macro.db has nothing")

    missing = {"jet", "delta", "vix"} - components.keys()
    if missing:
        print(f"\nNote: scored using only {sorted(components)} -- missing {sorted(missing)} were excluded and weights renormalized.")


if __name__ == "__main__":
    main()
