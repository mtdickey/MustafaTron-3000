"""Keeper history (data/manual/keeper_history.yml) against ESPN's draft data."""

import pytest
import yaml

from mustafatron.identity import load_managers
from mustafatron.keeper_engine import carry_over, end_of_season_rosters
from mustafatron.keepers import KeeperHistoryError, load_keeper_history, parse_keeper_history
from mustafatron.rules import load_rules

HISTORY = load_keeper_history()
RULES = load_rules()
FIRST_KEEPER_SEASON = 2024


@pytest.fixture(scope="module")
def league(player_league):
    return player_league


def _finished(league, season):
    return season in league.seasons and league.seasons[season].finished


def test_history_starts_when_espn_keepers_do(league):
    assert HISTORY.seasons[0] == FIRST_KEEPER_SEASON
    assert all(not p.keeper for s in range(2015, FIRST_KEEPER_SEASON) for p in league.seasons[s].draft)


@pytest.mark.parametrize("season", [2024, 2025])
def test_matches_espn_keeper_picks(league, season):
    """Every keeper ESPN flagged, and nothing else: same player, manager and round."""
    espn = {(p.player_id, p.manager_id, p.round) for p in league.seasons[season].draft if p.keeper}
    ours = {(k.player_id, k.manager_id, k.round) for k in HISTORY.in_season(season)}
    assert ours - espn == set(), "in keeper_history.yml, not flagged by ESPN"
    assert espn - ours == set(), "flagged by ESPN, missing from keeper_history.yml"


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_each_keeper_was_eligible_and_paid_one_round_earlier(league, season):
    """Drafted the season before after the cutoff round, and kept one round earlier than that pick.

    A collision (two keepers from the same round) moves one a round further; those carry a note.
    """
    cutoff = RULES.keeper_eligible_after_round(season)
    drafted = {p.player_id: p for p in league.seasons[season - 1].draft}
    for k in HISTORY.in_season(season):
        pick = drafted.get(k.player_id)
        assert pick is not None, f"{k.player} was not drafted in {season - 1}"
        assert pick.round > cutoff or pick.keeper, f"{k.player} drafted in round {pick.round}"
        expected = pick.round - 1
        if k.note:
            assert k.round < expected, k
        else:
            assert k.round == expected, k


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_at_most_espns_keeper_count_per_manager(league, season):
    known = [s for s in league.seasons if s <= season and league.seasons[s].settings.keeper_count]
    limit = league.seasons[max(known)].settings.keeper_count
    assert limit == 3
    assert all(len(keeps) <= limit for keeps in HISTORY.by_manager(season).values())


@pytest.mark.parametrize("season", [2024, 2025, 2026])
def test_keepers_came_off_the_right_roster(league, season):
    """At the end of the season before, each keeper was on the keeping manager's roster (or the one
    he took over), or on the roster of the manager his rights were traded from (``via``)."""
    owner = carry_over(end_of_season_rosters(league.seasons[season - 1]), load_managers(), season)
    for k in HISTORY.in_season(season):
        assert owner.get(k.player_id) == (k.via or k.manager_id), k


def test_names_match_espn(league):
    for k in HISTORY.keeps:
        players = league.seasons[k.season - 1].players  # drafted the season before
        assert players[k.player_id].name.replace(" III", "") == k.player, k


def test_kept_before():
    london = 4426502
    assert [(k.season, k.manager_id) for k in HISTORY.of_player(london)] == [
        (2024, "grudee"),
        (2025, "grudee"),
        (2026, "edwards"),
    ]
    assert len(HISTORY.kept_before(london, 2026)) == 2
    assert HISTORY.kept_before(london, 2024) == []


def _parse(text):
    return parse_keeper_history(yaml.safe_load(text), load_managers())


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("seasons: {2025: {nobody: [{player: X, player_id: 1, round: 5}]}}", "unknown manager"),
        ("seasons: {2026: {wilkins: [{player: X, player_id: 1, round: 5}]}}", "not in the league"),
        ("seasons: {2025: {dickey: [{player: X, player_id: 1, round: 5, via: dickey}]}}", "own manager"),
        (
            "seasons: {2025: {dickey: [{player: X, player_id: 1, round: 5}],"
            " joyce: [{player: X, player_id: 1, round: 6}]}}",
            "kept 2 times",
        ),
        (
            "seasons: {2025: {dickey: [{player: X, player_id: 1, round: 5},"
            " {player: Y, player_id: 2, round: 5}]}}",
            "collision",
        ),
    ],
)
def test_validation(text, problem):
    with pytest.raises(KeeperHistoryError, match=problem):
        _parse(text)
