"""Profile stats over 2015-2025 (no network)."""

from mustafatron.stats.profiles import best_and_worst_weeks, career_all_play, manager_weeks
from mustafatron.stats.seasons import all_play, week_scores
from mustafatron.transform import load_league

LEAGUE = load_league(range(2015, 2026))


def test_manager_weeks_cover_every_week_played():
    for m in LEAGUE.managers_with_games():
        seasons = [s for s in LEAGUE.seasons.values() if any(t.manager_id == m.id for t in s.teams)]
        weeks = manager_weeks(LEAGUE, m.id)
        assert len(weeks) == sum(s.settings.final_scoring_period for s in seasons), m.id
        assert all(w.opponent_id != m.id for w in weeks)


def test_best_and_worst_weeks_match_the_season_grid():
    best, worst = best_and_worst_weeks(LEAGUE, "grudee")
    assert len(best) == len(worst) == 5
    assert [w.points for w in best] == sorted((w.points for w in best), reverse=True)
    mine = [w.points for s in LEAGUE.seasons.values() for w in week_scores(s) if w.manager_id == "grudee"]
    assert best[0].points == max(mine) and worst[0].points == min(mine)


def test_career_all_play_sums_seasons():
    total = career_all_play(LEAGUE, "wolfe")
    by_season = [all_play(s)["wolfe"] for s in LEAGUE.seasons.values()]
    assert total.wins == sum(a.wins for a in by_season)
    league_wins = sum(career_all_play(LEAGUE, m.id).wins for m in LEAGUE.managers_with_games())
    league_losses = sum(career_all_play(LEAGUE, m.id).losses for m in LEAGUE.managers_with_games())
    assert league_wins == league_losses
