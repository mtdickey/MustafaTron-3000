"""mSettings parsed for every committed season, and cross-checked against that season's schedule."""

import json
from pathlib import Path

import pytest

from mustafatron.league_settings import load_settings

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
SEASONS = range(2015, 2026)
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "RB/WR/TE": 1, "D/ST": 1, "K": 1}


def schedule(season: int) -> list[dict]:
    return json.loads((RAW / str(season) / "matchups.json").read_text(encoding="utf-8"))["schedule"]


@pytest.mark.parametrize("season", SEASONS)
def test_settings_agree_with_the_schedule(season):
    s, games = load_settings(season), schedule(season)
    assert s.season == season
    assert s.team_count == 10
    assert s.final_matchup_period == max(g["matchupPeriodId"] for g in games)
    for g in games:
        mp = g["matchupPeriodId"]
        assert s.is_playoffs(mp) == (g["playoffTierType"] != "NONE"), (season, mp)
        for side in ("home", "away"):
            weeks = {int(w) for w in g[side].get("pointsByScoringPeriod", {})}
            assert weeks <= set(s.scoring_periods(mp)), (season, mp, weeks)
    bracket = {
        g[side]["teamId"]
        for g in games
        if g["playoffTierType"] == "WINNERS_BRACKET"
        for side in ("home", "away")
    }
    assert len(bracket) == s.playoff_team_count


@pytest.mark.parametrize("season", SEASONS)
def test_known_league_structure(season):
    s = load_settings(season)
    assert s.starter_slots == STARTERS
    assert s.bench_slots == 7
    assert s.playoff_team_count == 4
    assert s.playoff_matchup_length == 2
    if season == 2021:  # the NFL's first 18-week season; this league added a regular season week
        assert (s.regular_season_matchups, s.final_matchup_period, s.final_scoring_period) == (14, 16, 18)
    else:
        assert (s.regular_season_matchups, s.final_matchup_period, s.final_scoring_period) == (13, 15, 17)
    assert s.points_per_reception == (0.5 if season >= 2023 else 0.0)
    assert s.draft_type == "SNAKE"
    assert s.draft_date is not None and s.draft_date.year == season


def test_matchup_period_mapping():
    s = load_settings(2025)
    assert s.scoring_periods(13) == (13,)
    assert s.scoring_periods(15) == (16, 17)
    assert s.matchup_period_of(17) == 15
    assert list(s.playoff_matchup_periods) == [14, 15]
    with pytest.raises(ValueError):
        s.matchup_period_of(18)


def test_matchup_weeks_are_in_order():
    # ESPN lists 2021's first playoff matchup as [16, 15]; the season grid relies on order.
    assert load_settings(2021).scoring_periods(15) == (15, 16)
    for season in range(2015, 2026):
        assert all(list(w) == sorted(w) for w in load_settings(season).matchup_periods.values())
