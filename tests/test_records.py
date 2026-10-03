"""The records book over 2015-2025 (no network)."""

import pytest

from mustafatron.stats.records import one_week_games, records_book, streaks, week_totals
from mustafatron.stats.seasons import week_scores
from mustafatron.transform import load_league

LEAGUE = load_league(range(2015, 2026))
BOOK = records_book(LEAGUE)


def test_every_record_has_ten_ordered_marks():
    families = [BOOK.game, BOOK.matchup, BOOK.season, BOOK.streak, BOOK.week]
    assert sum(len(f) for f in families) == 20
    assert all(len(v) == 10 for f in families for v in f.values())


def test_win_and_loss_records_are_wins_and_losses():
    assert all(m.score < m.opponent_score for m in BOOK.game["most_points_in_loss"])
    assert all(m.score > m.opponent_score for m in BOOK.game["fewest_points_in_win"])
    best_loss = max(m.score for m in BOOK.game["most_points_in_loss"])
    sides = [(g.score_of(m), g.result_for(m)) for g in one_week_games(LEAGUE) for m in (g.home_id, g.away_id)]
    assert best_loss == max(s for s, r in sides if r == "L")


def test_matchup_records():
    games = one_week_games(LEAGUE)
    top = BOOK.matchup["highest_scoring_matchup"]
    assert top[0].total == pytest.approx(max(g.home_score + g.away_score for g in games))
    assert all(m.total == pytest.approx(m.home_score + m.away_score) for m in top)
    low = BOOK.matchup["lowest_scoring_matchup"]
    assert [m.total for m in low] == sorted(m.total for m in low)


def test_season_point_records():
    finished = [t for s in LEAGUE.seasons.values() if s.finished for t in s.teams]
    assert BOOK.season["most_points_season"][0].value == max(t.points_for for t in finished)
    assert BOOK.season["fewest_points_season"][0].value == min(t.points_for for t in finished)


def _regular_results(manager_id):
    games = sorted(
        (g for g in LEAGUE.games if not g.is_playoff and g.involves(manager_id)),
        key=lambda g: (g.season, g.week),
    )
    return [((g.season, g.week), g.result_for(manager_id)) for g in games]


@pytest.mark.parametrize("result", ["W", "L"])
def test_streaks_are_real_runs(result):
    for span in (True, False):
        for s in streaks(LEAGUE, result, span_seasons=span):
            seq = _regular_results(s.manager_id)
            i = next(i for i, (when, _) in enumerate(seq) if when == (s.start_season, s.start_week))
            run = seq[i : i + s.length]
            assert [r for _, r in run] == [result] * s.length
            assert run[-1][0] == (s.end_season, s.end_week)
            if not span:
                assert s.start_season == s.end_season
            # Maximal: the games either side break it.
            if i > 0 and (span or seq[i - 1][0][0] == s.start_season):
                assert seq[i - 1][1] != result
            nxt = i + s.length
            if nxt < len(seq) and (span or seq[nxt][0][0] == s.end_season):
                assert seq[nxt][1] != result


def test_spanning_streaks_are_at_least_as_long():
    for r in ("win", "loss"):
        assert (
            BOOK.streak[f"longest_{r}_streak"][0].length
            >= BOOK.streak[f"longest_{r}_streak_season"][0].length
        )


def test_week_totals_are_league_wide():
    weeks = week_totals(LEAGUE)
    assert len(weeks) == sum(s.settings.final_scoring_period for s in LEAGUE.seasons.values())
    top = BOOK.week["highest_scoring_week"][0]
    pts = [w.points for w in week_scores(LEAGUE.seasons[top.season]) if w.period == top.period]
    assert top.total == pytest.approx(sum(pts)) and top.teams == len(pts) == 10


def test_active_streaks_can_still_grow():
    # 2015-2025 only: the regular season is over, so nothing confined to a season is still running.
    assert not any(m.active for f in ("W", "L") for m in streaks(LEAGUE, f, span_seasons=False))
    in_2025 = {t.manager_id for t in LEAGUE.seasons[2025].teams}
    for r in ("W", "L"):
        for m in streaks(LEAGUE, r, span_seasons=True):
            if m.active:
                # Carries into next season, but only for someone still in the league.
                assert m.manager_id in in_2025 and m.end_season == 2025
    left = {"kariuki", "sedaghat", "ray", "moundous"}
    assert not any(
        m.active for r in ("W", "L") for m in streaks(LEAGUE, r, span_seasons=True) if m.manager_id in left
    )
