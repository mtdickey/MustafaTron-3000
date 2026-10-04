"""The coaching leaderboard: points left on the bench, lineup efficiency, and the "if only" list.

Built on ``stats.lineup`` (the actual and optimal lineup of every team-week), so it starts in 2018,
the first season ESPN kept weekly rosters (``data/README.md``).

**Which weeks count.** Every NFL week a team's game mattered: the regular season, the championship
bracket and the 3rd place game (it decides who gets the buy-in back). The losers' consolation ladder
is left out: nothing rides on it, and plenty of eliminated teams stop setting lineups.

**Normalization.** Totals favor whoever played the most weeks, so careers are ranked by points left
per week, and efficiency (actual as a share of optimal) is computed over the whole career rather than
averaged per week.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from mustafatron.model import Game, League, Season
from mustafatron.stats.lineup import TeamWeek, team_weeks

TOP_N = 10
COUNTED_TIERS = frozenset({"NONE", "WINNERS_BRACKET", "WINNERS_CONSOLATION_LADDER"})


def counted_weeks(season: Season) -> list[TeamWeek]:
    """The season's team-weeks whose game mattered, final weeks only."""
    tier = {}
    for g in season.games:
        if g.final:
            for period, *_ in g.period_scores:
                tier[(g.home_id, period)] = tier[(g.away_id, period)] = g.tier
    return [w for w in team_weeks(season) if tier.get((w.manager_id, w.period)) in COUNTED_TIERS]


@dataclass(frozen=True)
class CoachingLine:
    """Lineup decisions summed over some weeks: a season or a career."""

    manager_id: str
    weeks: int
    actual: float
    optimal: float
    perfect_weeks: int
    substitutions: int

    @property
    def left_on_bench(self) -> float:
        return round(self.optimal - self.actual, 2)

    @property
    def per_week(self) -> float:
        return self.left_on_bench / self.weeks if self.weeks else 0.0

    @property
    def efficiency(self) -> float:
        return self.actual / self.optimal if self.optimal else 1.0


@dataclass(frozen=True)
class SeasonCoaching(CoachingLine):
    season: int = 0


@dataclass(frozen=True)
class CareerCoaching(CoachingLine):
    seasons: int = 0


def _line(weeks: list[TeamWeek]) -> dict:
    return dict(
        manager_id=weeks[0].manager_id,
        weeks=len(weeks),
        actual=round(sum(w.actual for w in weeks), 2),
        optimal=round(sum(w.optimal for w in weeks), 2),
        perfect_weeks=sum(w.perfect for w in weeks),
        substitutions=sum(w.substitutions for w in weeks),
    )


@dataclass
class CoachingBook:
    first_season: int | None  # the first season with lineups, None if there are none
    weeks: list[TeamWeek]
    seasons: list[SeasonCoaching]  # by season, then fewest points left per week
    careers: list[CareerCoaching]  # fewest points left per week first
    worst_weeks: list[TeamWeek]  # most points left on the bench
    best_weeks: list[TeamWeek]  # perfect lineups, highest-scoring first
    if_only: list["IfOnly"]


@dataclass(frozen=True)
class IfOnly:
    """A loss the manager's own bench would have won."""

    game: Game
    manager_id: str
    weeks: tuple[TeamWeek, ...]  # one, or two for a two-week playoff matchup

    @property
    def score(self) -> float:
        return self.game.score_of(self.manager_id)

    @property
    def opponent_score(self) -> float:
        return self.game.score_of(self.game.opponent_of(self.manager_id))

    @property
    def optimal(self) -> float:
        return round(sum(w.optimal for w in self.weeks), 2)

    @property
    def left_on_bench(self) -> float:
        return round(sum(w.left_on_bench for w in self.weeks), 2)


def if_only(league: League, weeks: Iterable[TeamWeek]) -> list[IfOnly]:
    """Every final loss where the optimal lineup would have outscored the opponent's actual score.

    The opponent's lineup is taken as played. Most painful first: most points left on the bench.
    """
    by_key = {(w.season, w.manager_id, w.period): w for w in weeks}
    out = []
    for s in league.seasons.values():
        for g in s.games:
            if not g.final or g.tier not in COUNTED_TIERS:
                continue
            for mid in (g.home_id, g.away_id):
                if g.result_for(mid) != "L":
                    continue
                tws = tuple(by_key.get((s.season, mid, p)) for p, *_ in g.period_scores)
                if not tws or any(w is None for w in tws):
                    continue
                x = IfOnly(g, mid, tws)  # type: ignore[arg-type]
                if x.optimal > x.opponent_score:
                    out.append(x)
    return sorted(out, key=lambda x: (-x.left_on_bench, x.game.season, x.game.week))


def coaching_book(league: League, n: int = TOP_N) -> CoachingBook:
    weeks = [w for s in league.seasons.values() for w in counted_weeks(s)]
    by_season: dict[tuple[int, str], list[TeamWeek]] = defaultdict(list)
    by_manager: dict[str, list[TeamWeek]] = defaultdict(list)
    for w in weeks:
        by_season[(w.season, w.manager_id)].append(w)
        by_manager[w.manager_id].append(w)
    seasons = sorted(
        (SeasonCoaching(**_line(ws), season=season) for (season, _), ws in by_season.items()),
        key=lambda x: (x.season, x.per_week),
    )
    careers = sorted(
        (CareerCoaching(**_line(ws), seasons=len({w.season for w in ws})) for ws in by_manager.values()),
        key=lambda x: x.per_week,
    )
    worst = sorted(weeks, key=lambda w: (-w.left_on_bench, w.season, w.period))[:n]
    best = sorted((w for w in weeks if w.perfect), key=lambda w: (-w.actual, w.season, w.period))[:n]
    return CoachingBook(
        first_season=min((w.season for w in weeks), default=None),
        weeks=weeks,
        seasons=seasons,
        careers=careers,
        worst_weeks=worst,
        best_weeks=best,
        if_only=if_only(league, weeks)[:n],
    )
