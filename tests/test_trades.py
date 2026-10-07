"""Trade valuations and the trade ledger, over the committed 2015-2025 data."""

import pytest

from mustafatron.stats.coaching import counted_weeks
from mustafatron.stats.trades import trade_book


@pytest.fixture(scope="module")
def league(player_league):
    return player_league


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


def test_2022_intermediate_transfers_and_round_trip_are_separate_trades(league):
    s = league.seasons[2022]
    assert len({t.id for t in s.trades}) == 14
    assert all(t.players_in and t.players_out for t in s.trades)
    packages = {
        (
            t.scoring_period,
            t.manager_id,
            frozenset(s.players[p].name for p in t.players_in),
            frozenset(s.players[p].name for p in t.players_out),
        )
        for t in s.trades
    }
    assert (
        10,
        "edwards",
        frozenset({"Tyler Lockett"}),
        frozenset({"Raheem Mostert", "Kareem Hunt"}),
    ) in packages
    assert (
        10,
        "richardson",
        frozenset({"Tyler Lockett", "Chris Godwin"}),
        frozenset({"Geno Smith", "James Conner", "Chase Claypool"}),
    ) in packages
    assert (13, "grudee", frozenset({"Christian Watson"}), frozenset({"Rachaad White"})) in packages
    assert (
        13,
        "richardson",
        frozenset({"Justin Tucker", "Christian Watson", "Tyler Lockett"}),
        frozenset({"DeAndre Hopkins"}),
    ) in packages


def test_2023_trade_includes_gainwell_even_though_he_was_dropped(league):
    s = league.seasons[2023]
    trade = next(t for t in s.trades if t.scoring_period == 10 and t.manager_id == "grudee")
    assert {s.players[p].name for p in trade.players_in} == {"Sam LaPorta", "Kenneth Gainwell"}


def test_incomplete_executed_ledger_is_rejected(monkeypatch):
    from mustafatron import transform

    monkeypatch.setattr(transform, "executed_trades", lambda *_: [])
    with pytest.raises(ValueError, match="executed trade counts do not match ESPN"):
        transform.load_league([2022], player_data=True)


def test_executed_trade_rejects_missing_return():
    from mustafatron.transform import executed_trades

    record = {
        "id": "broken",
        "type": "TRADE_ACCEPT",
        "status": "EXECUTED",
        "scoringPeriodId": 10,
        "items": [{"type": "TRADE", "playerId": 1, "fromTeamId": 1, "toTeamId": 2}],
    }
    with pytest.raises(ValueError, match="missing players on one side"):
        executed_trades([record], 2022, {1: "edwards", 2: "carpenter"})
