"""All-time head-to-head records and rivalries, ported from ``scratch_h2h.py``.

Same definitions as the scratch script, with two deliberate differences:

- Managers are canonical (``mustafatron.identity``), so second ESPN accounts never split a series.
- Results are ESPN's: the one tied playoff score (2017 week 15, 154-154) was broken by ESPN, so it
  is a win here where the scratch script, comparing scores, called it a tie.

Playoff games, consolation ladders included, count toward every series, as in the scratch script.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby

from mustafatron.model import Game, Result
from mustafatron.rules import RivalryRules


@dataclass(frozen=True)
class Meeting:
    """One game between two managers, from the first manager's side."""

    season: int
    week: int
    score: float
    opponent_score: float
    result: Result
    playoff: bool

    @property
    def margin(self) -> float:
        return round(abs(self.score - self.opponent_score), 2)


@dataclass(frozen=True)
class Streak:
    holder: str | None  # None when the last meeting was a tie
    length: int


@dataclass(frozen=True)
class PairRecord:
    """Every meeting between ``a`` and ``b``, oldest first, from ``a``'s side."""

    a: str
    b: str
    meetings: tuple[Meeting, ...]

    def _count(self, result: Result, playoff_only: bool = False) -> int:
        return sum(m.result == result for m in self.meetings if m.playoff or not playoff_only)

    @property
    def games(self) -> int:
        return len(self.meetings)

    @property
    def wins(self) -> int:
        return self._count("W")

    @property
    def losses(self) -> int:
        return self._count("L")

    @property
    def ties(self) -> int:
        return self._count("T")

    @property
    def playoff_wins(self) -> int:
        return self._count("W", playoff_only=True)

    @property
    def playoff_losses(self) -> int:
        return self._count("L", playoff_only=True)

    @property
    def points_for(self) -> float:
        return round(sum(m.score for m in self.meetings), 2)

    @property
    def points_against(self) -> float:
        return round(sum(m.opponent_score for m in self.meetings), 2)

    @property
    def results(self) -> str:
        return "".join(m.result for m in self.meetings)

    @property
    def current_streak(self) -> Streak:
        if not self.meetings:
            return Streak(None, 0)
        last, run = next(groupby(reversed(self.results)))
        holder = {"W": self.a, "L": self.b}.get(last)
        return Streak(holder, len(list(run)))

    def longest_streak(self, manager_id: str) -> int:
        """Longest run of consecutive wins in this series by ``manager_id``."""
        ch = "W" if manager_id == self.a else "L"
        return max((len(list(run)) for r, run in groupby(self.results) if r == ch), default=0)

    @property
    def closest(self) -> Meeting:
        """Smallest margin (earliest on a tie)."""
        return min(self.meetings, key=lambda m: (m.margin, m.season, m.week))

    @property
    def blowout(self) -> Meeting:
        """Largest margin (latest on a tie)."""
        return max(self.meetings, key=lambda m: (m.margin, m.season, m.week))

    def flipped(self) -> "PairRecord":
        flip = {"W": "L", "L": "W", "T": "T"}
        return PairRecord(
            self.b,
            self.a,
            tuple(
                Meeting(m.season, m.week, m.opponent_score, m.score, flip[m.result], m.playoff)  # type: ignore[arg-type]
                for m in self.meetings
            ),
        )

    def before(self, season: int, week: int) -> "PairRecord":
        """The series as it stood entering ``season`` week ``week``."""
        return PairRecord(
            self.a, self.b, tuple(m for m in self.meetings if (m.season, m.week) < (season, week))
        )


def pair_record(games: Iterable[Game], a: str, b: str) -> PairRecord:
    meetings = [
        Meeting(g.season, g.week, g.score_of(a), g.score_of(b), g.result_for(a), g.is_playoff)
        for g in games
        if g.final and {g.home_id, g.away_id} == {a, b}
    ]
    return PairRecord(a, b, tuple(sorted(meetings, key=lambda m: (m.season, m.week))))


def all_pairs(games: Iterable[Game]) -> dict[tuple[str, str], PairRecord]:
    """Every pair that has met, keyed ``(a, b)`` with ``a < b``, from ``a``'s side."""
    by_pair: dict[tuple[str, str], list[Game]] = {}
    for g in games:
        if g.final:
            key = tuple(sorted((g.home_id, g.away_id)))
            by_pair.setdefault(key, []).append(g)  # type: ignore[arg-type]
    return {(a, b): pair_record(gs, a, b) for (a, b), gs in sorted(by_pair.items())}


def record_between(pairs: dict[tuple[str, str], PairRecord], x: str, y: str) -> PairRecord:
    """The series from ``x``'s side, whichever way round it is stored."""
    if (x, y) in pairs:
        return pairs[(x, y)]
    if (y, x) in pairs:
        return pairs[(y, x)].flipped()
    return PairRecord(x, y, ())


@dataclass(frozen=True)
class Flag:
    """A headline about a series. ``holder`` is set for streaks and lopsided series."""

    kind: str  # "streak", "lopsided" or "dead_even"
    holder: str | None = None
    wins: int = 0
    losses: int = 0


def notable_flags(rec: PairRecord, rules: RivalryRules) -> list[Flag]:
    """The scratch script's headline flags: hot streaks, lopsided series, dead-even rivalries."""
    if rec.games < rules.notable_min_games:
        return []
    flags = []
    streak = rec.current_streak
    if streak.holder is not None and streak.length >= rules.streak:
        flags.append(Flag("streak", streak.holder, wins=streak.length))
    w, losses = rec.wins, rec.losses
    if max(w, losses) / rec.games >= rules.lopsided_pct:
        flags.append(Flag("lopsided", rec.a if w >= losses else rec.b, max(w, losses), min(w, losses)))
    if abs(w - losses) <= rules.dead_even_max_diff and rec.games >= rules.dead_even_min_games:
        flags.append(Flag("dead_even"))
    return flags


def rivalries(pairs: dict[tuple[str, str], PairRecord], rules: RivalryRules) -> list[PairRecord]:
    """Series with enough meetings to count, closest first (then most meetings)."""
    qualifying = [p for p in pairs.values() if p.games >= rules.min_matchups]
    return sorted(qualifying, key=lambda p: (abs(p.wins - p.losses) / p.games, -p.games, p.a, p.b))
