"""The player-level datasets: drafts, weekly box scores, transactions and player stats.

Each is one committed file per season under ``data/raw/{season}/``, fetched through
``mustafatron.espn.cache`` like the team-level ones. Unlike those, the raw responses are big and
mostly irrelevant (every player object carries ownership trends, news, projections), so each is
**trimmed to the fields the hub uses**, keeping ESPN's field names. Trimming is also what keeps
SWIDs out: ``mDraftDetail`` picks carry the drafting member as a SWID *without* braces, which
``mustafatron.pseudonymize`` does not recognize, and they are simply not kept.

What ESPN serves differs by era (issue #26, ``data/README.md``):

- ``draft.json`` (``mDraftDetail``): every season.
- ``players.json`` (``kona_player_info``): every season. A league-scored season total for each
  player the other files mention, plus one line per NFL week from 2018.
- ``boxscores.json`` (``mBoxscore``) and ``transactions.json`` (``mTransactions2``): 2018 on only,
  and only one NFL week per request.

Weekly rosters (``mRoster``) are not a separate file: each box score already lists the team's whole
roster that week, bench and IR included, with the lineup slot each player was in.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mustafatron.espn.client import View

if TYPE_CHECKING:
    from mustafatron.espn.client import EspnClient

# The first season ESPN serves weekly box scores and transactions for.
WEEKLY_SINCE = 2018
# kona_player_info is asked about this many players at a time (the IDs travel in a header).
PLAYER_BATCH = 100

PICK_KEYS = (
    "id",
    "overallPickNumber",
    "roundId",
    "roundPickNumber",
    "teamId",
    "playerId",
    "keeper",
    "reservedForKeeper",
    "autoDraftTypeId",
)
# Executed adds and drops are kept as they are. Trades are messier: for most past trades ESPN no
# longer returns the executed record, only the bookkeeping around it, the acceptance (TRADE_ACCEPT,
# by the team receiving the offer), league votes (TRADE_UPHOLD) and vetoes (TRADE_VETO). Those are
# kept, plus any proposal one of them refers to, because they date the trades that
# ``mustafatron.transform`` finds by following players between rosters.
KEPT_MOVE_TYPES = frozenset({"WAIVER", "FREEAGENT"})
KEPT_TRADE_TYPES = frozenset({"TRADE_ACCEPT", "TRADE_UPHOLD", "TRADE_VETO"})
TRANSACTION_KEYS = (
    "id",
    "type",
    "status",
    "scoringPeriodId",
    "teamId",
    "proposedDate",
    "processDate",
    "bidAmount",
    "relatedTransactionId",
)
ITEM_KEYS = ("type", "playerId", "fromTeamId", "toTeamId")
KEPT_ITEM_TYPES = frozenset({"ADD", "DROP", "TRADE"})  # LINEUP items are lineup moves, not roster ones
PLAYER_KEYS = ("id", "fullName", "defaultPositionId", "eligibleSlots", "proTeamId")
ACTUAL = 0  # statSourceId: 0 actual, 1 projected
SEASON_SPLIT, WEEK_SPLIT = 0, 1  # statSplitTypeId


@dataclass(frozen=True)
class FetchContext:
    """What a dataset's fetch function gets from the cache."""

    client: "EspnClient"
    season: int
    finished: bool
    load: Callable[[str], dict]  # another dataset of the same season, by name ({} if unavailable)


def _pick(d: dict, keys: Iterable[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


def scoring_periods(ctx: FetchContext, first: int = 1) -> range:
    """The NFL weeks to fetch: the whole season once it is finished, the weeks so far while it isn't."""
    settings = ctx.load("settings")
    status = settings.get("status", {})
    matchup_periods = settings["settings"]["scheduleSettings"]["matchupPeriods"].values()
    final = status.get("finalScoringPeriod") or max(max(weeks) for weeks in matchup_periods)
    last = final if ctx.finished else min(final, status.get("latestScoringPeriod") or final)
    return range(first, last + 1)


def fetch_draft(ctx: FetchContext) -> dict:
    detail = ctx.client.season(ctx.season, [View.DRAFT_DETAIL]).get("draftDetail") or {}
    picks = sorted(detail.get("picks", []), key=lambda p: p["overallPickNumber"])
    return {
        "draftDetail": {
            **_pick(detail, ("drafted", "inProgress", "completeDate")),
            "picks": [_pick(p, PICK_KEYS) for p in picks],
        }
    }


def boxscore_period(raw: dict, period: int) -> dict:
    """One NFL week's rosters from an ``mBoxscore`` response: each team's players, slots and points."""
    teams = []
    for matchup in raw.get("schedule", []):
        for side in (matchup.get("home"), matchup.get("away")):
            roster = (side or {}).get("rosterForCurrentScoringPeriod")
            if roster is None:
                continue
            entries = [
                {
                    "playerId": e["playerId"],
                    "lineupSlotId": e["lineupSlotId"],
                    "points": round(float(e.get("playerPoolEntry", {}).get("appliedStatTotal", 0.0)), 2),
                }
                for e in roster.get("entries", [])
            ]
            entries.sort(key=lambda e: (e["lineupSlotId"], e["playerId"]))
            teams.append({"teamId": side["teamId"], "entries": entries})
    return {"scoringPeriodId": period, "teams": sorted(teams, key=lambda t: t["teamId"])}


def fetch_boxscores(ctx: FetchContext) -> dict:
    periods = []
    for period in scoring_periods(ctx):
        raw = ctx.client.season(ctx.season, [View.BOXSCORE, View.MATCHUP_SCORE], scoring_period=period)
        periods.append(boxscore_period(raw, period))
    return {"periods": periods}


def trim_transaction(t: dict) -> dict:
    items = [_pick(i, ITEM_KEYS) for i in t.get("items") or [] if i.get("type") in KEPT_ITEM_TYPES]
    return {**_pick(t, TRANSACTION_KEYS), "items": items}


def kept_transactions(transactions: Iterable[dict]) -> list[dict]:
    """Executed adds and drops, every trade record, and the proposals trade records refer to."""
    transactions = list(transactions)
    trade_refs = {t.get("relatedTransactionId") for t in transactions if t.get("type") in KEPT_TRADE_TYPES}
    return [
        t
        for t in transactions
        if (t.get("type") in KEPT_MOVE_TYPES and t.get("status") == "EXECUTED")
        or t.get("type") in KEPT_TRADE_TYPES
        or (t.get("type") == "TRADE_PROPOSAL" and t["id"] in trade_refs)
    ]


def fetch_transactions(ctx: FetchContext) -> dict:
    """Every executed add and drop, and the trade records. Week 0 holds moves made before week 1."""
    every: dict[str, dict] = {}
    for period in scoring_periods(ctx, first=0):
        raw = ctx.client.season(ctx.season, [View.TRANSACTIONS], scoring_period=period)
        every.update({t["id"]: t for t in raw.get("transactions") or []})
    found = {t["id"]: trim_transaction(t) for t in kept_transactions(every.values())}

    def when(t: dict) -> tuple:
        return (t.get("processDate") or t.get("proposedDate") or 0, t["id"])

    return {"transactions": sorted(found.values(), key=when)}


def mentioned_players(draft: dict, boxscores: dict, transactions: dict) -> list[int]:
    """Every player a season's draft, box scores or transactions refer to."""
    ids = {p["playerId"] for p in draft.get("draftDetail", {}).get("picks", [])}
    ids |= {e["playerId"] for p in boxscores.get("periods", []) for t in p["teams"] for e in t["entries"]}
    ids |= {i["playerId"] for t in transactions.get("transactions", []) for i in t["items"]}
    return sorted(ids)


def player_filter(ids: list[int], season: int, periods: int) -> dict[str, Any]:
    """``x-fantasy-filter`` for these players' season total ("00{season}") and per-week lines."""
    return {
        "players": {
            "filterIds": {"value": ids},
            "filterStatsForTopScoringPeriodIds": {"value": periods, "additionalValue": [f"00{season}"]},
        }
    }


def trim_player(player: dict, season: int) -> dict:
    """A player's identity and actual points: ``appliedTotalByScoringPeriod["0"]`` is the season total."""
    points = {}
    for s in player.get("stats", []):
        if s.get("statSourceId") != ACTUAL or s.get("seasonId", season) != season:
            continue
        split, period = s.get("statSplitTypeId"), s.get("scoringPeriodId", 0)
        if (split == SEASON_SPLIT and period == 0) or (split == WEEK_SPLIT and period > 0):
            points[str(period)] = round(float(s.get("appliedTotal", 0.0)), 2)
    by_period = dict(sorted(points.items(), key=lambda kv: int(kv[0])))
    return {**_pick(player, PLAYER_KEYS), "appliedTotalByScoringPeriod": by_period}


def fetch_players(ctx: FetchContext) -> dict:
    ids = mentioned_players(ctx.load("draft"), ctx.load("boxscores"), ctx.load("transactions"))
    periods = len(scoring_periods(ctx))
    players = []
    for start in range(0, len(ids), PLAYER_BATCH):
        batch = ids[start : start + PLAYER_BATCH]
        raw = ctx.client.season(
            ctx.season, [View.PLAYER_INFO], player_filter=player_filter(batch, ctx.season, periods)
        )
        players += [trim_player(p["player"], ctx.season) for p in raw.get("players", []) if "player" in p]
    return {"players": sorted(players, key=lambda p: p["id"])}
