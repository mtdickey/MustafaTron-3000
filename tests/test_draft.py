"""Draft value: the per-season expectation line, steals, busts and the drafter leaderboard."""

import pytest

from mustafatron.rules import load_rules
from mustafatron.stats.draft import _fit, draft_book, season_values

RULES = load_rules().draft_review


@pytest.fixture(scope="module")
def league(player_league):
    return player_league


@pytest.fixture(scope="module")
def book(league):
    return draft_book(league, RULES)


def test_fit_recovers_a_line():
    assert _fit([1, 2, 3, 4], [10, 8, 6, 4]) == pytest.approx((12, -2))


@pytest.mark.parametrize("season", range(2015, 2026))
def test_each_draft_is_graded_against_its_own_line(league, season):
    values = season_values(league.seasons[season])
    s = league.seasons[season]
    assert len(values) == len(s.draft) - sum(p.keeper for p in s.draft)  # every non-keeper pick
    # Least squares: residuals sum to zero within each season, and so do points above positional average
    # (to within the rounding of 160 values to hundredths).
    assert sum(v.value for v in values) == pytest.approx(0, abs=0.5)
    assert sum(v.points_above_avg for v in values) == pytest.approx(0, abs=0.5)
    # The line slopes down: early picks are expected to beat later ones.
    first, last = min(values, key=lambda v: v.overall_pick), max(values, key=lambda v: v.overall_pick)
    assert first.expected > last.expected
    for v in values:
        assert v.value == pytest.approx(v.points_above_avg - v.expected, abs=0.02)


def test_covers_every_finished_season(book):
    assert book.first_season == 2015
    assert {p.season for p in book.picks} == set(range(2015, 2026))


def test_steals_and_busts_respect_the_round_cutoffs(book):
    assert len(book.steals) == len(book.busts) == 10
    assert all(p.round > RULES.steals_after_round for p in book.steals)
    assert all(p.round <= RULES.busts_through_round for p in book.busts)
    assert book.steals[0].value == max(p.value for p in book.picks if p.round > RULES.steals_after_round)
    assert book.busts[0].value == min(p.value for p in book.picks if p.round <= RULES.busts_through_round)


def test_drafters_add_up(book):
    assert sum(d.picks for d in book.drafters) == len(book.picks)
    for d in book.drafters:
        assert d.early_picks + d.late_picks == d.picks
        assert d.early_value + d.late_value == pytest.approx(d.value, abs=0.05)
    assert [d.per_pick for d in book.drafters] == sorted((d.per_pick for d in book.drafters), reverse=True)


def test_rounds_and_draft_classes(book):
    assert [r.round for r in book.rounds] == list(range(1, 17))
    assert sum(r.picks for r in book.rounds) == len(book.picks)
    assert book.best_drafts[0].value >= book.best_drafts[-1].value > book.worst_drafts[-1].value
