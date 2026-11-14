# Development history

How this repo got to its current state, read from `git log`. Run
`git log --reverse --oneline` for the full list.

## Timeline

| Date | Commits | What happened |
|---|---|---|
| 2026-09-17 | 2 | Initial upload: the pipeline first, then the IBKR scripts and standalone data collectors |
| 2026-11-09 | 3 | `.env` kept out of git (with `.env.example`), rough backtest of the score, trade-log fixes |
| 2026-11-10 | 6 | Always-zero GDELT fix, scorer hardened against data gaps, stale macro data, SQLite lock fix (index), stop alerting on resolved markets, run timestamps in logs, `deploy/` folder |
| 2026-11-11 | 6 | Unfilled orders cancelled, jets feed fixed (adsb.lol 250 NM limit), non-US orders via SMART routing, stops rounded to tick size and checked for acceptance, poller pages through 500 markets, README on data sources |
| 2026-11-12 | 3 | US basket logged, market-hours guard and WSL login launcher, CSV data snapshot |
| 2026-11-13 | 1 | Code walkthrough (`docs/CODE_WALKTHROUGH.md`) |

## Notes

- **The first two commits are a migration.** The code was built and run
  locally first, then uploaded on 2026-09-17 in two large commits.
- **Gap from 2026-09-17 to 2026-11-09.** Nothing was committed in between. The
  system ran locally during that time; the fixes began once it was diagnosed.
- **After the migration, one change per commit.** Each later commit fixes or
  adds one specific thing, and its message says what and why. Most fixes come
  from a real failure that was found, such as GDELT always 0, jets dropping to
  0, a rejected tick-size stop, or an order filling pre-market.
- **AI-assisted.** Most commits since 2026-11-10 were written with Claude
  (Claude Code), and their messages say so (`Co-Authored-By: Claude`). I found
  the problems and decided the fixes; Claude wrote the code. See
  `docs/CODE_WALKTHROUGH.md` for an explanation of how the core code works.
- **History is unedited.** No commits have been squashed, reordered or
  back-dated.
