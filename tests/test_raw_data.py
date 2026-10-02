"""Guards on the committed data/raw/ seed."""

import json
from pathlib import Path

import pytest

from mustafatron.pseudonymize import MANAGER_ID_RE, find_swids

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
SEASONS = range(2015, 2026)
FILES = sorted(RAW.glob("*/*.json"))


def test_every_completed_season_is_present():
    assert [int(p.name) for p in sorted(RAW.iterdir()) if p.is_dir()] == list(SEASONS)


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_swid_or_private_field_is_committed(path):
    text = path.read_text(encoding="utf-8")
    assert "notificationSettings" not in text
    assert find_swids(json.loads(text)) == 0


@pytest.mark.parametrize("season", SEASONS)
def test_matchups_shape(season):
    data = json.loads((RAW / str(season) / "matchups.json").read_text(encoding="utf-8"))
    assert set(data) == {"members", "teams", "schedule"}
    assert len(data["teams"]) == 10
    assert all(MANAGER_ID_RE.match(m["id"]) for m in data["members"])
    member_ids = {m["id"] for m in data["members"]}
    assert all(t["primaryOwner"] in member_ids for t in data["teams"])
    assert data["schedule"]
