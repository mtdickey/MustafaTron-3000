"""Season detail stats: per-week scores, all-play and superlatives over 2015-2025 (no network)."""

import pytest

from mustafatron.stats.seasons import all_play, regular_season_periods, superlatives, week_scores
from mustafatron.transform import load_league

LEAGUE = load_league(range(2015, 2026))


@pytest.mark.parametrize("year", range(2015, 2026))
def test_weekly_points_add_up_to_matchup_totals(year):
    for g in LEAGUE.seasons[year].games:
        assert g.period_scores
        assert sum(h for _, h, _ in g.period_scores) == pytest.approx(g.home_score, abs=0.01)
        assert sum(a for *_, a in g.period_scores) == pytest.approx(g.away_score, abs=0.01)


def test_every_team_scores_every_week():
    for s in LEAGUE.seasons.values():
        weeks = week_scores(s)
        periods = {w.period for w in weeks}
        assert periods == set(range(1, s.settings.final_scoring_period + 1)), s.season
        assert len(weeks) == len(periods) * s.settings.team_count
    assert max(w.period for w in week_scores(LEAGUE.seasons[2021])) == 18  # the 16-matchup season


def test_results_only_on_one_week_matchups():
    s = LEAGUE.seasons[2025]
    regular = set(regular_season_periods(s))
    for w in week_scores(s):
        assert (w.result != "") == (w.period in regular)


def test_all_play_balances():
    for s in LEAGUE.seasons.values():
        ap = all_play(s)
        n_weeks = len(regular_season_periods(s))
        assert sum(a.wins for a in ap.values()) == sum(a.losses for a in ap.values())
        for a in ap.values():
            assert a.wins + a.losses + a.ties == n_weeks * (s.settings.team_count - 1)


def test_superlatives():
    for s in LEAGUE.seasons.values():
        sup = {x.key: x for x in superlatives(s)}
        assert len(sup) == 8
        weeks = week_scores(s)
        assert sup["high_week"].value == max(w.points for w in weeks)
        assert sup["low_week"].value == min(w.points for w in weeks)
        assert sup["luckiest"].value >= 0 >= sup["unluckiest"].value
        champ_pf = max(t.points_for for t in s.teams)
        assert sup["most_points"].value == champ_pf
