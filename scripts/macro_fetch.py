import os
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
import yfinance as yf

# Data directory for the .db files (default: home dir; override with PIPELINE_DATA_DIR).
DATA_DIR = Path(os.environ.get("PIPELINE_DATA_DIR", Path.home()))

TICKERS = ["^VIX", "^GSPC", "GC=F", "^TYX", "^TNX"]
DB_PATH = DATA_DIR / "macro.db"
FRED_API_KEY_PATH = Path.home() / ".fred_api_key"
FRED_SERIES = {
    "DGS2": "2-Year Treasury yield",
    "BAMLH0A0HYM2": "ICE BofA US High Yield OAS credit spread",
}
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    adj_close REAL, volume INTEGER,
    PRIMARY KEY (ticker, date)
)
"""

FRED_SCHEMA = """
CREATE TABLE IF NOT EXISTS fred_series (
    series_id TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (series_id, date)
)
"""

def last_date(conn: sqlite3.Connection, ticker: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(date) FROM prices WHERE ticker = ?", (ticker,)
    ).fetchone()
    return row[0]

def fetch_ticker(conn: sqlite3.Connection, ticker: str) -> int:
    # Re-fetch the last stored day (not last+1): with hourly runs a bar saved
    # mid-session is partial, and INSERT OR REPLACE overwrites it with the
    # final values. Also avoids yfinance's "start date after end date" error
    # when the job runs before the next trading day exists.
    start = last_date(conn, ticker)

    df = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=False)
    if df.empty:
        return 0

    rows = [
        (ticker, idx.date().isoformat(), r.Open, r.High, r.Low, r.Close, r["Adj Close"], int(r.Volume))
        for idx, r in df.iterrows()
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO prices
           (ticker, date, open, high, low, close, adj_close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)

def last_fred_date(conn: sqlite3.Connection, series_id: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(date) FROM fred_series WHERE series_id = ?", (series_id,)
    ).fetchone()
    return row[0]

def fetch_fred_series(conn: sqlite3.Connection, series_id: str, api_key: str) -> int:
    start = last_fred_date(conn, series_id) or "1900-01-01"

    resp = requests.get(
        FRED_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start,
        },
        timeout=15,
    )
    resp.raise_for_status()
    observations = resp.json().get("observations", [])

    rows = [
        (series_id, obs["date"], float(obs["value"]))
        for obs in observations
        if obs.get("value") not in (None, ".")
    ]
    if not rows:
        return 0

    conn.executemany(
        """INSERT OR REPLACE INTO fred_series (series_id, date, value)
           VALUES (?, ?, ?)""",
        rows,
    )
    return len(rows)

def main() -> None:
    print(f"--- {datetime.now().isoformat(timespec='seconds')}")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute(SCHEMA)
    conn.execute(FRED_SCHEMA)

    for ticker in TICKERS:
        n = fetch_ticker(conn, ticker)
        print(f"{ticker}: {n} rows upserted")

    if FRED_API_KEY_PATH.exists():
        api_key = FRED_API_KEY_PATH.read_text().strip()
        for series_id, label in FRED_SERIES.items():
            n = fetch_fred_series(conn, series_id, api_key)
            print(f"{series_id} ({label}): {n} rows upserted")
    else:
        print(f"Skipping FRED series -- no key found at {FRED_API_KEY_PATH}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
