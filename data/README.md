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

| File | ESPN views | Seasons | Size (all seasons) |
|---|---|---|---|
| `matchups.json` | `mTeam` + `mMatchupScore` | 2015–2025 | 0.8 MB |
| `settings.json` | `mSettings` (`settings`, `status`) | 2015–2025 | 0.15 MB |
| `draft.json` | `mDraftDetail`, trimmed | 2015–2025 | 0.4 MB |
| `players.json` | `kona_player_info`, trimmed | 2015–2025 | 1.1 MB |
| `boxscores.json` | `mBoxscore` one NFL week at a time, trimmed | 2018–2025 | 2.1 MB |
| `transactions.json` | `mTransactions2` one NFL week at a time, trimmed | 2018–2025 | 1.1 MB |

The player-level files (the last four, ~4.6 MB) are **trimmed to the fields the hub uses**, keeping
ESPN's field names: the raw responses repeat every player's ownership trends, news and projections
in every week. The trimming lives in `mustafatron.espn.player_data`. There is no `mRoster` file: each
week's box score already lists the whole roster, bench and IR included, with each player's slot.
Loading every season including the ~22k player-weeks takes about a quarter of a second, so there
are no Parquet intermediates; `to_frame(league.player_weeks)` builds the wide table on demand.

Seasons before 2018 come from the `leagueHistory/{league_id}?seasonId=` endpoint; 2018 onward from
`seasons/{year}/segments/0/leagues/{league_id}`. Both are on `lm-api-reads.fantasy.espn.com`.

### Player-level data by era

ESPN keeps far less player-level detail for the `leagueHistory` seasons. Probed in October 2026
(issue #26) with [`scripts/probe_player_views.py`](../scripts/probe_player_views.py), which can be
rerun to check whether that has changed:

| What | 2015–2017 (`leagueHistory`) | 2018 on |
|---|---|---|
| Draft (`mDraftDetail`) | ✅ all 160 picks, round and pick, `teamId` | ✅ same |
| Keeper flag on draft picks | `keeper: false` everywhere (no keepers then) | ✅ `keeper` / `reservedForKeeper`, set from 2024 (21 picks in 2024, 26 in 2025) |
| Player season totals (`kona_player_info`) | ✅ league-scored season total for any player | ✅ plus a line per NFL week |
| Weekly box scores (`mBoxscore`) | ⚠️ starters only (`rosterForMatchupPeriod`), no lineup slot, no bench; in 2015–2016 a few sides are missing a starter (8/10 and 6/10 sides add up to the team's score in week 3) | ✅ the whole roster (`rosterForCurrentScoringPeriod`): lineup slot, bench, IR, points |
| Weekly rosters (`mRoster`) | ❌ the requested week is ignored: always the final roster, season totals only | ✅ that week's roster |
| Transactions (`mTransactions2`) | ❌ nothing returned for any week | ✅ per NFL week (`scoringPeriodId` is required; without it nothing comes back) |

What that means for the hub:

- **Draft value covers all 11 seasons**, from draft picks plus season totals.
- **Bench points, optimal lineups and coaching stats start in 2018.** Without the bench there is
  nothing to optimize, and the pre-2018 starter lists are not complete enough to rely on. Pages
  that use them say "player-level stats available from 2018" rather than implying 11 seasons.
- **Trades, trade valuations and acquisition history start in 2018.** For 2015–2017 only ESPN's
  per-team counts survive (`transactionCounter` in `matchups.json`).
- **The keeper flag works,** which makes the keeper history backfill (M5) automatic from 2024 on.

Two traps the probe turned up: `mDraftDetail`'s `memberId` is a SWID *without* braces, which the
SWID scrubber's pattern does not match, so committed draft files keep only the fields the hub uses
(picks are attributed by `teamId` anyway); and transactions must be requested one NFL week at a time.

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

### `draft.json`

`draftDetail`: `drafted`, `completeDate`, and `picks[]` with `overallPickNumber`, `roundId`,
`roundPickNumber`, `teamId`, `playerId`, `keeper` / `reservedForKeeper` (set from 2024) and
`autoDraftTypeId`. 160 picks a season. `memberId` is dropped (a brace-less SWID; picks are
attributed by `teamId`).

### `players.json`

`players[]`: every player the season's draft, box scores or transactions mention, with `id`,
`fullName`, `defaultPositionId` (1 QB, 2 RB, 3 WR, 4 TE, 5 K, 16 D/ST), `eligibleSlots`, `proTeamId`
and `appliedTotalByScoringPeriod`: actual points in this league's scoring, `"0"` the season total,
`"1"`… each NFL week (2018 on; earlier seasons have the total only).

### `boxscores.json`

`periods[]`, one per NFL week: `scoringPeriodId` and `teams[]` (`teamId`, `entries[]` of `playerId`,
`lineupSlotId`, `points`). Lineup slot ids are ESPN's (20 bench, 21 IR; the rest in
`mustafatron.league_settings.SLOT_NAMES`). Every week the starters' points add up to the team's score
in `matchups.json`, and every entry matches the player's line in `players.json` (both are tested).

### `transactions.json`

`transactions[]`: executed `WAIVER` and `FREEAGENT` moves (with `items[]` of `ADD` / `DROP`:
`playerId`, `fromTeamId`, `toTeamId`), plus every trade record ESPN still has. Week 0 holds moves
made between the draft and week 1.

**Trades from 2019 use executed records from `kona_playercard`.** The per-week
`mTransactions2` view usually returns acceptance and league-vote bookkeeping without the exchanged
players. The fetcher also queries player cards for every player mentioned by the draft, weekly
rosters, and transactions, and merges executed `TRADE_ACCEPT` records by transaction ID. Only
allowlisted transaction/item fields are retained; member IDs are discarded.

`mustafatron.transform.executed_trades` uses each package's `TRADE` items, execution date and
scoring period. Shared proposal IDs identify a trade across duplicated records; distinct trades
between the same teams in the same week remain separate. Each team's ledger count must match
ESPN's `transactionCounter.trades`, otherwise loading fails with a refresh instruction.

**2018 still uses roster inference.** ESPN player cards do not return executed trade history for
that season. `infer_trades` follows ownership through the draft, executed adds/drops and weekly
rosters. This fallback cannot see transfers followed by another trade or a drop within one week.
The 2022 Lockett/Watson transfers and 2023 Gainwell trade are regression-tested against the executed
records rather than accepting drift. See `2022-trade-investigation.md` for the investigation.

Free agency is team `0`, or `-1` in 2018. Waivers ESPN processes itself carry `teamId` -2147483648.
From 2023, ESPN's `transactionCounter.acquisitions` runs 1–3 below the executed adds for a few
teams, with no pattern found yet. Counts on the site use ESPN's counter.

### Quirks

Known quirk: Ryan Richardson co-owns his team with a second ESPN account from 2024 (and Jon Grudee
from 2026), so those seasons list more members than teams. Member IDs are never used as manager
keys directly: `mustafatron.identity` resolves them to the canonical managers in
[`manual/managers.yml`](manual/managers.yml).

## `manual/` — hand-maintained league facts

| File | What |
|---|---|
| `managers.yml` | One entry per person: canonical id, display and short names, every ESPN member ID they have used, seasons active |
| `league_rules.yml` | Rules ESPN doesn't model: payouts, keeper eligibility, draft-review and rivalry thresholds, each season's NFL kickoff, and the league's awards (what decides each, from which season). Keyed by season where a rule changed. Anything in `mSettings` is deliberately not repeated here |
| `awards.yml` | Award winners recorded by hand: seasons the data can't decide (before 2018 for trades and benches) and overrides of computed winners. Empty until someone backfills the GroupMe-era winners |

To refetch from ESPN: `uv run mustafatron fetch --refresh 2015-2025`. (The original import from the
legacy `.h2h_cache/` was `scripts/import_h2h_cache.py`.)
