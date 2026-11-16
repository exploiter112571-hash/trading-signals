#!/usr/bin/env python3
"""Poll Kalshi for all open markets every 10 minutes and log to SQLite.

Uses GET /events?status=open&with_nested_markets=true rather than
GET /markets?status=open directly: the plain /markets endpoint is
dominated by auto-generated multivariate "combination" markets
(tickers starting with KXMVE...) -- over 240,000 of them and still
growing when sampled, with no server-side way to filter them out.
The /events endpoint returns each real event with its markets nested
inside, giving a complete, fast (~60 pages) snapshot of genuine open
markets. Any leftover multivariate events/markets are filtered out
client-side as a safety net.
"""

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Data directory for the .db files (default: home dir; override with PIPELINE_DATA_DIR).
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", Path.home()))

KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/events"
DB_PATH = DATA_DIR / "kalshi_markets.db"
POLL_INTERVAL_SECONDS = 10 * 60
REQUEST_TIMEOUT_SECONDS = 15
PAGE_LIMIT = 200


def is_multivariate(event_ticker):
    return "MVE" in (event_ticker or "")


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polled_at TEXT NOT NULL,
            ticker TEXT NOT NULL,
            event_ticker TEXT,
            title TEXT,
            status TEXT,
            yes_bid REAL,
            yes_ask REAL,
            no_bid REAL,
            no_ask REAL,
            last_price REAL,
            volume REAL,
            volume_24h REAL,
            open_interest REAL,
            liquidity REAL,
            close_time TEXT
        )
        """
    )
    conn.commit()


def fetch_page(cursor):
    params = {"status": "open", "with_nested_markets": "true", "limit": PAGE_LIMIT}
    if cursor:
        params["cursor"] = cursor
    try:
        response = requests.get(KALSHI_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"[{now_iso()}] ERROR: request to Kalshi timed out after {REQUEST_TIMEOUT_SECONDS}s")
    except requests.exceptions.ConnectionError as exc:
        print(f"[{now_iso()}] ERROR: connection error contacting Kalshi: {exc}")
    except requests.exceptions.HTTPError as exc:
        print(f"[{now_iso()}] ERROR: Kalshi returned HTTP error: {exc}")
    except requests.exceptions.RequestException as exc:
        print(f"[{now_iso()}] ERROR: unexpected request failure: {exc}")
    except ValueError as exc:
        print(f"[{now_iso()}] ERROR: could not parse JSON response: {exc}")
    return None


def fetch_all_open_markets():
    markets = []
    cursor = None

    while True:
        payload = fetch_page(cursor)
        if payload is None:
            break

        events = payload.get("events") or []
        for event in events:
            if is_multivariate(event.get("event_ticker")):
                continue
            for market in event.get("markets") or []:
                if is_multivariate(market.get("ticker")) or market.get("mve_collection_ticker"):
                    continue
                markets.append(market)

        cursor = payload.get("cursor")
        if not cursor or not events:
            break

    return markets


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def store_and_count(conn, markets):
    if not markets:
        print(f"[{now_iso()}] No open markets returned this poll.")
        return

    polled_at = now_iso()
    rows = [
        (
            polled_at,
            market.get("ticker"),
            market.get("event_ticker"),
            market.get("title"),
            market.get("status"),
            to_float(market.get("yes_bid_dollars")),
            to_float(market.get("yes_ask_dollars")),
            to_float(market.get("no_bid_dollars")),
            to_float(market.get("no_ask_dollars")),
            to_float(market.get("last_price_dollars")),
            to_float(market.get("volume_fp")),
            to_float(market.get("volume_24h_fp")),
            to_float(market.get("open_interest_fp")),
            to_float(market.get("liquidity_dollars")),
            market.get("close_time"),
        )
        for market in markets
    ]

    conn.executemany(
        """
        INSERT INTO markets (
            polled_at, ticker, event_ticker, title, status,
            yes_bid, yes_ask, no_bid, no_ask, last_price,
            volume, volume_24h, open_interest, liquidity, close_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()

    print(f"[{polled_at}] Stored {len(rows)} open market(s).")


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    try:
        while True:
            markets = fetch_all_open_markets()
            store_and_count(conn, markets)
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
