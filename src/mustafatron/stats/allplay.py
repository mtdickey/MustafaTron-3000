"""All-play records and luck, per season and across careers.

All-play is the record a team would have had playing everyone that week, the v0 report's "Records
vs. Entire League by Week" (``get_weekly_scores_df``; week by week it is now
``stats.weekly.all_play_through``). It counts final regular season NFL weeks, and each week is worth
one game against every other team, however many teams the league had that season
(``team_count - 1``, never a literal 10).

Luck is how far the actual record strays from that: **luck = actual win pct - all-play win pct**.
Positive means the schedule was kind (wins against weak weeks, or losses dodged); negative means
playing well into the wrong opponent. ``luck_wins`` puts the same thing in games: actual wins minus
the wins the all-play rate would have earned over the same games. Ties count half throughout.
"""

from collections import defaultdict
from dataclasses import dataclass

from mustafatron.model import League, Season
from mustafatron.stats.weeks import final_periods, regular_season_periods, week_scores

TOP_N = 10


@dataclass(frozen=True)
class AllPlay:
    manager_id: str
    wins: int
    losses: int
    ties: int

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        return (self.wins + self.ties / 2) / self.games if self.games else 0.0


def all_play(season: Season) -> dict[str, AllPlay]:
    """Each team's record against the whole league, week by week, over final regular season weeks."""
    final = final_periods(season) & set(regular_season_periods(season))
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


@dataclass(frozen=True)
class Luck:
    """An actual regular season record next to the all-play one: one season, or a career."""

    manager_id: str
    wins: int
    losses: int
    ties: int
    all_play: AllPlay

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        return (self.wins + self.ties / 2) / self.games if self.games else 0.0

    @property
    def luck(self) -> float:
        """Actual win pct minus all-play win pct."""
        return self.win_pct - self.all_play.win_pct

    @property
    def expected_wins(self) -> float:
        """Wins at the all-play rate over the games actually played."""
        return self.all_play.win_pct * self.games

    @property
    def luck_wins(self) -> float:
        return self.wins + self.ties / 2 - self.expected_wins


@dataclass(frozen=True)
class SeasonLuck(Luck):
    season: int = 0
    finished: bool = False
    final_rank: int | None = None


@dataclass(frozen=True)
class CareerLuck(Luck):
    seasons: int = 0


def season_luck(league: League) -> list[SeasonLuck]:
    """Every team-season with a regular season game played, oldest first."""
    out = []
    for s in league.seasons.values():
        ap = all_play(s)
        for t in s.teams:
            if t.games and ap[t.manager_id].games:
                out.append(
                    SeasonLuck(
                        manager_id=t.manager_id,
                        wins=t.wins,
                        losses=t.losses,
                        ties=t.ties,
                        all_play=ap[t.manager_id],
                        season=s.season,
                        finished=s.finished,
                        final_rank=t.final_rank,
                    )
                )
    return out


def career_luck(league: League) -> list[CareerLuck]:
    """Each manager's regular season record against the all-play one, summed over every season.

    The season in progress counts its weeks so far, as the standings do. Ranked by ``luck_wins``,
    how many wins the actual record over- (positive) or under-states (negative) the way the manager
    played: a one-season manager's win pct gap can be large and still mean little.
    """
    lines: dict[str, list[SeasonLuck]] = defaultdict(list)
    for x in season_luck(league):
        lines[x.manager_id].append(x)
    out = [
        CareerLuck(
            manager_id=m,
            wins=sum(x.wins for x in xs),
            losses=sum(x.losses for x in xs),
            ties=sum(x.ties for x in xs),
            all_play=AllPlay(
                m,
                sum(x.all_play.wins for x in xs),
                sum(x.all_play.losses for x in xs),
                sum(x.all_play.ties for x in xs),
            ),
            seasons=len(xs),
        )
        for m, xs in lines.items()
    ]
    return sorted(out, key=lambda c: -c.luck_wins)


def luckiest_seasons(league: League, n: int = TOP_N) -> tuple[list[SeasonLuck], list[SeasonLuck]]:
    """The luckiest and unluckiest finished seasons of all time, by the win pct gap.

    The pct gap rather than ``luck_wins`` because 2021's 14-game regular season would otherwise
    have more room to be lucky in. Ties keep the earlier season first.
    """
    finished = [x for x in season_luck(league) if x.finished]
    luckiest = sorted(finished, key=lambda x: -x.luck)[:n]
    unluckiest = sorted(finished, key=lambda x: x.luck)[:n]
    return luckiest, unluckiest
