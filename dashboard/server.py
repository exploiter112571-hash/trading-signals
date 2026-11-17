#!/usr/bin/env python3
"""Read-only web dashboard for the pipeline (score, odds, stock picks, news).

Standard library only. Binds to 127.0.0.1 by default so nothing is exposed on
your network; reach it from your phone through Tailscale with
`tailscale serve --bg 8050` (tailnet-only HTTPS) -- see docs/PHONE_ACCESS.md.

    python dashboard/server.py                 # http://127.0.0.1:8050
    DASHBOARD_PORT=9000 python dashboard/server.py
"""
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
DB_PATH = os.environ.get("SIGNALS_DB", str(HERE.parent / "signals.db"))
HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8050"))
INDEX_HTML = HERE / "index.html"

FRESHNESS = {  # table -> timestamp column
    "signals": "ts", "odds": "ts", "jets": "ts", "gdelt": "ts", "gdelt_v2": "fetched_ts",
    "mil_jets": "ts", "gnss": "ts", "news": "fetched_ts", "stock_picks": "ts",
}


def connect():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def safe(fn, default):
    try:
        return fn()
    except sqlite3.OperationalError:  # table not created yet on a fresh clone
        return default


def summary(hours):
    now = int(time.time())
    since = now - hours * 3600
    with connect() as conn:
        latest = safe(lambda: conn.execute(
            "SELECT ts, score, components FROM signals ORDER BY ts DESC LIMIT 1").fetchone(), None)
        history = safe(lambda: [
            [r["ts"], r["score"]] for r in conn.execute(
                "SELECT ts, score FROM signals WHERE ts >= ? ORDER BY ts", (since,))], [])
        odds = safe(lambda: [dict(r) for r in conn.execute("""
            WITH cur AS (SELECT slug, question, yes_probability, MAX(ts) ts FROM odds GROUP BY slug)
            SELECT cur.slug, cur.question, cur.yes_probability AS p, cur.ts,
                   (SELECT o.yes_probability FROM odds o WHERE o.slug = cur.slug
                      AND o.ts <= cur.ts - 86400 ORDER BY o.ts DESC LIMIT 1) AS p_24h
            FROM cur WHERE cur.ts >= ? ORDER BY cur.yes_probability DESC""", (now - 2 * 86400,))], [])
        picks = safe(lambda: [dict(r) for r in conn.execute("""
            SELECT ticker, name, grp, action, rank_score, price, ret_5d, ret_20d, vs_sma50,
                   regime, rationale, ts
            FROM stock_picks WHERE ts = (SELECT MAX(ts) FROM stock_picks)
            ORDER BY CASE action WHEN 'LONG-WATCH' THEN 0 WHEN 'HEDGE-WATCH' THEN 1
                     WHEN 'AVOID' THEN 2 ELSE 3 END, rank_score DESC""")], [])
        news = safe(lambda: [dict(r) for r in conn.execute("""
            SELECT title, link, source, published_ts, relevance FROM news
            WHERE published_ts >= ? ORDER BY published_ts DESC LIMIT 60""",
            (now - 3 * 86400,))], [])
        fresh = {}
        for table, col in FRESHNESS.items():
            fresh[table] = safe(lambda: conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0], None)
    return {
        "now": now,
        "latest": None if latest is None else {
            "ts": latest["ts"], "score": latest["score"],
            "components": json.loads(latest["components"])},
        "history": history,
        "odds": odds,
        "picks": picks,
        "news": news,
        "freshness": fresh,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/summary":
            try:
                hours = int(parse_qs(url.query).get("hours", ["168"])[0])
            except ValueError:
                hours = 168
            hours = max(1, min(hours, 24 * 90))
            try:
                body = json.dumps(summary(hours)).encode()
                self._send(200, body, "application/json")
            except sqlite3.Error as exc:
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif url.path == "/healthz":
            self._send(200, b"ok", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, fmt, *args):  # keep journald quiet
        pass


if __name__ == "__main__":
    print(f"dashboard on http://{HOST}:{PORT}  (db: {DB_PATH})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
