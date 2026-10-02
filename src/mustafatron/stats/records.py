"""The records book: single-game and single-season bests and worsts.

Single-game records only count one-week matchups. Playoff matchups here span two NFL weeks
(``LeagueSettings.matchup_periods``), so their totals are not comparable with a normal week's.
Scoring was standard through 2022 and half-PPR from 2023 (``points_per_reception``), so scoring
records lean recent; the published records carry the season so the site can say so.
"""

from collections.abc import Callable
from dataclasses import dataclass

from mustafatron.model import Game, League, TeamSeason

TOP_N = 10


@dataclass(frozen=True)
class GameMark:
    season: int
    week: int
    manager_id: str
    opponent_id: str
    score: float
    opponent_score: float
    playoff: bool

    @property
    def margin(self) -> float:
        return round(self.score - self.opponent_score, 2)


@dataclass(frozen=True)
class SeasonMark:
    season: int
    manager_id: str
    value: float
    wins: int
    losses: int
    ties: int
    points_for: float


def one_week_games(league: League) -> list[Game]:
    return [
        g
        for s in league.seasons.values()
        for g in s.games
        if g.final and len(s.settings.scoring_periods(g.week)) == 1
    ]


def _sides(games: list[Game]) -> list[GameMark]:
    return [
        GameMark(
            g.season, g.week, m, g.opponent_of(m), g.score_of(m), g.score_of(g.opponent_of(m)), g.is_playoff
        )
        for g in games
        for m in (g.home_id, g.away_id)
    ]


def _season_marks(league: League, value: Callable[[TeamSeason], float]) -> list[SeasonMark]:
    return [
        SeasonMark(t.season, t.manager_id, round(value(t), 2), t.wins, t.losses, t.ties, t.points_for)
        for s in league.seasons.values()
        if s.finished
        for t in s.teams
    ]


def records_book(league: League, n: int = TOP_N) -> dict[str, list[GameMark] | list[SeasonMark]]:
    """Top ``n`` of each record, keyed by record name. Ties in value keep the earlier one first."""
    sides = _sides(one_week_games(league))
    winners = [m for m in sides if m.margin > 0]
    ppg = _season_marks(league, lambda t: t.points_for / t.games)
    pct = _season_marks(league, lambda t: t.win_pct)

    def top(rows, key, reverse):
        chronological = sorted(rows, key=lambda r: (r.season, getattr(r, "week", 0)))
        return sorted(chronological, key=key, reverse=reverse)[:n]  # stable: earlier first on ties

    return {
        "highest_score": top(sides, lambda m: m.score, True),
        "lowest_score": top(sides, lambda m: m.score, False),
        "biggest_blowout": top(winners, lambda m: m.margin, True),
        "narrowest_win": top(winners, lambda m: m.margin, False),
        "most_points_per_game_season": top(ppg, lambda m: m.value, True),
        "fewest_points_per_game_season": top(ppg, lambda m: m.value, False),
        "best_record_season": top(pct, lambda m: (m.value, m.points_for), True),
        "worst_record_season": top(pct, lambda m: (m.value, m.points_for), False),
    }
