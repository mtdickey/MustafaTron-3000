"""The optimal-lineup engine: the best lineup a team could have started, every NFL week.

Replaces the legacy ``get_optimal_subs`` (hardcoded slot branches, a Taysom Hill special case) and
``optimal_lineup_score`` (greedy: fills fixed slots first, then flex, which can leave points on the
table when a multi-position player belongs in a flex). This one is exact and driven by data:

- **The lineup shape** comes from the season's ``mSettings`` (``LeagueSettings.starter_slots``).
- **Who may fill a slot** is the player's ESPN ``eligibleSlots``, plus any slot he actually started
  in that season. ESPN serves today's eligibility for past seasons, so a player whose position
  changed is still allowed where the league really played him.
- **The search** is a small dynamic program over (player, slots still open): a roster of ~16 and a
  9-slot lineup is a few thousand states, so every team-week is solved exactly.

Injured reserve is not part of the pool: a player on IR could not have been started. A slot nobody
can fill (no kicker on the roster) stays empty, as it did in the real lineup, and so does one whose
only candidate scored below zero: leaving it empty was the better call. Bye-week players score
0 and simply never make the optimal lineup.

:func:`team_weeks` computes this once per team-week, for the coaching leaderboard (#29), the trade
valuations (#31) and, later, the weekly coaching report (M4).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache

from mustafatron.model import PlayerWeek, Season

INJURED_RESERVE = "IR"


@dataclass(frozen=True)
class Candidate:
    """A player who could be started: his id, points that week and the starting slots open to him."""

    player_id: int
    points: float
    slots: frozenset[str]


@dataclass(frozen=True)
class Lineup:
    points: float
    slots: tuple[tuple[str, int], ...]  # (slot, player id), in slot order

    @property
    def player_ids(self) -> frozenset[int]:
        return frozenset(p for _, p in self.slots)


# A sliver of a point that breaks ties between equal lineups in favor of the one actually started,
# so a bench player who merely tied a starter is not counted as a missed substitution.
TIE_BREAK = 1e-6


def optimal_lineup(
    candidates: Iterable[Candidate], starter_slots: Mapping[str, int], prefer: frozenset[int] = frozenset()
) -> Lineup:
    """The highest-scoring legal lineup from these players; among equals, the most ``prefer`` players."""
    ranked = sorted(candidates, key=lambda c: (-c.points, c.player_id not in prefer))
    pool = _contenders(ranked, starter_slots)
    value = [c.points + (TIE_BREAK if c.player_id in prefer else 0.0) for c in pool]
    slot_names = tuple(starter_slots)
    open_slots = tuple(starter_slots[s] for s in slot_names)
    options = [tuple(i for i, s in enumerate(slot_names) if s in c.slots) for c in pool]

    @cache
    def best(i: int, remaining: tuple[int, ...]) -> tuple[float, tuple[tuple[int, int], ...]]:
        if i == len(pool) or not any(remaining):
            return 0.0, ()
        top, picks = best(i + 1, remaining)  # leave this player on the bench
        for slot in options[i]:
            if remaining[slot]:
                rest = remaining[:slot] + (remaining[slot] - 1,) + remaining[slot + 1 :]
                points, more = best(i + 1, rest)
                points += value[i]
                if points > top:
                    top, picks = points, ((slot, i), *more)
        return top, picks

    _, picks = best(0, open_slots)
    slots = tuple(sorted(((slot_names[s], pool[i].player_id) for s, i in picks), key=lambda x: x[0]))
    return Lineup(round(sum(pool[i].points for _, i in picks), 2), slots)


def _contenders(ranked: list[Candidate], starter_slots: Mapping[str, int]) -> list[Candidate]:
    """Drop players who cannot be in any optimal lineup, so the search stays small.

    Among players eligible for exactly the same slots, only as many as those slots hold can start:
    anyone ranked below that could always be swapped for a better one left on the bench.
    """
    seen: dict[frozenset[str], int] = defaultdict(int)
    out = []
    for c in ranked:
        slots = frozenset(c.slots & starter_slots.keys())
        if slots and seen[slots] < sum(starter_slots[s] for s in slots):
            seen[slots] += 1
            out.append(c)
    return out


@dataclass(frozen=True)
class TeamWeek:
    """One team's lineup decisions in one NFL week."""

    season: int
    period: int  # NFL week
    manager_id: str
    actual: float  # points the starters scored
    optimal: float  # points the best possible lineup would have scored
    started: frozenset[int]
    best: frozenset[int]  # the optimal lineup's players
    points: Mapping[int, float]  # every rostered player's points that week
    injured: frozenset[int] = frozenset()  # on injured reserve: not available to start

    @property
    def left_on_bench(self) -> float:
        return round(self.optimal - self.actual, 2)

    @property
    def efficiency(self) -> float:
        return self.actual / self.optimal if self.optimal else 1.0

    @property
    def should_have_started(self) -> list[int]:
        """Benched players the optimal lineup starts, best first."""
        return sorted(self.best - self.started, key=lambda p: -self.points[p])

    @property
    def should_have_sat(self) -> list[int]:
        """Starters the optimal lineup benches, worst first."""
        return sorted(self.started - self.best, key=lambda p: self.points[p])

    @property
    def substitutions(self) -> int:
        """Lineup changes that would have made it optimal (the number in the v0 bench charts).

        Usually a swap is one in and one out, but a slot can also be emptied (a starter who scored
        below zero with nobody to replace him) or filled (an empty slot with someone on the bench).
        """
        return max(len(self.should_have_started), len(self.should_have_sat))

    @property
    def perfect(self) -> bool:
        return self.left_on_bench < 0.005


def eligibility(season: Season) -> dict[int, frozenset[str]]:
    """Starting slots each player may fill: ESPN's eligibleSlots plus wherever he started this season."""
    starters = set(season.settings.starter_slots)
    out: dict[int, set[str]] = defaultdict(set)
    for pid, player in season.players.items():
        out[pid] |= set(player.eligible_slots) & starters
    for w in season.player_weeks:
        if w.starter:
            out[w.player_id].add(w.slot)
    return {pid: frozenset(slots) for pid, slots in out.items()}


def lineup_pool(rows: Iterable[PlayerWeek], eligible: Mapping[int, frozenset[str]]) -> list[Candidate]:
    return [
        Candidate(w.player_id, w.points, eligible.get(w.player_id, frozenset()))
        for w in rows
        if w.slot != INJURED_RESERVE
    ]


# Solved seasons, by object identity (the Season is kept alive in the value, so its id can't be
# reused). Coaching, trades and awards all need the same team-weeks; solving takes ~1s a season.
_solved: dict[int, tuple[Season, list[TeamWeek]]] = {}


def team_weeks(season: Season) -> list[TeamWeek]:
    """Every team's actual and optimal lineup, every NFL week ESPN has rosters for (2018 on)."""
    if not season.has_lineups:
        return []
    hit = _solved.get(id(season))
    if hit is None or hit[0] is not season:
        if len(_solved) > 64:
            _solved.clear()
        hit = _solved[id(season)] = (season, _solve(season))
    return list(hit[1])


def _solve(season: Season) -> list[TeamWeek]:
    eligible = eligibility(season)
    rosters: dict[tuple[str, int], list[PlayerWeek]] = defaultdict(list)
    for w in season.player_weeks:
        rosters[(w.manager_id, w.period)].append(w)
    out = []
    for (manager_id, period), rows in sorted(rosters.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        started = frozenset(w.player_id for w in rows if w.starter)
        best = optimal_lineup(lineup_pool(rows, eligible), season.settings.starter_slots, prefer=started)
        out.append(
            TeamWeek(
                season=season.season,
                period=period,
                manager_id=manager_id,
                actual=round(sum(w.points for w in rows if w.starter), 2),
                optimal=best.points,
                started=started,
                best=best.player_ids,
                points={w.player_id: w.points for w in rows},
                injured=frozenset(w.player_id for w in rows if w.slot == INJURED_RESERVE),
            )
        )
    return out
