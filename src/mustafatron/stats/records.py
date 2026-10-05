"""The records book: the league's all-time bests and worsts.

- **Single-game and matchup records** count one-week matchups only. Playoff matchups here span two
  NFL weeks (``LeagueSettings.matchup_periods``), so their totals are not comparable with a normal
  week's.
- **Week records** are per NFL week (``pointsByScoringPeriod``, see ``stats.seasons``): every team
  plays every NFL week, playoff weeks included, so those are comparable across the whole season.
- **Season records** count finished seasons only. 2021 had a 14-week regular season (13 otherwise),
  so total-points records favor it; points per game don't.
- **Top and bottom of the week** count regular season NFL weeks, every one final so far (the season
  in progress included), in which a manager had the league's highest or lowest score. Ties credit
  everyone tied.
- **Streaks** run over regular season games in order, ties breaking them. "Spanning" streaks may
  carry from one season into the next; "within a season" ones may not.

Scoring was standard through 2022 and half-PPR from 2023 (``points_per_reception``), so scoring
records lean recent; every mark carries its season so the site can say so. Ties in value keep the
earlier mark first.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import groupby

from mustafatron.model import Game, League, Season, TeamSeason
from mustafatron.stats.weeks import regular_season_periods, week_scores

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
class MatchupMark:
    season: int
    week: int
    home_id: str
    away_id: str
    home_score: float
    away_score: float
    playoff: bool

    @property
    def total(self) -> float:
        return round(self.home_score + self.away_score, 2)


@dataclass(frozen=True)
class SeasonMark:
    season: int
    manager_id: str
    value: float
    wins: int
    losses: int
    ties: int
    points_for: float


@dataclass(frozen=True)
class StreakMark:
    manager_id: str
    length: int
    start_season: int
    start_week: int
    end_season: int
    end_week: int
    active: bool  # can still grow: see streaks()


@dataclass(frozen=True)
class WeekMark:
    season: int
    period: int  # NFL week
    total: float  # every team's points that week
    teams: int


@dataclass(frozen=True)
class ExtremeMark:
    """How many weeks a manager was the league's top (or bottom) scorer, in a season or a career."""

    season: int | None  # None: career
    manager_id: str
    count: int
    weeks: int  # regular season weeks counted for this manager


@dataclass
class RecordsBook:
    game: dict[str, list[GameMark]] = field(default_factory=dict)
    matchup: dict[str, list[MatchupMark]] = field(default_factory=dict)
    season: dict[str, list[SeasonMark]] = field(default_factory=dict)
    streak: dict[str, list[StreakMark]] = field(default_factory=dict)
    week: dict[str, list[WeekMark]] = field(default_factory=dict)
    extremes: dict[str, list[ExtremeMark]] = field(default_factory=dict)


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


def streaks(league: League, result: str, *, span_seasons: bool) -> list[StreakMark]:
    """Every run of consecutive regular season ``result`` ("W" or "L") per manager.

    A streak is ``active`` while it can still grow: it includes the manager's latest regular season
    game, the manager is in the league's latest season, and, for a streak confined to one season,
    that season still has regular season games to play.
    """
    latest = league.seasons[max(league.seasons)]
    still_in = {t.manager_id for t in latest.teams}
    open_seasons = {
        s.season for s in league.seasons.values() if any(not g.final and not g.is_playoff for g in s.games)
    }
    by_manager: dict[str, list[Game]] = {}
    for g in league.games:
        if not g.is_playoff:
            for m in (g.home_id, g.away_id):
                by_manager.setdefault(m, []).append(g)
    out = []
    for mid, games in by_manager.items():
        games.sort(key=lambda g: (g.season, g.week))
        # A run is broken by a different result, or by a new season unless spanning seasons.
        keyed = [((0 if span_seasons else g.season), g.result_for(mid), g) for g in games]
        for (_, r), run in groupby(keyed, key=lambda x: x[:2]):
            if r != result:
                continue
            run = [g for *_, g in run]
            out.append(
                StreakMark(
                    mid,
                    len(run),
                    run[0].season,
                    run[0].week,
                    run[-1].season,
                    run[-1].week,
                    run[-1] is games[-1]
                    and mid in still_in
                    and (span_seasons or run[-1].season in open_seasons),
                )
            )
    return out


def _final_periods(season: Season) -> set[int]:
    """NFL weeks of a season in which every game is final."""
    return {p for g in season.games if g.final for p, *_ in g.period_scores} - {
        p for g in season.games if not g.final for p, *_ in g.period_scores
    }


def week_extremes(league: League) -> tuple[list[ExtremeMark], list[ExtremeMark]]:
    """Per season and manager: regular season weeks as the league's top and its bottom scorer."""
    top: list[ExtremeMark] = []
    bottom: list[ExtremeMark] = []
    for s in league.seasons.values():
        periods = set(regular_season_periods(s)) & _final_periods(s)
        by_period: dict[int, dict[str, float]] = {}
        for w in week_scores(s):
            if w.period in periods:
                by_period.setdefault(w.period, {})[w.manager_id] = w.points
        if not by_period:
            continue
        hi: dict[str, int] = {}
        lo: dict[str, int] = {}
        weeks: dict[str, int] = {}
        for scores in by_period.values():
            best, worst = max(scores.values()), min(scores.values())
            for mid, pts in scores.items():
                weeks[mid] = weeks.get(mid, 0) + 1
                hi[mid] = hi.get(mid, 0) + (pts == best)
                lo[mid] = lo.get(mid, 0) + (pts == worst)
        top += [ExtremeMark(s.season, m, hi[m], weeks[m]) for m in sorted(weeks)]
        bottom += [ExtremeMark(s.season, m, lo[m], weeks[m]) for m in sorted(weeks)]
    return top, bottom


def _careers(marks: list[ExtremeMark]) -> list[ExtremeMark]:
    totals: dict[str, tuple[int, int]] = {}
    for m in marks:
        c, w = totals.get(m.manager_id, (0, 0))
        totals[m.manager_id] = (c + m.count, w + m.weeks)
    return [ExtremeMark(None, mid, c, w) for mid, (c, w) in sorted(totals.items())]


def _when(mark: object) -> tuple[int, int]:
    """When a mark was set, for breaking ties in favor of the earlier one."""
    if isinstance(mark, ExtremeMark):
        return mark.season or 0, 0
    if isinstance(mark, StreakMark):
        return mark.start_season, mark.start_week
    if isinstance(mark, WeekMark):
        return mark.season, mark.period
    return mark.season, getattr(mark, "week", 0)  # type: ignore[attr-defined]


def _top(rows: Iterable, key: Callable, reverse: bool, n: int) -> list:
    chronological = sorted(rows, key=_when)
    return sorted(chronological, key=key, reverse=reverse)[:n]  # stable: earlier first on ties


def week_totals(league: League) -> list[WeekMark]:
    """League-wide points in every NFL week where every game is final."""
    out = []
    for s in league.seasons.values():
        final_weeks = _final_periods(s)
        by_period: dict[int, list[float]] = {}
        for w in week_scores(s):
            if w.period in final_weeks:
                by_period.setdefault(w.period, []).append(w.points)
        out += [WeekMark(s.season, p, round(sum(v), 2), len(v)) for p, v in sorted(by_period.items())]
    return out


def records_book(league: League, n: int = TOP_N) -> RecordsBook:
    """Top ``n`` of each record."""
    one_week = one_week_games(league)
    sides = _sides(one_week)
    winners = [m for m in sides if m.margin > 0]
    losers = [m for m in sides if m.margin < 0]
    matchups = [
        MatchupMark(g.season, g.week, g.home_id, g.away_id, g.home_score, g.away_score, g.is_playoff)
        for g in one_week
    ]
    ppg = _season_marks(league, lambda t: t.points_for / t.games)
    total = _season_marks(league, lambda t: t.points_for)
    pct = _season_marks(league, lambda t: t.win_pct)
    weeks = week_totals(league)
    book = RecordsBook()
    book.game = {
        "highest_score": _top(sides, lambda m: m.score, True, n),
        "lowest_score": _top(sides, lambda m: m.score, False, n),
        "biggest_blowout": _top(winners, lambda m: m.margin, True, n),
        "narrowest_win": _top(winners, lambda m: m.margin, False, n),
        "most_points_in_loss": _top(losers, lambda m: m.score, True, n),
        "fewest_points_in_win": _top(winners, lambda m: m.score, False, n),
    }
    book.matchup = {
        "highest_scoring_matchup": _top(matchups, lambda m: m.total, True, n),
        "lowest_scoring_matchup": _top(matchups, lambda m: m.total, False, n),
    }
    book.season = {
        "most_points_season": _top(total, lambda m: m.value, True, n),
        "fewest_points_season": _top(total, lambda m: m.value, False, n),
        "most_points_per_game_season": _top(ppg, lambda m: m.value, True, n),
        "fewest_points_per_game_season": _top(ppg, lambda m: m.value, False, n),
        "best_record_season": _top(pct, lambda m: (m.value, m.points_for), True, n),
        "worst_record_season": _top(pct, lambda m: (m.value, m.points_for), False, n),
    }
    book.streak = {
        "longest_win_streak": _top(streaks(league, "W", span_seasons=True), lambda m: m.length, True, n),
        "longest_loss_streak": _top(streaks(league, "L", span_seasons=True), lambda m: m.length, True, n),
        "longest_win_streak_season": _top(
            streaks(league, "W", span_seasons=False), lambda m: m.length, True, n
        ),
        "longest_loss_streak_season": _top(
            streaks(league, "L", span_seasons=False), lambda m: m.length, True, n
        ),
    }
    book.week = {
        "highest_scoring_week": _top(weeks, lambda m: m.total, True, n),
        "lowest_scoring_week": _top(weeks, lambda m: m.total, False, n),
    }
    # Most weeks first; on a tie, the one who did it in fewer weeks
    top, bottom = week_extremes(league)
    most = lambda m: (m.count, -m.weeks)  # noqa: E731
    book.extremes = {
        "most_weeks_top_scorer_season": _top(top, most, True, n),
        "most_weeks_lowest_scorer_season": _top(bottom, most, True, n),
        "most_weeks_top_scorer": _top(_careers(top), most, True, n),
        "most_weeks_lowest_scorer": _top(_careers(bottom), most, True, n),
    }
    return book
