#!/usr/bin/env python3
"""Poll OpenSky Network for all current aircraft state vectors and log to SQLite.

Uses GET /states/all with no bounding box (global query) as an anonymous
(unauthenticated) client. Anonymous access is capped at 400 credits/day and
a global query costs 4 credits, so this polls every 15 minutes
(96 requests/day * 4 credits = 384 credits/day, under the cap).

See https://openskynetwork.github.io/opensky-api/rest.html
"""

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Data directory for the .db files (default: home dir; override with PIPELINE_DATA_DIR).
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", Path.home()))

OPENSKY_URL = "https://opensky-network.org/api/states/all"
DB_PATH = DATA_DIR / "opensky_states.db"
POLL_INTERVAL_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 20

# State vector field order per the REST API docs.
FIELDS = [
    "icao24", "callsign", "origin_country", "time_position", "last_contact",
    "longitude", "latitude", "baro_altitude", "on_ground", "velocity",
    "true_track", "vertical_rate", "sensors", "geo_altitude", "squawk",
    "spi", "position_source", "category",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(conn):
    # A pre-existing opensky_states.db (from an earlier, slimmer poller) may
    # already have a "states" table missing some of these columns. Rather
    # than overwrite that history, create the table if absent and then
    # migrate any missing columns onto it.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polled_at TEXT NOT NULL,
            icao24 TEXT,
            callsign TEXT,
            origin_country TEXT,
            longitude REAL,
            latitude REAL,
            baro_altitude REAL,
            velocity REAL,
            on_ground INTEGER,
            last_contact INTEGER
        )
        """
    )

    required_columns = {
        "api_time": "INTEGER",
        "time_position": "INTEGER",
        "true_track": "REAL",
        "vertical_rate": "REAL",
        "geo_altitude": "REAL",
        "squawk": "TEXT",
        "spi": "INTEGER",
        "position_source": "INTEGER",
        "category": "INTEGER",
    }
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(states)")}
    for column, column_type in required_columns.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE states ADD COLUMN {column} {column_type}")

    conn.commit()


def fetch_states():
    try:
        response = requests.get(OPENSKY_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        remaining = response.headers.get("X-Rate-Limit-Remaining")
        if remaining is not None:
            print(f"[{now_iso()}] Rate limit credits remaining: {remaining}")
        if response.status_code == 429:
            retry_after = response.headers.get("X-Rate-Limit-Retry-After-Seconds", "unknown")
            print(f"[{now_iso()}] ERROR: rate limited, retry after {retry_after}s")
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"[{now_iso()}] ERROR: request to OpenSky timed out after {REQUEST_TIMEOUT_SECONDS}s")
    except requests.exceptions.ConnectionError as exc:
        print(f"[{now_iso()}] ERROR: connection error contacting OpenSky: {exc}")
    except requests.exceptions.HTTPError as exc:
        print(f"[{now_iso()}] ERROR: OpenSky returned HTTP error: {exc}")
    except requests.exceptions.RequestException as exc:
        print(f"[{now_iso()}] ERROR: unexpected request failure: {exc}")
    except ValueError as exc:
        print(f"[{now_iso()}] ERROR: could not parse JSON response: {exc}")
    return None


def store_and_count(conn, payload):
    states = (payload or {}).get("states") or []
    if not states:
        print(f"[{now_iso()}] No state vectors returned this poll.")
        return

    polled_at = now_iso()
    api_time = payload.get("time")
    rows = []
    for state in states:
        padded = list(state) + [None] * (len(FIELDS) - len(state))
        record = dict(zip(FIELDS, padded))
        rows.append(
            (
                polled_at,
                api_time,
                record["icao24"],
                record["callsign"],
                record["origin_country"],
                record["time_position"],
                record["last_contact"],
                record["longitude"],
                record["latitude"],
                record["baro_altitude"],
                record["on_ground"],
                record["velocity"],
                record["true_track"],
                record["vertical_rate"],
                record["geo_altitude"],
                record["squawk"],
                record["spi"],
                record["position_source"],
                record["category"],
            )
        )

    conn.executemany(
        """
        INSERT INTO states (
            polled_at, api_time, icao24, callsign, origin_country,
            time_position, last_contact, longitude, latitude, baro_altitude,
            on_ground, velocity, true_track, vertical_rate, geo_altitude,
            squawk, spi, position_source, category
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()

    print(f"[{polled_at}] Stored {len(rows)} state vector(s).")


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    try:
        while True:
            payload = fetch_states()
            store_and_count(conn, payload)
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
