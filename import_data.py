#!/usr/bin/env python3
"""Seed signals.db from the CSV snapshot in data/ (the inverse of export_data.sh).

signals.db is gitignored, so a fresh clone starts empty: the scorer then has
no 24h-old odds for market_delta and no 7-day jets/gdelt baseline. Run this
once in a fresh clone to restore the history. Uses only Python's sqlite3
module, so the sqlite3 CLI is not needed.

Safe to re-run: rows already present (same ts, plus slug for odds) are skipped.

Usage: python3 import_data.py [path/to/signals.db]
"""

import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DEFAULT_DB = HERE / "signals.db"

csv.field_size_limit(sys.maxsize)

SCHEMAS = [
    "CREATE TABLE IF NOT EXISTS odds (ts INTEGER NOT NULL, slug TEXT, question TEXT, yes_probability REAL)",
    "CREATE TABLE IF NOT EXISTS jets (ts INTEGER NOT NULL, aircraft_count INTEGER)",
    "CREATE TABLE IF NOT EXISTS gdelt (ts INTEGER NOT NULL, event_count INTEGER)",
    "CREATE TABLE IF NOT EXISTS signals (ts INTEGER NOT NULL, score REAL NOT NULL, components TEXT NOT NULL)",
]


def utc_to_ts(text):
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def num(text, cast):
    return None if text in ("", None) else cast(text)


def rows(name):
    with open(DATA / name, newline="") as f:
        yield from csv.DictReader(f)


def import_table(conn, table, cols, key_cols, records):
    existing = set(conn.execute(f"SELECT {', '.join(key_cols)} FROM {table}"))
    new = [r for r in records if tuple(r[c] for c in key_cols) not in existing]
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in new],
    )
    print(f"{table}: +{len(new)} rows ({len(existing)} already present)")


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    conn = sqlite3.connect(db_path)
    for schema in SCHEMAS:
        conn.execute(schema)

    import_table(conn, "odds", ["ts", "slug", "question", "yes_probability"], ["ts", "slug"], [
        {"ts": int(r["ts"]), "slug": r["slug"], "question": r["question"],
         "yes_probability": num(r["yes_probability"], float)}
        for r in rows("pipeline_odds.csv")
    ])
    import_table(conn, "jets", ["ts", "aircraft_count"], ["ts"], [
        {"ts": utc_to_ts(r["utc"]), "aircraft_count": num(r["aircraft_count"], int)}
        for r in rows("jets.csv")
    ])
    import_table(conn, "gdelt", ["ts", "event_count"], ["ts"], [
        {"ts": utc_to_ts(r["utc"]), "event_count": num(r["event_count"], int)}
        for r in rows("gdelt.csv")
    ])
    import_table(conn, "signals", ["ts", "score", "components"], ["ts"], [
        {"ts": utc_to_ts(r["utc"]), "score": float(r["score"]), "components": r["components"]}
        for r in rows("scores.csv")
    ])

    conn.commit()
    conn.close()
    exported = (DATA / "EXPORTED_AT").read_text().strip() if (DATA / "EXPORTED_AT").exists() else "unknown"
    print(f"Seeded {db_path} from snapshot ({exported}).")


if __name__ == "__main__":
    main()
