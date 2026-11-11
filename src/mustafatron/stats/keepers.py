"""The keeper book: who was kept each season, and how the keepers played.

Who was kept comes from ``data/manual/keeper_history.yml`` (``mustafatron.keepers``). How a keeper
played is valued like any other pick on the draft page (``mustafatron.stats.draft``): his season
points minus the average drafted player at his position, against that draft's line at his slot. The
line is fit on non-keeper picks only, so keepers are measured against what a normal pick at the same
spot in the draft produced.

``run`` counts consecutive seasons kept by anyone, the count the 3-year limit uses: it follows a player
through a trade, and a season back in the draft resets it (league_rules.yml, ``keepers``).
"""

from collections import defaultdict

from mustafatron import contract as c
from mustafatron.keeper_engine import kept_in_a_row
from mustafatron.keepers import Keep, KeeperHistory
from mustafatron.model import League
from mustafatron.stats.draft import DraftLine, draft_line


def run_length(history: KeeperHistory, keep: Keep) -> int:
    """Consecutive seasons the player has been kept, ending with this keep, whoever kept him."""
    return kept_in_a_row(history, keep.player_id, keep.season) + 1


def _position(league: League, keep: Keep) -> str | None:
    for season in (keep.season, keep.season - 1):
        if season in league.seasons and keep.player_id in league.seasons[season].players:
            return league.seasons[season].players[keep.player_id].position
    return None


def keeper_book(league: League, history: KeeperHistory) -> c.KeepersFile:
    """The published seasons' keepers. A season the site does not publish (2026 in an offline build)
    is left out, like it is from every other page, so its managers need not be published either."""
    seasons = [s for s in history.seasons if s in league.seasons]
    keeps = [k for k in history.keeps if k.season in league.seasons]
    lines: dict[int, DraftLine | None] = {}
    keepers: list[c.KeeperOut] = []
    totals: dict[str, list[float]] = defaultdict(list)
    for keep in keeps:
        season = league.seasons[keep.season]
        pick = next((p for p in season.draft if p.keeper and p.player_id == keep.player_id), None)
        position = _position(league, keep)
        points = value = None
        if season.finished and pick is not None and position is not None:
            if keep.season not in lines:
                lines[keep.season] = draft_line(season)
            line = lines[keep.season]
            player = season.players.get(keep.player_id)
            if line is not None and player is not None:
                points = player.season_points or 0.0
                v = line.value(points, position, pick.overall_pick)
                value = None if v is None else round(v, 2)
                points = round(points, 2)
        if value is not None:
            totals[keep.manager_id].append(value)
        keepers.append(
            c.KeeperOut(
                season=keep.season,
                manager=keep.manager_id,
                player=keep.player,
                position=position,
                round=keep.round,
                overall_pick=pick.overall_pick if pick else None,
                via=keep.via,
                run=run_length(history, keep),
                points=points,
                value=value,
            )
        )

    keeps_by_manager: dict[str, int] = defaultdict(int)
    for keep in keeps:
        keeps_by_manager[keep.manager_id] += 1
    managers = [
        c.KeeperManagerOut(
            manager=m.id,
            keeps=keeps_by_manager[m.id],
            seasons=sum(m.active_in(s) for s in seasons),
            valued=len(totals[m.id]),
            value=round(sum(totals[m.id]), 2),
        )
        for m in league.managers
        if any(m.active_in(s) for s in seasons)
    ]
    managers.sort(key=lambda m: (-m.value, -m.keeps, m.manager))
    slots = max((s.settings.keeper_count for s in league.seasons.values()), default=0)
    return c.KeepersFile(seasons=seasons, slots=slots, keepers=keepers, managers=managers)
