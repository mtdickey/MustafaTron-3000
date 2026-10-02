"""All-time standings: every manager's career, summed over their seasons, and the championship ledger."""

from dataclasses import dataclass
from statistics import mean

from mustafatron.model import League
from mustafatron.rules import LeagueRules


@dataclass(frozen=True)
class CareerLine:
    manager_id: str
    seasons: int
    finished_seasons: int  # seasons with a final rank, the ones finishes and payouts count
    wins: int  # regular season, as ESPN's standings count them
    losses: int
    ties: int
    points_for: float
    points_against: float
    playoff_appearances: int
    playoff_wins: int  # championship bracket games only, consolation ladders excluded
    playoff_losses: int
    playoff_points_for: float
    playoff_points_against: float
    championships: int
    runner_ups: int
    third_places: int
    last_places: int
    best_finish: int | None
    worst_finish: int | None
    avg_finish: float | None
    net_payout: float  # sum over finished seasons, in multiples of the buy-in

    @property
    def games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        return (self.wins + self.ties / 2) / self.games if self.games else 0.0

    @property
    def avg_margin(self) -> float:
        """Regular season points for minus against, per game."""
        return (self.points_for - self.points_against) / self.games if self.games else 0.0

    @property
    def roi(self) -> float:
        """Net payout per buy-in paid: 0.25 means a career return of 25% on every buy-in."""
        return self.net_payout / self.finished_seasons if self.finished_seasons else 0.0


def all_time_standings(league: League, rules: LeagueRules) -> list[CareerLine]:
    """One line per manager, best regular season win percentage first.

    Records include a season in progress; finishes, titles and payouts count finished seasons only.
    A playoff appearance is a seed inside the season's playoff field (``mSettings`` playoff team count).
    """
    lines = []
    for manager in league.managers_with_games():
        mid = manager.id
        teams = [(s, t) for s in league.seasons.values() for t in s.teams if t.manager_id == mid]
        finished = [(s, t) for s, t in teams if s.finished and t.final_rank]
        finishes = [t.final_rank for _, t in finished]
        bracket = [g for g in league.games if g.is_championship_bracket and g.involves(mid)]
        lines.append(
            CareerLine(
                manager_id=mid,
                seasons=len(teams),
                finished_seasons=len(finished),
                wins=sum(t.wins for _, t in teams),
                losses=sum(t.losses for _, t in teams),
                ties=sum(t.ties for _, t in teams),
                points_for=round(sum(t.points_for for _, t in teams), 2),
                points_against=round(sum(t.points_against for _, t in teams), 2),
                playoff_appearances=sum(
                    1 for s, t in finished if t.playoff_seed <= s.settings.playoff_team_count
                ),
                playoff_wins=sum(g.result_for(mid) == "W" for g in bracket),
                playoff_losses=sum(g.result_for(mid) == "L" for g in bracket),
                playoff_points_for=round(sum(g.score_of(mid) for g in bracket), 2),
                playoff_points_against=round(sum(g.score_of(g.opponent_of(mid)) for g in bracket), 2),
                championships=finishes.count(1),
                runner_ups=finishes.count(2),
                third_places=finishes.count(3),
                last_places=sum(t.final_rank == s.settings.team_count for s, t in finished),
                best_finish=min(finishes, default=None),
                worst_finish=max(finishes, default=None),
                avg_finish=round(mean(finishes), 2) if finishes else None,
                net_payout=round(sum(rules.payouts(s.season).for_rank(t.final_rank) for s, t in finished), 2),
            )
        )
    return sorted(lines, key=lambda c: (-c.win_pct, -c.points_for))


@dataclass(frozen=True)
class LedgerEntry:
    """Who finished where in one finished season."""

    season: int
    champion: str
    runner_up: str
    third: str
    last: str
    top_seed: str  # best regular season
    most_points: str  # most regular season points for
    champion_seed: int


def championship_ledger(league: League) -> list[LedgerEntry]:
    """One entry per finished season, newest first."""
    out = []
    for s in sorted(league.seasons.values(), key=lambda s: -s.season):
        if not s.finished:
            continue
        by_rank = {t.final_rank: t for t in s.teams}
        out.append(
            LedgerEntry(
                season=s.season,
                champion=by_rank[1].manager_id,
                runner_up=by_rank[2].manager_id,
                third=by_rank[3].manager_id,
                last=by_rank[s.settings.team_count].manager_id,
                top_seed=min(s.teams, key=lambda t: t.playoff_seed).manager_id,
                most_points=max(s.teams, key=lambda t: t.points_for).manager_id,
                champion_seed=by_rank[1].playoff_seed,
            )
        )
    return out
