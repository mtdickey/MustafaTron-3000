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
