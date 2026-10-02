"""Transforms from raw ESPN JSON to the entity model, checked against every committed season."""

from collections import defaultdict
from datetime import UTC, datetime

import pytest

from mustafatron.identity import load_managers
from mustafatron.model import Game, to_frame
from mustafatron.transform import draft_picks, games, load_league, team_name, team_seasons, transactions

SEASONS = range(2015, 2026)
LEAGUE = load_league(SEASONS)
MANAGERS = load_managers()


def test_all_seasons_load_offline():
    assert list(LEAGUE.seasons) == list(SEASONS)
    assert len(LEAGUE.games) == 830
    assert all(s.finished for s in LEAGUE.seasons.values())


@pytest.mark.parametrize("season", SEASONS)
def test_games_per_season(season):
    s = LEAGUE.seasons[season]
    assert len(s.games) == (80 if season == 2021 else 75)
    assert max(g.week for g in s.games) == s.settings.final_matchup_period
    assert all(g.is_playoff == s.settings.is_playoffs(g.week) for g in s.games)


@pytest.mark.parametrize("season", SEASONS)
def test_espn_standings_match_the_games(season):
    """ESPN's reported regular season record and points agree with the games we transformed."""
    s = LEAGUE.seasons[season]
    rec = defaultdict(lambda: [0, 0, 0, 0.0, 0.0])
    for g in s.games:
        if g.is_playoff:
            continue
        for m in (g.home_id, g.away_id):
            r = rec[m]
            r["WLT".index(g.result_for(m))] += 1
            r[3] += g.score_of(m)
            r[4] += g.score_of(g.opponent_of(m))
    for t in s.teams:
        w, losses, ties, pf, pa = rec[t.manager_id]
        assert (t.wins, t.losses, t.ties) == (w, losses, ties), t
        assert t.points_for == pytest.approx(pf, abs=0.01), t
        assert t.points_against == pytest.approx(pa, abs=0.01), t


@pytest.mark.parametrize("season", SEASONS)
def test_champion_won_the_final(season):
    s = LEAGUE.seasons[season]
    final = [g for g in s.games if g.is_championship_bracket and g.week == s.settings.final_matchup_period]
    assert len(final) == 1
    assert s.champion_id == final[0].winner_id
    assert sorted(t.final_rank for t in s.teams) == list(range(1, 11))


def test_ties():
    """Four regular season ties, all 2015-16. A tied playoff score is broken by ESPN, so it is not a tie."""
    ties = [(g.season, g.week) for g in LEAGUE.games if g.is_tie]
    assert ties == [(2015, 8), (2015, 9), (2016, 6), (2016, 11)]
    broken = [g for g in LEAGUE.games if g.final and g.home_score == g.away_score and not g.is_tie]
    assert [(g.season, g.week, g.tier, g.winner_id) for g in broken] == [
        (2017, 15, "LOSERS_CONSOLATION_LADDER", "carpenter")
    ]
    assert broken[0].result_for("kariuki") == "L"


def test_game_perspective_helpers():
    g = Game(2025, 3, "NONE", "dickey", "albert", 87.0, 84.8, final=True, winner_id="dickey")
    assert g.winner_id == "dickey"
    assert g.result_for("albert") == "L"
    assert g.opponent_of("albert") == "dickey"
    assert g.margin == pytest.approx(2.2)
    assert Game(2026, 4, "NONE", "a", "b", 40.0, 10.0, final=False).winner_id is None


def raw_season(winner="HOME", away=True):
    m1, m2 = MANAGERS["dickey"].espn_ids[0], MANAGERS["albert"].espn_ids[0]
    side = {"teamId": 2, "totalPoints": 90}
    return {
        "teams": [
            {"id": 1, "location": "Mid ", "nickname": " Tron", "primaryOwner": m1, "owners": [m1],
             "rankFinal": 0, "rankCalculatedFinal": 1, "record": {"overall": {"wins": 1, "pointsFor": 100}}},
            {"id": 2, "name": "Geno", "primaryOwner": m2, "owners": [m2], "rankCalculatedFinal": 2},
        ],
        "schedule": [
            {"matchupPeriodId": 1, "playoffTierType": "NONE", "winner": winner,
             "home": {"teamId": 1, "totalPoints": 100}, **({"away": side} if away else {})},
        ],
    }  # fmt: skip


def test_older_response_shapes():
    raw = raw_season()
    assert team_name(raw["teams"][0]) == "Mid Tron"
    t = team_seasons(raw, 2015, MANAGERS)[0]
    assert (t.manager_id, t.name, t.final_rank, t.points_for, t.acquisitions) == (
        "dickey",
        "Mid Tron",
        1,
        100.0,
        0,
    )
    g = games(raw, 2015, MANAGERS)[0]
    assert (g.home_score, g.away_score, g.winner_id) == (100.0, 90.0, "dickey")
    assert isinstance(g.home_score, float)


def test_bye_is_not_a_game():
    assert games(raw_season(away=False), 2015, MANAGERS) == []


def test_final_rank_is_unknown_until_the_season_ends():
    raw = raw_season(winner="UNDECIDED")
    assert all(t.final_rank is None for t in team_seasons(raw, 2026, MANAGERS))
    assert games(raw, 2026, MANAGERS)[0].final is False


def test_draft_picks_are_attributed_by_team_not_member():
    detail = {
        "picks": [
            {"overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "playerId": 22, "teamId": 2,
             "memberId": "not-a-manager", "keeper": False},
            {"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "playerId": 11, "teamId": 1,
             "reservedForKeeper": True},
        ]
    }  # fmt: skip
    picks = draft_picks(detail, 2025, {1: "dickey", 2: "albert"})
    assert [(p.overall_pick, p.manager_id, p.keeper) for p in picks] == [
        (1, "dickey", True),
        (2, "albert", False),
    ]


def test_transactions_keep_executed_moves_and_split_trades_by_team():
    ms = 1759334413859
    raw = [
        {"type": "WAIVER", "status": "EXECUTED", "teamId": 5, "bidAmount": 6, "scoringPeriodId": 5,
         "processDate": ms,
         "items": [{"type": "ADD", "playerId": 1, "fromTeamId": 0, "toTeamId": 5},
                   {"type": "DROP", "playerId": 2, "fromTeamId": 5, "toTeamId": 0}]},
        {"type": "WAIVER", "status": "FAILED_ROSTERLIMIT", "teamId": 5, "proposedDate": ms, "items": []},
        {"type": "TRADE_PROPOSAL", "status": "EXECUTED", "teamId": 1, "proposedDate": ms, "items": []},
        {"type": "TRADE_ACCEPT", "status": "EXECUTED", "teamId": 2, "scoringPeriodId": 6,
         "processDate": ms + 1,
         "items": [{"type": "TRADE", "playerId": 3, "fromTeamId": 1, "toTeamId": 2},
                   {"type": "TRADE", "playerId": 4, "fromTeamId": 2, "toTeamId": 1}]},
    ]  # fmt: skip
    tx = transactions(raw, 2025, {1: "dickey", 2: "albert", 5: "joyce"})
    assert [(t.type, t.manager_id, t.players_in, t.players_out, t.bid) for t in tx] == [
        ("WAIVER", "joyce", (1,), (2,), 6),
        ("TRADE", "albert", (3,), (4,), 0),
        ("TRADE", "dickey", (4,), (3,), 0),
    ]
    assert tx[0].date == datetime.fromtimestamp(ms / 1000, tz=UTC)


def test_to_frame():
    df = to_frame(LEAGUE.seasons[2025].teams)
    assert len(df) == 10 and {"manager_id", "wins", "points_for", "final_rank"} <= set(df.columns)
