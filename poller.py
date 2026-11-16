#!/usr/bin/env python3
"""Poll Polymarket for Iran/Hormuz/oil/OPEC/Israel/nuclear-related markets,
plus (best-effort) local Osiris routes for Gulf/Hormuz jet and conflict-news
activity, and log everything to SQLite.

Polymarket: GET https://gamma-api.polymarket.com/markets (closed=false, sorted
by volume24hr, 5 pages x 100 via offset), filtered client-side to markets
whose question contains a tracked keyword as a whole word (case-insensitive).

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

Direct sources (adopted from God's Eye View, github.com/bilawalsidhu/gods-eye-view;
see docs/OSINT_SOURCES.md), each best-effort and independent of Osiris:
  - gdelt_v2: real GDELT 2.0 15-minute event exports, Gulf events by
    bbox or action country, with CAMEO conflict counts and exact timestamps.
    `poller.py --backfill-gdelt 7` fills a 7-day baseline in one go.
  - mil_jets: adsb.lol /v2/mil military aircraft in GULF_BBOX.
  - gnss: GPS-integrity degradation (jamming/spoofing proxy) over the Gulf,
    read from the locally running God's Eye View app (localhost:4173).
"""

import argparse
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import time
import zipfile

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
# signals.db lives next to this file unless SIGNALS_DB points elsewhere.
DB_PATH = os.environ.get("SIGNALS_DB", str(Path(__file__).resolve().parent / "signals.db"))
REQUEST_TIMEOUT_SECONDS = 15
KEYWORDS = ["iran", "hormuz", "oil", "opec", "israel", "nuclear"]
# Whole-word match (plus common adjective forms): plain substring matching
# also caught sports markets like "Flyers vs. Oilers".
KEYWORDS_RE = re.compile(
    r"\b(" + "|".join(KEYWORDS + ["iranian", "israeli"]) + r")\b", re.I
)
# Gamma caps each /markets response at 100 rows regardless of `limit`, so
# the old limit=200 single request only ever saw the top 100 by 24h volume
# (11 tracked markets on 2026-11-11). Page through the top PAGES*100.
PAGE_SIZE = 100
PAGES = 5

OSIRIS_BASE_URL = "http://localhost:3000"
# Osiris /api/flights fans out to adsb.lol regions in parallel with a 12s
# per-region timeout, and its 45s cache is always cold at our 15-min cadence,
# so a cold call routinely exceeds 10s. Wait longer, and retry once: the
# retry usually hits the cache the first (abandoned) request populated.
OSIRIS_TIMEOUT_SECONDS = 30
OSIRIS_RETRIES = 1
# Gulf / Strait of Hormuz bounding box
GULF_BBOX = {"lat_min": 22, "lat_max": 30, "lon_min": 48, "lon_max": 58}
# Headline terms that make a conflict event Gulf/Hormuz-relevant regardless
# of where Osiris placed it on the map.
GULF_TERMS = [
    "iran", "iranian", "tehran", "irgc", "hormuz", "persian gulf", "gulf of oman",
    "bandar abbas", "kharg", "bahrain", "qatar", "doha", "uae", "emirates",
    "dubai", "abu dhabi", "oman", "kuwait", "aramco", "ras tanura", "abqaiq",
    "basra", "tanker",
]
GULF_TERMS_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in GULF_TERMS) + r")\b", re.I)

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

# --- Direct sources adopted from God's Eye View (github.com/bilawalsidhu/gods-eye-view) ---
# Real GDELT 2.0: the 15-minute event export files (keyless plain downloads,
# not the rate-limited search API). Unlike Osiris's RSS geo-mapper these carry
# CAMEO codes and an exact 15-minute timestamp, and old exports stay online,
# so a 7-day baseline can be backfilled (see --backfill-gdelt).
GDELT_V2_BASE = "https://data.gdeltproject.org/gdeltv2/"
GDELT_STEP_SECONDS = 15 * 60
GDELT_TIMEOUT_SECONDS = 30
# Exports caught up per normal poll if earlier polls were missed (2h).
GDELT_MAX_CATCHUP = 8
# Events table columns (GDELT 2.0, 61 columns).
GDELT_COL_ROOT_CODE = 28
GDELT_COL_QUAD_CLASS = 29
GDELT_COL_COUNTRY = 53
GDELT_COL_LAT = 56
GDELT_COL_LON = 57
# GDELT places a country-level story at the country centroid (Iran ~32N,
# outside GULF_BBOX), so also match on the action country (FIPS codes):
# Iran, Bahrain, Qatar, UAE, Oman, Kuwait.
GULF_FIPS = {"IR", "BA", "QA", "AE", "MU", "KU"}

# adsb.lol military aircraft feed (the one God's Eye View's military layer
# uses). Addresses KNOWN_RISKS #3: the Osiris jets count is mostly airliners.
ADSB_MIL_URL = "https://api.adsb.lol/v2/mil"
ADSB_TIMEOUT_SECONDS = 20
USER_AGENT = "trading-signals-pipeline/1.0"

# God's Eye View app itself, run locally (deploy/systemd/gods-eye-view.service).
# Its /api/gnss-integrity proxies adsb.lol and flags each aircraft whose
# reported NIC/NACp falls below the ADS-B Out minima (GEV's gpsjam-style
# rule) -- i.e. likely GPS jamming/spoofing. Anchors are whole degrees with a
# 250 NM radius; these four cover GULF_BBOX (same tiling as the Osiris patch).
GEV_BASE_URL = "http://localhost:4173"
GEV_TIMEOUT_SECONDS = 30
GEV_GNSS_ANCHORS = [(24, 51), (28, 51), (24, 56), (28, 56)]

GNSS_SCHEMA = """
CREATE TABLE IF NOT EXISTS gnss (
    ts INTEGER NOT NULL,
    aircraft INTEGER,        -- distinct aircraft in GULF_BBOX with integrity fields
    degraded INTEGER,        -- flagged by GEV's NIC/NACp rule
    degraded_pct REAL        -- gpsjam.org formula: 100 * max(0, degraded - 1) / aircraft
)
"""

GDELT_V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS gdelt_v2 (
    export_ts INTEGER PRIMARY KEY,   -- start of GDELT's 15-min export window (UTC epoch)
    fetched_ts INTEGER NOT NULL,
    gulf_events INTEGER,             -- all coded events placed in the Gulf
    gulf_material_conflict INTEGER,  -- QuadClass 4 (CAMEO roots 14-20): protest .. mass violence
    gulf_violence INTEGER            -- CAMEO roots 18-20 only (God's Eye View's "Conflicts")
)
"""

MIL_JETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mil_jets (
    ts INTEGER NOT NULL,
    gulf_count INTEGER,
    global_count INTEGER
)
"""

GDELT_SCHEMA = """
CREATE TABLE IF NOT EXISTS gdelt (
    ts INTEGER NOT NULL,
    event_count INTEGER
)
"""


def matches_keywords(question):
    return KEYWORDS_RE.search(question or "") is not None


def fetch_markets():
    markets = []
    seen = set()
    for page in range(PAGES):
        response = requests.get(
            GAMMA_URL,
            params={
                "closed": "false",
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        batch = response.json()
        for market in batch:
            key = market.get("id") or market.get("slug")
            if key not in seen:  # rankings can shift between page requests
                seen.add(key)
                markets.append(market)
        if len(batch) < PAGE_SIZE:
            break
    return markets


def extract_yes_probability(market):
    try:
        prices = market.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        return float(prices[0])
    except (TypeError, ValueError, IndexError, json.JSONDecodeError, KeyError):
        return None


def osiris_get(path):
    last_exc = None
    for _ in range(OSIRIS_RETRIES + 1):
        try:
            resp = requests.get(f"{OSIRIS_BASE_URL}{path}", timeout=OSIRIS_TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
    raise last_exc


def in_bbox(lat, lon, bbox):
    try:
        return bbox["lat_min"] <= lat <= bbox["lat_max"] and bbox["lon_min"] <= lon <= bbox["lon_max"]
    except TypeError:
        return False


def fetch_jets_in_bbox():
    data = osiris_get("/api/flights")

    count = 0
    for key in ("commercial_flights", "private_flights", "private_jets", "military_flights"):
        for flight in data.get(key, []):
            if in_bbox(flight.get("lat"), flight.get("lng"), GULF_BBOX):
                count += 1
    return count


def mentions_gulf(text):
    return GULF_TERMS_RE.search(text or "") is not None


def fetch_gdelt_events_in_bbox():
    data = osiris_get("/api/gdelt")

    # Osiris geo-maps each story to one jittered centroid per place name
    # (e.g. every Iran story lands at ~32.4N, outside GULF_BBOX), so the bbox
    # test alone never matched anything. Count an event if it either lands in
    # the bbox or its headline names a Gulf/Hormuz place.
    count = 0
    for event in data.get("events", []):
        if in_bbox(event.get("lat"), event.get("lng"), GULF_BBOX) or mentions_gulf(event.get("name")):
            count += 1
    return count


def gdelt_export_url(export_ts):
    stamp = datetime.fromtimestamp(export_ts, tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{GDELT_V2_BASE}{stamp}.export.CSV.zip"


def latest_gdelt_export_ts():
    resp = requests.get(f"{GDELT_V2_BASE}lastupdate.txt", timeout=GDELT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    url = resp.text.split()[2]  # first line: size, md5, export URL
    stamp = re.search(r"(\d{14})\.export\.CSV\.zip", url).group(1)
    return int(datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp())


def is_gulf_event(fields):
    if fields[GDELT_COL_COUNTRY] in GULF_FIPS:
        return True
    try:
        return in_bbox(float(fields[GDELT_COL_LAT]), float(fields[GDELT_COL_LON]), GULF_BBOX)
    except ValueError:
        return False


def fetch_gdelt_export_counts(export_ts):
    """Counts for one export, or None if GDELT has no file for that slot (404)."""
    resp = requests.get(gdelt_export_url(export_ts), timeout=GDELT_TIMEOUT_SECONDS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        table = zf.read(zf.namelist()[0]).decode("utf-8", "replace")
    events = conflict = violence = 0
    for line in table.splitlines():
        fields = line.split("\t")
        if len(fields) < 61 or not is_gulf_event(fields):
            continue
        events += 1
        if fields[GDELT_COL_QUAD_CLASS] == "4":
            conflict += 1
        if fields[GDELT_COL_ROOT_CODE] in ("18", "19", "20"):
            violence += 1
    return events, conflict, violence


def store_gdelt_exports(conn, export_ts_list):
    done = {r[0] for r in conn.execute("SELECT export_ts FROM gdelt_v2")}
    stored = 0
    for export_ts in export_ts_list:
        if export_ts in done:
            continue
        counts = fetch_gdelt_export_counts(export_ts)
        if counts is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO gdelt_v2 (export_ts, fetched_ts, gulf_events, gulf_material_conflict, gulf_violence) "
            "VALUES (?, ?, ?, ?, ?)",
            (export_ts, int(time.time()), *counts),
        )
        conn.commit()
        stored += 1
    return stored


def poll_gdelt_v2(conn):
    latest = latest_gdelt_export_ts()
    last = conn.execute("SELECT MAX(export_ts) FROM gdelt_v2").fetchone()[0]
    start = latest - (GDELT_MAX_CATCHUP - 1) * GDELT_STEP_SECONDS
    if last is not None:
        start = max(start, last + GDELT_STEP_SECONDS)
    stored = store_gdelt_exports(conn, range(start, latest + 1, GDELT_STEP_SECONDS))
    row = conn.execute(
        "SELECT gulf_events, gulf_material_conflict, gulf_violence FROM gdelt_v2 WHERE export_ts = ?", (latest,)
    ).fetchone()
    return stored, row


def backfill_gdelt_v2(conn, days):
    latest = latest_gdelt_export_ts()
    slots = range(latest - days * 86400 + GDELT_STEP_SECONDS, latest + 1, GDELT_STEP_SECONDS)
    print(f"Backfilling up to {len(slots)} GDELT exports ({days}d)...", flush=True)
    print(f"gdelt_v2: stored {store_gdelt_exports(conn, slots)} export(s)")


def fetch_mil_jets():
    resp = requests.get(ADSB_MIL_URL, timeout=ADSB_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    aircraft = resp.json().get("ac") or []
    # An empty worldwide list means the feed is broken, not that the sky is
    # empty: raise so no misleading 0 row is stored (KNOWN_RISKS #2).
    if not aircraft:
        raise ValueError("adsb.lol /v2/mil returned 0 aircraft worldwide")
    gulf = sum(1 for a in aircraft if in_bbox(a.get("lat"), a.get("lon"), GULF_BBOX))
    return gulf, len(aircraft)


def fetch_gnss_integrity():
    aircraft = {}
    for lat, lon in GEV_GNSS_ANCHORS:
        resp = requests.get(
            f"{GEV_BASE_URL}/api/gnss-integrity", params={"lat": lat, "lon": lon}, timeout=GEV_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        for row in resp.json().get("rows") or []:
            if in_bbox(row.get("lat"), row.get("lon"), GULF_BBOX):
                aircraft[row.get("hex")] = bool(row.get("degraded"))
    if not aircraft:
        raise ValueError("God's Eye View returned no aircraft in the Gulf bbox")
    total = len(aircraft)
    degraded = sum(aircraft.values())
    return total, degraded, round(100 * max(0, degraded - 1) / total, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backfill-gdelt", type=int, metavar="DAYS",
                        help="only backfill DAYS of GDELT 2.0 exports into gdelt_v2, then exit")
    args = parser.parse_args()

    # Run header so failures in the cron log can be dated.
    print(f"--- {datetime.now().isoformat(timespec='seconds')}", flush=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    conn.execute(JETS_SCHEMA)
    conn.execute(GDELT_SCHEMA)
    conn.execute(GDELT_V2_SCHEMA)
    conn.execute(MIL_JETS_SCHEMA)
    conn.execute(GNSS_SCHEMA)

    if args.backfill_gdelt:
        backfill_gdelt_v2(conn, args.backfill_gdelt)
        conn.close()
        return

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

    # --- GDELT 2.0 direct: best-effort ---
    try:
        stored, row = poll_gdelt_v2(conn)
        print(f"gdelt_v2: {stored} new export(s); latest Gulf events/conflict/violence = {row}")
    except Exception as exc:
        print(f"GDELT 2.0 export unavailable, skipping gdelt_v2: {exc}")

    # --- adsb.lol military: best-effort ---
    try:
        gulf, total = fetch_mil_jets()
        conn.execute("INSERT INTO mil_jets (ts, gulf_count, global_count) VALUES (?, ?, ?)", (ts, gulf, total))
        conn.commit()
        print(f"mil_jets: {gulf} military aircraft in Gulf bbox ({total} worldwide)")
    except Exception as exc:
        print(f"adsb.lol /v2/mil unavailable, skipping mil_jets row: {exc}")

    # --- God's Eye View GNSS integrity (local app): best-effort ---
    try:
        total, degraded, pct = fetch_gnss_integrity()
        conn.execute(
            "INSERT INTO gnss (ts, aircraft, degraded, degraded_pct) VALUES (?, ?, ?, ?)", (ts, total, degraded, pct)
        )
        conn.commit()
        print(f"gnss: {degraded}/{total} Gulf aircraft with degraded GPS integrity ({pct}%)")
    except Exception as exc:
        print(f"God's Eye View /api/gnss-integrity unavailable, skipping gnss row: {exc}")

    conn.close()


if __name__ == "__main__":
    main()
