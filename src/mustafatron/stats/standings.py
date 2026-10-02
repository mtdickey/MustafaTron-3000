"""All-time standings: every manager's career, summed over their seasons."""

from dataclasses import dataclass
from statistics import mean

from mustafatron.model import League
from mustafatron.rules import LeagueRules


@dataclass(frozen=True)
class CareerLine:
    manager_id: str
    seasons: int
    wins: int  # regular season, as ESPN's standings count them
    losses: int
    ties: int
    points_for: float
    points_against: float
    playoff_appearances: int
    championships: int
    runner_ups: int
    third_places: int
    best_finish: int | None
    avg_finish: float | None
    net_payout: float  # sum over finished seasons, in multiples of the buy-in

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        return (self.wins + self.ties / 2) / self.games if self.games else 0.0


def all_time_standings(league: League, rules: LeagueRules) -> list[CareerLine]:
    """One line per manager, best regular season win percentage first.

    Records include a season in progress; finishes, titles and payouts count finished seasons only.
    A playoff appearance is a seed inside the season's playoff field (``mSettings`` playoff team count).
    """
    lines = []
    for manager in league.managers_with_games():
        teams = [(s, t) for s in league.seasons.values() for t in s.teams if t.manager_id == manager.id]
        finishes = [t.final_rank for s, t in teams if s.finished and t.final_rank]
        lines.append(
            CareerLine(
                manager_id=manager.id,
                seasons=len(teams),
                wins=sum(t.wins for _, t in teams),
                losses=sum(t.losses for _, t in teams),
                ties=sum(t.ties for _, t in teams),
                points_for=round(sum(t.points_for for _, t in teams), 2),
                points_against=round(sum(t.points_against for _, t in teams), 2),
                playoff_appearances=sum(
                    1 for s, t in teams if s.finished and t.playoff_seed <= s.settings.playoff_team_count
                ),
                championships=finishes.count(1),
                runner_ups=finishes.count(2),
                third_places=finishes.count(3),
                best_finish=min(finishes, default=None),
                avg_finish=round(mean(finishes), 2) if finishes else None,
                net_payout=round(
                    sum(
                        rules.payouts(s.season).for_rank(t.final_rank)
                        for s, t in teams
                        if s.finished and t.final_rank
                    ),
                    2,
                ),
            )
        )
    return sorted(lines, key=lambda c: (-c.win_pct, -c.points_for))
