"""The optimal-lineup engine and the coaching leaderboard built on it."""

import pytest

from mustafatron.stats.coaching import COUNTED_TIERS, coaching_book
from mustafatron.stats.lineup import Candidate, Swap, TeamWeek, eligibility, optimal_lineup, team_weeks

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


def test_flex_takes_only_the_positions_it_lists():
    # A backup QB outscoring everyone still can't play RB/WR/TE; a TE can.
    roster = [c(1, 20, {"QB"}), c(2, 30, {"QB"}), c(3, 9, RB), c(4, 8, WR), c(5, 7, TE), c(6, 12, TE)]
    best = optimal_lineup(roster, {"QB": 1, "RB": 1, "WR": 1, "TE": 1, "RB/WR/TE": 1})
    assert dict(best.slots) == {"QB": 2, "RB": 3, "WR": 4, "TE": 6, "RB/WR/TE": 5}


def week(rows: dict[int, tuple[str, float, set[str]]], slots: dict[str, int]) -> TeamWeek:
    """A TeamWeek from {player: (slot he was in, points, starting slots he may fill)}."""
    started = frozenset(p for p, (slot, _, _) in rows.items() if slot != "BE")
    pool = [c(p, pts, ok) for p, (_, pts, ok) in rows.items()]
    best = optimal_lineup(pool, slots, prefer=started)
    return TeamWeek(
        season=2020,
        period=1,
        manager_id="x",
        actual=round(sum(rows[p][1] for p in started), 2),
        optimal=best.points,
        started=started,
        best=best.player_ids,
        points={p: pts for p, (_, pts, _) in rows.items()},
        slot={p: slot for p, (slot, _, _) in rows.items()},
        eligible={p: frozenset(ok) for p, (_, _, ok) in rows.items()},
    )


def test_swaps_pair_each_benched_player_with_the_starter_he_replaces():
    w = week(
        {
            1: ("WR", 3, WR), 2: ("BE", 15, WR),  # WR for WR
            3: ("RB", 10, RB), 4: ("BE", 12, RB),  # RB for RB
            5: ("BE", 8, {"K"}),  # the kicker slot was left empty
        },
        {"RB": 1, "WR": 1, "K": 1},
    )  # fmt: skip
    assert w.swaps == [Swap(2, 1, 12), Swap(5, None, 8), Swap(4, 3, 2)]
    assert sum(x.gain for x in w.swaps) == w.left_on_bench == 22
    assert len(w.swaps) == w.substitutions


def test_benching_a_negative_starter_is_a_swap_with_nobody():
    w = week({1: ("QB", -0.48, {"QB"}), 2: ("K", 9, {"K"})}, {"QB": 1, "K": 1})
    assert w.swaps == [Swap(None, 1, 0.48)]


def test_a_chain_through_a_player_who_moves_still_pairs_one_for_one():
    # The 2020 Taysom Hill week: he started at QB, the best lineup moves him to TE (where the league
    # really started him), so the benched QB replaces the started TE.
    w = week(
        {1: ("QB", 9, {"QB", "TE"}), 2: ("TE", 5, {"TE"}), 3: ("BE", 14, {"QB"})},
        {"QB": 1, "TE": 1},
    )
    assert w.best == {1, 3}
    assert w.swaps == [Swap(3, 2, 9)]


# On the committed seasons -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def league(player_league):
    return player_league


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


def test_swaps_add_up_to_the_bench_points_every_week(book):
    for w in book.weeks:
        assert len(w.swaps) == w.substitutions
        assert sum(x.gain for x in w.swaps) == pytest.approx(w.left_on_bench, abs=0.011)


def test_injured_reserve_never_starts(book):
    assert any(w.injured for w in book.weeks)
    assert all(not (w.best & w.injured) for w in book.weeks)


def test_eligibility_includes_where_the_league_really_started_someone(league):
    # ESPN now lists Taysom Hill as QB only; the league started him at TE in 2020 (the v0 "hacky fix").
    s = league.seasons[2020]
    hill = next(p for p in s.players.values() if p.name == "Taysom Hill")
    assert "TE" not in hill.eligible_slots
    assert "TE" in eligibility(s)[hill.id]


def test_the_solve_is_shared(league):
    s = league.seasons[2024]
    assert team_weeks(s)[0] is team_weeks(s)[0]  # computed once per season, not per report
