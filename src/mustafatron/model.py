"""The normalized entities everything downstream reads. Stats code never touches raw ESPN JSON.

Built from ``data/raw/`` by ``mustafatron.transform``. Every manager reference is a canonical
manager id from ``data/manual/managers.yml`` (see ``mustafatron.identity``), never an ESPN ID.

Deliberately not a database: ~850 games is small enough that plain objects, or pandas over them
(:func:`to_frame`), are the right tool.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

import pandas as pd

from mustafatron.identity import Manager, Managers
from mustafatron.league_settings import LeagueSettings

__all__ = [
    "DraftPick",
    "Game",
    "League",
    "Manager",
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
    """One manager's side of an executed roster move. A trade yields one per team involved."""

    season: int
    scoring_period: int
    date: datetime
    type: str  # TRADE, WAIVER, FREEAGENT
    manager_id: str
    players_in: tuple[int, ...]
    players_out: tuple[int, ...]
    bid: int = 0


@dataclass
class Season:
    season: int
    settings: LeagueSettings
    teams: list[TeamSeason]
    games: list[Game]  # every scheduled game, final or not, in week order

    @property
    def finished(self) -> bool:
        return bool(self.games) and all(g.final for g in self.games)

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

    def manager(self, manager_id: str) -> Manager:
        return self.managers[manager_id]

    def managers_with_games(self) -> list[Manager]:
        ids = {t.manager_id for t in self.team_seasons}
        return [m for m in self.managers if m.id in ids]


def to_frame(rows: Iterable[object]) -> pd.DataFrame:
    """A DataFrame with one column per dataclass field."""
    return pd.DataFrame([asdict(r) for r in rows])  # type: ignore[call-overload]
