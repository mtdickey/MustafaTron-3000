"""One season in detail: the week-by-week scores grid, all-play records and superlatives.

The weekly scores live in ``stats.weeks`` and all-play and luck in ``stats.allplay``; both are
re-exported here for the season pages.
"""

from dataclasses import dataclass

from mustafatron.model import Season
from mustafatron.stats.allplay import AllPlay, all_play
from mustafatron.stats.weeks import WeekScore, final_periods, regular_season_periods, week_scores

__all__ = [
    "AllPlay",
    "Superlative",
    "WeekScore",
    "all_play",
    "final_periods",
    "regular_season_periods",
    "superlatives",
    "week_scores",
]


@dataclass(frozen=True)
class Superlative:
    key: str
    manager_id: str
    value: float
    period: int | None = None  # the NFL week, for single-week superlatives


def superlatives(season: Season) -> list[Superlative]:
    """The season's headline numbers. Weekly ones use final weeks only; luck needs regular season games."""
    final = final_periods(season)
    weeks = [w for w in week_scores(season) if w.period in final]
    teams = [t for t in season.teams if t.games]
    out: list[Superlative] = []
    if weeks:
        hi = max(weeks, key=lambda w: (w.points, -w.period))
        lo = min(weeks, key=lambda w: (w.points, w.period))
        out += [
            Superlative("high_week", hi.manager_id, hi.points, hi.period),
            Superlative("low_week", lo.manager_id, lo.points, lo.period),
        ]
    if teams:
        most = max(teams, key=lambda t: t.points_for)
        fewest = min(teams, key=lambda t: t.points_for)
        against = max(teams, key=lambda t: t.points_against)
        out += [
            Superlative("most_points", most.manager_id, most.points_for),
            Superlative("fewest_points", fewest.manager_id, fewest.points_for),
            Superlative("most_points_against", against.manager_id, against.points_against),
        ]
        ap = all_play(season)
        if any(a.wins + a.losses for a in ap.values()):
            best = max(ap.values(), key=lambda a: a.win_pct)
            luck = {t.manager_id: t.win_pct - ap[t.manager_id].win_pct for t in teams}
            lucky = max(luck, key=lambda m: luck[m])
            unlucky = min(luck, key=lambda m: luck[m])
            out += [
                Superlative("best_all_play", best.manager_id, round(best.win_pct, 4)),
                Superlative("luckiest", lucky, round(luck[lucky], 4)),
                Superlative("unluckiest", unlucky, round(luck[unlucky], 4)),
            ]
    return out
