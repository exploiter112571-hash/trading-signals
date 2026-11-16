#!/usr/bin/env python3
"""Read the latest signals.db rows and compute a 0-100 composite risk score:

  - prediction-market 24h delta   (up to 35 pts)
  - Gulf jet count vs 7-day avg   (up to 25 pts)
  - GDELT conflict events vs 7-day avg (up to 20 pts)
  - VIX level, fetched fresh via yfinance (up to 20 pts)

Every run is logged to table `signals` (ts, score, components JSON) in the
same signals.db. If score >= ALERT_THRESHOLD, sends a Telegram message with
the full breakdown, reusing the bot credentials already configured for the
ews project (~/ews/.env).
"""

import json
from datetime import datetime
import sqlite3
import time
from pathlib import Path

import requests
import yfinance as yf

DB_PATH = "/home/roboslayer777/pipeline/signals.db"
EWS_ENV_PATH = Path.home() / "ews" / ".env"
REQUEST_TIMEOUT_SECONDS = 15

ALERT_THRESHOLD = 60

LOOKBACK_DAYS = 7
DELTA_WINDOW_SECONDS = 24 * 60 * 60
# The "24h-ago" odds snapshot must be no older than 24h + this slack. Without
# it, after the machine sleeps for days/weeks the delta silently compares
# against stale odds from long ago.
DELTA_MAX_SLACK_SECONDS = 6 * 60 * 60
# Latest jets/gdelt row must be this fresh, else that component scores 0
# (protects against scoring a stale reading when Osiris is down).
MAX_LATEST_AGE_SECONDS = 45 * 60
# Minimum baseline rows (~4h at 15-min cadence) before a 7-day average is
# trusted; with gaps in collection a handful of rows makes a noisy baseline.
MIN_BASELINE_SAMPLES = 16
# Floor on the baseline average for count data, so a 0 baseline doesn't
# zero out the component (previously avg 0 -> pct_above forced to 0).
BASELINE_AVG_FLOOR = 1.0

# --- component point caps ---
MARKET_DELTA_MAX_POINTS = 35
JETS_MAX_POINTS = 25
GDELT_MAX_POINTS = 20
VIX_MAX_POINTS = 20

# Market delta of 0 -> 0 pts, +0.20 (20 percentage points, 24h) -> full points.
# Negative deltas (probability falling) score 0, not negative.
MARKET_DELTA_FULL_SCALE = 0.20

# Percent-above-7-day-average that earns full points for jets/gdelt.
JETS_FULL_SCALE_PCT = 1.0   # +100% above average -> full 25 pts
GDELT_FULL_SCALE_PCT = 1.0  # +100% above average -> full 20 pts

# VIX linear scale: at/below VIX_FLOOR -> 0 pts, at/above VIX_CEILING -> full pts.
VIX_FLOOR = 12.0
VIX_CEILING = 32.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    ts INTEGER NOT NULL,
    score REAL NOT NULL,
    components TEXT NOT NULL
)
"""


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def load_telegram_credentials():
    if not EWS_ENV_PATH.exists():
        return None, None
    token = None
    channel = None
    for line in EWS_ENV_PATH.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip()
        elif line.startswith("TELEGRAM_CHANNEL="):
            channel = line.split("=", 1)[1].strip()
    return token or None, channel or None


def send_telegram_message(text):
    token, channel = load_telegram_credentials()
    if not token or not channel:
        print("Telegram credentials not found in ~/ews/.env -- skipping alert send.")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": channel, "text": text},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        print(f"Telegram send failed: {exc}")
        return False
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}")
        return False
    return True


# --- component: prediction-market 24h delta ---

def compute_market_delta_component(conn, now_ts):
    markets = [r[0] for r in conn.execute("SELECT DISTINCT slug FROM odds")]
    if not markets:
        return {"raw_avg_delta": None, "points": 0, "note": "no market data"}

    deltas = []
    for slug in markets:
        newer = conn.execute(
            "SELECT yes_probability FROM odds WHERE slug = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (slug, now_ts),
        ).fetchone()
        older = conn.execute(
            "SELECT yes_probability FROM odds WHERE slug = ? AND ts <= ? AND ts >= ? "
            "ORDER BY ts DESC LIMIT 1",
            (slug, now_ts - DELTA_WINDOW_SECONDS, now_ts - DELTA_WINDOW_SECONDS - DELTA_MAX_SLACK_SECONDS),
        ).fetchone()
        if newer and older and newer[0] is not None and older[0] is not None:
            deltas.append(newer[0] - older[0])

    if not deltas:
        return {"raw_avg_delta": None, "points": 0, "note": "no 24h-old pair available yet"}

    avg_delta = sum(deltas) / len(deltas)
    points = clamp(avg_delta / MARKET_DELTA_FULL_SCALE, 0, 1) * MARKET_DELTA_MAX_POINTS
    return {"raw_avg_delta": round(avg_delta, 4), "n_markets": len(deltas), "points": round(points, 2)}


# --- component: Gulf jet count vs 7-day average ---

def compute_vs_baseline_component(conn, table, value_col, now_ts, full_scale_pct, max_points, label):
    latest_row = conn.execute(
        f"SELECT ts, {value_col} FROM {table} ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if not latest_row:
        return {"raw_latest": None, "raw_avg_7d": None, "points": 0, "note": f"no {label} data"}

    latest_ts, latest_value = latest_row
    if now_ts - latest_ts > MAX_LATEST_AGE_SECONDS:
        return {
            "raw_latest": latest_value,
            "raw_avg_7d": None,
            "points": 0,
            "note": f"latest {label} row is stale ({(now_ts - latest_ts) // 60} min old)",
        }

    cutoff = now_ts - LOOKBACK_DAYS * 24 * 60 * 60
    baseline_rows = conn.execute(
        f"SELECT {value_col} FROM {table} WHERE ts >= ? AND ts < ?",
        (cutoff, latest_ts),
    ).fetchall()

    if len(baseline_rows) < MIN_BASELINE_SAMPLES:
        return {
            "raw_latest": latest_value,
            "raw_avg_7d": None,
            "n_baseline": len(baseline_rows),
            "points": 0,
            "note": f"{label} baseline too thin ({len(baseline_rows)}/{MIN_BASELINE_SAMPLES} rows in last 7d)",
        }

    avg_7d = sum(r[0] for r in baseline_rows) / len(baseline_rows)
    denom = max(avg_7d, BASELINE_AVG_FLOOR)
    pct_above = (latest_value - denom) / denom

    points = clamp(pct_above / full_scale_pct, 0, 1) * max_points
    return {
        "raw_latest": latest_value,
        "raw_avg_7d": round(avg_7d, 2),
        "n_baseline": len(baseline_rows),
        "pct_above_avg": round(pct_above, 3),
        "points": round(points, 2),
    }


# --- component: VIX level via fresh yfinance fetch ---

def compute_vix_component():
    try:
        df = yf.Ticker("^VIX").history(period="5d", interval="1d", auto_adjust=False)
        if df.empty:
            return {"raw_vix": None, "points": 0, "note": "yfinance returned no data"}
        vix_level = float(df["Close"].iloc[-1])
    except Exception as exc:
        return {"raw_vix": None, "points": 0, "note": f"yfinance fetch failed: {exc}"}

    span = VIX_CEILING - VIX_FLOOR
    points = clamp((vix_level - VIX_FLOOR) / span, 0, 1) * VIX_MAX_POINTS
    return {"raw_vix": round(vix_level, 2), "points": round(points, 2)}


# --- shadow components (God's Eye View sources; see docs/OSINT_SOURCES.md) ---
# Computed and logged with every score so they can be compared against the
# Osiris-based jets/gdelt components, but their points are NOT added to the
# score until they have been checked against real data. To switch over, add
# them to the score sum in main() and drop the components they replace.

# gdelt_v2 compares the last 6h of Gulf material-conflict events with the
# average 6h total over the past 7 days. 15-min counts alone are mostly 0.
GDELT_V2_WINDOW_SECONDS = 6 * 60 * 60
# An export covers the 15 min before it is published, and is polled every
# 15 min, so the newest export_ts is normally 15-30 min old.
GDELT_V2_MAX_LATEST_AGE_SECONDS = 60 * 60
# Minimum exports (~2 days) before the 7-day baseline is trusted.
GDELT_V2_MIN_BASELINE_EXPORTS = 192


def compute_gdelt_v2_component(conn, now_ts):
    latest = conn.execute("SELECT MAX(export_ts) FROM gdelt_v2").fetchone()[0]
    if latest is None:
        return {"points": 0, "note": "no gdelt_v2 data"}
    if now_ts - latest > GDELT_V2_MAX_LATEST_AGE_SECONDS:
        return {"points": 0, "note": f"latest gdelt_v2 export is stale ({(now_ts - latest) // 60} min old)"}

    window_start = latest - GDELT_V2_WINDOW_SECONDS
    recent = conn.execute(
        "SELECT SUM(gulf_material_conflict), COUNT(*) FROM gdelt_v2 WHERE export_ts > ?", (window_start,)
    ).fetchone()
    baseline = conn.execute(
        "SELECT AVG(gulf_material_conflict), COUNT(*) FROM gdelt_v2 WHERE export_ts > ? AND export_ts <= ?",
        (now_ts - LOOKBACK_DAYS * 24 * 60 * 60, window_start),
    ).fetchone()
    raw_6h = recent[0] or 0
    if baseline[1] < GDELT_V2_MIN_BASELINE_EXPORTS:
        return {"raw_6h": raw_6h, "points": 0,
                "note": f"gdelt_v2 baseline too thin ({baseline[1]}/{GDELT_V2_MIN_BASELINE_EXPORTS} exports)"}

    # Scale the per-export mean to the number of exports actually in the window.
    avg_6h = baseline[0] * recent[1]
    denom = max(avg_6h, BASELINE_AVG_FLOOR)
    pct_above = (raw_6h - denom) / denom
    points = clamp(pct_above / GDELT_FULL_SCALE_PCT, 0, 1) * GDELT_MAX_POINTS
    return {
        "raw_6h": raw_6h,
        "raw_avg_6h_7d": round(avg_6h, 2),
        "n_baseline": baseline[1],
        "pct_above_avg": round(pct_above, 3),
        "points": round(points, 2),
    }


def compute_shadow_components(conn, now_ts):
    shadow = {}
    try:
        shadow["gdelt_v2"] = compute_gdelt_v2_component(conn, now_ts)
    except sqlite3.OperationalError as exc:  # table not created yet
        shadow["gdelt_v2"] = {"points": 0, "note": f"gdelt_v2 unavailable: {exc}"}
    try:
        shadow["mil_jets"] = compute_vs_baseline_component(
            conn, "mil_jets", "gulf_count", now_ts, JETS_FULL_SCALE_PCT, JETS_MAX_POINTS, "mil_jets"
        )
    except sqlite3.OperationalError as exc:
        shadow["mil_jets"] = {"points": 0, "note": f"mil_jets unavailable: {exc}"}
    try:
        # Relative to the 7-day average rather than gpsjam's fixed 2%/10%
        # bands: the Gulf has chronic GPS interference, so a fixed band
        # would read "high" permanently.
        shadow["gnss"] = compute_vs_baseline_component(
            conn, "gnss", "degraded_pct", now_ts, JETS_FULL_SCALE_PCT, JETS_MAX_POINTS, "gnss"
        )
    except sqlite3.OperationalError as exc:
        shadow["gnss"] = {"points": 0, "note": f"gnss unavailable: {exc}"}
    return shadow


def main():
    # Run header so failures in the cron log can be dated.
    print(f"--- {datetime.now().isoformat(timespec='seconds')}", flush=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)

    now_ts = int(time.time())

    market_component = compute_market_delta_component(conn, now_ts)
    jets_component = compute_vs_baseline_component(
        conn, "jets", "aircraft_count", now_ts, JETS_FULL_SCALE_PCT, JETS_MAX_POINTS, "jets"
    )
    gdelt_component = compute_vs_baseline_component(
        conn, "gdelt", "event_count", now_ts, GDELT_FULL_SCALE_PCT, GDELT_MAX_POINTS, "gdelt"
    )
    vix_component = compute_vix_component()

    score = (
        market_component["points"]
        + jets_component["points"]
        + gdelt_component["points"]
        + vix_component["points"]
    )
    score = round(score, 2)

    components = {
        "market_delta": market_component,
        "jets": jets_component,
        "gdelt": gdelt_component,
        "vix": vix_component,
        # Logged for comparison only; not part of `score` (see above).
        "shadow": compute_shadow_components(conn, now_ts),
    }

    conn.execute(
        "INSERT INTO signals (ts, score, components) VALUES (?, ?, ?)",
        (now_ts, score, json.dumps(components)),
    )
    conn.commit()
    conn.close()

    print(f"Score: {score}/100")
    print(json.dumps(components, indent=2))

    if score >= ALERT_THRESHOLD:
        lines = [f"Gulf/Hormuz risk score: {score}/100 (threshold {ALERT_THRESHOLD})", ""]
        lines.append(
            f"Market delta: {market_component.get('raw_avg_delta')} "
            f"({market_component['points']}/{MARKET_DELTA_MAX_POINTS} pts)"
        )
        lines.append(
            f"Gulf jets: {jets_component.get('raw_latest')} vs 7d avg "
            f"{jets_component.get('raw_avg_7d')} ({jets_component['points']}/{JETS_MAX_POINTS} pts)"
        )
        lines.append(
            f"GDELT conflict events: {gdelt_component.get('raw_latest')} vs 7d avg "
            f"{gdelt_component.get('raw_avg_7d')} ({gdelt_component['points']}/{GDELT_MAX_POINTS} pts)"
        )
        lines.append(
            f"VIX: {vix_component.get('raw_vix')} ({vix_component['points']}/{VIX_MAX_POINTS} pts)"
        )
        if send_telegram_message("\n".join(lines)):
            print("Score >= threshold, Telegram alert sent.")
        else:
            print("Score >= threshold, but Telegram alert was NOT sent (see above).")


if __name__ == "__main__":
    main()
