"""Trade valuations and the trade ledger, over the committed 2015-2025 data."""

import pytest

from mustafatron.stats.coaching import counted_weeks
from mustafatron.stats.trades import trade_book
from mustafatron.transform import load_league


@pytest.fixture(scope="module")
def league():
    return load_league(range(2015, 2026), player_data=True)


@pytest.fixture(scope="module")
def book(league):
    return trade_book(league)


def test_every_trade_is_in_the_ledger(league, book):
    assert book.first_season == 2018
    for season in range(2018, 2026):
        ids = {t.id for t in league.seasons[season].trades}
        assert ids == {t.id for t in book.trades if t.season == season}


def test_sides_mirror_each_other(book):
    for t in book.trades:
        a, b = t.sides
        assert set(a.players_in) == set(b.players_out) and set(a.players_out) == set(b.players_in)
        assert t.winner.value >= t.loser.value and t.margin == pytest.approx(t.winner.value - t.loser.value)


def test_values_are_bounded_by_what_the_players_scored(league, book):
    # Adding players can't add more than they scored; losing them can't cost more than they scored.
    for t in book.trades:
        s = league.seasons[t.season]
        for side in t.sides:
            mine = [w for w in counted_weeks(s) if w.manager_id == side.manager_id]
            weeks = [w.period for w in mine if w.period >= t.period]
            assert side.weeks == len(weeks)
            got = sum(max(0.0, s.players[p].points_in(w)) for p in side.players_in for w in weeks)
            gave = sum(max(0.0, s.players[p].points_in(w)) for p in side.players_out for w in weeks)
            assert -gave - 0.01 <= side.value <= got + 0.01


def test_best_worst_and_lopsided_are_ranked(book):
    sides = [s for t in book.trades for s in t.sides]
    assert book.best[0][1].value == max(s.value for s in sides)
    assert book.worst[0][1].value == min(s.value for s in sides)
    assert [t.margin for t in book.lopsided] == sorted((t.margin for t in book.trades), reverse=True)[:10]


def test_counts_cover_every_season_from_espn(league, book):
    assert {x.season for x in book.counts} == set(range(2015, 2026))
    for x in book.counts:
        team = league.seasons[x.season].team_of(x.manager_id)
        assert (x.trades, x.acquisitions) == (team.trades, team.acquisitions)
