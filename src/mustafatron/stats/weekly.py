"""The weekly report: one per matchup week of every season, each "through week N".

A report exists for every matchup week whose games are all final, regular season and playoffs, so
the archive covers 2015 on and the season in progress gains one each week. Everything in a report is
as it stood when its week ended: nothing from a later week leaks in, so 2022 week 12 reads in 2030
the way it read the Tuesday after it was played.

``week`` is ESPN's matchup period throughout, as everywhere else: a playoff report covers both NFL
weeks of its matchup (``ReportWeek.periods``).
"""

from dataclasses import dataclass

from mustafatron.league_settings import LeagueSettings
from mustafatron.model import Game, Season
from mustafatron.rules import DraftReviewRules
from mustafatron.stats.allplay import AllPlay, Luck
from mustafatron.stats.coaching import counted_weeks
from mustafatron.stats.draft import DraftLine, PickValue, draft_line, steals_and_busts
from mustafatron.stats.lineup import TeamWeek
from mustafatron.stats.weeks import final_periods, regular_season_periods, week_scores


@dataclass(frozen=True)
class ReportWeek:
    season: int
    week: int  # matchup period
    label: str  # "Week 5", "Semifinals"
    playoff: bool
    periods: tuple[int, ...]  # the NFL weeks it covers


def week_label(settings: LeagueSettings, week: int) -> str:
    """ "Week 5" in the regular season; the playoff round's name after it."""
    if not settings.is_playoffs(week):
        return f"Week {week}"
    rounds = list(settings.playoff_matchup_periods)
    from_last = len(rounds) - 1 - rounds.index(week)
    return {0: "Championship", 1: "Semifinals"}.get(from_last, f"Playoffs, round {rounds.index(week) + 1}")


def report_weeks(season: Season) -> list[ReportWeek]:
    """Every matchup week of the season whose games are all final, in order."""
    weeks = sorted({g.week for g in season.games})
    return [
        ReportWeek(
            season=season.season,
            week=w,
            label=week_label(season.settings, w),
            playoff=season.settings.is_playoffs(w),
            periods=season.settings.scoring_periods(w),
        )
        for w in weeks
        if all(g.final for g in season.games if g.week == w)
    ]


def games_in(season: Season, week: int) -> list[Game]:
    return [g for g in season.games if g.week == week]


def periods_through(season: Season, week: int) -> list[int]:
    """Every NFL week up to the end of matchup week ``week``."""
    return [
        p for mp in season.settings.matchup_periods if mp <= week for p in season.settings.scoring_periods(mp)
    ]


@dataclass(frozen=True)
class StandingLine:
    manager_id: str
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float

    @property
    def win_pct(self) -> float:
        games = self.wins + self.losses + self.ties
        return (self.wins + self.ties / 2) / games if games else 0.0


def standings_through(season: Season, week: int) -> list[StandingLine]:
    """Regular season records and points through ``week``: best record first, then most points.

    In the playoffs the regular season is over, so this is its final table, in seed order.
    """
    tally = {t.manager_id: [0, 0, 0, 0.0, 0.0] for t in season.teams}
    for g in season.games:
        if g.final and not g.is_playoff and g.week <= week:
            for mid in (g.home_id, g.away_id):
                row = tally[mid]
                row["WLT".index(g.result_for(mid))] += 1
                row[3] += g.score_of(mid)
                row[4] += g.score_of(g.opponent_of(mid))
    lines = [StandingLine(m, w, lo, t, round(pf, 2), round(pa, 2)) for m, (w, lo, t, pf, pa) in tally.items()]
    if season.settings.is_playoffs(week):
        seed = {t.manager_id: t.playoff_seed for t in season.teams}
        return sorted(lines, key=lambda x: seed[x.manager_id])
    return sorted(lines, key=lambda x: (-x.win_pct, -x.points_for))


# All-play and luck (the v0 report's "Records" panel) ---------------------------------------------


@dataclass(frozen=True)
class AllPlayCell:
    """One team's NFL week: its score, its real game, and how it ranked against the whole league."""

    period: int
    points: float
    opponent_id: str
    opponent_points: float
    result: str  # W/L/T in the real game
    rank: int  # 1 = the week's high score (tied scores share a rank)
    all_play: AllPlay  # that week alone: a game against every other team

    @property
    def pct(self) -> float:
        return self.all_play.win_pct


@dataclass(frozen=True)
class AllPlayRow:
    manager_id: str
    cells: dict[int, AllPlayCell]  # by NFL week
    luck: Luck  # the actual record through the week next to the all-play one

    @property
    def all_play(self) -> AllPlay:
        return self.luck.all_play


def all_play_through(season: Season, week: int) -> tuple[list[int], list[AllPlayRow]]:
    """(NFL weeks, rows) of the all-play grid through matchup week ``week``: best all-play pct first.

    Regular season only, as everywhere all-play is counted (``stats.allplay``); a playoff report
    shows the final regular season grid.
    """
    allowed = set(periods_through(season, week)) & set(regular_season_periods(season)) & final_periods(season)
    games = {}
    for g in season.games:
        if g.final and not g.is_playoff and g.week <= week:
            for period, *_ in g.period_scores:
                games[(g.home_id, period)] = games[(g.away_id, period)] = g
    by_period: dict[int, dict[str, float]] = {}
    for w in week_scores(season):
        if w.period in allowed:
            by_period.setdefault(w.period, {})[w.manager_id] = w.points
    cells: dict[str, dict[int, AllPlayCell]] = {t.manager_id: {} for t in season.teams}
    for period, scores in sorted(by_period.items()):
        for mid, pts in scores.items():
            others = [v for m, v in scores.items() if m != mid]
            g = games[(mid, period)]
            opp = g.opponent_of(mid)
            cells[mid][period] = AllPlayCell(
                period=period,
                points=pts,
                opponent_id=opp,
                opponent_points=scores[opp],
                result=g.result_for(mid),
                rank=1 + sum(v > pts for v in others),
                all_play=AllPlay(
                    mid,
                    sum(pts > v for v in others),
                    sum(pts < v for v in others),
                    sum(pts == v for v in others),
                ),
            )
    record = {x.manager_id: x for x in standings_through(season, week)}
    rows = []
    for mid, cs in cells.items():
        ap = AllPlay(
            mid,
            sum(c.all_play.wins for c in cs.values()),
            sum(c.all_play.losses for c in cs.values()),
            sum(c.all_play.ties for c in cs.values()),
        )
        r = record[mid]
        rows.append(AllPlayRow(mid, cs, Luck(mid, r.wins, r.losses, r.ties, ap)))
    rows.sort(key=lambda r: (-r.all_play.win_pct, -sum(c.points for c in r.cells.values())))
    return sorted(by_period), rows


# Coaching (the v0 report's "Coaching" panel) -------------------------------------------------------

TOP_MISSES = 10  # the "If only..." list
MISSES_PER_MANAGER = 3


@dataclass(frozen=True)
class MissedStart:
    """A player a manager should have started, summed over every week he should have."""

    manager_id: str
    player_id: int
    weeks: int
    gain: float  # points his starts would have added, over the starters they'd have replaced


@dataclass(frozen=True)
class BenchLine:
    manager_id: str
    weeks: list[TeamWeek]  # counted weeks through the report's week

    @property
    def left_on_bench(self) -> float:
        return round(sum(w.left_on_bench for w in self.weeks), 2)

    @property
    def substitutions(self) -> int:
        return sum(w.substitutions for w in self.weeks)

    @property
    def perfect_weeks(self) -> int:
        return sum(w.perfect for w in self.weeks)


@dataclass
class WeekCoaching:
    bench: list[BenchLine]  # most points left first
    if_only: list[MissedStart]  # the league's biggest misses
    by_manager: dict[str, list[MissedStart]]  # each manager's biggest misses


def coaching_through(season: Season, week: int) -> WeekCoaching | None:
    """Lineup decisions through matchup week ``week``; None before 2018 (no bench data).

    Every number comes from the one cached solve (``stats.lineup.team_weeks``): bench totals sum the
    team-weeks, and the misses sum their swaps, so the panel's charts always agree with each other.
    Weeks count as on the coaching page: regular season, championship bracket and 3rd place game.
    """
    if not season.has_lineups:
        return None
    periods = set(periods_through(season, week))
    by_manager: dict[str, list[TeamWeek]] = {t.manager_id: [] for t in season.teams}
    for w in counted_weeks(season):
        if w.period in periods:
            by_manager[w.manager_id].append(w)
    misses: dict[tuple[str, int], list[float]] = {}
    for mid, weeks in by_manager.items():
        for w in weeks:
            for x in w.swaps:
                if x.player_in is not None:
                    misses.setdefault((mid, x.player_in), []).append(x.gain)
    ranked = sorted(
        (MissedStart(m, p, len(g), round(sum(g), 2)) for (m, p), g in misses.items()),
        key=lambda x: (-x.gain, -x.weeks, x.manager_id, x.player_id),
    )
    return WeekCoaching(
        bench=sorted((BenchLine(m, ws) for m, ws in by_manager.items()), key=lambda b: -b.left_on_bench),
        if_only=ranked[:TOP_MISSES],
        by_manager={m: [x for x in ranked if x.manager_id == m][:MISSES_PER_MANAGER] for m in by_manager},
    )


# Draft (the v0 report's "Draft" panel) -------------------------------------------------------------


@dataclass
class WeekDraft:
    line: DraftLine  # every pick, valued on points so far against that line
    steals: list[PickValue]
    busts: list[PickValue]


def draft_through(season: Season, week: int, rules: DraftReviewRules) -> WeekDraft | None:
    """The season's draft graded on the players' points through matchup week ``week``.

    The all-time draft page (``stats.draft``) waits for a season to finish; this is the in-season
    version the v0 report ran every week, with the same model fitted on points so far. None before
    2018: ESPN kept only season totals then, so there are no points "through week N".
    """
    periods = set(periods_through(season, week))
    if not any(p.weekly_points for p in season.players.values()):
        return None
    points = {
        pid: sum(v for period, v in p.weekly_points.items() if period in periods)
        for pid, p in season.players.items()
    }
    line = draft_line(season, points)
    if line is None:
        return None
    steals, busts = steals_and_busts(line.picks, rules)
    return WeekDraft(line, steals, busts)
