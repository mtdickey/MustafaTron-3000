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


# Published path → model. seasons/{year}.json all use SeasonFile.
FILES: dict[str, type[ContractFile]] = {
    "meta.json": Meta,
    "managers.json": ManagersFile,
    "games.json": GamesFile,
    "h2h.json": H2HFile,
    "standings.json": StandingsFile,
    "records.json": RecordsFile,
    "profiles.json": ProfilesFile,
    "luck.json": LuckFile,
}
SEASON_FILE = SeasonFile


def model_for(relpath: str) -> type[ContractFile]:
    if relpath.startswith("seasons/"):
        return SEASON_FILE
    return FILES[relpath]
