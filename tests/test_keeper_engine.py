"""The keeper engine: the rules in league_rules.yml, their worked examples, and the commissioner's sheets."""

import csv
from pathlib import Path

import pytest

from mustafatron.keeper_engine import (
    EARLY_ROUND,
    MAX_SEASONS,
    UNDRAFTED,
    KeeperOption,
    KeeperRulesError,
    assign_rounds,
    choose,
    default_order,
    end_of_season_rosters,
    keeper_options,
    kept_in_a_row,
)
from mustafatron.keepers import load_keeper_history
from mustafatron.rules import load_rules

HISTORY = load_keeper_history()
RULES = load_rules()
SHEETS = Path(__file__).parent / "fixtures" / "keeper_sheets"

COLLINS, JACKSON, LONDON, FLOWERS, PICKENS = 4258173, 3916387, 4426502, 4429615, 4426354


@pytest.fixture(scope="module")
def options(player_league):
    """Every season's options computed from the season before, keyed by (season, player id)."""
    out = {}
    for season in (2024, 2025, 2026):
        for o in keeper_options(player_league, HISTORY, RULES.keepers(season), season):
            out[(season, o.player_id)] = o
    return out


def test_rules_from_the_yml():
    assert RULES.keepers(2023) is None
    k = RULES.keepers(2026)
    assert (k.eligible_after_round, k.rounds_earlier, k.max_consecutive) == (3, 1, 3)
    assert k.cost(10) == 9


# The worked examples in league_rules.yml ----------------------------------------------------------


def test_collins_three_straight_seasons(options):
    assert [options[(s, COLLINS)].cost for s in (2024, 2025, 2026)] == [13, 12, 11]
    assert kept_in_a_row(HISTORY, COLLINS, 2027) == 3  # 2024-2026: no 2027 keep


def test_lamar_jackson_reaches_round_three_and_stops(options):
    assert options[(2024, JACKSON)].cost == 4
    assert options[(2025, JACKSON)].cost == 3  # round 3 is the earliest a keeper can cost
    assert options[(2026, JACKSON)].reason == EARLY_ROUND  # his 2025 round was 3
    assert options[(2026, JACKSON)].last_round == 3


def test_the_count_follows_a_traded_player():
    """Drake London: kept by Jon in 2024 and 2025, by Dylan in 2026 after a trade of his keeper rights."""
    assert [(k.season, k.manager_id) for k in HISTORY.of_player(LONDON)] == [
        (2024, "grudee"),
        (2025, "grudee"),
        (2026, "edwards"),
    ]
    assert kept_in_a_row(HISTORY, LONDON, 2026) == 2
    assert kept_in_a_row(HISTORY, LONDON, 2027) == 3  # >= max_consecutive: nobody can keep him


def test_a_season_back_in_the_draft_resets_the_count(options):
    """Zay Flowers: kept in 2024, back in the 2025 draft, kept in 2026 as a first-year keeper."""
    assert kept_in_a_row(HISTORY, FLOWERS, 2026) == 0
    assert options[(2026, FLOWERS)].eligible and options[(2026, FLOWERS)].cost == 5
    assert kept_in_a_row(HISTORY, FLOWERS, 2027) == 1


def test_pickens_and_flowers_collision(options):
    """Both from 2023's round 9 (cost 8). The default order is what happened: Flowers stayed in 8."""
    mine = [options[(2024, p)] for p in (PICKENS, FLOWERS, 4385690)]  # plus Dalton Kincaid, round 14
    rounds = choose(mine, RULES.keepers(2024), slots=3)
    assert rounds == {FLOWERS: 8, PICKENS: 7, 4385690: 14}
    assert {(k.player_id, k.round) for k in HISTORY.in_season(2024) if k.manager_id == "edwards"} == set(
        rounds.items()
    )
    # The manager's choice: put Pickens first and Flowers moves instead.
    assert choose(mine, RULES.keepers(2024), slots=3, order=[PICKENS, FLOWERS, 4385690])[FLOWERS] == 7


def test_max_seasons_reason():
    o = KeeperOption(2027, "edwards", LONDON, 5, 45, 3, None, MAX_SEASONS)
    assert o.explain(RULES.keepers(2027)) == "Already kept 3 seasons in a row"


# Collisions -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("costs", "rounds"),
    [
        ([9, 6, 12], [9, 6, 12]),  # no collision: everyone keeps his cost
        ([8, 8], [8, 7]),  # two from one round take it and the one before
        ([8, 8, 8], [8, 7, 6]),  # three take it and the two before
        ([7, 7, 6], [7, 6, 5]),  # the second 7 lands on 6 and pushes the 6 to 5 (a cascade)
        ([7, 6, 7], [7, 6, 5]),  # same keepers, the 6 preferred: the second 7 jumps past it
        ([4, 4, 3], [4, 3, 2]),  # a collision can push a keeper ahead of round 3
        ([3, 3, 3], [3, 2, 1]),
    ],
)
def test_assign_rounds(costs, rounds):
    assert assign_rounds(costs) == rounds


def test_assign_rounds_runs_out():
    with pytest.raises(KeeperRulesError, match="no round left"):
        assign_rounds([1, 1])


def test_choose_rejects_bad_choices(options):
    rules = RULES.keepers(2026)
    mine = [o for (s, _), o in options.items() if s == 2026 and o.manager_id == "joyce"]
    eligible = [o for o in mine if o.eligible]
    with pytest.raises(KeeperRulesError, match="limit is 3"):
        choose(eligible[:4], rules, slots=3)
    with pytest.raises(KeeperRulesError, match="can't be kept"):
        choose([next(o for o in mine if not o.eligible)], rules, slots=3)
    with pytest.raises(KeeperRulesError, match="each chosen keeper once"):
        choose(eligible[:2], rules, slots=3, order=[eligible[0].player_id])
    other = next(o for (s, _), o in options.items() if s == 2026 and o.manager_id == "wolfe" and o.eligible)
    with pytest.raises(KeeperRulesError, match="more than one manager"):
        choose([eligible[0], other], rules, slots=3)


def test_default_order_breaks_ties_by_later_pick(options):
    a, b = options[(2024, PICKENS)], options[(2024, FLOWERS)]
    assert a.cost == b.cost and a.last_overall < b.last_overall
    assert [o.player_id for o in default_order([a, b])] == [FLOWERS, PICKENS]


# Every keeper ever kept, and the commissioner's sheets --------------------------------------------


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_every_actual_keeper_was_eligible_at_his_cost(player_league, season):
    """Rosters at keeper time: how last season ended, plus the offseason trades of keeper rights (via)."""
    rosters = end_of_season_rosters(player_league.seasons[season - 1])
    for k in HISTORY.in_season(season):
        if k.via:
            assert rosters[k.player_id] == k.via, k
            rosters[k.player_id] = k.manager_id
    rules = RULES.keepers(season)
    options = {o.player_id: o for o in keeper_options(player_league, HISTORY, rules, season, rosters)}
    by_manager = {}
    for k in HISTORY.in_season(season):
        o = options[k.player_id]
        assert o.eligible and o.manager_id == k.manager_id, (k, o)
        by_manager.setdefault(k.manager_id, []).append(k)
    for manager, keeps in by_manager.items():
        rounds = choose([options[k.player_id] for k in keeps], rules, slots=3)
        assert rounds == {k.player_id: k.round for k in keeps}, manager


# Players the sheets list that the committed data can't: picked up after the last move on file (in
# the offseason, before the sheet was made), or dropped after it. Each was checked in the data: the
# player's last box score and transactions put him elsewhere. Anything else the sheets and the
# engine disagree on fails the test.
PICKED_UP_LATER = {
    2024: {("J.K. Dobbins", "grudee")},
    2025: {
        ("Caleb Williams", "grudee"),
        ("Tyler Allgeier", "grudee"),
        ("Khalil Herbert", "grudee"),
        ("Hollywood Brown", "dickey"),
        ("Dalton Schultz", "dickey"),
    },
    2026: {
        ("Joe Mixon", "grudee"),
        ("Jaydon Blue", "grudee"),
        ("Jerry Jeudy", "grudee"),
        ("Jordan Addison", "grudee"),
        ("Najee Harris", "grudee"),
        ("Xavier Worthy", "grudee"),
        ("Ray Davis", "edwards"),
    },
}
DROPPED_LATER = {2026: {("Chase McLaughlin", "grudee")}}


def _sheet(season):
    with (SHEETS / f"{season}.csv").open(encoding="utf-8") as f:
        return {(int(r["player_id"]), r["manager"]): (r["player"], int(r["cost"])) for r in csv.DictReader(f)}


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_matches_the_commissioners_sheet(player_league, options, season):
    """The engine's eligible list is the sheet's "available players", player, manager and cost."""
    sheet = _sheet(season)
    engine = {(o.player_id, o.manager_id): o for (s, _), o in options.items() if s == season and o.eligible}
    names = {
        o.player_id: p.name
        for o in engine.values()
        for p in [player_league.seasons[season - 1].players[o.player_id]]
    }
    only_sheet = {(name, m) for (pid, m), (name, _) in sheet.items() if (pid, m) not in engine}
    only_engine = {(names[pid], m) for (pid, m) in engine if (pid, m) not in sheet}
    assert only_sheet == PICKED_UP_LATER.get(season, set())
    assert only_engine == DROPPED_LATER.get(season, set())
    for key in engine.keys() & sheet.keys():
        assert engine[key].cost == sheet[key][1], sheet[key]


def test_a_new_manager_keeps_from_the_team_he_took_over(options):
    """Brian Alligood took over Rich Wilkins's team for 2026: Wilkins's 2025 roster is his to keep from."""
    alligood = {o.player_id for (s, _), o in options.items() if s == 2026 and o.manager_id == "alligood"}
    assert {k.player_id for k in HISTORY.in_season(2026) if k.manager_id == "alligood"} <= alligood
    assert not any(o.manager_id == "wilkins" for (s, _), o in options.items() if s == 2026)


def test_ineligible_players_say_why(options):
    reasons = {o.reason for (s, _), o in options.items() if s == 2026}
    assert reasons == {None, UNDRAFTED, EARLY_ROUND}
    early = next(o for (s, _), o in options.items() if s == 2026 and o.reason == EARLY_ROUND)
    assert "keepers must come from round 4 or later" in early.explain(RULES.keepers(2026))
