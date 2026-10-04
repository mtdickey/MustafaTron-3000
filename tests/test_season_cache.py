import json
from datetime import date

import pytest

from mustafatron.cli import parse_seasons
from mustafatron.espn.cache import MATCHUPS as MATCHUPS_DS
from mustafatron.espn.cache import RAW_DIR, Dataset, SeasonCache, is_complete, latest_season
from mustafatron.espn.client import EspnAuthError, SeasonNotFoundError, View
from mustafatron.pseudonymize import MANAGER_ID_RE

SWID = "{11111111-2222-3333-4444-555555555555}"
SETTINGS = Dataset("settings", (View.SETTINGS,), ("settings",))


def season(*winners: str) -> dict:
    return {
        "members": [{"id": SWID, "firstName": "Mustafa", "notificationSettings": [{"id": 1}]}],
        "teams": [{"id": 1, "primaryOwner": SWID}],
        "schedule": [{"matchupPeriodId": i + 1, "winner": w} for i, w in enumerate(winners)],
        "settings": {"size": 10},
        "draftDetail": {"drafted": True},  # not kept by either dataset
    }


class FakeClient:
    def __init__(self, seasons: dict[int, dict]):
        self.seasons = seasons
        self.calls: list[tuple[int, tuple]] = []

    def season(self, year, views, *, scoring_period=None, player_filter=None):
        self.calls.append((year, tuple(views)))
        if year not in self.seasons:
            raise SeasonNotFoundError(str(year))
        return json.loads(json.dumps(self.seasons[year]))


def make_cache(tmp_path, seasons) -> tuple[SeasonCache, FakeClient]:
    client = FakeClient(seasons)
    return SeasonCache(tmp_path, client=lambda: client, manager_key=lambda: b"k"), client


def offline_cache(tmp_path) -> SeasonCache:
    def no_network():
        raise AssertionError("tried to reach ESPN")

    return SeasonCache(tmp_path, client=no_network, manager_key=no_network)


def test_is_complete():
    assert is_complete(season("HOME", "AWAY", "TIE"))
    assert not is_complete(season("HOME", "UNDECIDED"))
    assert not is_complete(season())  # no schedule yet (offseason, pre-draft)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 2), 2026),
        (date(2026, 8, 1), 2026),
        (date(2026, 7, 31), 2025),
        (date(2027, 1, 15), 2026),
    ],
)
def test_latest_season(today, expected):
    assert latest_season(today) == expected


def test_finished_season_is_fetched_once_scrubbed_and_written(tmp_path):
    cache, client = make_cache(tmp_path, {2024: season("HOME", "AWAY")})
    data = cache.load(2024)
    assert set(data) == {"members", "teams", "schedule"}
    assert MANAGER_ID_RE.match(data["members"][0]["id"])
    assert "notificationSettings" not in data["members"][0]
    written = json.loads((tmp_path / "2024" / "matchups.json").read_text(encoding="utf-8"))
    assert written == data
    assert list((tmp_path / "2024").iterdir()) == [tmp_path / "2024" / "matchups.json"]  # no temp files

    # From now on it never touches the network, even from a brand new cache.
    assert offline_cache(tmp_path).load(2024) == data
    assert len(client.calls) == 1


def test_season_in_progress_is_live_and_never_written(tmp_path):
    cache, client = make_cache(tmp_path, {2026: season("HOME", "UNDECIDED")})
    assert cache.load_with_source(2026)[1] == "live"
    assert cache.load_with_source(2026)[1] == "live"
    assert len(client.calls) == 1  # memoized within one run
    assert not (tmp_path / "2026").exists()

    cache2, client2 = make_cache(tmp_path, {2026: season("HOME", "UNDECIDED")})
    cache2.load(2026)
    assert len(client2.calls) == 1  # but a new run fetches again


def test_unfinished_file_on_disk_is_not_trusted(tmp_path):
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "matchups.json").write_text(json.dumps(season("UNDECIDED")), encoding="utf-8")
    cache, _ = make_cache(tmp_path, {2026: season("HOME", "AWAY")})
    assert cache.load_with_source(2026)[1] == "fetched"
    assert is_complete(json.loads((tmp_path / "2026" / "matchups.json").read_text(encoding="utf-8")))


def test_refresh_refetches_and_overwrites_a_finished_season(tmp_path):
    cache, client = make_cache(tmp_path, {2019: season("HOME")})
    cache.load(2019)
    client.seasons[2019] = season("AWAY")  # ESPN corrected history
    assert cache.load(2019)["schedule"][0]["winner"] == "HOME"
    assert cache.load(2019, refresh=True)["schedule"][0]["winner"] == "AWAY"
    assert offline_cache(tmp_path).load(2019)["schedule"][0]["winner"] == "AWAY"


def test_other_datasets_freeze_with_the_season(tmp_path):
    cache, _ = make_cache(tmp_path, {2025: season("HOME"), 2026: season("UNDECIDED")})
    assert cache.load(2025, SETTINGS) == {"settings": {"size": 10}}
    assert (tmp_path / "2025" / "settings.json").exists()
    assert cache.load_with_source(2026, SETTINGS)[1] == "live"
    assert not (tmp_path / "2026").exists()


def test_backfill_resumes_where_it_left_off(tmp_path):
    seasons = {y: season("HOME") for y in (2015, 2016, 2017)}
    cache, _ = make_cache(tmp_path, {2015: seasons[2015]})  # ESPN "fails" after 2015
    report = cache.backfill([2015, 2016, 2017])
    assert report[0] == (2015, "matchups", "fetched")
    assert report[1][2].startswith("error") and report[2][2].startswith("error")

    cache, client = make_cache(tmp_path, seasons)
    assert cache.backfill([2015, 2016, 2017]) == [
        (2015, "matchups", "cached"),
        (2016, "matchups", "fetched"),
        (2017, "matchups", "fetched"),
    ]
    assert [y for y, _ in client.calls] == [2016, 2017]


def test_backfill_stops_on_expired_cookies(tmp_path):
    class Expired(FakeClient):
        def season(self, year, views, **kwargs):
            self.calls.append((year, tuple(views)))
            raise EspnAuthError("401")

    client = Expired({})
    cache = SeasonCache(tmp_path, client=lambda: client, manager_key=lambda: b"k")
    with pytest.raises(EspnAuthError):
        cache.backfill([2015, 2016, 2017])
    assert len(client.calls) == 1  # no point asking again with the same cookies


def test_backfill_refresh_only_touches_named_seasons(tmp_path):
    cache, _ = make_cache(tmp_path, {2015: season("HOME"), 2016: season("HOME")})
    cache.backfill([2015, 2016])
    cache, client = make_cache(tmp_path, {2015: season("HOME"), 2016: season("HOME")})
    assert [o for *_, o in cache.backfill([2015, 2016], refresh=[2016])] == ["cached", "fetched"]
    assert [y for y, _ in client.calls] == [2016]


def test_dataset_espn_does_not_serve_that_far_back_is_never_fetched(tmp_path):
    late = Dataset("late", (View.BOXSCORE,), ("schedule",), since=2018)
    cache, client = make_cache(tmp_path, {2017: season("HOME")})
    assert cache.load_with_source(2017, late) == ({}, "unavailable")
    assert client.calls == []
    assert cache.backfill([2017], [late]) == [(2017, "late", "unavailable")]


def test_refresh_refetches_each_dataset_once_per_run(tmp_path):
    cache, client = make_cache(tmp_path, {2019: season("HOME")})
    cache.backfill([2019], [MATCHUPS_DS, SETTINGS])
    cache, client = make_cache(tmp_path, {2019: season("AWAY")})
    cache.backfill([2019], [MATCHUPS_DS, SETTINGS], refresh=[2019])
    # matchups once (not again when settings checks whether the season is finished), settings once
    assert client.calls == [(2019, ("mTeam", "mMatchupScore")), (2019, ("mSettings",))]


def test_committed_seasons_load_offline():
    cache = offline_cache(RAW_DIR)
    for year in range(2015, 2026):
        assert cache.is_frozen(year)
        assert len(cache.load(year)["teams"]) == 10


@pytest.mark.parametrize(
    ("spec", "seasons"),
    [("2019", [2019]), ("2015-2017", [2015, 2016, 2017]), ("2021,2015-2016", [2015, 2016, 2021])],
)
def test_parse_seasons(spec, seasons):
    assert parse_seasons(spec) == seasons
