#!/usr/bin/env python3
"""Collect Gulf/Hormuz/oil headlines from RSS feeds into signals.db (table `news`).

Each headline gets a keyword relevance score; only items scoring > 0 are kept,
deduplicated by link. Read-only to the rest of the pipeline: nothing here feeds
the composite score -- it is context for the dashboard.

    python news.py            # fetch all feeds once (cron: every 15 min)
"""
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

DB_PATH = os.environ.get("SIGNALS_DB", str(Path(__file__).resolve().parent / "signals.db"))
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (trading-signals news collector)"
KEEP_DAYS = 30

# One Google News query only: a second query in quick succession gets a 429.
FEEDS = {
    "Google News": "https://news.google.com/rss/search?q=Hormuz+OR+%22Persian+Gulf%22+OR+Iran+tanker+OR+%22Brent+crude%22&hl=en-US&gl=US&ceid=US:en",
    "BBC Middle East": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "OilPrice.com": "https://oilprice.com/rss/main",
}

# keyword (regex, case-insensitive) -> weight
KEYWORDS = {
    r"hormuz": 5, r"persian gulf|gulf of oman": 4, r"tanker": 3, r"strait": 2,
    r"iran(ian)?": 3, r"irgc|revolutionary guard": 4, r"houthi": 3, r"red sea": 2,
    r"oman|qatar|bahrain|kuwait|uae|emirates|saudi": 1,
    r"missile|drone|strike|attack|seiz(e|ed|ure)": 2, r"navy|naval|warship|carrier": 2,
    r"sanction": 2, r"opec": 2, r"brent|crude|oil price": 2, r"lng|shipping": 1,
}
KEYWORD_RES = [(re.compile(rf"\b(?:{k})s?\b", re.I), w) for k, w in KEYWORDS.items()]

SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    link TEXT PRIMARY KEY,
    published_ts INTEGER,
    fetched_ts INTEGER NOT NULL,
    source TEXT,
    title TEXT NOT NULL,
    relevance INTEGER NOT NULL,
    keywords TEXT
);
CREATE INDEX IF NOT EXISTS news_published ON news(published_ts);
"""


def score_title(title):
    hits, total = [], 0
    for rx, weight in KEYWORD_RES:
        m = rx.search(title)
        if m:
            hits.append(m.group(0).lower())
            total += weight
    return total, hits


def parse_ts(text):
    if not text:
        return None
    try:
        return int(parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError):
        return None


def fetch_feed(name, url):
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        source = name
        src_el = item.find("source")  # Google News names the real outlet here
        if src_el is not None and src_el.text:
            source = src_el.text.strip()
            suffix = f" - {source}"
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        items.append((link, parse_ts(item.findtext("pubDate")), source, title))
    return items


def main():
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    added = 0
    for name, url in FEEDS.items():
        try:
            items = fetch_feed(name, url)
        except Exception as exc:  # best-effort per feed
            print(f"[news] {name}: failed ({exc})", file=sys.stderr)
            continue
        kept = 0
        for link, pub_ts, source, title in items:
            relevance, hits = score_title(title)
            if relevance <= 0:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?,?)",
                (link, pub_ts or now, now, source, title, relevance, ",".join(hits)),
            )
            kept += cur.rowcount
        added += kept
        print(f"[news] {name}: {len(items)} items, {kept} new relevant")
    conn.execute("DELETE FROM news WHERE published_ts < ?", (now - KEEP_DAYS * 86400,))
    conn.commit()
    conn.close()
    print(f"[news] {added} new headlines stored")


if __name__ == "__main__":
    main()
