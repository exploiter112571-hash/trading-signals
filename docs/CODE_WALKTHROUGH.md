# Code walkthrough: `poller.py` and `scorer.py`

Plain-language explanation of what each function does and *why* it is written
that way. Line numbers refer to the files as of this commit; many of the "why"
answers are real bugs that were hit and fixed (see git history).

## The big picture

Every 15 minutes cron runs `poller.py` then `scorer.py`.

- **`poller.py` collects.** It saves Polymarket odds, a count of aircraft over
  the Gulf, and a count of Gulf conflict news into `signals.db`.
- **`scorer.py` judges.** It compares the newest readings with recent history
  and turns that into a 0–100 risk score. At 60 or more it sends a Telegram
  alert.
- **Trades are never automatic.** The score informs a manual decision; nothing
  in the pipeline talks to IBKR.

---

## poller.py

### `KEYWORDS_RE` and `matches_keywords()` (lines 34–39, 84–85)

- A regular expression with `\b` word boundaries, so "oil" matches *oil* but
  not *Oilers*. The earlier substring check was catching hockey markets.
- `re.I` makes it case-insensitive.
- `question or ""` guards against a market with no question text (`None`).

### `fetch_markets()` (lines 88–112)

- Polymarket's Gamma API returns at most 100 markets per request no matter
  what `limit` says, so this asks for 5 pages using `offset` (0, 100, 200…),
  covering the top 500 markets by 24-hour volume.
- `seen` is a set of market IDs. Rankings can shift between page requests, so
  the same market could appear on two pages; the set skips duplicates.
- `raise_for_status()` turns an HTTP error into an exception, so failures show
  up in the log instead of passing silently.
- If a page returns fewer than 100 markets there are no more pages, so the
  loop stops early.

### `extract_yes_probability()` (lines 115–122)

- Polymarket sends `outcomePrices` as a JSON *string* such as
  `'["0.23","0.77"]'`, so the code parses it and takes element 0, the "Yes"
  price, which is the market's probability.
- Any malformed data returns `None` instead of crashing the whole run.

### `in_bbox()` (lines 125–129)

- True if a latitude/longitude falls inside the Gulf/Hormuz box
  (lat 22–30, lon 48–58).
- A missing coordinate (`None`) raises `TypeError` in the comparison; that is
  caught and treated as "not in the box".

### `fetch_jets_in_bbox()` (lines 132–142)

- Calls the local Osiris server's `/api/flights` and counts every aircraft
  (commercial, private, private jets, military) whose position is inside the
  Gulf box.

### `fetch_gdelt_events_in_bbox()` (lines 149–162)

- Gets news events from Osiris and counts one if *either*:
  - its coordinates are inside the Gulf box, or
  - its headline names a Gulf place (`GULF_TERMS`, lines 52–58).
- **Why both:** Osiris pins every "Iran" story to one point in central Iran,
  outside the box. With the box test alone the count was always 0.
- The count is a live snapshot of what Osiris currently shows, not a strict
  6-hour window (Osiris gives no per-event timestamp; see the docstring).

### `main()` (lines 165–210)

- The timestamp header (`--- 2026-…`) makes failures in the cron log datable.
- `CREATE TABLE IF NOT EXISTS` means the first run builds the database.
- One `ts` is shared by every row written in the same run.
- **Order matters:** Polymarket runs first and commits on its own.
- The jets and GDELT blocks are each wrapped in `try/except`, so if Osiris is
  down they are skipped with a message and the odds are still saved
  ("best-effort").

---

## scorer.py

Score = market delta (max 35) + jets (25) + GDELT (20) + VIX (20) = 100.

### `clamp()` (lines 73–74)

- Keeps a value between `lo` and `hi`. Used so each component stays inside its
  points range: never negative, never above its cap.

### `compute_market_delta_component()` (lines 106–130)

- For each market, takes the newest probability and the probability from about
  24 hours ago.
- The "24 hours ago" reading must fall between 24 and 30 hours ago
  (`DELTA_MAX_SLACK_SECONDS`). Otherwise, after the PC sleeps for days, it
  would silently compare against weeks-old odds.
- Averages the changes across markets. An average rise of +20 percentage
  points gives the full 35 points; falling odds give 0, not negative points.

### `compute_vs_baseline_component()` (lines 135–177)

Used for both jets and GDELT: is the latest reading unusually high compared
with the last 7 days?

1. **Newest row.** No data → 0 points.
2. **Staleness check.** Newest row more than 45 minutes old → 0 points, so
   stale data is never scored when Osiris is down.
3. **Baseline.** All rows from the last 7 days, *excluding* the latest one, so
   the reading isn't compared with itself.
4. **Too little history.** Fewer than 16 baseline rows (about 4 hours) → 0
   points, because the average isn't trustworthy yet.
5. **Compare.** `pct_above = (latest − avg) / avg`. The average is floored at
   1.0 (`BASELINE_AVG_FLOOR`), so a zero average can't break the division.
6. **Points.** `clamp(pct_above / 1.0, 0, 1) × max_points`: double the average
   or more → full points; at or below the average → 0.

*Example (2026-11-12 21:30):* 97 jets vs a 7-day average of 97.84 → −0.9% →
0 points.

### `compute_vix_component()` (lines 182–193)

- Fetches VIX live through yfinance and scales it linearly: VIX ≤ 12 → 0,
  VIX ≥ 32 → full 20 points.
- *Example:* VIX 19.1 → (19.1 − 12) / 20 × 20 = 7.1 points.
- A failed fetch scores 0 with a note instead of crashing the run.

### `main()` (lines 196–256)

- Adds the four components, saves the score with its full breakdown as JSON in
  the `signals` table, and prints it to the log.
- If the score is 60 or more (`ALERT_THRESHOLD`), sends a Telegram alert
  listing each component.
