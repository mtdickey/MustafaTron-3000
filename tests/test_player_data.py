"""The player-level datasets: how they are fetched and trimmed, and that the committed files hold up."""

import json
from collections import Counter, defaultdict

import pytest

from mustafatron.espn import player_data as pd_
from mustafatron.espn.cache import BOXSCORES, DRAFT, PLAYERS, RAW_DIR, TRANSACTIONS
from mustafatron.espn.player_data import FetchContext
from mustafatron.pseudonymize import find_swids

SEASONS = range(2015, 2026)
WEEKLY = range(2018, 2026)
BARE_SWID = "3436600c-3252-4b39-a933-1f7beead9084"  # how mDraftDetail sends memberId: no braces


class WeeklyClient:
    """Answers per-view, per-week requests from canned responses and records them."""

    def __init__(self, responses):
        self.responses = responses
        self.calls: list[tuple] = []

    def season(self, year, views, *, scoring_period=None, player_filter=None):
        self.calls.append((year, tuple(views), scoring_period, player_filter))
        respond = self.responses[tuple(views)[0]]
        return json.loads(json.dumps(respond(scoring_period, player_filter)))


SETTINGS_RAW = {
    "settings": {"scheduleSettings": {"matchupPeriods": {"1": [1], "2": [2], "3": [3]}}},
    "status": {"finalScoringPeriod": 3, "latestScoringPeriod": 2},
}


def context(client, finished=True, **datasets) -> FetchContext:
    loaded = {"settings": SETTINGS_RAW, **datasets}
    return FetchContext(client, 2021, finished, lambda name: loaded.get(name, {}))


def box_response(period, _):
    pool = {"appliedStatTotal": 12.345, "player": {"x": 1}}
    entry = {"playerId": 7, "lineupSlotId": 2, "playerPoolEntry": pool}
    bench = {"playerId": 8, "lineupSlotId": 20, "playerPoolEntry": {"appliedStatTotal": 3}}
    return {
        "schedule": [
            {"home": {"teamId": 2, "rosterForCurrentScoringPeriod": {"entries": [bench, entry]}},
             "away": {"teamId": 1, "rosterForCurrentScoringPeriod": {"entries": [entry]}}},
            {"home": {"teamId": 3}},  # another week's matchup: no roster
        ]
    }  # fmt: skip


def test_draft_keeps_picks_but_not_the_bare_swid():
    raw = {"draftDetail": {"drafted": True, "picks": [
        {"overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "teamId": 4, "playerId": 9,
         "memberId": BARE_SWID, "keeper": True, "owningTeamIds": [4]},
        {"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 3, "playerId": 8,
         "memberId": BARE_SWID, "keeper": False},
    ]}}  # fmt: skip
    out = pd_.fetch_draft(context(WeeklyClient({"mDraftDetail": lambda *_: raw})))
    picks = out["draftDetail"]["picks"]
    assert [p["playerId"] for p in picks] == [8, 9]
    assert picks[1] == {
        "overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "teamId": 4, "playerId": 9, "keeper": True
    }  # fmt: skip
    assert BARE_SWID not in json.dumps(out)


def test_box_scores_are_fetched_one_week_at_a_time_and_trimmed():
    client = WeeklyClient({"mBoxscore": box_response})
    out = pd_.fetch_boxscores(context(client))
    assert [c[2] for c in client.calls] == [1, 2, 3]  # every week of a finished season
    week = out["periods"][0]
    assert week["scoringPeriodId"] == 1
    assert [t["teamId"] for t in week["teams"]] == [1, 2]
    assert week["teams"][1]["entries"] == [
        {"playerId": 7, "lineupSlotId": 2, "points": 12.35},
        {"playerId": 8, "lineupSlotId": 20, "points": 3.0},
    ]


def test_a_season_in_progress_fetches_only_the_weeks_so_far():
    client = WeeklyClient({"mBoxscore": box_response})
    pd_.fetch_boxscores(context(client, finished=False))
    assert [c[2] for c in client.calls] == [1, 2]


def test_transactions_keep_executed_moves_and_trade_records():
    def respond(period, _):
        return {"transactions": [
            {"id": "w", "type": "WAIVER", "status": "EXECUTED", "scoringPeriodId": period, "teamId": 1,
             "memberId": "{11111111-2222-3333-4444-555555555555}",
             "items": [{"type": "ADD", "playerId": 5, "fromTeamId": 0, "toTeamId": 1, "isKeeper": False},
                       {"type": "LINEUP", "playerId": 6, "fromTeamId": 1, "toTeamId": 1}]},
            {"id": "f", "type": "WAIVER", "status": "FAILED_ROSTERLIMIT", "teamId": 1, "items": []},
            {"id": "p1", "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": 1,
             "items": [{"type": "TRADE", "playerId": 7, "fromTeamId": 1, "toTeamId": 2}]},
            {"id": "p2", "type": "TRADE_PROPOSAL", "status": "CANCELED", "teamId": 1, "items": []},
            {"id": "a", "type": "TRADE_ACCEPT", "status": None, "teamId": 2, "relatedTransactionId": "p1"},
            {"id": "u", "type": "TRADE_UPHOLD", "status": "EXECUTED", "relatedTransactionId": "p1"},
            {"id": "d", "type": "TRADE_DECLINE", "status": "EXECUTED", "relatedTransactionId": "p2"},
        ]}  # fmt: skip

    client = WeeklyClient({"mTransactions2": respond})
    out = pd_.fetch_transactions(context(client))
    assert [c[2] for c in client.calls] == [0, 1, 2, 3]  # week 0: before the season starts
    by_id = {t["id"]: t for t in out["transactions"]}
    assert set(by_id) == {"w", "p1", "a", "u"}
    assert by_id["w"]["items"] == [{"type": "ADD", "playerId": 5, "fromTeamId": 0, "toTeamId": 1}]
    assert "memberId" not in by_id["w"]


def test_players_are_the_ones_the_other_files_mention():
    def line(season, source, split, period, total):
        return {"seasonId": season, "statSourceId": source, "statSplitTypeId": split,
                "scoringPeriodId": period, "appliedTotal": total}  # fmt: skip

    stats = [
        line(2021, 0, 0, 0, 100),  # actual, season total
        line(2021, 0, 1, 2, 9.5),  # actual, week 2
        line(2021, 1, 1, 2, 11),  # projected
        line(2020, 0, 0, 0, 50),  # another season
    ]

    def respond(_, flt):
        ids = flt["players"]["filterIds"]["value"]
        player = {"fullName": "P", "defaultPositionId": 2, "ownership": {"x": 1}, "stats": stats}
        return {"players": [{"player": {**player, "id": i, "fullName": f"P{i}"}} for i in ids]}

    client = WeeklyClient({"kona_player_info": respond})
    draft = {"draftDetail": {"picks": [{"playerId": i} for i in range(150)]}}
    tx = {"transactions": [{"items": [{"playerId": 999}]}]}
    out = pd_.fetch_players(context(client, draft=draft, transactions=tx))
    assert [len(c[3]["players"]["filterIds"]["value"]) for c in client.calls] == [100, 51]
    assert client.calls[0][3]["players"]["filterStatsForTopScoringPeriodIds"]["additionalValue"] == ["002021"]
    assert out["players"][0] == {
        "id": 0,
        "fullName": "P0",
        "defaultPositionId": 2,
        "appliedTotalByScoringPeriod": {"0": 100.0, "2": 9.5},  # actual only, this season only
    }


# The committed files ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def league(player_league):
    return player_league


def raw(season: int, name: str) -> dict:
    return json.loads((RAW_DIR / str(season) / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("season", SEASONS)
def test_every_season_has_a_draft_and_player_totals(season):
    present = {p.stem for p in (RAW_DIR / str(season)).glob("*.json")}
    weekly = {"boxscores", "transactions"} if season >= pd_.WEEKLY_SINCE else set()
    assert present == {"matchups", "settings", "draft", "players"} | weekly


@pytest.mark.parametrize("season", SEASONS)
def test_no_member_ids_are_committed(season):
    for name in ("draft", "boxscores", "transactions", "players"):
        path = RAW_DIR / str(season) / f"{name}.json"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert "memberId" not in text and find_swids(json.loads(text)) == 0


def test_drafts(league):
    for s in league.seasons.values():
        assert len(s.draft) == s.settings.team_count * 16
        assert all(s.players[p.player_id].season_points is not None for p in s.draft)
    # Keepers started in 2024 and ESPN flags them on the pick: the M5 keeper history backfill.
    assert {y: sum(p.keeper for p in s.draft) for y, s in league.seasons.items() if y >= 2023} == {
        2023: 0,
        2024: 21,
        2025: 26,
    }


@pytest.mark.parametrize("season", WEEKLY)
def test_starters_add_up_to_the_team_score_every_week(league, season):
    s = league.seasons[season]
    starters: dict[tuple[str, int], float] = defaultdict(float)
    for w in s.player_weeks:
        if w.starter:
            starters[(w.manager_id, w.period)] += w.points
    for g in s.games:
        for period, home, away in g.period_scores:
            assert starters[(g.home_id, period)] == pytest.approx(home, abs=0.01)
            assert starters[(g.away_id, period)] == pytest.approx(away, abs=0.01)


@pytest.mark.parametrize("season", WEEKLY)
def test_box_scores_agree_with_player_stat_lines(league, season):
    s = league.seasons[season]
    differ = [w for w in s.player_weeks if abs(s.players[w.player_id].points_in(w.period) - w.points) > 0.01]
    assert len(differ) <= 1  # a stat correction ESPN applied to one copy and not the other


@pytest.mark.parametrize("season", WEEKLY)
def test_every_team_has_a_full_roster_every_week(league, season):
    s = league.seasons[season]
    per_team_week = Counter((w.manager_id, w.period) for w in s.player_weeks)
    assert {w for _, w in per_team_week} == set(range(1, s.settings.final_scoring_period + 1))
    assert len(per_team_week) == s.settings.team_count * s.settings.final_scoring_period
    assert all(12 <= n <= 18 for n in per_team_week.values())


# Two trades in 2022 passed a player through a third team inside one week (Tyler Lockett went
# Carpenter -> Edwards -> Richardson in week 10). Weekly rosters can't see the middle hop, so those
# show as direct moves: each team's net players are still right, but the per-team trade counts drift.
TRADE_COUNT_DRIFT = {2022: {"grudee": -1, "edwards": 1, "richardson": 1, "carpenter": 1}}


@pytest.mark.parametrize("season", WEEKLY)
def test_trades_found_from_rosters_match_espns_counts(league, season):
    s = league.seasons[season]
    found = Counter(t.manager_id for t in s.trades)
    drift = {t.manager_id: found[t.manager_id] - t.trades for t in s.teams if found[t.manager_id] != t.trades}
    assert drift == TRADE_COUNT_DRIFT.get(season, {})


@pytest.mark.parametrize("season", WEEKLY)
def test_trade_sides_mirror_each_other(league, season):
    by_trade = defaultdict(list)
    for t in league.seasons[season].trades:
        by_trade[t.id].append(t)
    for sides in by_trade.values():
        assert len(sides) == 2
        a, b = sides
        assert set(a.players_in) == set(b.players_out) and set(a.players_out) == set(b.players_in)
        assert a.scoring_period == b.scoring_period and a.date == b.date


@pytest.mark.parametrize("season", WEEKLY)
def test_adds_match_espns_acquisition_counts_closely(league, season):
    s = league.seasons[season]
    adds = Counter(m for t in s.transactions if t.type != "TRADE" for m in [t.manager_id] * len(t.players_in))
    # Exact through 2022. From 2023 ESPN's counter runs 1-3 short for a few teams, always low.
    for team in s.teams:
        assert 0 <= adds[team.manager_id] - team.acquisitions <= (0 if season <= 2022 else 3)


def test_datasets_are_registered_for_fetch():
    assert (DRAFT.since, PLAYERS.since) == (None, None)
    assert BOXSCORES.since == TRANSACTIONS.since == pd_.WEEKLY_SINCE == 2018
