"""Waiver statistics preserve coverage, zero-dollar wins, and season-specific baselines."""

from dataclasses import replace

import pytest

from mustafatron.model import League, Transaction
from mustafatron.stats.waivers import waiver_book


def test_history_coverage_and_totals(player_league):
    book = waiver_book(player_league)
    assert book.detail_seasons == list(range(2018, 2026))
    assert book.faab_seasons == [2024, 2025]
    assert sum(m.acquisitions for m in book.managers) == sum(
        t.acquisitions for t in player_league.team_seasons
    )
    assert all(s.waiver_wins is None for s in book.seasons if s.season < 2018)
    assert all(s.waiver_wins is not None for s in book.seasons if s.season >= 2018)
    assert len(book.expensive) == 25
    assert book.expensive[0].bid == 48
    assert all(p.season >= 2024 for p in book.expensive)
    assert [p.bid for p in book.expensive] == sorted((p.bid for p in book.expensive), reverse=True)


def test_bids_ignore_drops_trades_and_traditional_waivers(player_league):
    base = player_league.seasons[2024]
    a, b = [t.manager_id for t in base.teams[:2]]

    def move(manager, bid, kind="WAIVER", players=(1,)):
        return Transaction(2024, 1, None, kind, manager, players, (), bid)

    season = replace(
        base,
        teams=base.teams[:2],
        transactions=[
            move(a, 10),
            move(a, 0),
            move(b, 2),
            move(a, 99, players=()),
            move(a, 100, "TRADE"),
            move(a, 0, "FREEAGENT"),
        ],
    )
    league = League(player_league.managers, {2024: season})
    book = waiver_book(league)
    stats = {m.manager: m for m in book.managers}
    assert stats[a].faab_wins == 2
    assert stats[a].spent == 10
    assert stats[a].average_bid == 5
    assert stats[a].premium == 3  # (10 - 2 + 0 - 2) / 2
    assert stats[b].premium == -3
    assert stats[a].free_agents == 1
    assert book.expensive[0].budget_pct == 10
    assert stats[a].per_season == base.teams[0].acquisitions
    traditional = replace(season, settings=replace(base.settings, uses_faab=False))
    assert waiver_book(League(league.managers, {2024: traditional})).expensive == []


def test_empty_history_and_no_other_bidders(player_league):
    assert waiver_book(League(player_league.managers)).managers == []
    base = player_league.seasons[2024]
    a = base.teams[0].manager_id
    season = replace(
        base, teams=base.teams[:1], transactions=[Transaction(2024, 0, None, "WAIVER", a, (1,), (), 0)]
    )
    stat = waiver_book(League(player_league.managers, {2024: season})).managers[0]
    assert stat.premium is None
    assert stat.average_bid == 0
    assert stat.faab_wins == 1


def test_average_per_season_includes_zero_activity(player_league):
    base = player_league.seasons[2024]
    team = replace(base.teams[0], acquisitions=10)
    first = replace(base, teams=[team], transactions=[])
    second = replace(base, season=2025, teams=[replace(team, acquisitions=0)], transactions=[])
    stat = waiver_book(League(player_league.managers, {2024: first, 2025: second})).managers[0]
    assert stat.per_season == pytest.approx(5)
    assert stat.detail_seasons == 2
    assert stat.waivers_per_season == 0
