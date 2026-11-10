import sqlite3, logging, os

THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", 0.3))  # score = probability (0-1)

logging.basicConfig(filename="/home/roboslayer777/alerts.log", level=logging.INFO,
                     format="%(asctime)s %(message)s")

conn = sqlite3.connect("/home/roboslayer777/polymarket_odds.db", timeout=30)
# Only consider markets seen in a recent fetch. Closed/expired markets drop
# out of the Polymarket search results but their last row stays in the table,
# so without this cutoff they alerted forever on months-old prices.
FRESH_WINDOW_SECONDS = int(os.environ.get("ALERT_FRESH_WINDOW_SECONDS", 3600))

latest = conn.execute("""
    SELECT market, prob FROM odds o
    WHERE ts = (SELECT MAX(ts) FROM odds WHERE market = o.market)
      AND ts >= strftime('%s', 'now') - ?
""", (FRESH_WINDOW_SECONDS,)).fetchall()

for market, prob in latest:
    if prob >= THRESHOLD:
        logging.info(f"ALERT    market={market!r} score={prob:.3f} threshold={THRESHOLD}")
        print(f"ALERT: {market} ({prob:.0%})")
    else:
        logging.info(f"FILTERED market={market!r} score={prob:.3f} threshold={THRESHOLD}")

conn.close()
