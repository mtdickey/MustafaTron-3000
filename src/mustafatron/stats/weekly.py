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
from mustafatron.stats.allplay import AllPlay, Luck
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
