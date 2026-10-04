"""The site JSON contract: offline publish validates, and schema/ is current."""

import json

import pytest

from mustafatron import contract as c
from mustafatron.publish import check, publish, stale_schemas, validate


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    files = publish(out, offline=True)
    return out, files


def test_offline_publish_writes_every_file(published):
    out, files = published
    names = {p.relative_to(out).as_posix() for p in out.rglob("*.json")}
    weeks = {n for n in names if n.startswith("weeks/")}
    assert names == set(c.FILES) | {f"seasons/{y}.json" for y in range(2015, 2026)} | weeks
    assert names == set(files)


def test_published_output_validates(published):
    out, _ = published
    assert validate(out) == []


def test_schema_dir_is_current():
    assert stale_schemas() == []


def test_check_is_what_ci_runs():
    assert check(offline=True) == []


def test_validate_catches_a_broken_file(published, tmp_path):
    out, _ = published
    bad = json.loads((out / "games.json").read_text(encoding="utf-8"))
    bad["games"][0][0] = "2015"  # a string season: strict validation does not coerce it
    (tmp_path / "games.json").write_text(json.dumps(bad), encoding="utf-8")
    errors = validate(tmp_path)
    assert any(e.startswith("games.json: ") for e in errors)
    assert "meta.json: missing" in errors


def test_games_are_positional_rows(published):
    out, _ = published
    games = json.loads((out / "games.json").read_text(encoding="utf-8"))
    assert games["columns"] == list(c.GAME_COLUMNS)
    assert len(games["games"]) == 830
    season, week, tier, home, away, hs, as_, winner = games["games"][0]
    assert (season, week, games["tiers"][tier]) == (2015, 1, "NONE")
    assert winner in (home, away, None)
    assert games["upcoming"] == []  # offline: the latest published season is finished


def test_meta_and_managers(published):
    out, _ = published
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert meta["current_season"] == 2025 and meta["current_season_finished"]
    assert meta["upcoming_week"] is None and meta["last_completed_week"] == 15
    managers = json.loads((out / "managers.json").read_text(encoding="utf-8"))["managers"]
    assert len(managers) == 14  # everyone who managed a team 2015-2025
    assert all(m["seasons"] for m in managers)


def test_season_file(published):
    out, _ = published
    s = json.loads((out / "seasons" / "2021.json").read_text(encoding="utf-8"))
    assert s["finished"] and s["champion"] == s["teams"][0]["manager"]
    assert [t["final_rank"] for t in s["teams"]] == list(range(1, 11))
    assert s["settings"]["final_week"] == 16 and len(s["games"]) == 80


def test_weekly_reports(published):
    out, _ = published
    index = json.loads((out / "weeks.json").read_text(encoding="utf-8"))
    assert index["current"] is None  # offline: no season in progress
    refs = [(w["season"], w["week"]) for w in index["weeks"]]
    assert refs == sorted(refs) and len(refs) == 166
    for season, week in refs:
        assert (out / "weeks" / str(season) / f"{week}.json").exists()
    w = json.loads((out / "weeks" / "2022" / "12.json").read_text(encoding="utf-8"))
    assert (w["label"], w["playoff"], w["periods"]) == ("Week 12", False, [12])
    assert len(w["games"]) == 5 and all(g[1] == 12 for g in w["games"])
    assert [x["manager"] for x in w["standings"]][:2] == ["joyce", "grudee"]
