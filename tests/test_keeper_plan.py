"""The keeper planner: ESPN's current rosters (mRoster), the plan built from them, and the fallback."""

from dataclasses import replace

import pytest

from mustafatron.espn.client import EspnAuthError, EspnError
from mustafatron.espn.rosters import RosterFetchError, compare, fetch_rosters, parse_rosters
from mustafatron.keeper_engine import end_of_season_rosters
from mustafatron.keepers import load_keeper_history
from mustafatron.model import League
from mustafatron.publish import _keeper_rosters, roster_report
from mustafatron.rules import load_rules
from mustafatron.stats.keepers import keeper_plan, plan_seasons

HISTORY = load_keeper_history()
RULES = load_rules()
SWID = "{11111111-2222-3333-4444-555555555555}"


def fake_mroster(league, season=2025, extra=None, team_ids=None):
    """An mTeam + mRoster response with every team's roster as the season ended, plus ``extra``
    (player id -> (manager, name, ESPN position id)) to stand in for moves since."""
    s = league.seasons[season]
    owner = end_of_season_rosters(s)
    for pid, (mid, *_rest) in (extra or {}).items():
        owner[pid] = mid
    teams = []
    for t in s.teams:
        mine = sorted(p for p, m in owner.items() if m == t.manager_id)
        entries = []
        for pid in mine:
            name, pos = (extra or {}).get(pid, (None, s.players[pid].name, 2))[1:]
            entries.append(
                {"playerId": pid, "playerPoolEntry": {"player": {"fullName": name, "defaultPositionId": pos}}}
            )
        manager = league.managers[t.manager_id]
        teams.append({"id": t.team_id, "primaryOwner": manager.espn_ids[0], "roster": {"entries": entries}})
    return {"teams": teams[:team_ids] if team_ids else teams, "members": []}


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def season(self, season, views, **kwargs):
        self.calls.append((season, [str(v) for v in views]))
        if self.error:
            raise self.error
        return self.response


def test_parse_rosters(player_league):
    rosters = parse_rosters(fake_mroster(player_league), player_league.managers)
    assert len({e.manager_id for e in rosters.values()}) == 10
    collins = rosters[4258173]
    assert (collins.name, collins.manager_id, collins.position) == ("Nico Collins", "joyce", "RB")


def test_fetch_asks_for_teams_and_rosters_and_scrubs_swids(player_league):
    raw = fake_mroster(player_league)
    raw["members"] = [{"id": SWID, "firstName": "X"}]
    client = FakeClient(raw)
    rosters = fetch_rosters(client, 2025, player_league.managers, b"k")
    assert client.calls == [(2025, ["mTeam", "mRoster"])]
    assert len(rosters) == len(end_of_season_rosters(player_league.seasons[2025]))


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda r: r.update(teams=[]), "no teams"),
        (
            lambda r: r["teams"][0]["roster"].update(entries=r["teams"][0]["roster"]["entries"][:3]),
            "has 3 players",
        ),
        (
            lambda r: r["teams"][1]["roster"]["entries"].append(r["teams"][0]["roster"]["entries"][0]),
            "two rosters",
        ),
    ],
)
def test_sanity_checks(player_league, break_it, message):
    raw = fake_mroster(player_league)
    break_it(raw)
    with pytest.raises(RosterFetchError, match=message):
        parse_rosters(raw, player_league.managers)


def test_compare():
    assert compare({1: "a", 2: "b", 3: "c"}, {1: "a", 2: "c", 4: "d"}) == {
        "added": [3],
        "dropped": [4],
        "moved": [2],
    }


def test_plan_from_committed_data(player_league):
    """Offline, data/raw/ ends with 2025, so the plan is for the 2026 draft from how 2025 ended."""
    assert plan_seasons(player_league) == (2026, 2025)
    plan = keeper_plan(player_league, HISTORY, RULES)
    assert (plan.season, plan.from_season, plan.from_season_finished) == (2026, 2025, True)
    assert (plan.rosters, plan.rosters_as_of, plan.slots, plan.min_round, plan.max_consecutive) == (
        "season_end",
        None,
        3,
        4,
        3,
    )
    teams = {t.manager: t for t in plan.teams}
    assert set(teams) == {m.id for m in player_league.managers if m.active_in(2026)}  # Alligood, not Wilkins
    assert teams["alligood"].name == "Brian Alligood"
    albert = {p.player: p for p in teams["albert"].players}
    assert (albert["Rome Odunze"].cost, albert["Rome Odunze"].kept_in_a_row) == (8, 1)
    assert albert["Lamar Jackson"].cost is None and "round 3" in albert["Lamar Jackson"].reason
    costs = [p.cost for p in teams["albert"].players]
    eligible = [c for c in costs if c is not None]
    assert eligible == sorted(eligible) and costs[: len(eligible)] == eligible  # keepable first, by cost


def test_plan_from_espn_rosters_includes_moves_since(player_league):
    """Grudee picked up Jordan Addison (2025 round 9) after the last move on file: ESPN's rosters
    have him, so he is keepable at round 8, like the 2026 sheet said."""
    addison = next(
        p.player_id for p in player_league.seasons[2025].draft if p.round == 9 and p.round_pick == 2
    )
    end = end_of_season_rosters(player_league.seasons[2025])
    assert addison not in end or end[addison] != "grudee"
    raw = fake_mroster(player_league, extra={addison: ("grudee", "Jordan Addison", 3)})
    rosters = parse_rosters(raw, player_league.managers)
    plan = keeper_plan(player_league, HISTORY, RULES, rosters, "2026-07-05")
    assert (plan.rosters, plan.rosters_as_of) == ("espn", "2026-07-05")
    grudee = {p.player: p for t in plan.teams if t.manager == "grudee" for p in t.players}
    assert grudee["Jordan Addison"].cost == 8 and grudee["Jordan Addison"].position == "WR"
    report = roster_report(player_league, 2025, rosters)
    assert "ESPN 2025, 10 teams" in report and "Jordan Addison (grudee)" in report


def test_plan_before_the_new_seasons_draft(player_league):
    """ESPN has the new season but it hasn't drafted: plan that draft, from the season before."""
    seasons = dict(player_league.seasons)
    seasons[2026] = replace(seasons[2025], season=2026, draft=[])
    league = League(player_league.managers, seasons)
    assert plan_seasons(league) == (2026, 2025)


class FakeCache:
    def __init__(self, error=None, rosters=None):
        self.error, self._rosters = error, rosters

    def rosters(self, season, managers):
        if self.error:
            raise self.error
        return self._rosters


@pytest.mark.parametrize("error", [EspnError("timed out"), RosterFetchError("team 3 has 2 players")])
def test_a_failed_fetch_falls_back_to_season_end_with_a_warning(player_league, capsys, error):
    assert _keeper_rosters(FakeCache(error), player_league) is None
    assert "::warning::keeper rosters:" in capsys.readouterr().out


def test_expired_cookies_still_fail_the_build(player_league):
    with pytest.raises(EspnAuthError):
        _keeper_rosters(FakeCache(EspnAuthError("401")), player_league)


def test_a_good_fetch_is_reported(player_league, capsys):
    rosters = parse_rosters(fake_mroster(player_league), player_league.managers)
    assert _keeper_rosters(FakeCache(rosters=rosters), player_league) is rosters
    out = capsys.readouterr().out
    assert "keeper rosters: ESPN 2025, 10 teams" in out
    assert "added since the last move on file: 0" in out
