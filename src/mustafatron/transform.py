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
"""

from collections.abc import Iterable
from datetime import UTC, datetime

from mustafatron.espn.cache import MATCHUPS, SeasonCache, is_complete, latest_season
from mustafatron.espn.client import SeasonNotFoundError
from mustafatron.espn.raw import RawSeason, RawTeam
from mustafatron.identity import Managers, load_managers
from mustafatron.league_settings import load_settings
from mustafatron.model import DraftPick, Game, League, Season, TeamSeason, Transaction

FIRST_SEASON = 2015
DECIDED = ("HOME", "AWAY", "TIE")
TRANSACTION_TYPES = {"TRADE_ACCEPT": "TRADE", "WAIVER": "WAIVER", "FREEAGENT": "FREEAGENT"}


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
            )
        )
    return sorted(out, key=lambda g: (g.week, g.home_id))


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


def transactions(
    raw_transactions: Iterable[dict], season: int, team_managers: dict[int, str]
) -> list[Transaction]:
    """From ``mTransactions2`` ``transactions``: executed trades, waiver claims and free agent moves only."""
    out = []
    for t in raw_transactions:
        kind = TRANSACTION_TYPES.get(t.get("type", ""))
        if kind is None or t.get("status") != "EXECUTED":
            continue
        items = t.get("items", [])
        teams = sorted({i["toTeamId"] for i in items if i.get("toTeamId")} | {t["teamId"]})
        when = datetime.fromtimestamp((t.get("processDate") or t["proposedDate"]) / 1000, tz=UTC)
        for team in teams:
            players_in = tuple(i["playerId"] for i in items if i.get("toTeamId") == team)
            players_out = tuple(i["playerId"] for i in items if i.get("fromTeamId") == team)
            if not players_in and not players_out:
                continue
            out.append(
                Transaction(
                    season=season,
                    scoring_period=t.get("scoringPeriodId", 0),
                    date=when,
                    type=kind,
                    manager_id=team_managers[team],
                    players_in=players_in,
                    players_out=players_out,
                    bid=t.get("bidAmount", 0) if kind == "WAIVER" else 0,
                )
            )
    return sorted(out, key=lambda x: (x.date, x.manager_id))


def build_season(raw: RawSeason, season: int, managers: Managers) -> Season:
    return Season(
        season=season,
        settings=load_settings(season),
        teams=team_seasons(raw, season, managers),
        games=games(raw, season, managers),
    )


def load_league(
    seasons: Iterable[int] | None = None,
    *,
    cache: SeasonCache | None = None,
    managers: Managers | None = None,
) -> League:
    """The whole league, one ``Season`` per season that ESPN has.

    Finished seasons come from ``data/raw/`` (offline); a season in progress is fetched live, which
    needs ESPN cookies. Pass ``seasons=range(2015, 2026)`` to stay offline.
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
    return league
