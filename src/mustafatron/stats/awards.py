"""The league's awards, every season: computed where the data supports it, recorded by hand otherwise.

Which awards exist, what decides each one and from which season the data supports it are in
``data/manual/league_rules.yml`` (``awards``). This module holds the metrics those entries name.
Winners recorded by hand (``data/manual/awards.yml``) fill in seasons a metric can't compute and
override a computed winner when the league decided differently.

Only finished seasons get awards.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

import yaml

from mustafatron.model import League, Season
from mustafatron.rules import AwardRule
from mustafatron.stats.allplay import season_luck
from mustafatron.stats.lineup import team_weeks
from mustafatron.stats.trades import Trade, TradeSide, season_trades
from mustafatron.stats.weeks import regular_season_periods

MANUAL_YML = Path(__file__).resolve().parents[3] / "data" / "manual" / "awards.yml"

Source = Literal["computed", "manual", "unrecorded"]


@dataclass(frozen=True)
class Winner:
    manager_id: str
    value: float | None
    detail: str


@dataclass(frozen=True)
class AwardResult:
    season: int
    source: Source
    winner: Winner | None  # None when unrecorded


def _trade_detail(season: Season, trade: Trade, side: TradeSide) -> str:
    def names(ids: tuple[int, ...]) -> str:
        return ", ".join(season.players[p].name if p in season.players else str(p) for p in ids) or "nothing"

    return f"Week {trade.period}: got {names(side.players_in)} for {names(side.players_out)}"


def worst_trade(league: League, season: Season) -> Winner | None:
    sides = [(t, s) for t in season_trades(season) for s in t.sides]
    if not sides:
        return None
    trade, side = min(sides, key=lambda x: (x[1].value, x[0].period))
    return Winner(side.manager_id, side.value, _trade_detail(season, trade, side))


def best_trade(league: League, season: Season) -> Winner | None:
    sides = [(t, s) for t in season_trades(season) for s in t.sides]
    if not sides:
        return None
    trade, side = max(sides, key=lambda x: (x[1].value, -x[0].period))
    return Winner(side.manager_id, side.value, _trade_detail(season, trade, side))


def fewest_bench_points(league: League, season: Season) -> Winner | None:
    """Regular season only: every team plays the same weeks, so totals compare fairly."""
    regular = set(regular_season_periods(season))
    left: dict[str, float] = {}
    for w in team_weeks(season):
        if w.period in regular:
            left[w.manager_id] = left.get(w.manager_id, 0.0) + w.left_on_bench
    if not left:
        return None
    best = min(left, key=lambda m: left[m])
    weeks = len(regular)
    return Winner(best, round(left[best], 2), f"Over {weeks} regular season weeks")


def _luck(league: League, season: Season, sign: int) -> Winner | None:
    lines = [x for x in season_luck(league) if x.season == season.season]
    if not lines:
        return None
    x = max(lines, key=lambda x: sign * x.luck)  # the pct gap, as stats.allplay ranks seasons
    record = f"{x.wins}-{x.losses}" + (f"-{x.ties}" if x.ties else "")
    detail = f"{record} on a {x.all_play.win_pct:.3f}".replace(" 0.", " .") + " all-play rate"
    return Winner(x.manager_id, round(x.luck_wins, 2), detail)


def luckiest(league: League, season: Season) -> Winner | None:
    return _luck(league, season, 1)


def unluckiest(league: League, season: Season) -> Winner | None:
    return _luck(league, season, -1)


METRICS: dict[str, Callable[[League, Season], Winner | None]] = {
    "worst_trade": worst_trade,
    "best_trade": best_trade,
    "fewest_bench_points": fewest_bench_points,
    "luckiest": luckiest,
    "unluckiest": unluckiest,
}


def parse_manual(doc: dict | None) -> dict[str, dict[int, Winner]]:
    out: dict[str, dict[int, Winner]] = {}
    for award, seasons in (doc or {}).items():
        out[award] = {
            int(season): Winner(entry["manager"], entry.get("value"), entry.get("note", ""))
            for season, entry in (seasons or {}).items()
        }
    return out


@cache
def load_manual(path: Path = MANUAL_YML) -> dict[str, dict[int, Winner]]:
    return parse_manual(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def award_history(
    league: League, award: AwardRule, manual: dict[str, dict[int, Winner]] | None = None
) -> list[AwardResult]:
    """Every finished season's winner of one award, newest first."""
    manual = load_manual() if manual is None else manual
    if award.metric not in METRICS:
        raise KeyError(f"award {award.id}: unknown metric {award.metric!r} (league_rules.yml)")
    by_hand = manual.get(award.id, {})
    out = []
    for season in sorted(league.seasons, reverse=True):
        s = league.seasons[season]
        if not s.finished:
            continue
        if season in by_hand:
            out.append(AwardResult(season, "manual", by_hand[season]))
            continue
        winner = METRICS[award.metric](league, s) if season >= award.since else None
        out.append(AwardResult(season, "computed" if winner else "unrecorded", winner))
    return out
