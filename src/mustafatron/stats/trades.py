"""Trade history and retrospective trade valuations.

The valuation is the v0 one (``get_point_diff_for_trade``), kept because it asks the right question:
**how many points did the trade add to this team's best possible lineups for the rest of the
season?** For every week from the trade on, the team's roster that week is rebuilt twice, once with
the players it got and once with the players it gave up (each scoring what they really scored that
week, wherever they were), the optimal-lineup engine (``stats.lineup``) solves both, and the
difference is summed.

Changed from v0:

- **The season length** comes from the data: every week the team's game mattered (regular season,
  championship bracket, 3rd place game; ``stats.coaching.COUNTED_TIERS``), not ``range(start, 18)``.
- **The trade's first week** is the first NFL week the players were on their new rosters
  (``transform.infer_trades``), replacing the hand-typed season start date the old code counted
  from, which disagreed with itself.
- Each side is valued on its own roster, so a trade can help both teams, or neither.

Trades start in 2018, the first season ESPN kept weekly rosters. Trade and acquisition *counts* come
from ESPN's own per-team counters and cover every season.
"""

from collections import defaultdict
from dataclasses import dataclass

from mustafatron.model import League, Season, Transaction
from mustafatron.stats.coaching import counted_weeks
from mustafatron.stats.lineup import Candidate, eligibility, optimal_lineup

TOP_N = 10


@dataclass(frozen=True)
class TradeSide:
    manager_id: str
    players_in: tuple[int, ...]
    players_out: tuple[int, ...]
    value: float  # points the trade added to this team's best lineups, rest of season
    weeks: int  # weeks valued


@dataclass(frozen=True)
class Trade:
    id: str
    season: int
    period: int  # first NFL week the players were on their new rosters
    date: str | None  # ISO date of ESPN's acceptance, when known
    sides: tuple[TradeSide, TradeSide]

    @property
    def winner(self) -> TradeSide:
        return max(self.sides, key=lambda s: s.value)

    @property
    def loser(self) -> TradeSide:
        return min(self.sides, key=lambda s: s.value)

    @property
    def margin(self) -> float:
        """How lopsided it was: the winner's value minus the loser's."""
        return round(self.winner.value - self.loser.value, 2)


def side_value(season: Season, side: Transaction, eligible: dict[int, frozenset[str]]) -> tuple[float, int]:
    """Points the trade added to ``side``'s best lineups, over its counted weeks from the trade on."""
    traded = set(side.players_in) | set(side.players_out)
    weeks = [
        w
        for w in counted_weeks(season)
        if w.manager_id == side.manager_id and w.period >= side.scoring_period
    ]
    slots = season.settings.starter_slots

    def candidates(players: tuple[int, ...], week: int) -> list[Candidate]:
        return [
            Candidate(
                p,
                season.players[p].points_in(week) if p in season.players else 0.0,
                eligible.get(p, frozenset()),
            )
            for p in players
        ]

    total = 0.0
    for w in weeks:
        rest = [
            Candidate(p, pts, eligible.get(p, frozenset()))
            for p, pts in w.points.items()
            if p not in traded and p not in w.injured
        ]
        with_new = optimal_lineup(rest + candidates(side.players_in, w.period), slots)
        with_old = optimal_lineup(rest + candidates(side.players_out, w.period), slots)
        total += with_new.points - with_old.points
    return round(total, 2), len(weeks)


# Valued seasons, by object identity, as stats.lineup caches team-weeks: awards and the trade
# book both need them, and valuing a season's trades solves a few thousand lineups.
_valued: dict[int, tuple[Season, list[Trade]]] = {}


def season_trades(season: Season) -> list[Trade]:
    """Every trade of a season, each side valued."""
    hit = _valued.get(id(season))
    if hit is None or hit[0] is not season:
        if len(_valued) > 64:
            _valued.clear()
        hit = _valued[id(season)] = (season, _value_trades(season))
    return list(hit[1])


def _value_trades(season: Season) -> list[Trade]:
    eligible = eligibility(season)
    by_id: dict[str, list[Transaction]] = defaultdict(list)
    for t in season.trades:
        by_id[t.id].append(t)
    out = []
    for trade_id, sides in by_id.items():
        valued = []
        for side in sorted(sides, key=lambda s: s.manager_id):
            value, weeks = side_value(season, side, eligible)
            valued.append(TradeSide(side.manager_id, side.players_in, side.players_out, value, weeks))
        first = sides[0]
        out.append(
            Trade(
                id=trade_id,
                season=season.season,
                period=first.scoring_period,
                date=first.date.date().isoformat() if first.date else None,
                sides=(valued[0], valued[1]),
            )
        )
    return sorted(out, key=lambda t: (t.period, t.id))


@dataclass(frozen=True)
class TradeCount:
    season: int
    manager_id: str
    trades: int  # ESPN's count: every season
    acquisitions: int  # adds, ESPN's count


@dataclass
class TradeBook:
    first_season: int | None  # first season with trade detail
    trades: list[Trade]  # every trade, oldest first
    best: list[tuple[Trade, TradeSide]]  # the sides that gained the most
    worst: list[tuple[Trade, TradeSide]]  # the sides that lost the most
    lopsided: list[Trade]  # biggest margin between the two sides
    counts: list[TradeCount]  # every manager, every season


def trade_book(league: League, n: int = TOP_N) -> TradeBook:
    """Every trade with its verdict (finished seasons only, so each is valued over a whole season)."""
    trades = [t for s in league.seasons.values() if s.finished for t in season_trades(s)]
    sides = [(t, side) for t in trades for side in t.sides]
    return TradeBook(
        first_season=min((t.season for t in trades), default=None),
        trades=trades,
        best=sorted(sides, key=lambda x: -x[1].value)[:n],
        worst=sorted(sides, key=lambda x: x[1].value)[:n],
        lopsided=sorted(trades, key=lambda t: -t.margin)[:n],
        counts=[
            TradeCount(s.season, t.manager_id, t.trades, t.acquisitions)
            for s in league.seasons.values()
            for t in sorted(s.teams, key=lambda t: t.manager_id)
        ],
    )
