"""The site JSON contract: what ``publish.py`` writes to ``web/public/data/`` and the site reads.

These pydantic models are the single source of truth. ``publish`` builds every file through them
(so output can't drift from them), and their JSON Schemas are committed under ``schema/`` for the
site to generate types from. ``uv run mustafatron publish --offline --check`` (run in CI) rebuilds
everything, validates every file, and fails if ``schema/`` is stale.

Conventions:

- Managers are referenced by canonical id (``"dickey"``); names live only in ``managers.json``.
- ``week`` is ESPN's matchup period: a playoff "week" here spans two NFL weeks.
- Games are positional arrays, in the spirit of ``scratch_h2h.py --export``: ~850 rows stay small.
  Each file that has them documents its column order in ``columns``.
- Bump ``SCHEMA_VERSION`` on any breaking change.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

TIERS = ("NONE", "WINNERS_BRACKET", "WINNERS_CONSOLATION_LADDER", "LOSERS_CONSOLATION_LADDER")
GAME_COLUMNS = ("season", "week", "tier", "home", "away", "home_score", "away_score", "winner")
UPCOMING_COLUMNS = ("season", "week", "home", "away")

# [season, week, tier (index into TIERS), home, away, home_score, away_score, winner (null = tie)]
GameRow = tuple[int, int, int, str, str, float, float, str | None]
# [season, week, home, away]
UpcomingRow = tuple[int, int, str, str]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContractFile(_Model):
    schema_version: Literal[1] = SCHEMA_VERSION


# meta.json ---------------------------------------------------------------------------------------


class Meta(ContractFile):
    """What was published: seasons covered and where the current season stands."""

    league_name: str
    seasons: list[int]
    current_season: int
    current_season_finished: bool
    last_completed_week: int | None = Field(
        description="Latest week of the current season with every game final"
    )
    upcoming_week: int | None = Field(description="Next week of the current season with games still to play")


# managers.json -----------------------------------------------------------------------------------


class ManagerOut(_Model):
    id: str
    name: str
    short_name: str
    first_season: int
    last_season: int | None = Field(description="null while still in the league")
    seasons: list[int] = Field(description="Seasons with a team, from the published data")


class ManagersFile(ContractFile):
    managers: list[ManagerOut]


# games.json --------------------------------------------------------------------------------------


class GamesFile(ContractFile):
    """Every final game, all seasons, plus the current season's unplayed schedule."""

    columns: list[str] = Field(default=list(GAME_COLUMNS))
    tiers: list[str] = Field(default=list(TIERS), description="tier column values index into this")
    games: list[GameRow]
    upcoming_columns: list[str] = Field(default=list(UPCOMING_COLUMNS))
    upcoming: list[UpcomingRow]


# h2h.json ----------------------------------------------------------------------------------------


class MeetingOut(_Model):
    season: int
    week: int
    score: float = Field(description="Manager a's score")
    opponent_score: float = Field(description="Manager b's score")


class StreakOut(_Model):
    holder: str | None = Field(description="null when the last meeting was a tie")
    length: int


class FlagOut(_Model):
    kind: Literal["streak", "lopsided", "dead_even"]
    holder: str | None = None
    wins: int = 0
    losses: int = 0


class PairOut(_Model):
    """One all-time series, from manager ``a``'s side (``a`` < ``b`` alphabetically)."""

    a: str
    b: str
    games: int
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    playoff_wins: int
    playoff_losses: int
    results: str = Field(description="W/L/T from a's side, oldest meeting first")
    win_pct: float = Field(description="a's share of the series, ties counting half")
    avg_score: float = Field(description="a's average score")
    avg_opponent_score: float = Field(description="b's average score")
    avg_margin: float = Field(description="a's average margin; negative when b outscores a")
    last_five: str = Field(description="Last five results from a's side, oldest to newest")
    current_streak: StreakOut
    longest_streak_a: int
    longest_streak_b: int
    last_meeting: MeetingOut
    closest: MeetingOut
    blowout: MeetingOut
    rivalry: bool = Field(description="Enough meetings to count as a rivalry (league_rules.yml)")
    flags: list[FlagOut]


class H2HFile(ContractFile):
    pairs: list[PairOut]
    most_competitive: list[tuple[str, str]] = Field(
        description="Rivalries (a, b), closest to .500 first: abs(0.5 - win_pct), then most meetings"
    )


# standings.json ----------------------------------------------------------------------------------


class CareerOut(_Model):
    manager: str
    seasons: int
    finished_seasons: int = Field(description="Seasons with a final rank; finishes and payouts count these")
    wins: int = Field(description="Regular season")
    losses: int
    ties: int
    win_pct: float
    points_for: float = Field(description="Regular season")
    points_against: float
    avg_margin: float = Field(description="Regular season (points for - against) per game")
    playoff_appearances: int
    playoff_wins: int = Field(description="Championship bracket games; consolation ladders excluded")
    playoff_losses: int
    playoff_points_for: float
    playoff_points_against: float
    championships: int
    runner_ups: int
    third_places: int
    last_places: int
    best_finish: int | None
    worst_finish: int | None
    avg_finish: float | None
    net_payout: float = Field(description="Career winnings in multiples of the buy-in")
    roi: float = Field(description="net_payout per buy-in paid (finished seasons)")


class LedgerOut(_Model):
    season: int
    champion: str
    runner_up: str
    third: str
    last: str
    top_seed: str = Field(description="Best regular season record (playoff seed 1)")
    most_points: str = Field(description="Most regular season points for")
    champion_seed: int


class StandingsFile(ContractFile):
    """All-time standings, best regular season win percentage first, and every finished season's podium."""

    standings: list[CareerOut]
    ledger: list[LedgerOut] = Field(description="Finished seasons, newest first")


# records.json ------------------------------------------------------------------------------------


class GameMarkOut(_Model):
    season: int
    week: int
    manager: str
    opponent: str
    score: float
    opponent_score: float
    playoff: bool


class SeasonMarkOut(_Model):
    season: int
    manager: str
    value: float
    wins: int
    losses: int
    ties: int
    points_for: float


class MatchupMarkOut(_Model):
    season: int
    week: int
    home: str
    away: str
    home_score: float
    away_score: float
    total: float
    playoff: bool


class StreakMarkOut(_Model):
    manager: str
    length: int
    start_season: int
    start_week: int
    end_season: int
    end_week: int
    active: bool = Field(
        description="Can still grow: includes the manager's latest regular season game, the manager is "
        "still in the league, and (one-season streaks) that season's regular season isn't over"
    )


class WeekMarkOut(_Model):
    season: int
    period: int = Field(description="NFL week")
    total: float = Field(description="Every team's points that NFL week")
    teams: int


class RecordsFile(ContractFile):
    """Top 10 of each record, best first.

    Game and matchup records count one-week matchups only; week records are per NFL week, league-wide;
    season records count finished seasons; streaks are regular season games (see stats/records.py).
    """

    game_records: dict[str, list[GameMarkOut]]
    matchup_records: dict[str, list[MatchupMarkOut]]
    season_records: dict[str, list[SeasonMarkOut]]
    streak_records: dict[str, list[StreakMarkOut]]
    week_records: dict[str, list[WeekMarkOut]]


# seasons/{year}.json -----------------------------------------------------------------------------


class SeasonSettingsOut(_Model):
    team_count: int
    regular_season_weeks: int
    final_week: int
    playoff_team_count: int
    points_per_reception: float


class TeamOut(_Model):
    manager: str
    team_id: int
    name: str
    abbrev: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    playoff_seed: int
    final_rank: int | None
    acquisitions: int
    trades: int
    co_managers: list[str]


class WeeklyOut(_Model):
    """One team's season, NFL week by NFL week."""

    manager: str
    scores: list[float | None] = Field(description="Points per NFL week, aligned with SeasonFile.periods")
    results: str = Field(
        description="One character per period: W/L/T for a final one-week matchup, '-' otherwise"
    )
    all_play_wins: int = Field(description="Regular season record against the whole league each week")
    all_play_losses: int
    all_play_ties: int


SUPERLATIVES = (
    "high_week",
    "low_week",
    "most_points",
    "fewest_points",
    "most_points_against",
    "best_all_play",
    "luckiest",
    "unluckiest",
)


class SuperlativeOut(_Model):
    key: Literal[SUPERLATIVES]  # type: ignore[valid-type]
    manager: str
    value: float = Field(
        description="Points, or a win pct (best_all_play), or win pct minus all-play pct (luck)"
    )
    period: int | None = Field(description="NFL week, for single-week superlatives")


class SeasonFile(ContractFile):
    season: int
    finished: bool
    champion: str | None
    settings: SeasonSettingsOut
    teams: list[TeamOut] = Field(description="Final standings order once finished, else by seed")
    columns: list[str] = Field(default=list(GAME_COLUMNS))
    games: list[GameRow] = Field(description="Every game this season, final or not")
    periods: list[int] = Field(description="NFL weeks with scores so far, in order")
    playoff_start_period: int | None = Field(description="First NFL week of the playoffs")
    weekly: list[WeeklyOut] = Field(description="Same order as teams")
    superlatives: list[SuperlativeOut]


# profiles.json -----------------------------------------------------------------------------------


class WeekLineOut(_Model):
    season: int
    period: int = Field(description="NFL week")
    points: float
    opponent: str
    result: Literal["W", "L", "T"] | None = Field(description="null for half of a two-week playoff matchup")


class ProfileOut(_Model):
    """What a manager's page needs beyond standings.json, seasons/*.json and h2h.json."""

    manager: str
    all_play_wins: int = Field(description="Career regular season record against the whole league each week")
    all_play_losses: int
    all_play_ties: int
    best_weeks: list[WeekLineOut] = Field(description="Highest single NFL weeks, best first")
    worst_weeks: list[WeekLineOut] = Field(description="Lowest single NFL weeks, worst first")


class ProfilesFile(ContractFile):
    profiles: list[ProfileOut]


# luck.json ---------------------------------------------------------------------------------------


class LuckLineOut(_Model):
    manager: str
    wins: int = Field(description="Regular season")
    losses: int
    ties: int
    win_pct: float
    all_play_wins: int = Field(description="Against every other team, every final regular season week")
    all_play_losses: int
    all_play_ties: int
    all_play_pct: float
    luck: float = Field(description="win_pct - all_play_pct: positive means the schedule was kind")
    luck_wins: float = Field(description="Actual wins minus wins at the all-play rate over the same games")


class CareerLuckOut(LuckLineOut):
    seasons: int


class SeasonLuckOut(LuckLineOut):
    season: int
    finished: bool
    final_rank: int | None


class LuckFile(ContractFile):
    """All-play records and luck: careers, every team-season, and the luckiest and unluckiest seasons."""

    careers: list[CareerLuckOut] = Field(description="Record most overstated (luck_wins) first")
    seasons: list[SeasonLuckOut] = Field(description="Every team-season, oldest first")
    luckiest: list[SeasonLuckOut] = Field(description="Finished seasons, by luck, top 10")
    unluckiest: list[SeasonLuckOut] = Field(description="Finished seasons, by luck, bottom 10")


# coaching.json -----------------------------------------------------------------------------------


class PlayerPointsOut(_Model):
    name: str
    position: str
    points: float


class CoachingLineOut(_Model):
    manager: str
    weeks: int = Field(description="NFL weeks counted: regular season, championship bracket, 3rd place game")
    actual: float = Field(description="Points the starters scored")
    optimal: float = Field(description="Points the best possible lineups would have scored")
    left_on_bench: float = Field(description="optimal - actual")
    per_week: float = Field(description="left_on_bench per week counted")
    efficiency: float = Field(description="actual / optimal")
    perfect_weeks: int
    substitutions: int = Field(description="Lineup changes that would have made every week optimal")


class SeasonCoachingOut(CoachingLineOut):
    season: int


class CareerCoachingOut(CoachingLineOut):
    seasons: int


class CoachingWeekOut(_Model):
    season: int
    period: int = Field(description="NFL week")
    manager: str
    actual: float
    optimal: float
    left_on_bench: float
    substitutions: int
    should_have_started: list[PlayerPointsOut] = Field(description="Benched players the best lineup starts")
    should_have_sat: list[PlayerPointsOut] = Field(description="Starters the best lineup benches")


class IfOnlyOut(_Model):
    season: int
    week: int = Field(description="Matchup period")
    tier: str
    manager: str
    opponent: str
    score: float
    opponent_score: float
    optimal: float = Field(description="What the manager's best lineup would have scored")
    left_on_bench: float
    weeks: list[CoachingWeekOut] = Field(description="One per NFL week of the matchup")


class CoachingFile(ContractFile):
    """Lineup decisions, from the first season ESPN kept weekly rosters (2018)."""

    first_season: int | None = Field(description="First season with player-level lineups")
    careers: list[CareerCoachingOut] = Field(description="Fewest points left per week first")
    seasons: list[SeasonCoachingOut] = Field(description="By season, fewest points left per week first")
    worst_weeks: list[CoachingWeekOut] = Field(description="Most points left on the bench, top 10")
    best_weeks: list[CoachingWeekOut] = Field(description="Perfect lineups, highest-scoring first, top 10")
    if_only: list[IfOnlyOut] = Field(description="Losses the bench would have won, most points left first")


# draft.json --------------------------------------------------------------------------------------


class PickValueOut(_Model):
    season: int
    round: int
    round_pick: int
    overall_pick: int
    manager: str
    player: str
    position: str
    points: float = Field(description="The player's season in this league's scoring")
    points_above_avg: float = Field(description="Points minus the mean of drafted players at his position")
    expected: float = Field(description="That season's line for this pick")
    value: float = Field(description="points_above_avg - expected: points above what the pick promised")


class DrafterOut(_Model):
    manager: str
    seasons: int
    picks: int
    value: float
    per_pick: float
    early_picks: int
    early_per_pick: float = Field(description="Rounds 1 through DraftFile.early_rounds")
    late_picks: int
    late_per_pick: float


class DraftClassOut(_Model):
    season: int
    manager: str
    picks: int
    value: float
    best: PickValueOut


class RoundOut(_Model):
    round: int
    picks: int
    avg_points: float
    by_manager: dict[str, float] = Field(description="Average value per pick in this round, by manager")


class DraftFile(ContractFile):
    """Draft value, every finished season, keepers excluded. Each draft is valued against its own line."""

    first_season: int | None
    early_rounds: int = Field(description="Rounds 1 through this are 'early' (the bust cutoff)")
    steals_after_round: int
    busts_through_round: int
    drafters: list[DrafterOut] = Field(description="Best average value per pick first")
    steals: list[PickValueOut]
    busts: list[PickValueOut]
    best_drafts: list[DraftClassOut]
    worst_drafts: list[DraftClassOut]
    rounds: list[RoundOut]


# trades.json -------------------------------------------------------------------------------------


class PlayerRefOut(_Model):
    name: str
    position: str


class TradeSideOut(_Model):
    manager: str
    received: list[PlayerRefOut]
    sent: list[PlayerRefOut]
    value: float = Field(description="Points the trade added to this team's best lineups, rest of season")
    weeks: int = Field(description="Weeks valued: from the trade to the team's last game that mattered")


class TradeOut(_Model):
    id: str
    season: int
    period: int = Field(description="First NFL week the players were on their new rosters")
    date: str | None = Field(description="ISO date ESPN recorded the acceptance, when it could be matched")
    sides: list[TradeSideOut] = Field(description="Two sides, by manager id")
    winner: str
    margin: float = Field(description="Winner's value minus loser's")


class TradeSideRefOut(_Model):
    trade: str = Field(description="TradeOut.id")
    manager: str


class TradeCountOut(_Model):
    season: int
    manager: str
    trades: int = Field(description="ESPN's count")
    acquisitions: int = Field(description="Adds, ESPN's count")


class TradesFile(ContractFile):
    """Every trade with its retrospective verdict (from 2018), and trade and add counts (every season)."""

    first_season: int | None = Field(description="First season with trade detail")
    trades: list[TradeOut] = Field(description="Finished seasons, oldest first")
    best: list[TradeSideRefOut] = Field(description="Sides that gained the most, top 10")
    worst: list[TradeSideRefOut] = Field(description="Sides that lost the most, top 10")
    lopsided: list[str] = Field(description="Trade ids, biggest margin first, top 10")
    counts: list[TradeCountOut]


# awards.json -------------------------------------------------------------------------------------


class AwardWinnerOut(_Model):
    season: int
    source: Literal["computed", "manual", "unrecorded"] = Field(
        description="computed from the data, recorded by hand (data/manual/awards.yml), or not recorded"
    )
    manager: str | None
    value: float | None = Field(description="The metric: trade value, bench points, or luck in wins")
    detail: str


class AwardOut(_Model):
    id: str
    name: str
    description: str
    status: Literal["official", "proposed"]
    since: int = Field(description="First season the data can decide it")
    winners: list[AwardWinnerOut] = Field(description="Every finished season, newest first")


class AwardsFile(ContractFile):
    """The league's awards and every season's winner (league_rules.yml says what decides each)."""

    awards: list[AwardOut]


# weeks.json and weeks/{year}/{week}.json --------------------------------------------------------


class WeekRefOut(_Model):
    season: int
    week: int = Field(description="Matchup period")
    label: str = Field(description='"Week 5", or the playoff round: "Semifinals", "Championship"')
    playoff: bool


class WeeksFile(ContractFile):
    """Every weekly report, the archive the /week pages are built from."""

    weeks: list[WeekRefOut] = Field(description="Every week with all its games final, oldest first")
    current: WeekRefOut | None = Field(
        description="The latest report of the season in progress (the front page); null between seasons"
    )


class StandingLineOut(_Model):
    manager: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


class AllPlayCellOut(_Model):
    """One team's NFL week in the all-play grid."""

    points: float
    opponent: str
    opponent_points: float
    result: Literal["W", "L", "T"] = Field(description="The real game's result")
    rank: int = Field(description="Where the score ranked that week, 1 = highest")
    wins: int = Field(description="All-play that week: teams outscored")
    losses: int
    ties: int


class AllPlayRowOut(LuckLineOut):
    cells: list[AllPlayCellOut | None] = Field(description="Aligned with AllPlayGridOut.periods")


class AllPlayGridOut(_Model):
    """All-play week by week through the report's week (regular season), and luck: the v0 Records panel."""

    periods: list[int] = Field(description="Final regular season NFL weeks through this week")
    rows: list[AllPlayRowOut] = Field(description="Best all-play pct first")


class SwapOut(_Model):
    player_in: PlayerPointsOut | None = Field(description="Benched player who should have started")
    player_out: PlayerPointsOut | None = Field(description="Starter he'd have replaced (null: an empty slot)")
    gain: float


class BenchWeekOut(_Model):
    period: int = Field(description="NFL week")
    actual: float
    optimal: float
    left_on_bench: float
    swaps: list[SwapOut] = Field(
        description="The lineup changes that would have made it optimal, biggest first"
    )


class BenchLineOut(_Model):
    manager: str
    weeks: int = Field(description="NFL weeks counted through this week")
    left_on_bench: float
    substitutions: int
    perfect_weeks: int
    detail: list[BenchWeekOut] = Field(description="Weeks with points left on the bench, most first")


class MissedStartOut(_Model):
    manager: str
    player: str
    position: str
    weeks: int = Field(description="Weeks he should have started and didn't")
    gain: float = Field(description="Points those starts would have added")


class WeekCoachingOut(_Model):
    """Lineup decisions through the week (from 2018): the v0 report's Coaching panel."""

    bench: list[BenchLineOut] = Field(description="Most points left on the bench first")
    if_only: list[MissedStartOut] = Field(description="The league's biggest missed starts, top 10")
    by_manager: dict[str, list[MissedStartOut]] = Field(description="Each manager's biggest missed starts")


class WeekDraftOut(_Model):
    """The draft graded on points so far (from 2018): the v0 report's Draft panel, plus its regression."""

    steals_after_round: int
    busts_through_round: int
    intercept: float = Field(
        description="The draft's line: expected points_above_avg = intercept + slope * pick"
    )
    slope: float
    picks: list[PickValueOut] = Field(description="Every non-keeper pick, by overall pick")
    steals: list[PickValueOut] = Field(description="Biggest value after round steals_after_round, top 10")
    busts: list[PickValueOut] = Field(description="Smallest value through round busts_through_round, top 10")


class RecapOut(_Model):
    """One game of the week retold in rivalry context (stats/narrative.py)."""

    home: str
    away: str
    text: str = Field(description="Prose; managers appear as @[id] tokens for the site to link")
    first_meeting: bool
    manager: str = Field(description="The side the record and streak are from: the winner (home on a tie)")
    wins: int = Field(description="The series after the game, from manager's side")
    losses: int
    ties: int
    streak: StreakOut = Field(description="The series' current streak after the game")
    flags: list[FlagOut] = Field(description="Notable flags on the series after the game (league_rules.yml)")


class WeekFile(ContractFile):
    """One weekly report, everything as it stood when the week ended ("through week N")."""

    season: int
    week: int = Field(description="Matchup period")
    label: str
    playoff: bool
    periods: list[int] = Field(description="The NFL weeks this matchup week covers")
    columns: list[str] = Field(default=list(GAME_COLUMNS))
    games: list[GameRow] = Field(description="This week's games")
    recaps: list[RecapOut] = Field(description="The week's games retold, same order as games")
    headlines: list[str] = Field(
        description="High and low score, closest game, biggest blowout (@[id] tokens)"
    )
    standings: list[StandingLineOut] = Field(
        description="Regular season through this week, best record first; seed order in the playoffs"
    )
    all_play: AllPlayGridOut
    coaching: WeekCoachingOut | None = Field(description="null before 2018: ESPN kept no bench data")
    draft: WeekDraftOut | None = Field(description="null before 2018: ESPN kept no weekly player points")


# Published path → model. seasons/{year}.json all use SeasonFile, weeks/{year}/{week}.json WeekFile.
FILES: dict[str, type[ContractFile]] = {
    "meta.json": Meta,
    "managers.json": ManagersFile,
    "games.json": GamesFile,
    "h2h.json": H2HFile,
    "standings.json": StandingsFile,
    "records.json": RecordsFile,
    "profiles.json": ProfilesFile,
    "luck.json": LuckFile,
    "coaching.json": CoachingFile,
    "draft.json": DraftFile,
    "trades.json": TradesFile,
    "awards.json": AwardsFile,
    "weeks.json": WeeksFile,
}
SEASON_FILE = SeasonFile
WEEK_FILE = WeekFile


def model_for(relpath: str) -> type[ContractFile]:
    if relpath.startswith("seasons/"):
        return SEASON_FILE
    if relpath.startswith("weeks/"):
        return WEEK_FILE
    return FILES[relpath]
