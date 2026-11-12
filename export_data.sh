#!/bin/bash
# Export a CSV snapshot of the pipeline's own data into data/ for the repo.
# The raw .db files stay out of git (size; kalshi/polymarket market dumps are
# multi-GB, above GitHub's 100 MB file limit). Re-run before committing to refresh.
set -eu
cd "$(dirname "$0")"
S=signals.db; M=$HOME/macro.db; O=$HOME/polymarket_odds.db
q() { sqlite3 -header -csv "$1" "$2" > "data/$3"; echo "data/$3: $(($(wc -l < data/$3)-1)) rows"; }
q $S "select datetime(ts,'unixepoch') utc, score, components from signals order by ts" scores.csv
q $S "select datetime(ts,'unixepoch') utc, aircraft_count from jets order by ts" jets.csv
q $S "select datetime(ts,'unixepoch') utc, event_count from gdelt order by ts" gdelt.csv
q $S "select datetime(ts,'unixepoch') utc, * from odds order by ts" pipeline_odds.csv
q $O "select datetime(ts,'unixepoch') utc, * from odds order by ts" polymarket_odds.csv
q $M "select * from prices order by date" macro_prices.csv
q $M "select * from fred_series order by date" fred_series.csv
date -u '+exported %F %T UTC' > data/EXPORTED_AT
