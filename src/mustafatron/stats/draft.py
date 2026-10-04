"""The all-time draft leaderboard: who drafts well, the biggest steals and busts, value by round.

The model is the v0 draft review's (``get_draft_df`` and ``visuals.py``), kept deliberately simple:

1. ``points_above_avg`` = a pick's season points minus the mean for drafted players at his position
2. a straight line ``points_above_avg ~ overall_pick`` is the expectation for each pick
3. ``value`` = actual minus that line ("points above pick"). Positive: more than the slot promised.

**Fit per season.** One line across all eleven seasons would compare 2015's standard scoring with
2023's half-PPR, and each era's positional scarcity with another's. So the positional means and the
line are both computed within a season, and a 2015 steal is measured against 2015's draft only.

Season points are the player's whole NFL season in this league's scoring (``players.json``),
available for every season, so the leaderboard covers 2015 on. ESPN's projections are not used:
the player object only carries rest-of-season projections, not draft-day ones (the v0 dead end).

**Keepers** (2024 on) are left out. A kept player was not a draft-day choice, and keeper value is the
keeper module's job (M5).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from mustafatron.model import League, Season
from mustafatron.rules import DraftReviewRules

TOP_N = 10


@dataclass(frozen=True)
class PickValue:
    season: int
    round: int
    round_pick: int
    overall_pick: int
    manager_id: str
    player_id: int
    player: str
    position: str
    points: float  # the player's season, this league's scoring
    points_above_avg: float  # vs drafted players at his position that season
    expected: float  # the season's line at this pick
    value: float  # points_above_avg - expected


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares: (intercept, slope)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx if sxx else 0.0
    return my - slope * mx, slope


def season_values(season: Season) -> list[PickValue]:
    """Every non-keeper pick of one draft, valued against that draft's own expectation line."""
    picks = [p for p in season.draft if not p.keeper and p.player_id in season.players]
    points = {p.player_id: season.players[p.player_id].season_points or 0.0 for p in picks}
    position = {p.player_id: season.players[p.player_id].position for p in picks}
    by_position: dict[str, list[float]] = defaultdict(list)
    for p in picks:
        by_position[position[p.player_id]].append(points[p.player_id])
    mean = {pos: sum(v) / len(v) for pos, v in by_position.items()}
    above = {p.player_id: points[p.player_id] - mean[position[p.player_id]] for p in picks}
    if len(picks) < 2:
        return []
    intercept, slope = _fit([p.overall_pick for p in picks], [above[p.player_id] for p in picks])
    out = []
    for p in picks:
        expected = intercept + slope * p.overall_pick
        out.append(
            PickValue(
                season=season.season,
                round=p.round,
                round_pick=p.round_pick,
                overall_pick=p.overall_pick,
                manager_id=p.manager_id,
                player_id=p.player_id,
                player=season.players[p.player_id].name,
                position=position[p.player_id],
                points=round(points[p.player_id], 2),
                points_above_avg=round(above[p.player_id], 2),
                expected=round(expected, 2),
                value=round(above[p.player_id] - expected, 2),
            )
        )
    return out


@dataclass(frozen=True)
class DrafterLine:
    manager_id: str
    seasons: int
    picks: int
    value: float  # total points above pick
    early_picks: int
    early_value: float  # rounds 1 through the bust cutoff
    late_picks: int
    late_value: float

    @property
    def per_pick(self) -> float:
        return self.value / self.picks if self.picks else 0.0

    @property
    def early_per_pick(self) -> float:
        return self.early_value / self.early_picks if self.early_picks else 0.0

    @property
    def late_per_pick(self) -> float:
        return self.late_value / self.late_picks if self.late_picks else 0.0


@dataclass(frozen=True)
class RoundLine:
    round: int
    picks: int
    avg_points: float
    avg_value_by_manager: dict[str, float]


@dataclass(frozen=True)
class DraftClass:
    """One manager's whole draft in one season."""

    season: int
    manager_id: str
    picks: int
    value: float
    best: PickValue


@dataclass
class DraftBook:
    first_season: int | None
    picks: list[PickValue]
    drafters: list[DrafterLine]  # best average value per pick first
    steals: list[PickValue]  # biggest value after the steal cutoff round
    busts: list[PickValue]  # smallest value through the bust cutoff round
    rounds: list[RoundLine]
    best_drafts: list[DraftClass]
    worst_drafts: list[DraftClass]
    early_rounds: int  # rounds 1 through this are "early" in DrafterLine (the bust cutoff)


def drafters(picks: Iterable[PickValue], early_rounds: int) -> list[DrafterLine]:
    by_manager: dict[str, list[PickValue]] = defaultdict(list)
    for p in picks:
        by_manager[p.manager_id].append(p)
    out = []
    for m, ps in by_manager.items():
        early = [p for p in ps if p.round <= early_rounds]
        late = [p for p in ps if p.round > early_rounds]
        out.append(
            DrafterLine(
                manager_id=m,
                seasons=len({p.season for p in ps}),
                picks=len(ps),
                value=round(sum(p.value for p in ps), 2),
                early_picks=len(early),
                early_value=round(sum(p.value for p in early), 2),
                late_picks=len(late),
                late_value=round(sum(p.value for p in late), 2),
            )
        )
    return sorted(out, key=lambda d: -d.per_pick)


def draft_book(league: League, rules: DraftReviewRules, n: int = TOP_N) -> DraftBook:
    """Every finished season's draft. A draft in progress is valued only once its season ends."""
    picks = [v for s in league.seasons.values() if s.finished for v in season_values(s)]
    steals = sorted((p for p in picks if p.round > rules.steals_after_round), key=lambda p: -p.value)[:n]
    busts = sorted((p for p in picks if p.round <= rules.busts_through_round), key=lambda p: p.value)[:n]
    by_round: dict[int, list[PickValue]] = defaultdict(list)
    for p in picks:
        by_round[p.round].append(p)
    rounds = []
    for r, ps in sorted(by_round.items()):
        per_manager: dict[str, list[float]] = defaultdict(list)
        for p in ps:
            per_manager[p.manager_id].append(p.value)
        rounds.append(
            RoundLine(
                round=r,
                picks=len(ps),
                avg_points=round(sum(p.points for p in ps) / len(ps), 2),
                avg_value_by_manager={m: round(sum(v) / len(v), 2) for m, v in sorted(per_manager.items())},
            )
        )
    classes: dict[tuple[int, str], list[PickValue]] = defaultdict(list)
    for p in picks:
        classes[(p.season, p.manager_id)].append(p)
    drafts = [
        DraftClass(season, m, len(ps), round(sum(p.value for p in ps), 2), max(ps, key=lambda p: p.value))
        for (season, m), ps in classes.items()
    ]
    return DraftBook(
        first_season=min((p.season for p in picks), default=None),
        picks=picks,
        drafters=drafters(picks, rules.busts_through_round),
        steals=steals,
        busts=busts,
        rounds=rounds,
        best_drafts=sorted(drafts, key=lambda d: -d.value)[:n],
        worst_drafts=sorted(drafts, key=lambda d: d.value)[:n],
        early_rounds=rules.busts_through_round,
    )
