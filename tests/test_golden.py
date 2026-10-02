"""Golden-file tests: known-good numbers the data layer must keep producing.

Everything here runs on the committed ``data/raw/`` alone (``conftest.py`` blocks the network), so
a contributor or CI can validate the whole analytics layer offline, with no ESPN credentials.

- ``golden/standings_{2015,2021,2025}.json``: ESPN's final standings for three seasons that
  exercise different eras (ties and leagueHistory; the 14-week 2021 season; half-PPR with a
  co-owned team).
- ``golden/h2h_scratch_2015_2025.json``: every head-to-head series as computed by the original
  ``scratch_h2h.py`` before the M1 refactor (see its ``_source``).
- The identity guard (exactly 10 canonical managers per season) lives in ``test_identity.py``.
"""

import json
from pathlib import Path

import pytest

from mustafatron.espn.cache import SeasonCache
from mustafatron.stats.h2h import all_pairs, record_between
from mustafatron.transform import load_league

GOLDEN = Path(__file__).parent / "golden"
SEASONS = range(2015, 2026)


def _offline_cache() -> SeasonCache:
    def no_espn():
        raise AssertionError("a finished season tried to reach ESPN")

    return SeasonCache(client=no_espn, manager_key=no_espn)


LEAGUE = load_league(SEASONS, cache=_offline_cache())
PAIRS = all_pairs(LEAGUE.games)
SCRATCH = json.loads((GOLDEN / "h2h_scratch_2015_2025.json").read_text(encoding="utf-8"))

# Where the data layer deliberately differs from scratch_h2h.py. The scratch script compared scores;
# the model uses ESPN's result, and ESPN broke the one tied playoff score (2017 week 15, consolation
# ladder, 154-154) in Carpenter's favor. That flips one playoff "T" to a "W" in one series.
KNOWN_DIFFERENCES = {
    "carpenter|kariuki": {"wins": 7, "ties": 0, "playoff_wins": 2, "results": "LWLWWWLLLWWW"},
}

CHAMPIONS = {
    2015: "dickey",
    2016: "joyce",
    2017: "joyce",
    2018: "joyce",
    2019: "grudee",
    2020: "grudee",
    2021: "grudee",
    2022: "grudee",
    2023: "wolfe",
    2024: "grudee",
    2025: "wolfe",
}


@pytest.mark.parametrize("season", [2015, 2021, 2025])
def test_final_standings(season):
    golden = json.loads((GOLDEN / f"standings_{season}.json").read_text(encoding="utf-8"))
    teams = sorted(LEAGUE.seasons[season].teams, key=lambda t: t.final_rank)
    assert [
        {
            "rank": t.final_rank,
            "manager": t.manager_id,
            "team": t.name,
            "record": f"{t.wins}-{t.losses}-{t.ties}",
            "points_for": t.points_for,
            "points_against": t.points_against,
            "seed": t.playoff_seed,
        }
        for t in teams
    ] == golden["standings"]


def test_champions():
    assert {y: s.champion_id for y, s in LEAGUE.seasons.items()} == CHAMPIONS


def test_same_games_as_scratch():
    assert len(LEAGUE.games) == SCRATCH["games"] == 830
    assert {f"{a}|{b}" for a, b in PAIRS} == set(SCRATCH["pairs"])


@pytest.mark.parametrize("pair", sorted(SCRATCH["pairs"]))
def test_h2h_matches_scratch(pair):
    expected = {**SCRATCH["pairs"][pair], **KNOWN_DIFFERENCES.get(pair, {})}
    a, b = pair.split("|")
    p = PAIRS[(a, b)]
    last = p.meetings[-1]
    assert {
        "games": p.games,
        "wins": p.wins,
        "losses": p.losses,
        "ties": p.ties,
        "points_for": p.points_for,
        "points_against": p.points_against,
        "results": p.results,
        "longest_streak_a": p.longest_streak(a),
        "longest_streak_b": p.longest_streak(b),
        "playoff_wins": p.playoff_wins,
        "playoff_losses": p.playoff_losses,
        "last_meeting": [last.season, last.week, last.score, last.opponent_score],
    } == expected


def test_known_difference_is_the_tie_broken_playoff_game():
    scratch, ours = SCRATCH["pairs"]["carpenter|kariuki"]["results"], PAIRS[("carpenter", "kariuki")].results
    diffs = [i for i, (x, y) in enumerate(zip(scratch, ours, strict=True)) if x != y]
    assert len(diffs) == 1 and (scratch[diffs[0]], ours[diffs[0]]) == ("T", "W")
    meeting = PAIRS[("carpenter", "kariuki")].meetings[diffs[0]]
    assert (meeting.season, meeting.week, meeting.score, meeting.opponent_score) == (2017, 15, 154.0, 154.0)


def test_readable_spot_checks():
    """A few series spelled out, cross-checked by eye against the scratch_h2h.py matrix."""
    s = record_between(PAIRS, "dickey", "grudee")
    assert (s.wins, s.losses, s.ties) == (6, 17, 0)
    assert s.longest_streak("grudee") == 5
    assert (s.meetings[-1].season, s.meetings[-1].week) == (2025, 10)

    s = record_between(PAIRS, "richardson", "joyce")
    assert (s.wins, s.losses) == (13, 10)

    s = record_between(PAIRS, "edwards", "richardson")
    assert (s.wins, s.losses, s.ties) == (10, 12, 1)

    s = record_between(PAIRS, "joyce", "dickey")
    assert (s.wins, s.losses, s.ties) == (6, 8, 1)


def test_the_suite_cannot_reach_the_network():
    import requests

    with pytest.raises(RuntimeError, match="must not use the network"):
        requests.get("https://lm-api-reads.fantasy.espn.com", timeout=5)
