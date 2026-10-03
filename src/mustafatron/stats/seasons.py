"""One season in detail: the week-by-week scores grid, all-play records and superlatives.

Weekly numbers are per **NFL week** (ESPN's scoring period, from ``pointsByScoringPeriod``), not
per matchup: a two-week playoff matchup contributes two weekly scores. Every team plays every NFL
week here (consolation ladders included), so any week's scores are comparable across the league.

All-play is the record a team would have had playing everyone that week, the v0 report's
"Records vs. Entire League by Week". It counts regular season weeks only, and is what luck is
measured against: luck = actual win pct - all-play win pct.
"""

from dataclasses import dataclass

from mustafatron.model import Season


@dataclass(frozen=True)
class WeekScore:
    period: int  # NFL week
    manager_id: str
    points: float
    result: str  # W/L/T for a final one-week matchup, "" otherwise (in progress, or half of a two-week one)


@dataclass(frozen=True)
class AllPlay:
    manager_id: str
    wins: int
    losses: int
    ties: int

    @property
    def win_pct(self) -> float:
        n = self.wins + self.losses + self.ties
        return (self.wins + self.ties / 2) / n if n else 0.0


@dataclass(frozen=True)
class Superlative:
    key: str
    manager_id: str
    value: float
    period: int | None = None  # the NFL week, for single-week superlatives


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


def _final_periods(season: Season) -> set[int]:
    """NFL weeks whose matchups are all final (an in-progress week's partial scores don't count)."""
    done: dict[int, bool] = {}
    for g in season.games:
        for period, *_ in g.period_scores:
            done[period] = done.get(period, True) and g.final
    return {p for p, ok in done.items() if ok}


def all_play(season: Season) -> dict[str, AllPlay]:
    """Each team's record against the whole league, week by week, over final regular season weeks."""
    final = _final_periods(season) & set(regular_season_periods(season))
    by_period: dict[int, dict[str, float]] = {}
    for w in week_scores(season):
        if w.period in final:
            by_period.setdefault(w.period, {})[w.manager_id] = w.points
    tally = {t.manager_id: [0, 0, 0] for t in season.teams}
    for scores in by_period.values():
        for mid, pts in scores.items():
            others = [v for m, v in scores.items() if m != mid]
            tally[mid][0] += sum(pts > v for v in others)
            tally[mid][1] += sum(pts < v for v in others)
            tally[mid][2] += sum(pts == v for v in others)
    return {m: AllPlay(m, *t) for m, t in tally.items()}


def superlatives(season: Season) -> list[Superlative]:
    """The season's headline numbers. Weekly ones use final weeks only; luck needs regular season games."""
    final = _final_periods(season)
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
