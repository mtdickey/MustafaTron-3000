"""The weekly reports: which weeks get one, and that each sees only what had happened by then."""

import pytest

from mustafatron.rules import load_rules
from mustafatron.stats.allplay import all_play
from mustafatron.stats.coaching import coaching_book
from mustafatron.stats.weekly import (
    MISSES_PER_MANAGER,
    all_play_through,
    coaching_through,
    draft_through,
    games_in,
    report_weeks,
    standings_through,
    week_label,
)
from mustafatron.stats.weeks import regular_season_periods
from mustafatron.transform import load_league

RULES = load_rules()


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


# All-play and luck ---------------------------------------------------------------------------------


def test_the_v0_2022_week_12_report(league):
    # The left panel of img/example-report.png: all-play records through week 12 of 2022, best first.
    _, rows = all_play_through(league.seasons[2022], 12)
    ap = [(r.all_play.wins, r.all_play.losses) for r in rows]
    assert ap == [
        (82, 26),
        (77, 31),
        (67, 41),
        (63, 45),
        (59, 49),
        (51, 57),
        (49, 59),
        (43, 65),
        (27, 81),
        (22, 86),
    ]


def test_all_play_through_the_regular_season_matches_the_season_totals(league):
    for s in league.seasons.values():
        periods, rows = all_play_through(s, report_weeks(s)[-1].week)  # a playoff week: the regular season
        assert periods == regular_season_periods(s)
        full = all_play(s)
        assert all(r.all_play == full[r.manager_id] for r in rows)


def test_each_week_is_one_game_against_every_other_team(league):
    s = league.seasons[2019]
    periods, rows = all_play_through(s, 6)
    assert periods == [1, 2, 3, 4, 5, 6]
    for r in rows:
        for c in r.cells.values():
            assert c.all_play.games == s.settings.team_count - 1
            assert c.rank == 1 + c.all_play.losses
            assert c.result in "WLT"
        assert r.luck.games == 6


def test_luck_through_a_week_uses_only_that_weeks_record(league):
    s = league.seasons[2022]
    _, rows = all_play_through(s, 12)
    albert = next(r for r in rows if r.manager_id == "albert")
    assert (albert.luck.wins, albert.luck.losses) == (7, 5)
    assert albert.luck.luck == pytest.approx(7 / 12 - 43 / 108)


# Coaching ------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def players(player_league):
    return player_league


def test_no_coaching_report_before_2018(players):
    assert coaching_through(players.seasons[2017], 5) is None


def test_the_v0_2022_week_12_coaching_panel(players):
    s = players.seasons[2022]
    c = coaching_through(s, 12)
    # img/example-report.png: "Dylan Edwards (33)" leads the bench chart, and "Dylan would've started
    # Amari Cooper (5)" the "If only..." list.
    top = c.bench[0]
    assert (top.manager_id, top.substitutions) == ("edwards", 33)
    assert top.left_on_bench == pytest.approx(285.26)
    first = c.if_only[0]
    assert (first.manager_id, s.players[first.player_id].name, first.weeks) == ("edwards", "Amari Cooper", 5)
    assert [x.gain for x in c.if_only] == sorted((x.gain for x in c.if_only), reverse=True)


def test_coaching_through_the_last_week_is_the_season_line(players):
    book = {(x.season, x.manager_id): x for x in coaching_book(players).seasons}
    for s in players.seasons.values():
        if not s.has_lineups:
            continue
        for b in coaching_through(s, report_weeks(s)[-1].week).bench:
            line = book[(s.season, b.manager_id)]
            assert (len(b.weeks), b.substitutions) == (line.weeks, line.substitutions)
            assert b.left_on_bench == pytest.approx(line.left_on_bench, abs=0.01)


def test_coaching_never_sees_a_later_week(players):
    s = players.seasons[2024]
    c = coaching_through(s, 6)
    assert all(w.period <= 6 for b in c.bench for w in b.weeks)
    assert all(len(b.weeks) == 6 for b in c.bench)
    for m, misses in c.by_manager.items():
        assert len(misses) <= MISSES_PER_MANAGER and all(x.manager_id == m for x in misses)


# Draft ---------------------------------------------------------------------------------------------


def test_no_weekly_draft_report_before_2018(players):
    assert draft_through(players.seasons[2017], 5, RULES.draft_review) is None


def test_the_v0_2022_week_12_draft_panel(players):
    # The right panel of img/example-report.png, every bar in order.
    d = draft_through(players.seasons[2022], 12, RULES.draft_review)
    assert [(p.player, p.overall_pick) for p in d.steals] == [
        ("Josh Jacobs", 44), ("Jalen Hurts", 76), ("Patrick Mahomes", 49), ("Jamaal Williams", 128),
        ("Josh Allen", 37), ("Travis Kelce", 17), ("Nick Chubb", 15), ("Stefon Diggs", 19),
        ("Joe Burrow", 93), ("Cowboys D/ST", 148),
    ]  # fmt: skip
    assert [(p.player, p.overall_pick) for p in d.busts] == [
        ("Javonte Williams", 21), ("Cam Akers", 34), ("Keenan Allen", 33), ("D'Andre Swift", 14),
        ("Kyle Pitts", 31), ("James Conner", 23), ("Mike Williams", 38), ("Jonathan Taylor", 1),
        ("Alvin Kamara", 11), ("Najee Harris", 8),
    ]  # fmt: skip
    assert all(p.round > 1 for p in d.steals) and all(p.round <= 4 for p in d.busts)


def test_the_line_is_the_fit_and_values_are_residuals(players):
    d = draft_through(players.seasons[2024], 6, RULES.draft_review)
    assert not any(
        p
        for p in players.seasons[2024].draft
        if p.keeper and p.player_id in {x.player_id for x in d.line.picks}
    )
    for p in d.line.picks:
        assert p.expected == pytest.approx(d.line.expected(p.overall_pick), abs=0.01)
        assert p.value == pytest.approx(p.points_above_avg - p.expected, abs=0.02)
    assert sum(p.value for p in d.line.picks) == pytest.approx(0, abs=0.5)  # least squares residuals


def test_points_so_far_never_include_a_later_week(players):
    s = players.seasons[2022]
    d = draft_through(s, 3, RULES.draft_review)
    for p in d.line.picks[:20]:
        assert p.points == pytest.approx(
            sum(s.players[p.player_id].points_in(w) for w in (1, 2, 3)), abs=0.01
        )
