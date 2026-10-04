"""Per-manager career detail for the profile pages: best and worst weeks, record against the field.

Everything else on a profile (career line, seasons, rivalries) is already published by
``standings``, ``seasons`` and ``h2h``; the site joins those.
"""

from dataclasses import dataclass

from mustafatron.model import League, Result
from mustafatron.stats.allplay import AllPlay, all_play
from mustafatron.stats.weeks import final_periods

TOP_WEEKS = 5


@dataclass(frozen=True)
class WeekLine:
    """One manager's points in one NFL week."""

    season: int
    period: int  # NFL week
    points: float
    opponent_id: str
    result: Result | None  # None for half of a two-week playoff matchup


def manager_weeks(league: League, manager_id: str) -> list[WeekLine]:
    """Every final NFL week the manager played, oldest first."""
    out = []
    for s in league.seasons.values():
        done = final_periods(s)
        for g in s.games:
            if not g.involves(manager_id):
                continue
            one_week = len(g.period_scores) == 1
            for period, home_pts, away_pts in g.period_scores:
                if period not in done:
                    continue
                pts = home_pts if manager_id == g.home_id else away_pts
                result = g.result_for(manager_id) if one_week else None
                out.append(WeekLine(s.season, period, pts, g.opponent_of(manager_id), result))
    return sorted(out, key=lambda w: (w.season, w.period))


def best_and_worst_weeks(
    league: League, manager_id: str, n: int = TOP_WEEKS
) -> tuple[list[WeekLine], list[WeekLine]]:
    weeks = manager_weeks(league, manager_id)
    best = sorted(weeks, key=lambda w: -w.points)[:n]  # stable: the earlier week first on a tie
    worst = sorted(weeks, key=lambda w: w.points)[:n]
    return best, worst


def career_all_play(league: League, manager_id: str) -> AllPlay:
    """Regular season record against the whole league every week, summed over the manager's seasons."""
    lines = [
        all_play(s)[manager_id]
        for s in league.seasons.values()
        if any(t.manager_id == manager_id for t in s.teams)
    ]
    return AllPlay(
        manager_id,
        sum(a.wins for a in lines),
        sum(a.losses for a in lines),
        sum(a.ties for a in lines),
    )
