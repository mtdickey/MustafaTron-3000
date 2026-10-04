"""The weekly reports: which weeks get one, and that each sees only what had happened by then."""

import pytest

from mustafatron.stats.weekly import games_in, report_weeks, standings_through, week_label
from mustafatron.transform import load_league


@pytest.fixture(scope="module")
def league():
    return load_league(range(2015, 2026))


def test_every_week_of_a_finished_season_has_a_report(league):
    for s in league.seasons.values():
        weeks = report_weeks(s)
        assert [w.week for w in weeks] == sorted(s.settings.matchup_periods)
        assert all(all(g.final for g in games_in(s, w.week)) for w in weeks)


def test_labels_name_the_playoff_rounds(league):
    s = league.seasons[2021]
    assert week_label(s.settings, 1) == "Week 1"
    assert week_label(s.settings, s.settings.regular_season_matchups) == "Week 14"
    assert [w.label for w in report_weeks(s) if w.playoff] == ["Semifinals", "Championship"]
    assert report_weeks(s)[-1].periods == (17, 18)  # a playoff matchup spans two NFL weeks


def test_standings_through_the_last_regular_week_match_espn(league):
    for s in league.seasons.values():
        table = {x.manager_id: x for x in standings_through(s, s.settings.regular_season_matchups)}
        for t in s.teams:
            x = table[t.manager_id]
            assert (x.wins, x.losses, x.ties) == (t.wins, t.losses, t.ties)
            assert x.points_for == pytest.approx(t.points_for, abs=0.01)


def test_standings_never_see_a_later_week(league):
    s = league.seasons[2022]
    for week in range(1, s.settings.regular_season_matchups + 1):
        table = standings_through(s, week)
        assert all(x.wins + x.losses + x.ties == week for x in table)
        assert [x.win_pct for x in table] == sorted((x.win_pct for x in table), reverse=True)


def test_playoff_standings_are_in_seed_order(league):
    s = league.seasons[2025]
    last = report_weeks(s)[-1]
    seeds = {t.manager_id: t.playoff_seed for t in s.teams}
    assert [seeds[x.manager_id] for x in standings_through(s, last.week)] == sorted(seeds.values())
