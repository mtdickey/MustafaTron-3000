"""Canonical manager identity, checked against every committed season."""

import json
from pathlib import Path

import pytest

from mustafatron.identity import UnknownManagerError, load_managers, parse_managers

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
SEASONS = range(2015, 2026)
MANAGERS = load_managers()


def season(year: int) -> dict:
    return json.loads((RAW / str(year) / "matchups.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("year", SEASONS)
def test_exactly_ten_canonical_managers_per_season(year):
    """The guard that catches a duplicate ESPN account before it splits a career in the record book."""
    data = season(year)
    managers = MANAGERS.season_managers(data)
    assert len(managers) == len(data["teams"]) == 10
    assert len(set(managers.values())) == 10


@pytest.mark.parametrize("year", SEASONS)
def test_every_member_resolves(year):
    for member in season(year)["members"]:
        MANAGERS.resolve(member["id"])


@pytest.mark.parametrize("year", SEASONS)
def test_seasons_active_match_the_data(year):
    managing = set(MANAGERS.season_managers(season(year)).values())
    assert managing == set(MANAGERS.active_in(year))


@pytest.mark.parametrize("year", SEASONS)
def test_no_co_managers_only_second_accounts(year):
    """Every multi-owner team so far is one person with two accounts, not a real co-ownership."""
    for team in season(year)["teams"]:
        assert MANAGERS.co_managers(team) == []


def test_second_accounts_resolve_to_the_same_person():
    ryan = MANAGERS["richardson"]
    assert len(ryan.espn_ids) == 2
    assert {MANAGERS.resolve(i) for i in ryan.espn_ids} == {ryan}
    team = next(t for t in season(2025)["teams"] if len(t["owners"]) == 2)
    assert MANAGERS.team_manager(team) == ryan


def test_names_are_canonical_not_espn():
    assert MANAGERS["grudee"].name == "Jon Grudee"  # ESPN: "jon grudee"
    assert MANAGERS.by_name("jon  grudee") == MANAGERS.by_name("Jonathan Grudee") == MANAGERS["grudee"]
    assert MANAGERS.by_name("Matthew Albert").short_name == "Matt A."
    assert MANAGERS.by_name("Matthew Carpenter").short_name == "Matt C."


def test_names_and_short_names_are_unique():
    assert len({m.name for m in MANAGERS}) == len(MANAGERS)
    assert len({m.short_name for m in MANAGERS}) == len(MANAGERS)


def test_unknown_member_fails_loudly_with_a_fix():
    with pytest.raises(UnknownManagerError, match="managers.yml"):
        MANAGERS.resolve("m_0000000000000000")
    with pytest.raises(UnknownManagerError):
        MANAGERS.by_name("Mustafa Greene")


def test_season_spec_and_activity():
    m = parse_managers(
        {
            "managers": {
                "a": {"name": "A", "short_name": "A", "espn_ids": ["m_1"], "seasons": "2016-"},
                "b": {"name": "B", "short_name": "B", "espn_ids": ["m_2"], "seasons": "2015-2021"},
                "c": {"name": "C", "short_name": "C", "espn_ids": ["m_3"], "seasons": 2015},
            }
        }
    )
    assert [x.id for x in m.active_in(2015)] == ["b", "c"]
    assert [x.id for x in m.active_in(2030)] == ["a"]


def test_an_espn_id_cannot_belong_to_two_people():
    doc = {
        "managers": {
            "a": {"name": "A", "short_name": "A", "espn_ids": ["m_1"], "seasons": "2015-"},
            "b": {"name": "B", "short_name": "B", "espn_ids": ["m_1"], "seasons": "2015-"},
        }
    }
    with pytest.raises(ValueError, match="m_1"):
        parse_managers(doc)
