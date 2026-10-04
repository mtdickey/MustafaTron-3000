"""The optimal-lineup engine and the coaching leaderboard built on it."""

import pytest

from mustafatron.stats.coaching import COUNTED_TIERS, coaching_book
from mustafatron.stats.lineup import Candidate, optimal_lineup, team_weeks
from mustafatron.transform import load_league

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "D/ST": 1, "K": 1}
RB, WR, TE = {"RB", "RB/WR/TE"}, {"WR", "RB/WR/TE"}, {"TE", "RB/WR/TE"}


def c(pid: int, points: float, slots: set[str]) -> Candidate:
    return Candidate(pid, points, frozenset(slots))


def test_fills_every_slot_with_the_best_eligible_player():
    roster = [
        c(1, 20, {"QB"}), c(2, 25, {"QB"}),  # the backup QB outscored the starter
        c(3, 15, RB), c(4, 12, RB), c(5, 11, RB),
        c(6, 18, WR), c(7, 9, WR), c(8, 3, WR),
        c(9, 8, TE), c(10, 7, {"D/ST"}), c(11, 6, {"K"}),
    ]  # fmt: skip
    best = optimal_lineup(roster, SLOTS)
    assert best.player_ids == {2, 3, 4, 5, 6, 7, 9, 10, 11}
    assert dict(best.slots)["RB/WR/TE"] == 5  # the third RB beats the third WR for the flex
    assert best.points == 25 + 15 + 12 + 11 + 18 + 9 + 8 + 7 + 6


def test_multi_position_player_goes_where_he_frees_the_most_points():
    # Filling RB first puts the RB/WR (12) there and leaves a 3-point WR; exact puts him at WR.
    roster = [c(1, 12, {"RB", "WR"}), c(2, 10, {"RB"}), c(3, 3, {"WR"})]
    best = optimal_lineup(roster, {"RB": 1, "WR": 1})
    assert dict(best.slots) == {"RB": 2, "WR": 1}
    assert best.points == 22


def test_a_negative_starter_is_better_left_out():
    best = optimal_lineup([c(1, -0.48, {"QB"}), c(2, 9, {"K"})], {"QB": 1, "K": 1})
    assert dict(best.slots) == {"K": 2} and best.points == 9


def test_an_empty_slot_stays_empty_and_bye_weeks_score_nothing():
    roster = [c(1, 20, {"QB"}), c(2, 0, RB), c(3, 14, RB), c(4, 10, WR), c(5, 9, WR), c(6, 4, TE)]
    best = optimal_lineup(roster, SLOTS)  # no kicker, no defense on the roster
    assert "K" not in dict(best.slots) and "D/ST" not in dict(best.slots)
    assert best.points == 20 + 14 + 10 + 9 + 4  # the bye-week RB adds nothing


def test_ties_keep_the_player_who_actually_started():
    roster = [c(1, 10, {"QB"}), c(2, 10, {"QB"})]
    assert optimal_lineup(roster, {"QB": 1}, prefer=frozenset({2})).player_ids == {2}
    assert optimal_lineup(roster, {"QB": 1}, prefer=frozenset({1})).player_ids == {1}


# On the committed seasons -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def league():
    return load_league(range(2015, 2026), player_data=True)


@pytest.fixture(scope="module")
def book(league):
    return coaching_book(league)


def test_no_lineups_before_2018(league):
    assert all(team_weeks(league.seasons[y]) == [] for y in (2015, 2016, 2017))


def test_every_team_week_is_solved_and_never_beats_the_optimum(book):
    assert book.first_season == 2018
    for w in book.weeks:
        assert w.optimal >= w.actual - 0.005
        assert (w.substitutions == 0) == w.perfect
        gained = sum(w.points[p] for p in w.should_have_started) - sum(w.points[p] for p in w.should_have_sat)
        assert gained == pytest.approx(w.left_on_bench, abs=0.01)


def test_only_weeks_that_mattered_count(league, book):
    counted = {(w.season, w.manager_id, w.period) for w in book.weeks}
    for s in league.seasons.values():
        for g in s.games:
            for period, *_ in g.period_scores:
                for mid in (g.home_id, g.away_id):
                    if s.has_lineups and g.final:
                        assert ((s.season, mid, period) in counted) == (g.tier in COUNTED_TIERS)


def test_careers_and_seasons_add_up(book):
    for c in book.careers:
        seasons = [s for s in book.seasons if s.manager_id == c.manager_id]
        assert c.weeks == sum(s.weeks for s in seasons)
        assert c.left_on_bench == pytest.approx(sum(s.left_on_bench for s in seasons), abs=0.05)
    assert [x.per_week for x in book.careers] == sorted(x.per_week for x in book.careers)


def test_if_only_losses_really_would_have_been_wins(book):
    assert book.if_only
    for x in book.if_only:
        assert x.game.result_for(x.manager_id) == "L"
        assert x.score < x.opponent_score < x.optimal
        assert x.score == pytest.approx(sum(w.actual for w in x.weeks), abs=0.01)
    assert book.worst_weeks[0].left_on_bench == max(w.left_on_bench for w in book.weeks)
