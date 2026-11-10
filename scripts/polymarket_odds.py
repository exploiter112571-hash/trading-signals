import requests, sqlite3, json, time, sys
from datetime import datetime

# Timestamp any crash so failures in polymarket_odds.log can be dated.
_default_hook = sys.excepthook
def _timestamped_hook(*exc):
    print(f"--- {datetime.now().isoformat(timespec='seconds')} polymarket_odds.py failed:", file=sys.stderr)
    _default_hook(*exc)
sys.excepthook = _timestamped_hook

KEYWORDS = ["iran", "oil", "hormuz"]
URL = "https://gamma-api.polymarket.com/public-search"

conn = sqlite3.connect("polymarket_odds.db", timeout=30)
conn.execute("CREATE TABLE IF NOT EXISTS odds (ts INTEGER, market TEXT, prob REAL)")
# alerts.py looks up each market's latest row; without this index that query
# rescans the whole table per market (~14 min at 100k rows), overlapping the
# next 15-min run and causing "database is locked" crashes.
conn.execute("CREATE INDEX IF NOT EXISTS idx_odds_market_ts ON odds (market, ts)")

for kw in KEYWORDS:
    r = requests.get(URL, params={"q": kw, "limit_per_type": 20, "events_status": "active"}, timeout=10)
    for event in r.json().get("events", []):
        for m in event.get("markets", []):
            try:
                prob = json.loads(m["outcomePrices"])[0]
            except (KeyError, IndexError, json.JSONDecodeError):
                continue
            conn.execute("INSERT INTO odds VALUES (?, ?, ?)", (int(time.time()), m["question"], float(prob)))

conn.commit()
conn.close()
