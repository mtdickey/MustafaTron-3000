"""All-play and luck across seasons and careers, over 2015-2025 (no network)."""

import pytest

from mustafatron.stats.allplay import all_play, career_luck, luckiest_seasons, season_luck
from mustafatron.stats.weeks import regular_season_periods
from mustafatron.transform import load_league

LEAGUE = load_league(range(2015, 2026))


def test_all_play_uses_the_team_count_from_settings():
    for s in LEAGUE.seasons.values():
        for a in all_play(s).values():
            assert a.games == len(regular_season_periods(s)) * (s.settings.team_count - 1)


def test_season_luck_lines_up_with_the_standings_and_all_play():
    lines = season_luck(LEAGUE)
    assert len(lines) == sum(len(s.teams) for s in LEAGUE.seasons.values())
    for x in lines:
        team = LEAGUE.seasons[x.season].team_of(x.manager_id)
        assert (x.wins, x.losses, x.ties) == (team.wins, team.losses, team.ties)
        assert x.luck == pytest.approx(team.win_pct - x.all_play.win_pct)
        assert x.luck_wins == pytest.approx(x.luck * x.games)


def test_luck_sums_to_about_zero_across_the_league_each_season():
    # Every H2H win is someone's loss and every all-play win too, so league-wide luck nets out.
    for season in LEAGUE.seasons:
        total = sum(x.luck_wins for x in season_luck(LEAGUE) if x.season == season)
        assert total == pytest.approx(0, abs=1e-6)


def test_careers_are_the_sum_of_their_seasons():
    by_manager = {}
    for x in season_luck(LEAGUE):
        by_manager.setdefault(x.manager_id, []).append(x)
    careers = career_luck(LEAGUE)
    assert [c.luck_wins for c in careers] == sorted((c.luck_wins for c in careers), reverse=True)
    for c in careers:
        xs = by_manager[c.manager_id]
        assert c.seasons == len(xs)
        assert c.wins == sum(x.wins for x in xs)
        assert c.all_play.wins == sum(x.all_play.wins for x in xs)
        assert c.luck_wins == pytest.approx(c.wins + c.ties / 2 - c.all_play.win_pct * c.games)


def test_luckiest_and_unluckiest_seasons():
    lucky, unlucky = luckiest_seasons(LEAGUE)
    assert len(lucky) == len(unlucky) == 10
    finished = [x for x in season_luck(LEAGUE) if x.finished]
    assert lucky[0].luck == max(x.luck for x in finished)
    assert unlucky[0].luck == min(x.luck for x in finished)
    assert all(a.luck >= b.luck for a, b in zip(lucky, lucky[1:], strict=False))
    assert lucky[-1].luck > 0 > unlucky[-1].luck
