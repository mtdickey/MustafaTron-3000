"""The normalized entities everything downstream reads. Stats code never touches raw ESPN JSON.

Built from ``data/raw/`` by ``mustafatron.transform``. Every manager reference is a canonical
manager id from ``data/manual/managers.yml`` (see ``mustafatron.identity``), never an ESPN ID.

Deliberately not a database: ~850 games is small enough that plain objects, or pandas over them
(:func:`to_frame`), are the right tool. The player level is bigger (~23k player-weeks across
2018-2025) but still fits the same way: ``to_frame(league.player_weeks)`` is the wide table.

Player-level fields (``Season.draft``, ``players``, ``player_weeks``, ``transactions``) are filled
only when the league is loaded with ``load_league(player_data=True)``. What ESPN serves differs by
era: drafts and player season totals exist for every season, weekly rosters and transactions only
from 2018 (``Season.has_lineups``; see ``data/README.md``).
"""

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd

from mustafatron.identity import Manager, Managers
from mustafatron.league_settings import NON_STARTING_SLOTS, LeagueSettings

__all__ = [
    "DraftPick",
    "Game",
    "League",
    "Manager",
    "Player",
    "PlayerWeek",
    "Result",
    "Season",
    "TeamSeason",
    "Transaction",
    "to_frame",
]

Result = Literal["W", "L", "T"]
REGULAR_SEASON = "NONE"
CHAMPIONSHIP_BRACKET = "WINNERS_BRACKET"


@dataclass(frozen=True)
class TeamSeason:
    """One manager's team in one season. Record and points are regular season only, as ESPN reports them."""

    season: int
    manager_id: str
    team_id: int
    name: str
    abbrev: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    playoff_seed: int
    final_rank: int | None  # None until the season is finished
    acquisitions: int
    trades: int
    co_manager_ids: tuple[str, ...] = ()

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        return (self.wins + self.ties / 2) / self.games if self.games else 0.0


@dataclass(frozen=True)
class Game:
    """One head-to-head matchup. ``week`` is ESPN's matchup period (a playoff "week" spans two NFL weeks)."""

    season: int
    week: int
    tier: str  # ESPN playoffTierType: NONE (regular season), WINNERS_BRACKET, or a consolation ladder
    home_id: str
    away_id: str
    home_score: float
    away_score: float
    final: bool  # False for scheduled and in-progress games, whose scores are partial
    # ESPN's result, not the scores: playoff ties are broken by ESPN (2017 week 15 ended 154-154).
    winner_id: str | None = None  # None while not final, or for a regular season tie
    # (NFL week, home points, away points) for each scoring period the matchup covers: one for a
    # regular season game, two for a playoff matchup here. Empty when ESPN sent no breakdown.
    period_scores: tuple[tuple[int, float, float], ...] = ()

    @property
    def is_playoff(self) -> bool:
        """Any postseason game, consolation ladders included."""
        return self.tier != REGULAR_SEASON

    @property
    def is_championship_bracket(self) -> bool:
        return self.tier == CHAMPIONSHIP_BRACKET

    @property
    def is_tie(self) -> bool:
        return self.final and self.winner_id is None

    @property
    def margin(self) -> float:
        return abs(self.home_score - self.away_score)

    def involves(self, manager_id: str) -> bool:
        return manager_id in (self.home_id, self.away_id)

    def score_of(self, manager_id: str) -> float:
        return self.home_score if manager_id == self.home_id else self.away_score

    def opponent_of(self, manager_id: str) -> str:
        return self.away_id if manager_id == self.home_id else self.home_id

    def result_for(self, manager_id: str) -> Result:
        """W/L/T from ``manager_id``'s side: ESPN's result once final, the current scores before that."""
        if self.final:
            return "T" if self.winner_id is None else "W" if self.winner_id == manager_id else "L"
        mine, theirs = self.score_of(manager_id), self.score_of(self.opponent_of(manager_id))
        return "W" if mine > theirs else "L" if mine < theirs else "T"


@dataclass(frozen=True)
class DraftPick:
    season: int
    round: int
    round_pick: int
    overall_pick: int
    player_id: int
    manager_id: str
    keeper: bool


@dataclass(frozen=True)
class Transaction:
    """One manager's side of a roster move. A trade yields one per team involved, sharing ``id``.

    Adds and drops are ESPN's executed records. Trades are found by following players from roster to
    roster (``transform.infer_trades``), because ESPN no longer returns the executed record of most
    past trades: their ``scoring_period`` is the first NFL week the players were on their new rosters,
    and ``date`` comes from ESPN's acceptance record when one can be matched (else None).
    """

    season: int
    scoring_period: int
    date: datetime | None
    type: str  # TRADE, WAIVER, FREEAGENT
    manager_id: str
    players_in: tuple[int, ...]
    players_out: tuple[int, ...]
    bid: int = 0
    id: str = ""


@dataclass(frozen=True)
class Player:
    """An NFL player (or team defense) in one season, with his points under this league's scoring."""

    id: int
    name: str
    position: str  # QB, RB, WR, TE, K, D/ST
    eligible_slots: tuple[str, ...]
    season_points: float | None  # None when ESPN has no stat line
    # NFL week -> points, 2018 on (empty before: ESPN kept only season totals)
    weekly_points: Mapping[int, float] = field(default_factory=dict, compare=False, hash=False)

    def points_in(self, period: int) -> float:
        return self.weekly_points.get(period, 0.0)


@dataclass(frozen=True)
class PlayerWeek:
    """One player on one team's roster in one NFL week: the lineup slot he was in and his points."""

    season: int
    period: int  # NFL week
    manager_id: str
    player_id: int
    slot: str  # a LeagueSettings lineup slot: QB, RB, ..., RB/WR/TE, BE, IR
    points: float

    @property
    def starter(self) -> bool:
        return self.slot not in NON_STARTING_SLOTS


@dataclass
class Season:
    season: int
    settings: LeagueSettings
    teams: list[TeamSeason]
    games: list[Game]  # every scheduled game, final or not, in week order
    # Player level, filled by load_league(player_data=True)
    draft: list[DraftPick] = field(default_factory=list)
    players: dict[int, Player] = field(default_factory=dict)
    player_weeks: list[PlayerWeek] = field(default_factory=list)  # 2018 on
    transactions: list[Transaction] = field(default_factory=list)  # 2018 on

    @property
    def finished(self) -> bool:
        return bool(self.games) and all(g.final for g in self.games)

    @property
    def has_lineups(self) -> bool:
        """Weekly rosters with lineup slots and bench points: ESPN serves these from 2018."""
        return bool(self.player_weeks)

    @property
    def trades(self) -> list[Transaction]:
        return [t for t in self.transactions if t.type == "TRADE"]

    def team_of(self, manager_id: str) -> TeamSeason:
        return next(t for t in self.teams if t.manager_id == manager_id)

    @property
    def champion_id(self) -> str | None:
        return next((t.manager_id for t in self.teams if t.final_rank == 1), None)


@dataclass
class League:
    managers: Managers
    seasons: dict[int, Season] = field(default_factory=dict)

    @property
    def games(self) -> list[Game]:
        """Every final game across all seasons, in order."""
        return [g for s in self.seasons.values() for g in s.games if g.final]

    @property
    def team_seasons(self) -> list[TeamSeason]:
        return [t for s in self.seasons.values() for t in s.teams]

    @property
    def player_weeks(self) -> list[PlayerWeek]:
        return [w for s in self.seasons.values() for w in s.player_weeks]

    def manager(self, manager_id: str) -> Manager:
        return self.managers[manager_id]

    def managers_with_games(self) -> list[Manager]:
        ids = {t.manager_id for t in self.team_seasons}
        return [m for m in self.managers if m.id in ids]


def to_frame(rows: Iterable[object]) -> pd.DataFrame:
    """A DataFrame with one column per dataclass field."""
    return pd.DataFrame([asdict(r) for r in rows])  # type: ignore[call-overload]
