"""Keeper eligibility and cost: who each manager can keep for a season's draft, and what it costs.

The rules are in ``data/manual/league_rules.yml`` (``keepers``, with worked examples); the record of
who was kept is ``data/manual/keeper_history.yml`` (``mustafatron.keepers``). For a season's draft:

- **Eligible** players are on the manager's roster when keepers are chosen, went in last season's
  draft (as a keeper or not) after ``eligible_after_round``, and haven't already been kept
  ``max_consecutive`` seasons in a row. The count follows a player through trades; a season back in
  the draft resets it.
- **Cost** is last season's round minus ``rounds_earlier``.
- **Collisions**: keepers costing the same round can't share it. ``assign_rounds`` gives each the
  latest free round at or before its cost, in the manager's order of preference.

Rosters are an input. ``end_of_season_rosters`` reads them from the committed data (each team's last
box score, then any later moves on file). A move made after that data was fetched, such as an
offseason pickup, isn't there; pass the rosters as of keeper time to account for it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from mustafatron.identity import Managers
from mustafatron.keepers import KeeperHistory
from mustafatron.model import League, Season
from mustafatron.rules import KeeperRules

UNDRAFTED = "undrafted"
EARLY_ROUND = "early_round"
MAX_SEASONS = "max_seasons"
REASONS = {
    UNDRAFTED: "Not drafted last season (a waiver or free agent pickup)",
    EARLY_ROUND: "Drafted in round {round} last season; keepers must come from round {min_round} or later",
    MAX_SEASONS: "Already kept {kept} seasons in a row",
}


class KeeperRulesError(ValueError):
    """A keeper choice the rules don't allow."""


@dataclass(frozen=True)
class KeeperOption:
    """One rostered player and whether his manager can keep him for ``season``'s draft."""

    season: int
    manager_id: str
    player_id: int
    last_round: int | None  # his round in last season's draft; None if undrafted
    last_overall: int | None
    kept_in_a_row: int  # seasons in a row he has been kept before ``season``, by anyone
    cost: int | None  # the round he would cost, before collisions; None if ineligible
    reason: str | None  # why he can't be kept (a key of REASONS); None if eligible

    @property
    def eligible(self) -> bool:
        return self.reason is None

    def explain(self, rules: KeeperRules) -> str | None:
        """The reason in words, for the site."""
        if self.reason is None:
            return None
        return REASONS[self.reason].format(
            round=self.last_round, min_round=rules.eligible_after_round + 1, kept=self.kept_in_a_row
        )


def kept_in_a_row(history: KeeperHistory, player_id: int, season: int) -> int:
    """Seasons in a row the player was kept, ending with the one before ``season``, whoever kept him."""
    kept = {k.season for k in history.of_player(player_id)}
    n = 0
    while season - 1 - n in kept:
        n += 1
    return n


def end_of_season_rosters(season: Season) -> dict[int, str]:
    """Player id -> manager when the season ended: each team's last box score, then later moves.

    Teams out of the playoffs stop having box scores early, so each team's own last week is used. A
    move dated after the final week (a waiver claim in week 19, say) still counts.
    """
    if not season.player_weeks:
        raise ValueError(f"{season.season} has no weekly rosters (ESPN keeps them from 2018)")
    last: dict[str, int] = {}
    for pw in season.player_weeks:
        last[pw.manager_id] = max(last.get(pw.manager_id, 0), pw.period)
    owner = {pw.player_id: pw.manager_id for pw in season.player_weeks if pw.period == last[pw.manager_id]}
    end = max(last.values())
    for t in sorted(season.transactions, key=lambda t: t.scoring_period):
        if t.scoring_period <= end:
            continue
        for pid in t.players_out:
            if owner.get(pid) == t.manager_id:
                del owner[pid]
        for pid in t.players_in:
            owner[pid] = t.manager_id
    return owner


def carry_over(rosters: Mapping[int, str], managers: Managers, season: int) -> dict[int, str]:
    """Rosters handed to ``season``'s managers: a team a new manager took over is now his."""
    successor = {m.took_over: m.id for m in managers if m.took_over and m.first_season == season}
    return {pid: successor.get(mid, mid) for pid, mid in rosters.items()}


def keeper_options(
    league: League,
    history: KeeperHistory,
    rules: KeeperRules,
    season: int,
    rosters: Mapping[int, str] | None = None,
) -> list[KeeperOption]:
    """Every rostered player's keeper status for ``season``'s draft, by manager then cost.

    ``rosters`` (player id -> manager, as of keeper time) defaults to how last season ended.
    """
    last = league.seasons[season - 1]
    if rosters is None:
        rosters = end_of_season_rosters(last)
    rosters = carry_over(rosters, league.managers, season)
    picks = {p.player_id: p for p in last.draft}
    out = []
    for player_id, manager_id in rosters.items():
        pick = picks.get(player_id)
        in_a_row = kept_in_a_row(history, player_id, season)
        if pick is None:
            reason = UNDRAFTED
        elif pick.round <= rules.eligible_after_round:
            reason = EARLY_ROUND
        elif in_a_row >= rules.max_consecutive:
            reason = MAX_SEASONS
        else:
            reason = None
        out.append(
            KeeperOption(
                season=season,
                manager_id=manager_id,
                player_id=player_id,
                last_round=pick.round if pick else None,
                last_overall=pick.overall_pick if pick else None,
                kept_in_a_row=in_a_row,
                cost=rules.cost(pick.round) if reason is None else None,
                reason=reason,
            )
        )
    out.sort(key=lambda o: (o.manager_id, o.cost is None, o.cost or 0, o.last_overall or 0, o.player_id))
    return out


def default_order(options: Iterable[KeeperOption]) -> list[KeeperOption]:
    """A manager's keepers in the default order of preference for collisions: latest cost first, and
    within a round, the later pick last season first. That is how the league's one collision so far
    went (2024: Zay Flowers, the later 2023 pick, kept round 8; George Pickens moved to round 7)."""
    return sorted(options, key=lambda o: (-(o.cost or 0), -(o.last_overall or 0)))


def assign_rounds(costs: Sequence[int]) -> list[int]:
    """The rounds a manager's keepers take, given their costs in his order of preference.

    Each keeper takes the latest round at or before his cost that an earlier one hasn't taken. So
    keepers that don't collide keep their costs, two from one round take it and the round before,
    and a keeper pushed into a round another one costs pushes that one further (a cascade).
    """
    taken: set[int] = set()
    out = []
    for cost in costs:
        r = cost
        while r in taken:
            r -= 1
        if r < 1:
            raise KeeperRulesError(f"no round left for a keeper costing round {cost}")
        taken.add(r)
        out.append(r)
    return out


def choose(
    options: Sequence[KeeperOption], rules: KeeperRules, slots: int, order: Sequence[int] | None = None
) -> dict[int, int]:
    """Validate one manager's keepers and resolve collisions: player id -> round forfeited.

    ``options`` are the chosen players' options. ``order`` lists their player ids in the manager's
    order of preference for collisions (the first keeps his round); ``default_order`` if omitted.
    """
    if len({o.manager_id for o in options}) > 1:
        raise KeeperRulesError("keepers from more than one manager")
    if len(options) > slots:
        raise KeeperRulesError(f"{len(options)} keepers chosen; the limit is {slots}")
    for o in options:
        if not o.eligible:
            raise KeeperRulesError(f"player {o.player_id} can't be kept: {o.explain(rules)}")
    by_id = {o.player_id: o for o in options}
    if order is None:
        ranked = default_order(options)
    else:
        if sorted(order) != sorted(by_id):
            raise KeeperRulesError("the order must list each chosen keeper once")
        ranked = [by_id[pid] for pid in order]
    rounds = assign_rounds([o.cost for o in ranked])
    return {o.player_id: r for o, r in zip(ranked, rounds, strict=True)}
