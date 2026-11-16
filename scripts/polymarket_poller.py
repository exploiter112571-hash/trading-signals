#!/usr/bin/env python3
"""Poll Polymarket's Gamma API for all active, open markets and log to SQLite.

Uses GET https://gamma-api.polymarket.com/markets with active=true&closed=false
and offset/limit pagination (no auth needed for public market data). Pages
until a response comes back shorter than the page size.

See https://docs.polymarket.com/developers/gamma-markets-api/get-markets
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Data directory for the .db files (default: home dir; override with PIPELINE_DATA_DIR).
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", Path.home()))

GAMMA_URL = "https://gamma-api.polymarket.com/markets/keyset"
DB_PATH = DATA_DIR / "polymarket_markets.db"
# A full crawl covers 50,000+ active markets (Polymarket generates huge
# numbers of templated per-state/per-price-level markets, similar in spirit
# to Kalshi's combination markets) and takes many minutes on its own, so
# polling hourly rather than every 10 minutes avoids hammering the API and
# disk back-to-back-to-back all day.
POLL_INTERVAL_SECONDS = 60 * 60
REQUEST_TIMEOUT_SECONDS = 15
# offset/limit pagination on /markets errors past offset=2100 ("offset too
# large, use /markets/keyset for deeper pagination"), so this uses the
# keyset endpoint with a cursor instead. It also caps `limit` at 100.
PAGE_LIMIT = 100
# Commit to disk every this many pages instead of buffering the entire
# multi-tens-of-thousands-market crawl in memory before one giant insert --
# a full crawl was measured ballooning to 1.6GB+ RAM before ever writing a
# single row under the old all-at-once approach.
COMMIT_EVERY_PAGES = 5


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polled_at TEXT NOT NULL,
            market_id TEXT,
            condition_id TEXT,
            slug TEXT,
            question TEXT,
            outcomes TEXT,
            outcome_prices TEXT,
            volume REAL,
            volume_24hr REAL,
            liquidity REAL,
            last_trade_price REAL,
            best_bid REAL,
            best_ask REAL,
            start_date TEXT,
            end_date TEXT,
            active INTEGER,
            closed INTEGER,
            archived INTEGER,
            restricted INTEGER
        )
        """
    )
    conn.commit()


PAGE_RETRIES = 3
PAGE_RETRY_BACKOFF_SECONDS = 5


def fetch_page(cursor):
    params = {
        "active": "true",
        "closed": "false",
        "limit": PAGE_LIMIT,
    }
    if cursor:
        params["after_cursor"] = cursor

    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            response = requests.get(GAMMA_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            print(f"[{now_iso()}] ERROR: request to Polymarket timed out after {REQUEST_TIMEOUT_SECONDS}s (attempt {attempt}/{PAGE_RETRIES})")
        except requests.exceptions.ConnectionError as exc:
            print(f"[{now_iso()}] ERROR: connection error contacting Polymarket: {exc} (attempt {attempt}/{PAGE_RETRIES})")
        except requests.exceptions.HTTPError as exc:
            print(f"[{now_iso()}] ERROR: Polymarket returned HTTP error: {exc} (attempt {attempt}/{PAGE_RETRIES})")
        except requests.exceptions.RequestException as exc:
            print(f"[{now_iso()}] ERROR: unexpected request failure: {exc} (attempt {attempt}/{PAGE_RETRIES})")
        except ValueError as exc:
            print(f"[{now_iso()}] ERROR: could not parse JSON response: {exc} (attempt {attempt}/{PAGE_RETRIES})")

        if attempt < PAGE_RETRIES:
            time.sleep(PAGE_RETRY_BACKOFF_SECONDS)

    return None


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_json_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def to_bool_int(value):
    if value is None:
        return None
    return 1 if value else 0


def market_to_row(market, polled_at):
    return (
        polled_at,
        str(market.get("id")) if market.get("id") is not None else None,
        market.get("conditionId"),
        market.get("slug"),
        market.get("question"),
        as_json_text(market.get("outcomes")),
        as_json_text(market.get("outcomePrices")),
        to_float(market.get("volumeNum", market.get("volume"))),
        to_float(market.get("volume24hr")),
        to_float(market.get("liquidityNum", market.get("liquidity"))),
        to_float(market.get("lastTradePrice")),
        to_float(market.get("bestBid")),
        to_float(market.get("bestAsk")),
        market.get("startDate"),
        market.get("endDate"),
        to_bool_int(market.get("active")),
        to_bool_int(market.get("closed")),
        to_bool_int(market.get("archived")),
        to_bool_int(market.get("restricted")),
    )


def store_page(conn, markets, polled_at):
    if not markets:
        return
    conn.executemany(
        """
        INSERT INTO markets (
            polled_at, market_id, condition_id, slug, question,
            outcomes, outcome_prices, volume, volume_24hr, liquidity,
            last_trade_price, best_bid, best_ask, start_date, end_date,
            active, closed, archived, restricted
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [market_to_row(m, polled_at) for m in markets],
    )


def poll_once(conn):
    """Streams the crawl straight to disk page-by-page (committing every
    COMMIT_EVERY_PAGES pages) instead of buffering the whole multi-tens-of-
    thousands-market result set in memory before writing anything."""
    polled_at = now_iso()
    cursor = None
    total = 0
    pages_since_commit = 0
    complete = True

    while True:
        payload = fetch_page(cursor)
        if payload is None:
            print(f"[{now_iso()}] ERROR: giving up on this poll after repeated failures; data is incomplete.")
            complete = False
            break

        page = payload.get("markets") or []
        store_page(conn, page, polled_at)
        total += len(page)
        pages_since_commit += 1
        if pages_since_commit >= COMMIT_EVERY_PAGES:
            conn.commit()
            pages_since_commit = 0

        cursor = payload.get("next_cursor")
        if not cursor or len(page) < PAGE_LIMIT:
            break

    conn.commit()

    if total == 0:
        print(f"[{now_iso()}] No active markets returned this poll.")
    else:
        status = "" if complete else " (INCOMPLETE - fetch failed partway through)"
        print(f"[{polled_at}] Stored {total} active market(s).{status}")


def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    try:
        while True:
            poll_once(conn)
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
