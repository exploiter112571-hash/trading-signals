#!/usr/bin/env python3
"""Poll Polymarket for Iran/Hormuz/oil/OPEC/Israel/nuclear-related markets,
plus (best-effort) local Osiris routes for Gulf/Hormuz jet and conflict-news
activity, and log everything to SQLite.

Polymarket: GET https://gamma-api.polymarket.com/markets?closed=false&limit=200
&order=volume24hr&ascending=false, filters client-side to markets whose
question contains any of the tracked keywords (case-insensitive).

Osiris (http://localhost:3000): GET /api/flights and /api/gdelt. These are
optional/local -- if Osiris isn't running, both fetches log a warning and
are skipped, and the Polymarket fetch/insert above is never affected by an
Osiris failure (it always runs first and commits independently).

Note on "last 6 hours" for gdelt: /api/gdelt does not expose a per-event
timestamp (each poll returns whatever is currently live from its RSS-based
source), so event_count is a live snapshot count of conflict-type events
in the bounding box at fetch time, not a strict 6h-windowed query. A true
6h rolling count would need to be computed downstream from our own stored
gdelt rows.
"""

import json
import sqlite3
import time

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
DB_PATH = "/home/roboslayer777/pipeline/signals.db"
REQUEST_TIMEOUT_SECONDS = 15
KEYWORDS = ["iran", "hormuz", "oil", "opec", "israel", "nuclear"]

OSIRIS_BASE_URL = "http://localhost:3000"
OSIRIS_TIMEOUT_SECONDS = 10
# Gulf / Strait of Hormuz bounding box
GULF_BBOX = {"lat_min": 22, "lat_max": 30, "lon_min": 48, "lon_max": 58}

SCHEMA = """
CREATE TABLE IF NOT EXISTS odds (
    ts INTEGER NOT NULL,
    slug TEXT,
    question TEXT,
    yes_probability REAL
)
"""

JETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jets (
    ts INTEGER NOT NULL,
    aircraft_count INTEGER
)
"""

GDELT_SCHEMA = """
CREATE TABLE IF NOT EXISTS gdelt (
    ts INTEGER NOT NULL,
    event_count INTEGER
)
"""


def matches_keywords(question):
    text = (question or "").lower()
    return any(keyword in text for keyword in KEYWORDS)


def fetch_markets():
    response = requests.get(
        GAMMA_URL,
        params={
            "closed": "false",
            "limit": 200,
            "order": "volume24hr",
            "ascending": "false",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def extract_yes_probability(market):
    try:
        prices = market.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        return float(prices[0])
    except (TypeError, ValueError, IndexError, json.JSONDecodeError, KeyError):
        return None


def in_bbox(lat, lon, bbox):
    try:
        return bbox["lat_min"] <= lat <= bbox["lat_max"] and bbox["lon_min"] <= lon <= bbox["lon_max"]
    except TypeError:
        return False


def fetch_jets_in_bbox():
    resp = requests.get(f"{OSIRIS_BASE_URL}/api/flights", timeout=OSIRIS_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()

    count = 0
    for key in ("commercial_flights", "private_flights", "private_jets", "military_flights"):
        for flight in data.get(key, []):
            if in_bbox(flight.get("lat"), flight.get("lng"), GULF_BBOX):
                count += 1
    return count


def fetch_gdelt_events_in_bbox():
    resp = requests.get(f"{OSIRIS_BASE_URL}/api/gdelt", timeout=OSIRIS_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()

    count = 0
    for event in data.get("events", []):
        if in_bbox(event.get("lat"), event.get("lng"), GULF_BBOX):
            count += 1
    return count


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    conn.execute(JETS_SCHEMA)
    conn.execute(GDELT_SCHEMA)

    ts = int(time.time())

    # --- Polymarket: always attempted, never skipped because of Osiris ---
    markets = fetch_markets()
    rows = []
    for market in markets:
        question = market.get("question")
        if not matches_keywords(question):
            continue
        rows.append((ts, market.get("slug"), question, extract_yes_probability(market)))

    if rows:
        conn.executemany(
            "INSERT INTO odds (ts, slug, question, yes_probability) VALUES (?, ?, ?, ?)",
            rows,
        )
    conn.commit()
    print(f"Matched {len(rows)} market(s) out of {len(markets)} fetched.")

    # --- Osiris flights: best-effort, log and skip on any failure ---
    try:
        aircraft_count = fetch_jets_in_bbox()
        conn.execute("INSERT INTO jets (ts, aircraft_count) VALUES (?, ?)", (ts, aircraft_count))
        conn.commit()
        print(f"jets: {aircraft_count} aircraft in Gulf/Hormuz bbox")
    except Exception as exc:
        print(f"Osiris /api/flights unavailable, skipping jets row: {exc}")

    # --- Osiris gdelt: best-effort, log and skip on any failure ---
    try:
        event_count = fetch_gdelt_events_in_bbox()
        conn.execute("INSERT INTO gdelt (ts, event_count) VALUES (?, ?)", (ts, event_count))
        conn.commit()
        print(f"gdelt: {event_count} conflict event(s) in Gulf/Hormuz bbox")
    except Exception as exc:
        print(f"Osiris /api/gdelt unavailable, skipping gdelt row: {exc}")

    conn.close()


if __name__ == "__main__":
    main()
