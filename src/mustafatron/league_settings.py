"""League structure per season, read from ESPN's ``mSettings`` view instead of hardcoded.

ESPN is the source of truth for anything it knows: team count, lineup slots, regular season
length, playoff format, scoring. Rules ESPN does not model (payouts, keeper cost, analysis
thresholds) live in ``data/manual/league_rules.yml``.

Vocabulary, following ESPN:

- A **scoring period** is an NFL week (1-18).
- A **matchup period** is one head-to-head game slot. In the regular season it is one NFL week;
  playoff matchups here span two (``matchup_periods[15] == (16, 17)``). ``matchupPeriodId`` in
  ``schedule`` and the "week" everywhere in the hub are matchup periods.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache

from mustafatron.espn.cache import SETTINGS, SeasonCache

# ESPN lineupSlotCounts keys. Names match espn-api's, which the legacy code uses.
SLOT_NAMES = {
    0: "QB",
    1: "TQB",
    2: "RB",
    3: "RB/WR",
    4: "WR",
    5: "WR/TE",
    6: "TE",
    7: "OP",
    8: "DT",
    9: "DE",
    10: "LB",
    11: "DL",
    12: "CB",
    13: "S",
    14: "DB",
    15: "DP",
    16: "D/ST",
    17: "K",
    18: "P",
    19: "HC",
    20: "BE",
    21: "IR",
    23: "RB/WR/TE",
    24: "ER",
}
NON_STARTING_SLOTS = frozenset({"BE", "IR"})
RECEPTIONS_STAT_ID = 53


@dataclass(frozen=True)
class LeagueSettings:
    season: int
    name: str
    team_count: int
    division_count: int
    regular_season_matchups: int
    playoff_team_count: int
    playoff_matchup_length: int
    matchup_periods: dict[int, tuple[int, ...]]  # matchup period -> the NFL weeks it covers
    final_scoring_period: int
    lineup_slots: dict[str, int]  # every slot with a nonzero count, bench and IR included
    points_per_reception: float
    keeper_count: int
    draft_type: str
    draft_date: datetime | None
    trade_deadline: datetime | None
    playoff_seeding_tiebreak: str

    @property
    def final_matchup_period(self) -> int:
        return max(self.matchup_periods)

    @property
    def starter_slots(self) -> dict[str, int]:
        """Starting lineup shape, e.g. ``{"QB": 1, "RB": 2, ..., "RB/WR/TE": 1}``."""
        return {k: v for k, v in self.lineup_slots.items() if k not in NON_STARTING_SLOTS}

    @property
    def bench_slots(self) -> int:
        return self.lineup_slots.get("BE", 0)

    @property
    def playoff_matchup_periods(self) -> range:
        return range(self.regular_season_matchups + 1, self.final_matchup_period + 1)

    def is_playoffs(self, matchup_period: int) -> bool:
        return matchup_period > self.regular_season_matchups

    def scoring_periods(self, matchup_period: int) -> tuple[int, ...]:
        return self.matchup_periods[matchup_period]

    def matchup_period_of(self, scoring_period: int) -> int:
        """The matchup period an NFL week belongs to."""
        for mp, weeks in self.matchup_periods.items():
            if scoring_period in weeks:
                return mp
        raise ValueError(f"{self.season}: NFL week {scoring_period} is not in any matchup period")


def parse_settings(season: int, raw: dict) -> LeagueSettings:
    """Build ``LeagueSettings`` from a ``settings.json`` (the ``settings`` and ``status`` of mSettings)."""
    s, status = raw["settings"], raw.get("status", {})
    schedule = s["scheduleSettings"]
    matchup_periods = {int(k): tuple(v) for k, v in schedule["matchupPeriods"].items()}
    slots = {
        SLOT_NAMES.get(int(k), f"slot{k}"): n for k, n in s["rosterSettings"]["lineupSlotCounts"].items() if n
    }
    ppr = next(
        (i["points"] for i in s["scoringSettings"]["scoringItems"] if i["statId"] == RECEPTIONS_STAT_ID),
        0.0,
    )
    draft = s.get("draftSettings", {})
    return LeagueSettings(
        season=season,
        name=s.get("name", ""),
        team_count=s["size"],
        division_count=len(schedule.get("divisions", [])),
        regular_season_matchups=schedule["matchupPeriodCount"],
        playoff_team_count=schedule["playoffTeamCount"],
        playoff_matchup_length=schedule.get("playoffMatchupPeriodLength", 1),
        matchup_periods=dict(sorted(matchup_periods.items())),
        final_scoring_period=status.get("finalScoringPeriod")
        or max(max(w) for w in matchup_periods.values()),
        lineup_slots=slots,
        points_per_reception=float(ppr),
        keeper_count=draft.get("keeperCount", 0),
        draft_type=draft.get("type", ""),
        draft_date=_from_ms(draft.get("date")),
        trade_deadline=_from_ms(s.get("tradeSettings", {}).get("deadlineDate")),
        playoff_seeding_tiebreak=schedule.get("playoffSeedingRule", ""),
    )


def _from_ms(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None


@cache
def load_settings(season: int) -> LeagueSettings:
    """Settings for a season: from ``data/raw/`` when finished, from ESPN while in progress."""
    return parse_settings(season, SeasonCache().load(season, SETTINGS))
