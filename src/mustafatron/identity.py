"""Canonical manager identity: ESPN member IDs and names → one ``Manager`` per person.

All-time records are only trustworthy if a manager is one entity across every season. ESPN gets in
the way three ways, all handled here and nowhere else:

1. **One person, several accounts.** Ryan Richardson (2024-) and Jon Grudee (2026-) each co-own their
   team with a second ESPN account, so those seasons list more members than teams.
2. **Co-owned teams.** A team's manager is its ``primaryOwner``; any other owner who is a different
   person is a co-manager, never part of the key.
3. **Inconsistent names.** ESPN has ``"jon grudee"`` in lower case, and two managers are named
   Matthew. Display and short names come from ``data/manual/managers.yml``, not ESPN.
"""

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from mustafatron.espn.raw import RawSeason, RawTeam

MANAGERS_YML = Path(__file__).resolve().parents[2] / "data" / "manual" / "managers.yml"


class UnknownManagerError(LookupError):
    """An ESPN member ID or name that ``managers.yml`` does not know."""


@dataclass(frozen=True)
class Manager:
    id: str
    name: str
    short_name: str
    espn_ids: tuple[str, ...]
    first_season: int
    last_season: int | None  # None while still in the league
    aliases: tuple[str, ...] = field(default=())

    def active_in(self, season: int) -> bool:
        return self.first_season <= season and (self.last_season is None or season <= self.last_season)


def _parse_seasons(spec: str | int) -> tuple[int, int | None]:
    """``"2015-2025"`` → (2015, 2025); ``"2016-"`` → (2016, None); ``"2015"`` → (2015, 2015)."""
    first, dash, last = str(spec).partition("-")
    if not dash:
        return int(first), int(first)
    return int(first), int(last) if last.strip() else None


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


class Managers:
    """The league's managers, with lookups from ESPN IDs, ESPN teams and names."""

    def __init__(self, managers: list[Manager]):
        self.by_id: dict[str, Manager] = {}
        self._by_espn_id: dict[str, Manager] = {}
        self._by_name: dict[str, Manager] = {}
        for m in managers:
            if m.id in self.by_id:
                raise ValueError(f"duplicate manager id {m.id!r}")
            self.by_id[m.id] = m
            for espn_id in m.espn_ids:
                if espn_id in self._by_espn_id:
                    raise ValueError(
                        f"ESPN id {espn_id} listed under both {self._by_espn_id[espn_id].id} and {m.id}"
                    )
                self._by_espn_id[espn_id] = m
            for name in (m.name, *m.aliases):
                self._by_name[_norm(name)] = m

    def __iter__(self):
        return iter(self.by_id.values())

    def __len__(self) -> int:
        return len(self.by_id)

    def __getitem__(self, manager_id: str) -> Manager:
        return self.by_id[manager_id]

    def resolve(self, espn_id: str) -> Manager:
        """The manager behind an ESPN member ID (pseudonymized, as stored in ``data/raw/``)."""
        try:
            return self._by_espn_id[espn_id]
        except KeyError:
            raise UnknownManagerError(
                f"ESPN member {espn_id} is not in data/manual/managers.yml. If it is a new manager, add an "
                "entry; if it is a second account of an existing one, add it to their espn_ids."
            ) from None

    def by_name(self, name: str) -> Manager:
        """Look up by an ESPN-style full name, case-insensitively (for code that only has names)."""
        try:
            return self._by_name[_norm(name)]
        except KeyError:
            raise UnknownManagerError(f"no manager named {name!r} in data/manual/managers.yml") from None

    def team_manager(self, team: RawTeam) -> Manager:
        """A team's manager: whoever its ``primaryOwner`` is (falling back to its first owner)."""
        owner = team.get("primaryOwner") or (team.get("owners") or [None])[0]
        if owner is None:
            raise UnknownManagerError(f"team {team.get('id')} has no owner")
        return self.resolve(owner)

    def co_managers(self, team: RawTeam) -> list[Manager]:
        """Other people who co-own a team (second accounts of the manager do not count)."""
        primary = self.team_manager(team)
        out: list[Manager] = []
        for owner in team.get("owners", []):
            m = self.resolve(owner)
            if m != primary and m not in out:
                out.append(m)
        return out

    def season_managers(self, season: RawSeason) -> dict[int, Manager]:
        """ESPN team id → manager, for one season."""
        return {t["id"]: self.team_manager(t) for t in season["teams"]}

    def active_in(self, season: int) -> list[Manager]:
        return [m for m in self if m.active_in(season)]


def parse_managers(doc: dict) -> Managers:
    out = []
    for manager_id, entry in doc["managers"].items():
        first, last = _parse_seasons(entry["seasons"])
        out.append(
            Manager(
                id=manager_id,
                name=entry["name"],
                short_name=entry["short_name"],
                espn_ids=tuple(entry["espn_ids"]),
                first_season=first,
                last_season=last,
                aliases=tuple(entry.get("aliases", ())),
            )
        )
    return Managers(out)


@cache
def load_managers(path: Path = MANAGERS_YML) -> Managers:
    return parse_managers(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
