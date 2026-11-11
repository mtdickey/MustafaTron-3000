"""Current rosters from ESPN (``mRoster``), for choosing keepers.

Keepers come off the rosters as they stand when they are chosen, which can differ from how the
season's committed data ends: managers pick players up after the last box score (the offseason
pickups in the 2025 and 2026 keeper sheets). ``mRoster`` without a scoring period is each team's
roster now, the same source the v1 keeper script read for those sheets.

Rosters are fetched live and never written to ``data/raw/``: they change until the draft.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from mustafatron.espn.client import EspnClient, View
from mustafatron.identity import Managers
from mustafatron.pseudonymize import find_swids, scrub_season

# A team's roster is its lineup slots plus bench and IR: 16 in this league. Anything far outside this
# range means the response isn't what we think it is.
MIN_ROSTER, MAX_ROSTER = 8, 30


class RosterFetchError(RuntimeError):
    """ESPN's rosters failed a sanity check, so they are not used."""


@dataclass(frozen=True)
class RosterEntry:
    player_id: int
    manager_id: str
    name: str
    position: str


def parse_rosters(raw: Mapping, managers: Managers) -> dict[int, RosterEntry]:
    """``mTeam`` + ``mRoster`` (already scrubbed of SWIDs) -> player id -> entry.

    Raises ``RosterFetchError`` unless every team resolves to a manager and has a plausible roster.
    """
    teams = raw.get("teams") or []
    if not teams:
        raise RosterFetchError("ESPN returned no teams")
    from mustafatron.transform import POSITIONS  # here, not at the top: transform imports espn.cache

    out: dict[int, RosterEntry] = {}
    for team in teams:
        manager = managers.team_manager(team).id
        entries = (team.get("roster") or {}).get("entries") or []
        if not MIN_ROSTER <= len(entries) <= MAX_ROSTER:
            raise RosterFetchError(f"team {team.get('id')} ({manager}) has {len(entries)} players")
        for e in entries:
            player = (e.get("playerPoolEntry") or {}).get("player") or {}
            pid = int(e["playerId"])
            if pid in out:
                raise RosterFetchError(f"player {pid} is on two rosters")
            out[pid] = RosterEntry(
                player_id=pid,
                manager_id=manager,
                name=player.get("fullName") or str(pid),
                position=POSITIONS.get(player.get("defaultPositionId", 0), "?"),
            )
    counts = Counter(e.manager_id for e in out.values())
    if len(counts) != len(teams):
        raise RosterFetchError(f"{len(teams)} teams but {len(counts)} managers")
    return out


def fetch_rosters(client: EspnClient, season: int, managers: Managers, key: bytes) -> dict[int, RosterEntry]:
    """Every team's roster now, for one season of the league."""
    raw = client.season(season, [View.TEAM, View.ROSTER])
    data = scrub_season({"teams": raw.get("teams", []), "members": raw.get("members", [])}, key)
    if find_swids(data):
        raise RosterFetchError("SWIDs survived pseudonymization")
    return parse_rosters(data, managers)


def compare(fetched: Mapping[int, str], season_end: Mapping[int, str]) -> dict[str, list[int]]:
    """How ESPN's current rosters differ from the season-end rosters in the committed data:
    players added since, dropped since, and moved to another team."""
    return {
        "added": sorted(p for p in fetched if p not in season_end),
        "dropped": sorted(p for p in season_end if p not in fetched),
        "moved": sorted(p for p in fetched if p in season_end and fetched[p] != season_end[p]),
    }
