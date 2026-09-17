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
        return
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": channel, "text": text},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        print(f"Telegram send failed: {resp.status_code} {resp.text}")


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
            "SELECT yes_probability FROM odds WHERE slug = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
            (slug, now_ts - DELTA_WINDOW_SECONDS),
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
    cutoff = now_ts - LOOKBACK_DAYS * 24 * 60 * 60
    baseline_rows = conn.execute(
        f"SELECT {value_col} FROM {table} WHERE ts >= ? AND ts < ?",
        (cutoff, latest_ts),
    ).fetchall()

    if not baseline_rows:
        return {
            "raw_latest": latest_value,
            "raw_avg_7d": None,
            "points": 0,
            "note": f"no {label} baseline yet (need >7d of history)",
        }

    avg_7d = sum(r[0] for r in baseline_rows) / len(baseline_rows)
    if avg_7d <= 0:
        pct_above = 0
    else:
        pct_above = (latest_value - avg_7d) / avg_7d

    points = clamp(pct_above / full_scale_pct, 0, 1) * max_points
    return {
        "raw_latest": latest_value,
        "raw_avg_7d": round(avg_7d, 2),
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


def main():
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
        send_telegram_message("\n".join(lines))
        print("Score >= threshold, Telegram alert sent.")


if __name__ == "__main__":
    main()
