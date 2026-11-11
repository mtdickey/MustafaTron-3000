"""Keeper history: who each manager kept, by season, from ``data/manual/keeper_history.yml``.

ESPN flags keeper picks only from 2024, when the league started keeping players. The file holds
every season since then; tests/test_keepers.py checks it against ESPN's flags for every finished
season. This module only records what happened. Eligibility and cost (how many years a player has
been kept, what he costs next) are the keeper engine's job, issue #42, once the rules in #40 settle.
"""

from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from mustafatron.identity import Managers, load_managers

KEEPER_HISTORY_YML = Path(__file__).resolve().parents[2] / "data" / "manual" / "keeper_history.yml"


class KeeperHistoryError(ValueError):
    """``keeper_history.yml`` contradicts itself or ``managers.yml``."""


@dataclass(frozen=True)
class Keep:
    """One player kept by one manager for one season's draft."""

    season: int
    manager_id: str
    player_id: int
    player: str
    round: int  # the draft round the keeper took
    via: str | None = None  # manager who traded the keeper rights in the offseason
    note: str | None = None


class KeeperHistory:
    def __init__(self, keeps: list[Keep]):
        self.keeps = sorted(keeps, key=lambda k: (k.season, k.manager_id, k.round))

    @property
    def seasons(self) -> list[int]:
        return sorted({k.season for k in self.keeps})

    def in_season(self, season: int) -> list[Keep]:
        return [k for k in self.keeps if k.season == season]

    def by_manager(self, season: int) -> dict[str, list[Keep]]:
        out: dict[str, list[Keep]] = {}
        for k in self.in_season(season):
            out.setdefault(k.manager_id, []).append(k)
        return out

    def of_player(self, player_id: int) -> list[Keep]:
        """Every season the player was kept, oldest first, whoever kept him."""
        return [k for k in self.keeps if k.player_id == player_id]

    def kept_before(self, player_id: int, season: int) -> list[Keep]:
        """The player's keeps in seasons before ``season``: the raw input to "times kept"."""
        return [k for k in self.of_player(player_id) if k.season < season]


def parse_keeper_history(doc: dict[str, Any], managers: Managers) -> KeeperHistory:
    keeps: list[Keep] = []
    for season, by_manager in (doc.get("seasons") or {}).items():
        season = int(season)
        for manager_id, entries in (by_manager or {}).items():
            for e in entries or []:
                keeps.append(
                    Keep(
                        season=season,
                        manager_id=manager_id,
                        player_id=int(e["player_id"]),
                        player=str(e["player"]),
                        round=int(e["round"]),
                        via=e.get("via"),
                        note=e.get("note"),
                    )
                )
    _validate(keeps, managers)
    return KeeperHistory(keeps)


def _validate(keeps: list[Keep], managers: Managers) -> None:
    problems: list[str] = []
    known = {m.id for m in managers}
    for k in keeps:
        where = f"{k.season} {k.manager_id} {k.player}"
        for role, mid in (("manager", k.manager_id), ("via", k.via)):
            if mid is None:
                continue
            if mid not in known:
                problems.append(f"{where}: unknown {role} {mid!r} (not in managers.yml)")
            elif not managers[mid].active_in(k.season - 1 if role == "via" else k.season):
                problems.append(f"{where}: {role} {mid!r} was not in the league then")
        if k.via == k.manager_id:
            problems.append(f"{where}: via is the keeper's own manager")
        if k.round < 1:
            problems.append(f"{where}: round {k.round}")
    for (season, pid), n in Counter((k.season, k.player_id) for k in keeps).items():
        if n > 1:
            problems.append(f"{season}: player {pid} kept {n} times")
    for (season, mid, rnd), n in Counter((k.season, k.manager_id, k.round) for k in keeps).items():
        if n > 1:
            problems.append(f"{season} {mid}: {n} keepers in round {rnd}; a collision moves one earlier")
    if problems:
        raise KeeperHistoryError("data/manual/keeper_history.yml:\n  " + "\n  ".join(problems))


@cache
def load_keeper_history(path: Path = KEEPER_HISTORY_YML) -> KeeperHistory:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse_keeper_history(doc, load_managers())
