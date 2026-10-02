# data/

## `raw/` — committed ESPN responses

`raw/{season}/{dataset}.json`, one directory per season. Finished seasons are fetched once and never
change, so they are committed: a fresh clone and every CI run work offline, and history survives
if ESPN changes or drops old data. Only the current season is ever refetched.

The rule lives in `mustafatron.espn.cache`: a season is **finished** once every matchup in its
schedule has a result (no `UNDECIDED`). That is decided from the data, not the calendar, so the
offseason needs no special case. (`rankFinal` can't be used: it is 0 for every team in every season
of this league. `rankCalculatedFinal` holds the real finish.) Unfinished seasons are loaded live and
never written. `uv run mustafatron fetch` backfills whatever is missing, resuming where an
interrupted run stopped; `--refresh 2019` refetches and overwrites a finished season if ESPN
corrects it.

| File | ESPN views | Seasons |
|---|---|---|
| `matchups.json` | `mTeam` + `mMatchupScore` | 2015–2025 |
| `settings.json` | `mSettings` (`settings`, `status`) | 2015–2025 |

More views (`mBoxscore`, `mRoster`, `mDraftDetail`, `mTransactions2`) arrive in M3 as sibling files.

Seasons before 2018 come from the `leagueHistory/{league_id}?seasonId=` endpoint; 2018 onward from
`seasons/{year}/segments/0/leagues/{league_id}`. Both are on `lm-api-reads.fantasy.espn.com`.

### What is changed from the ESPN response

Files are written by `mustafatron.pseudonymize.scrub_season`, which:

- **Replaces every SWID** (ESPN's `{XXXXXXXX-...}` account ID, half of the login cookie pair) with
  `m_` + 16 hex chars of HMAC-SHA256(`MANAGER_ID_KEY`, SWID). The same person always gets the same
  ID, so seasons join, but the real SWID can't be recovered without the key, which lives only in
  `.env` and GitHub Actions secrets. **Changing the key breaks joins with these files.**
- **Drops `members[].notificationSettings`** (private ESPN preferences).

Manager names (`firstName`, `lastName`, `displayName`) are kept, since the hub displays them.

A test (`tests/test_raw_data.py`) fails if any SWID or `notificationSettings` appears here.

### `matchups.json`

Top-level keys: `members`, `teams`, `schedule`.

- `members[]`: `id` (pseudonymized), `displayName`, `firstName`, `lastName`
- `teams[]`: `id`, `name`, `abbrev`, `primaryOwner` / `owners[]` (pseudonymized member IDs),
  `record`, `points`, `playoffSeed`, `rankFinal`, `rankCalculatedFinal`, `transactionCounter`,
  `valuesByStat` (2019 onward), ...
- `schedule[]`: `matchupPeriodId`, `home` / `away` (`teamId`, `totalPoints`,
  `pointsByScoringPeriod`), `winner` (`HOME` / `AWAY` / `TIE`; `UNDECIDED` for unplayed games), `playoffTierType`
  (`NONE` / `WINNERS_BRACKET` / `WINNERS_CONSOLATION_LADDER` / `LOSERS_CONSOLATION_LADDER`).
  A bye has no `away` (none occur in 2015–2025).

### `settings.json`

Top-level keys: `settings` (`size`, `scheduleSettings`, `rosterSettings`, `scoringSettings`,
`draftSettings`, `tradeSettings`, ...) and `status` (`finalScoringPeriod`, ...). Parsed by
`mustafatron.league_settings` into team count, lineup slots, regular season length, playoff
format and scoring. Across 2015–2025: 10 teams, QB/2RB/2WR/TE/FLEX/D-ST/K + 7 bench, 4-team
playoffs of two-week matchups; 13 regular season matchups (14 in 2021), so the last matchup period
is 15 (16 in 2021); standard scoring through 2022, half-PPR from 2023.

### Quirks

Known quirk: Ryan Richardson co-owns his team with a second ESPN account from 2024 (and Jon Grudee
from 2026), so those seasons list more members than teams. Member IDs are never used as manager
keys directly: `mustafatron.identity` resolves them to the canonical managers in
[`manual/managers.yml`](manual/managers.yml).

## `manual/` — hand-maintained league facts

| File | What |
|---|---|
| `managers.yml` | One entry per person: canonical id, display and short names, every ESPN member ID they have used, seasons active |
| `league_rules.yml` | Rules ESPN doesn't model: payouts, keeper eligibility, draft-review and rivalry thresholds, each season's NFL kickoff. Keyed by season where a rule changed. Anything in `mSettings` is deliberately not repeated here |

To refetch from ESPN: `uv run mustafatron fetch --refresh 2015-2025`. (The original import from the
legacy `.h2h_cache/` was `scripts/import_h2h_cache.py`.)
