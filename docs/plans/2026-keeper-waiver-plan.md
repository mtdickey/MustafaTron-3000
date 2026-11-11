# Plan: 2026 waiver moves for 2027 keeper value

A hand-off for a local Claude Code session. Goal: this week's waiver adds and drops for
**MidTron 3000** (Dickey, ESPN team id 6) in Mustafa Greene's Fan Club, chosen **only** for keeper
value in the 2027 draft.

## The manager's priorities (settled; don't re-ask)

- **2027 only.** The team expects to miss the 2026 playoffs. Ignore rest-of-season value completely,
  for adds and for drops. No waiver analyzer or start/sit weighting.
- **Hoarding is fine.** An add doesn't have to beat the team's 3rd-best keeper. More than 3 keeper
  options is good, as cover for offseason and preseason changes.
- **Younger is better.** Prefer rookies and second-year players whose 2027 keeper cost is far below
  their projected 2027 redraft round.
- **The IR slot is a second stash spot.** Lamar Jackson is on IR and assumed done for 2026. Free
  that slot for a keeper candidate who is IR-eligible **now** (ESPN status Out or IR), e.g. Adam
  Randall. See step 2 for the one exception.
- Example move the manager had in mind: drop Dallas Goedert, add JaKobi Lane (if he qualifies).

## Keeper rules (from `data/manual/league_rules.yml`, applied by `src/mustafatron/keeper_engine.py`)

- **Eligible** only if the player went in the **2026 draft after round 3**, to any team. Players
  nobody drafted (waiver and free agent pickups) **can't be kept**. A waiver add only has keeper
  value if another team drafted him in round 4+ and then dropped him.
- **Cost** = his 2026 round minus 1, using the original drafter's round. Earliest possible cost is
  round 3.
- **Max 3 seasons in a row** kept, by anyone. A season back in the draft resets the count. Check
  `data/manual/keeper_history.yml`; no free agent should be close to the limit, but verify for
  anyone added.
- **Collisions:** keepers costing the same round can't share it; one moves to the latest free round
  before it. The team's current 2027 costs: Zay Flowers round 4, Travis Etienne Jr. round 6,
  Javonte Williams round 8 (all kept in 2026, so this would be their 2nd straight season).
- League: 10 teams, half PPR; roster QB, 2 RB, 2 WR, TE, FLEX, DST, K, 7 bench, 1 IR (16 + IR).

## Step 0: get the 2026 draft (the blocker)

The 2026 draft isn't in `data/raw/` until the season finishes, and the FantasyPros sync has no draft
rounds. Export it with the ESPN cookies:

```powershell
# .env in the repo root (gitignored) with ESPN_SWID={...} and ESPN_S2=...
python scripts\export_draft_picks.py --out draft_2026.csv
```

The CSV has, per pick: round, overall, keeper flag, drafting team, player, position, **current
fantasy team** (`FREE AGENT` if unowned) and ESPN **injury status**. Expect 160 rows. A 401 means
the cookies expired. Don't commit the CSV (current-season data stays out of the repo), or delete it
when done.

## Step 1: rate the team's own roster on 2027 keeper value

Current roster (FantasyPros sync): QB Lamar Jackson (IR), Patrick Mahomes II, C.J. Stroud; RB
Ashton Jeanty, Tony Pollard, Travis Etienne Jr., Javonte Williams, Zach Charbonnet; WR Amon-Ra St.
Brown, Tetairoa McMillan, Zay Flowers, KC Concepcion Jr., Stefon Diggs; TE Sam LaPorta, Dallas
Goedert; DST Saints; K Jake Bates. Re-pull with `get_roster` in case it changed.

- **No keeper value:** drafted rounds 1–3, undrafted pickups, or already kept 3 straight. Free to
  drop. Goedert, Diggs, Pollard and Mahomes are likely here; confirm with the CSV.
- **Keeper value:** cost and projected 2027 round as in step 4; drop only if a free agent clearly
  beats them.
- **K and DST** will never be keepers, so they're drop candidates. ESPN allows empty lineup slots;
  dropping them means taking zeros there. Mention it as an option, not a default.

## Step 2: Lamar Jackson and the IR slot

Lamar wasn't kept in 2026 (his 2025 keeper cost was round 3), so he went back into the 2026 draft
and his streak reset.

- Drafted in rounds 1–3 in 2026: no keeper value. Drop him to free the IR slot.
- Drafted in round 4+: he's eligible again, and a cheap 2027 Lamar may be the team's best keeper.
  Keep him and spend a bench spot instead; say so clearly.

## Step 3: build the candidate pools

From the CSV: `current_team == FREE AGENT` and `round >= 4`. Confirm availability with FantasyPros
`get_player_ownership` / `waiver_finder` for anyone shortlisted (the CSV is a snapshot).

- **Bench stashes:** everyone in the pool.
- **IR stashes:** those whose injury status is Out or IR (re-check with FantasyPros
  `injury_status`). Flag short-term injuries: if he's activated he leaves IR and needs a bench spot,
  and ESPN blocks further moves until that's sorted out.

## Step 4: value each candidate for 2027

Combine several sources into a projected 2027 redraft round (10 teams, about overall rank / 10):

- FantasyPros (league key `nfl~ccaf88c0-7bb4-4d46-afb3-921265637f10`; pass it on every
  league-scoped call): `get_ecr` with `ranking_type="DYNASTY"` (and `ROOKIES` for rookies),
  `get_adp` with `adp_type="dynasty"` / `"rookie"`, `get_keeper_value` (pick cost = the 2027 round;
  note its cheatsheet may still reflect 2026 redraft), `get_player_stats` for 2026 usage, and
  `get_nfl_depth_charts`.
- One or two outside dynasty boards (e.g. KeepTradeCut) as a second opinion. Per the FantasyPros
  server rules, outside sources are only for what its tools can't answer; cite source and date.
- Context: age, 2027 depth chart and contract outlook (e.g. a veteran ahead of him leaving).

**Score** = cost round − projected 2027 round (surplus), weighted toward younger players and away
from players whose value is a one-year role.

## Step 5: pair the moves

Match the best adds with the lowest-value drops until the next add isn't worth more than the next
drop. The IR slot goes to the best IR-eligible stash, unless step 2 says Lamar stays. Check the
collision rule against the team's existing keeper costs (rounds 4, 6, 8) when two candidates would
cost the same round.

## Deliverable

1. A ranked list of moves: add / drop, 2027 cost, projected 2027 round, surplus, age, sources, and a
   one-line reason. IR stash called out separately.
2. A watchlist: next-best stashes to grab if a roster spot opens later, and players to watch on
   other teams' rosters if they get dropped.
3. Caveats: the CSV is a snapshot, rankings are mid-season, collisions can shift a cost.
