"""Every team's points NFL week by NFL week, the base of the season grid, all-play and records.

Weekly numbers are per **NFL week** (ESPN's scoring period, from ``pointsByScoringPeriod``), not
per matchup: a two-week playoff matchup contributes two weekly scores. Every team plays every NFL
week here (consolation ladders included), so any week's scores are comparable across the league.
"""

from dataclasses import dataclass

from mustafatron.model import Season


@dataclass(frozen=True)
class WeekScore:
    period: int  # NFL week
    manager_id: str
    points: float
    result: str  # W/L/T for a final one-week matchup, "" otherwise (in progress, or half of a two-week one)


def week_scores(season: Season) -> list[WeekScore]:
    """Every team's points in every NFL week with a final or in-progress score, week order.

    ESPN lists unplayed weeks with zero points; those are left out until scoring starts.
    """
    out = []
    for g in season.games:
        one_week = len(g.period_scores) == 1
        for period, home_pts, away_pts in g.period_scores:
            if not g.final and home_pts == away_pts == 0:
                continue
            for mid, pts in ((g.home_id, home_pts), (g.away_id, away_pts)):
                result = g.result_for(mid) if g.final and one_week else ""
                out.append(WeekScore(period, mid, pts, result))
    return sorted(out, key=lambda w: (w.period, w.manager_id))


def regular_season_periods(season: Season) -> list[int]:
    return [
        p
        for mp in range(1, season.settings.regular_season_matchups + 1)
        if mp in season.settings.matchup_periods
        for p in season.settings.scoring_periods(mp)
    ]


def final_periods(season: Season) -> set[int]:
    """NFL weeks whose matchups are all final (an in-progress week's partial scores don't count)."""
    done: dict[int, bool] = {}
    for g in season.games:
        for period, *_ in g.period_scores:
            done[period] = done.get(period, True) and g.final
    return {p for p, ok in done.items() if ok}
