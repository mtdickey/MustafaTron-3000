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

Known quirk: one manager has two SWIDs across seasons, so 2024–25 show 11 members for 10 teams.
Canonical identity is resolved in M1 (`data/manual/managers.yml`).

To refetch from ESPN: `uv run mustafatron fetch --refresh 2015-2025`. (The original import from the
legacy `.h2h_cache/` was `scripts/import_h2h_cache.py`.)
