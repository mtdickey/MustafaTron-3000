"""The keeper book behind /keepers: runs, values on the draft line, and which seasons are published."""

from dataclasses import replace

import pytest

from mustafatron.keepers import load_keeper_history
from mustafatron.model import League
from mustafatron.stats.draft import draft_line
from mustafatron.stats.keepers import keeper_book, run_length

HISTORY = load_keeper_history()
NAME_TO_ID = {k.player: k.player_id for k in HISTORY.keeps}


@pytest.fixture(scope="module")
def book(player_league):
    return keeper_book(player_league, HISTORY)


def _keep(season, player):
    return next(k for k in HISTORY.in_season(season) if k.player == player)


@pytest.mark.parametrize(
    ("season", "player", "run"),
    [
        (2024, "Drake London", 1),
        (2025, "Drake London", 2),
        (2026, "Drake London", 3),  # the run goes on after Grudee traded his rights to Dylan
        (2026, "Zay Flowers", 1),  # kept in 2024, back in the 2025 draft: the run starts over
        (2026, "Nico Collins", 3),
    ],
)
def test_run_counts_straight_seasons_kept_by_anyone(season, player, run):
    assert run_length(HISTORY, _keep(season, player)) == run


def test_only_published_seasons(book, player_league):
    """data/raw/ ends with 2025, so the offline book does too; 2026 appears once its season is loaded."""
    assert max(player_league.seasons) == 2025
    assert book.seasons == [2024, 2025]
    assert {k.season for k in book.keepers} == {2024, 2025}
    assert len(book.keepers) == 21 + 26
    assert "alligood" not in {m.manager for m in book.managers}  # only a manager from 2026
    assert book.slots == 3


def test_every_finished_keeper_is_valued_on_his_drafts_line(book, player_league):
    for k in book.keepers:
        season = player_league.seasons[k.season]
        line = draft_line(season)
        player = season.players[NAME_TO_ID[k.player]]
        assert k.overall_pick is not None and k.value is not None, k
        expected = line.value(player.season_points or 0.0, player.position, k.overall_pick)
        assert k.value == pytest.approx(expected, abs=0.01)
        assert k.points == pytest.approx(player.season_points or 0.0, abs=0.01)


def test_the_line_is_the_draft_pages(player_league):
    """A non-keeper's value through DraftLine.value is the value the draft page publishes for him."""
    line = draft_line(player_league.seasons[2025])
    for p in line.picks[:20]:
        assert line.value(p.points, p.position, p.overall_pick) == pytest.approx(p.value, abs=0.02)


def test_best_and_worst(book):
    ranked = sorted(book.keepers, key=lambda k: -k.value)
    assert (ranked[0].player, ranked[0].season, ranked[0].manager) == ("Jonathan Taylor", 2025, "wolfe")
    assert (ranked[-1].player, ranked[-1].season, ranked[-1].manager) == ("Jayden Daniels", 2025, "joyce")


def test_manager_totals_add_up(book):
    for m in book.managers:
        mine = [k for k in book.keepers if k.manager == m.manager]
        assert m.keeps == len(mine)
        assert m.valued == len(mine)
        assert m.value == pytest.approx(sum(k.value for k in mine), abs=0.05)
        assert m.keeps <= m.seasons * book.slots
    assert [m.value for m in book.managers] == sorted((m.value for m in book.managers), reverse=True)
    wilkins = next(m for m in book.managers if m.manager == "wilkins")
    assert (wilkins.seasons, wilkins.keeps) == (2, 3)  # kept nobody in 2024, three in 2025


def test_unfinished_season_has_keepers_but_no_values(player_league):
    """A season in progress lists its keepers (with their picks) but grades none of them."""
    s2025 = player_league.seasons[2025]
    unfinished = replace(s2025, games=[*s2025.games[:-1], replace(s2025.games[-1], final=False)])
    assert not unfinished.finished
    book = keeper_book(League(player_league.managers, {2025: unfinished}), HISTORY)
    assert book.seasons == [2025]
    assert len(book.keepers) == 26
    assert all(k.overall_pick is not None and k.points is None and k.value is None for k in book.keepers)
    assert all(m.valued == 0 and m.value == 0 for m in book.managers)
