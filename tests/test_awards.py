"""The league's awards: rules from league_rules.yml, computed winners, hand-recorded overrides."""

import pytest

from mustafatron.rules import load_rules
from mustafatron.stats.awards import METRICS, Winner, award_history, load_manual, parse_manual
from mustafatron.stats.coaching import coaching_book
from mustafatron.stats.trades import trade_book

RULES = load_rules()
AWARDS = {a.id: a for a in RULES.awards}


@pytest.fixture(scope="module")
def league(player_league):
    return player_league


def test_the_named_awards_are_defined_with_known_metrics():
    assert {"kariuki", "grudee", "coach"} <= set(AWARDS)
    assert all(AWARDS[a].status == "official" for a in ("kariuki", "grudee", "coach"))
    assert all(a.metric in METRICS and a.status in ("official", "proposed") for a in RULES.awards)


def test_the_committed_manual_file_parses():
    manual = load_manual()
    for award, seasons in manual.items():
        assert award in AWARDS
        assert all(isinstance(w, Winner) for w in seasons.values())


def test_every_finished_season_gets_a_row_and_gaps_are_marked(league):
    for award in RULES.awards:
        rows = award_history(league, award, manual={})
        assert [r.season for r in rows] == list(range(2025, 2014, -1))
        for r in rows:
            assert (r.source == "unrecorded") == (r.winner is None)
            if r.season < award.since:
                assert r.source == "unrecorded"


def test_trade_awards_match_the_trade_book(league):
    book = trade_book(league)
    kariuki = {r.season: r.winner for r in award_history(league, AWARDS["kariuki"], manual={})}
    grudee = {r.season: r.winner for r in award_history(league, AWARDS["grudee"], manual={})}
    for season in range(2018, 2026):
        sides = [s for t in book.trades if t.season == season for s in t.sides]
        assert kariuki[season].value == min(s.value for s in sides)
        assert grudee[season].value == max(s.value for s in sides)


def test_coach_of_the_year_has_the_fewest_regular_season_bench_points(league):
    weeks = coaching_book(league).weeks
    for r in award_history(league, AWARDS["coach"], manual={}):
        if r.winner is None:
            continue
        s = league.seasons[r.season]
        regular = s.settings.regular_season_matchups
        left: dict[str, float] = {}
        for w in weeks:
            if w.season == r.season and s.settings.matchup_period_of(w.period) <= regular:
                left[w.manager_id] = left.get(w.manager_id, 0.0) + w.left_on_bench
        assert r.winner.value == pytest.approx(min(left.values()), abs=0.01)


def test_a_hand_recorded_winner_fills_a_gap_and_overrides_a_computed_one(league):
    manual = parse_manual(
        {"kariuki": {2016: {"manager": "kariuki", "note": "the original"}, 2025: {"manager": "albert"}}}
    )
    rows = {r.season: r for r in award_history(league, AWARDS["kariuki"], manual=manual)}
    assert (rows[2016].source, rows[2016].winner.manager_id, rows[2016].winner.detail) == (
        "manual",
        "kariuki",
        "the original",
    )
    assert (rows[2025].source, rows[2025].winner.manager_id) == ("manual", "albert")
    assert rows[2024].source == "computed"
