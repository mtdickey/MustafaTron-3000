"""Raw ESPN season JSON → the entities in ``mustafatron.model``.

This is the only layer that knows how ESPN's responses differ across eras, so stats code never
has to. The differences handled here:

- **Endpoint shape.** ``leagueHistory`` (before 2018) wraps the season in a list; the client
  unwraps it, so by the time JSON reaches this module both eras are one season object.
- **Team names.** Most responses send ``name``; some send ``location`` + ``nickname`` instead.
- **Scores.** Older seasons have whole-number scores (and ties); they become floats.
- **Results.** ESPN's ``winner`` decides, not the scores: playoff ties are broken by ESPN.
- **Final rank.** ``rankFinal`` is 0 for every team in this league; ``rankCalculatedFinal`` is
  the real finish. Neither is trusted until the season is finished.
- **Byes.** A matchup with no ``away`` side is a bye and is not a game (none occur 2015-2025).
- **Owners.** Teams are keyed by canonical manager via ``mustafatron.identity``, never by ESPN ID.
- **Player data by era.** Drafts and player season totals exist for every season; weekly rosters
  and transactions only from 2018 (``data/README.md``). A missing file loads as nothing.
- **Trades.** Executed player-card records supply the actual packages from 2019.
  Only 2018 falls back to following ownership through weekly rosters (:func:`infer_trades`).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from mustafatron.espn.cache import (
    BOXSCORES,
    DRAFT,
    MATCHUPS,
    PLAYERS,
    TRANSACTIONS,
    SeasonCache,
    is_complete,
    latest_season,
)
from mustafatron.espn.client import SeasonNotFoundError
from mustafatron.espn.player_data import EXECUTED_TRADES_SINCE
from mustafatron.espn.raw import RawSeason, RawTeam
from mustafatron.identity import Managers, load_managers
from mustafatron.league_settings import SLOT_NAMES, LeagueSettings, load_settings
from mustafatron.model import DraftPick, Game, League, Player, PlayerWeek, Season, TeamSeason, Transaction

FIRST_SEASON = 2015
DECIDED = ("HOME", "AWAY", "TIE")
MOVE_TYPES = ("WAIVER", "FREEAGENT")  # executed adds and drops; trades are parsed separately
EPOCH = datetime.fromtimestamp(0, tz=UTC)
# ESPN defaultPositionId. Names match espn-api's POSITION_MAP.
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 7: "P", 9: "DT", 10: "DE", 11: "LB", 12: "CB",
             13: "S", 14: "HC", 16: "D/ST"}  # fmt: skip


def team_name(team: RawTeam) -> str:
    name = team.get("name") or f"{team.get('location', '')} {team.get('nickname', '')}"
    return " ".join(name.split())


def team_seasons(raw: RawSeason, season: int, managers: Managers) -> list[TeamSeason]:
    finished = is_complete(raw)  # type: ignore[arg-type]
    out = []
    for t in raw["teams"]:
        overall = t.get("record", {}).get("overall", {})
        counter = t.get("transactionCounter", {})
        rank = t.get("rankFinal") or t.get("rankCalculatedFinal") or None
        out.append(
            TeamSeason(
                season=season,
                manager_id=managers.team_manager(t).id,
                team_id=t["id"],
                name=team_name(t),
                abbrev=t.get("abbrev", ""),
                wins=overall.get("wins", 0),
                losses=overall.get("losses", 0),
                ties=overall.get("ties", 0),
                points_for=round(float(overall.get("pointsFor", 0.0)), 2),
                points_against=round(float(overall.get("pointsAgainst", 0.0)), 2),
                playoff_seed=t.get("playoffSeed", 0),
                final_rank=rank if finished else None,
                acquisitions=counter.get("acquisitions", 0),
                trades=counter.get("trades", 0),
                co_manager_ids=tuple(m.id for m in managers.co_managers(t)),
            )
        )
    return sorted(out, key=lambda t: (t.final_rank or 99, t.playoff_seed))


def games(raw: RawSeason, season: int, managers: Managers) -> list[Game]:
    by_team = managers.season_managers(raw)
    out = []
    for m in raw["schedule"]:
        if "away" not in m:  # bye
            continue
        home, away = m["home"], m["away"]
        home_id, away_id = by_team[home["teamId"]].id, by_team[away["teamId"]].id
        winner = m.get("winner")
        out.append(
            Game(
                season=season,
                week=m["matchupPeriodId"],
                tier=m.get("playoffTierType", "NONE"),
                home_id=home_id,
                away_id=away_id,
                home_score=round(float(home.get("totalPoints", 0.0)), 2),
                away_score=round(float(away.get("totalPoints", 0.0)), 2),
                final=winner in DECIDED,
                winner_id=home_id if winner == "HOME" else away_id if winner == "AWAY" else None,
                period_scores=period_scores(home, away),
            )
        )
    return sorted(out, key=lambda g: (g.week, g.home_id))


def period_scores(home: dict, away: dict) -> tuple[tuple[int, float, float], ...]:
    """Per-NFL-week points from ``pointsByScoringPeriod``, the breakdown of a multi-week matchup."""
    h, a = home.get("pointsByScoringPeriod") or {}, away.get("pointsByScoringPeriod") or {}
    weeks = sorted({int(w) for w in h} | {int(w) for w in a})
    return tuple((w, round(float(h.get(str(w), 0.0)), 2), round(float(a.get(str(w), 0.0)), 2)) for w in weeks)


def draft_picks(draft_detail: dict, season: int, team_managers: dict[int, str]) -> list[DraftPick]:
    """From an ``mDraftDetail`` ``draftDetail``. Picks are attributed by ``teamId``, never ``memberId``."""
    return [
        DraftPick(
            season=season,
            round=p["roundId"],
            round_pick=p["roundPickNumber"],
            overall_pick=p["overallPickNumber"],
            player_id=p["playerId"],
            manager_id=team_managers[p["teamId"]],
            keeper=bool(p.get("keeper") or p.get("reservedForKeeper")),
        )
        for p in sorted(draft_detail.get("picks", []), key=lambda p: p["overallPickNumber"])
    ]


def _when(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None


def transactions(
    raw_transactions: Iterable[dict], season: int, team_managers: dict[int, str]
) -> list[Transaction]:
    """Executed adds and drops (waiver claims and free agent moves) from ``transactions.json``.

    Trades are parsed separately by :func:`executed_trades` (2018 uses :func:`infer_trades`).
    """
    out = []
    for t in raw_transactions:
        if t.get("type") not in MOVE_TYPES or t.get("status") != "EXECUTED":
            continue
        items = t.get("items") or []
        # Free agency is team 0 (-1 in 2018); waivers ESPN runs itself have teamId -2147483648.
        teams = sorted(
            team for team in {i.get("toTeamId", 0) for i in items} | {t.get("teamId", 0)} if team > 0
        )
        for team in teams:
            players_in = tuple(i["playerId"] for i in items if i.get("toTeamId") == team)
            players_out = tuple(i["playerId"] for i in items if i.get("fromTeamId") == team)
            if not players_in and not players_out:
                continue
            out.append(
                Transaction(
                    season=season,
                    scoring_period=t.get("scoringPeriodId", 0),
                    date=_when(t.get("processDate") or t.get("proposedDate")),
                    type=t["type"],
                    manager_id=team_managers[team],
                    players_in=players_in,
                    players_out=players_out,
                    bid=t.get("bidAmount", 0) if t["type"] == "WAIVER" else 0,
                    id=t.get("id", ""),
                )
            )
    return sorted(out, key=lambda x: (x.date or EPOCH, x.manager_id))


def executed_trades(
    raw_transactions: Iterable[dict], season: int, team_managers: dict[int, str]
) -> list[Transaction]:
    """Actual executed packages, preserving multiple trades between a pair within one week."""
    records = {}
    for t in raw_transactions:
        if t.get("type") in {"TRADE", "TRADE_ACCEPT"} and t.get("status") == "EXECUTED":
            records[t.get("relatedTransactionId") or t["id"]] = t
    out = []
    for root, t in records.items():
        items = [i for i in t.get("items") or [] if i.get("type") == "TRADE"]
        teams = {i["fromTeamId"] for i in items} | {i["toTeamId"] for i in items}
        if len(teams) != 2 or not teams <= team_managers.keys():
            raise ValueError(f"{season} trade {root}: incomplete or unsupported trade package")
        for team in sorted(teams):
            received = tuple(sorted(i["playerId"] for i in items if i["toTeamId"] == team))
            sent = tuple(sorted(i["playerId"] for i in items if i["fromTeamId"] == team))
            if not received or not sent:
                raise ValueError(f"{season} trade {root}: missing players on one side")
            out.append(
                Transaction(
                    season=season,
                    scoring_period=t["scoringPeriodId"],
                    date=_when(t.get("processDate") or t.get("proposedDate")),
                    type="TRADE",
                    manager_id=team_managers[team],
                    players_in=received,
                    players_out=sent,
                    id=f"{season}-{root}",
                )
            )
    return sorted(out, key=lambda t: (t.scoring_period, t.date or EPOCH, t.id, t.manager_id))


def infer_trades(
    picks: Iterable[dict],
    periods: Iterable[dict],
    raw_transactions: Iterable[dict],
    season: int,
    team_managers: dict[int, str],
) -> list[Transaction]:
    """Trades, found by following every player from roster to roster.

    A player's holder starts as the team that drafted him and changes with each executed add (to the
    adding team) and drop (to nobody). A player who turns up on a team's weekly roster while another
    team still holds him can only have been traded there. Moves between the same two teams in the
    same NFL week are one trade, attributed to that week: the first the players were on their new
    rosters, which is also the first week the trade could change a lineup.

    ``picks``, ``periods`` and ``raw_transactions`` are the ``draft.json``, ``boxscores.json`` and
    ``transactions.json`` lists. The tests check the result against ESPN's per-team trade counts.
    """
    raw_transactions = list(raw_transactions)
    # Per player: (week, order, time, team or None, on a roster). Drafted first, then within a week
    # adds and drops in time order, then the weekly roster.
    events: dict[int, list[tuple]] = defaultdict(list)
    for p in picks:
        events[p["playerId"]].append((0, 0, 0, p["teamId"], False))
    for t in raw_transactions:
        if t.get("type") not in MOVE_TYPES or t.get("status") != "EXECUTED":
            continue
        week, when = t.get("scoringPeriodId", 0), t.get("processDate") or t.get("proposedDate") or 0
        for i in t.get("items") or []:
            if i["type"] == "ADD":
                events[i["playerId"]].append((week, 1, when, i["toTeamId"], False))
            elif i["type"] == "DROP":
                events[i["playerId"]].append((week, 1, when, None, False))
    for period in periods:
        for team in period["teams"]:
            for e in team["entries"]:
                events[e["playerId"]].append((period["scoringPeriodId"], 2, 0, team["teamId"], True))

    moved: dict[tuple[int, int, int], list[int]] = defaultdict(list)  # (week, from, to) -> players
    for player, timeline in events.items():
        holder = None
        for week, _, _, team, on_roster in sorted(timeline, key=lambda e: e[:3]):
            if on_roster and holder is not None and holder != team:
                moved[(week, holder, team)].append(player)
            holder = team

    # (week, the two teams) -> team -> (players in, players out)
    trades: dict[tuple[int, frozenset[int]], dict[int, tuple[list[int], list[int]]]] = {}
    for (week, src, dst), moved_players in sorted(moved.items()):
        sides = trades.setdefault((week, frozenset((src, dst))), {src: ([], []), dst: ([], [])})
        sides[dst][0].extend(moved_players)
        sides[src][1].extend(moved_players)

    out = []
    used: set[str] = set()  # acceptance records already matched to a trade
    for (week, pair), sides in trades.items():
        a, b = sorted(pair)
        date = _trade_date(raw_transactions, week, pair, used)
        for team, (players_in, players_out) in sorted(sides.items()):
            out.append(
                Transaction(
                    season=season,
                    scoring_period=week,
                    date=date,
                    type="TRADE",
                    manager_id=team_managers[team],
                    players_in=tuple(sorted(players_in)),
                    players_out=tuple(sorted(players_out)),
                    id=f"{season}-w{week}-t{a}-t{b}",
                )
            )
    return sorted(out, key=lambda x: (x.scoring_period, x.id, x.manager_id))


def _trade_date(
    raw_transactions: list[dict], week: int, pair: frozenset[int], used: set[str]
) -> datetime | None:
    """When the trade was accepted, if exactly one unused acceptance record can be this trade.

    Acceptances are made by one of the two teams, in the trade's week or the one before (a trade
    accepted late in a week shows on the rosters the next). A same-week match is preferred.
    """
    proposals = {t["id"]: t for t in raw_transactions if t.get("type") == "TRADE_PROPOSAL"}
    vetoed = {t.get("relatedTransactionId") for t in raw_transactions if t.get("type") == "TRADE_VETO"}
    for accepted_in in (week, week - 1):
        candidates: dict[str, list[dict]] = defaultdict(list)
        for t in raw_transactions:
            if t.get("type") != "TRADE_ACCEPT" or t.get("teamId") not in pair:
                continue
            root = t.get("relatedTransactionId") or t["id"]
            if t.get("scoringPeriodId") != accepted_in or root in vetoed or root in used:
                continue
            proposal = proposals.get(root)
            if proposal is not None:  # the proposal names both teams: it must be these two
                teams = {i.get("fromTeamId") for i in proposal.get("items") or []} - {0, None}
                if teams and teams != set(pair):
                    continue
            candidates[root].append(t)
        if len(candidates) == 1:
            ((root, records),) = candidates.items()
            used.add(root)
            return _when(min(t.get("processDate") or t.get("proposedDate") or 0 for t in records))
        if candidates:  # ambiguous: leave it undated rather than guess
            return None
    return None


def players(raw_players: Iterable[dict]) -> dict[int, Player]:
    """From ``players.json``: identity plus points by NFL week, week ``"0"`` being the season total."""
    out = {}
    for p in raw_players:
        points = {int(k): v for k, v in p.get("appliedTotalByScoringPeriod", {}).items()}
        out[p["id"]] = Player(
            id=p["id"],
            name=p.get("fullName", str(p["id"])),
            position=POSITIONS.get(p.get("defaultPositionId", 0), "?"),
            eligible_slots=tuple(SLOT_NAMES.get(s, f"slot{s}") for s in p.get("eligibleSlots", [])),
            season_points=points.pop(0, None),
            weekly_points=points,
        )
    return out


def player_weeks(periods: Iterable[dict], season: int, team_managers: dict[int, str]) -> list[PlayerWeek]:
    """From ``boxscores.json``: every rostered player, every NFL week, with his lineup slot and points."""
    return [
        PlayerWeek(
            season=season,
            period=p["scoringPeriodId"],
            manager_id=team_managers[t["teamId"]],
            player_id=e["playerId"],
            slot=SLOT_NAMES.get(e["lineupSlotId"], f"slot{e['lineupSlotId']}"),
            points=e["points"],
        )
        for p in periods
        for t in p["teams"]
        for e in t["entries"]
    ]


def add_player_data(season: Season, raw: RawSeason, cache: SeasonCache, managers: Managers) -> None:
    """Fill a season's player-level fields from its draft, box score, transaction and player files."""
    team_managers = {team_id: m.id for team_id, m in managers.season_managers(raw).items()}
    picks = cache.load(season.season, DRAFT).get("draftDetail", {}).get("picks", [])
    periods = cache.load(season.season, BOXSCORES).get("periods", [])
    raw_tx = cache.load(season.season, TRANSACTIONS).get("transactions", [])
    season.draft = draft_picks({"picks": picks}, season.season, team_managers)
    season.players = players(cache.load(season.season, PLAYERS).get("players", []))
    season.player_weeks = player_weeks(periods, season.season, team_managers)
    if periods:  # without weekly rosters there is nothing to follow trades through
        moves = transactions(raw_tx, season.season, team_managers)
        if season.season >= EXECUTED_TRADES_SINCE:
            trades = executed_trades(raw_tx, season.season, team_managers)
            counts = Counter(t.manager_id for t in trades)
            if any(counts[t.manager_id] != t.trades for t in season.teams):
                raise ValueError(
                    f"{season.season}: executed trade counts do not match ESPN; refresh transactions"
                )
        else:
            trades = infer_trades(picks, periods, raw_tx, season.season, team_managers)
        season.transactions = sorted(
            moves + trades, key=lambda t: (t.scoring_period, t.date or EPOCH, t.id, t.manager_id)
        )


def build_season(
    raw: RawSeason, season: int, managers: Managers, settings: LeagueSettings | None = None
) -> Season:
    return Season(
        season=season,
        settings=settings or load_settings(season),
        teams=team_seasons(raw, season, managers),
        games=games(raw, season, managers),
    )


def load_league(
    seasons: Iterable[int] | None = None,
    *,
    cache: SeasonCache | None = None,
    managers: Managers | None = None,
    player_data: bool = False,
) -> League:
    """The whole league, one ``Season`` per season that ESPN has.

    Finished seasons come from ``data/raw/`` (offline); a season in progress is fetched live, which
    needs ESPN cookies. Pass ``seasons=range(2015, 2026)`` to stay offline. ``player_data`` also
    loads drafts, players, weekly rosters and transactions (see ``mustafatron.model.Season``).
    """
    cache = cache or SeasonCache()
    managers = managers or load_managers()
    league = League(managers)
    for season in seasons if seasons is not None else range(FIRST_SEASON, latest_season() + 1):
        try:
            raw = cache.load(season, MATCHUPS)
        except SeasonNotFoundError:
            continue
        if raw.get("schedule"):
            league.seasons[season] = build_season(raw, season, managers)  # type: ignore[arg-type]
            if player_data:
                add_player_data(league.seasons[season], raw, cache, managers)  # type: ignore[arg-type]
    return league
