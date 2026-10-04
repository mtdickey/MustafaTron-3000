"""League rules ESPN does not model, from ``data/manual/league_rules.yml``.

The counterpart of ``mustafatron.league_settings``: settings ESPN knows come from there, everything
else (payouts, keeper eligibility, analysis thresholds, week boundaries) from here. Nothing in the
codebase should hardcode any of these values.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from mustafatron.league_settings import load_settings

RULES_YML = Path(__file__).resolve().parents[2] / "data" / "manual" / "league_rules.yml"


@dataclass(frozen=True)
class Payouts:
    by_rank: dict[int, float]
    otherwise: float

    def for_rank(self, rank: int) -> float:
        """Net return as a multiple of the buy-in: +5.5 for a title, -1.0 for losing the buy-in."""
        return self.by_rank.get(rank, self.otherwise)


@dataclass(frozen=True)
class RivalryRules:
    min_matchups: int
    notable_min_games: int
    streak: int
    lopsided_pct: float
    dead_even_max_diff: int
    dead_even_min_games: int


@dataclass(frozen=True)
class AwardRule:
    """One of the league's awards: which metric decides it, and from when the data supports it."""

    id: str
    name: str
    description: str
    metric: str  # a key of mustafatron.stats.awards.METRICS
    status: str  # official (the league gives it) or proposed
    since: int


@dataclass(frozen=True)
class DraftReviewRules:
    steals_after_round: int
    busts_through_round: int


class LeagueRules:
    def __init__(self, doc: dict[str, Any]):
        self._doc = doc
        self.history_start: int = doc["history_start"]
        self.rivalry = RivalryRules(**doc["rivalry"])
        self.draft_review = DraftReviewRules(**doc["draft_review"])
        self._kickoffs = {int(y): _utc(v) for y, v in doc["nfl_week1_kickoff"].items()}
        self.awards: list[AwardRule] = [AwardRule(**a) for a in doc.get("awards", [])]

    def _for_season(self, rule: str, season: int) -> Any:
        """The value of a ``[{since, value}, ...]`` rule in effect for a season (None before the first)."""
        entries = sorted(self._doc[rule], key=lambda e: e["since"])
        current = None
        for e in entries:
            if e["since"] <= season:
                current = e["value"]
        return current

    def payouts(self, season: int) -> Payouts:
        v = self._for_season("payouts", season)
        if v is None:
            raise KeyError(f"no payout rule for {season}")
        return Payouts({int(k): float(x) for k, x in v["by_rank"].items()}, float(v["otherwise"]))

    def keeper_eligible_after_round(self, season: int) -> int | None:
        """Players drafted after this round can be kept; None in seasons without keepers."""
        v = self._for_season("keepers", season)
        return None if v is None else v["eligible_after_round"]

    def week1_kickoff(self, season: int) -> datetime:
        try:
            return self._kickoffs[season]
        except KeyError:
            raise KeyError(
                f"no NFL week 1 kickoff for {season} in data/manual/league_rules.yml (nfl_week1_kickoff)"
            ) from None

    def week_start(self, season: int, nfl_week: int) -> datetime:
        return self.week1_kickoff(season) + timedelta(weeks=nfl_week - 1)

    def first_week_after(self, season: int, when: datetime, final_week: int | None = None) -> int | None:
        """The first NFL week that starts after ``when``: the week a roster move made then counts from.

        None if the move came after the final week started. ``final_week`` defaults to the season's
        final scoring period from ESPN.
        """
        if when.tzinfo is None:
            raise ValueError("pass a timezone-aware datetime")
        final_week = final_week or load_settings(season).final_scoring_period
        for week in range(1, final_week + 1):
            if self.week_start(season, week) > when:
                return week
        return None


def _utc(v: str | datetime | date) -> datetime:
    if isinstance(v, datetime):
        return v.astimezone(UTC) if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=UTC)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(UTC)


@cache
def load_rules(path: Path = RULES_YML) -> LeagueRules:
    return LeagueRules(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
