#!/usr/bin/env python3
"""Rule-based stock screen driven by the Gulf-risk composite score.

NOT investment advice and never places orders. It ranks a fixed watchlist of
tickers whose prices historically react to Gulf/Hormuz risk, combining:

  * the regime from the latest composite score (signals table):
        calm < 30 <= elevated < 60 <= high   (60 = Telegram alert threshold)
  * the score's 24h trend (rising / falling)
  * each ticker's own price momentum (5d / 20d return, close vs 50-day SMA)

Groups:
  beneficiaries -- tend to gain when Gulf risk rises (energy, tankers, defense, gold)
  exposed       -- tend to lose when Gulf risk rises (airlines, cruise lines)

Actions written to the `stock_picks` table (one batch per run):
  LONG-WATCH   beneficiary, risk elevated/high or rising, price momentum confirms
  AVOID        exposed name while risk is elevated/high or rising
  HEDGE-WATCH  exposed name breaking down (below 50d SMA) while risk is rising
  NEUTRAL      everything else

    python stock_picks.py      # cron: hourly
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = os.environ.get("SIGNALS_DB", str(Path(__file__).resolve().parent / "signals.db"))

UNIVERSE = {
    "beneficiaries": {
        "XLE": "Energy sector ETF", "XOM": "Exxon Mobil", "CVX": "Chevron",
        "OXY": "Occidental", "FRO": "Frontline (tankers)", "DHT": "DHT Holdings (tankers)",
        "INSW": "Intl Seaways (tankers)", "STNG": "Scorpio Tankers",
        "LMT": "Lockheed Martin", "RTX": "RTX", "NOC": "Northrop Grumman",
        "LHX": "L3Harris", "GLD": "Gold ETF",
    },
    "exposed": {
        "JETS": "Airlines ETF", "DAL": "Delta Air Lines", "UAL": "United Airlines",
        "CCL": "Carnival", "RCL": "Royal Caribbean",
    },
}

CALM_BELOW = 30
HIGH_AT = 60
TREND_POINTS = 5  # score change over 24h that counts as rising/falling

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_picks (
    ts INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    name TEXT,
    grp TEXT NOT NULL,
    action TEXT NOT NULL,
    rank_score REAL,
    price REAL,
    ret_5d REAL,
    ret_20d REAL,
    vs_sma50 REAL,
    regime TEXT,
    rationale TEXT
);
CREATE INDEX IF NOT EXISTS stock_picks_ts ON stock_picks(ts);
"""


def risk_context(conn, now):
    row = conn.execute("SELECT ts, score FROM signals ORDER BY ts DESC LIMIT 1").fetchone()
    if not row:
        return None, None, "calm", "flat"
    ts, score = row
    old = conn.execute(
        "SELECT score FROM signals WHERE ts <= ? ORDER BY ts DESC LIMIT 1", (ts - 86400,)
    ).fetchone()
    delta = None if old is None else score - old[0]
    regime = "high" if score >= HIGH_AT else "elevated" if score >= CALM_BELOW else "calm"
    trend = "flat"
    if delta is not None and delta >= TREND_POINTS:
        trend = "rising"
    elif delta is not None and delta <= -TREND_POINTS:
        trend = "falling"
    return score, delta, regime, trend


def price_stats(tickers):
    import yfinance as yf

    data = yf.download(tickers, period="6mo", interval="1d", progress=False, auto_adjust=True)
    closes = data["Close"]
    stats = {}
    for t in tickers:
        s = closes[t].dropna() if t in closes else None
        if s is None or len(s) < 50:
            continue
        last = float(s.iloc[-1])
        stats[t] = {
            "price": last,
            "ret_5d": last / float(s.iloc[-6]) - 1,
            "ret_20d": last / float(s.iloc[-21]) - 1,
            "vs_sma50": last / float(s.iloc[-50:].mean()) - 1,
        }
    return stats


def decide(grp, st, regime, trend):
    momentum = 0.5 * st["ret_5d"] + 0.3 * st["ret_20d"] + 0.2 * st["vs_sma50"]
    risk_on = regime in ("elevated", "high") or trend == "rising"
    above = st["vs_sma50"] > 0
    if grp == "beneficiaries":
        if risk_on and above and momentum > 0:
            return "LONG-WATCH", momentum, (
                f"Gulf risk {regime}/{trend}; trading {st['vs_sma50']:+.1%} vs 50d SMA, "
                f"5d {st['ret_5d']:+.1%}")
        why = "risk calm" if not risk_on else "momentum not confirming"
        return "NEUTRAL", momentum, f"{why}; 5d {st['ret_5d']:+.1%}, 20d {st['ret_20d']:+.1%}"
    # exposed names: rank by weakness
    if risk_on and trend == "rising" and not above:
        return "HEDGE-WATCH", -momentum, (
            f"risk rising and price {st['vs_sma50']:+.1%} vs 50d SMA (breaking down)")
    if risk_on:
        return "AVOID", -momentum, f"Gulf risk {regime}/{trend}; exposed to fuel/route disruption"
    return "NEUTRAL", -momentum, f"risk calm; 5d {st['ret_5d']:+.1%}, 20d {st['ret_20d']:+.1%}"


def main():
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    try:
        score, delta, regime, trend = risk_context(conn, now)
    except sqlite3.OperationalError:  # no signals table yet (fresh DB)
        score, delta, regime, trend = None, None, "calm", "flat"
    tickers = [t for grp in UNIVERSE.values() for t in grp]
    try:
        stats = price_stats(tickers)
    except Exception as exc:
        print(f"[picks] price download failed: {exc}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for grp, names in UNIVERSE.items():
        for t, name in names.items():
            if t not in stats:
                continue
            st = stats[t]
            action, rank, why = decide(grp, st, regime, trend)
            rows.append((now, t, name, grp, action, round(rank, 5), round(st["price"], 2),
                         round(st["ret_5d"], 5), round(st["ret_20d"], 5),
                         round(st["vs_sma50"], 5), regime, why))
    conn.executemany("INSERT INTO stock_picks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("DELETE FROM stock_picks WHERE ts < ?", (now - 30 * 86400,))
    conn.commit()
    conn.close()
    summary = {}
    for r in rows:
        summary.setdefault(r[4], []).append(r[1])
    print(f"[picks] score={score} delta24h={delta} regime={regime} trend={trend} "
          f"{json.dumps(summary)}")


if __name__ == "__main__":
    main()
