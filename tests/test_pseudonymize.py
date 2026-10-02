from mustafatron.pseudonymize import MANAGER_ID_RE, find_swids, manager_id, pseudonymize, scrub_season

KEY = b"test-key"
SWID_A = "{11111111-2222-3333-4444-555555555555}"
SWID_B = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"


def test_manager_id_is_stable_and_opaque():
    mid = manager_id(SWID_A, KEY)
    assert MANAGER_ID_RE.match(mid)
    assert mid == manager_id(SWID_A.lower(), KEY)
    assert mid != manager_id(SWID_B, KEY)
    assert mid != manager_id(SWID_A, b"other-key")


def test_pseudonymize_replaces_swids_at_any_depth():
    season = {
        "members": [{"id": SWID_A, "firstName": "Mustafa"}],
        "teams": [{"id": 1, "primaryOwner": SWID_A, "owners": [SWID_A, SWID_B]}],
        "schedule": [{"home": {"teamId": 1}, "winner": "HOME"}],
    }
    out = pseudonymize(season, KEY)
    assert find_swids(out) == 0
    assert out["members"][0]["id"] == out["teams"][0]["primaryOwner"] == out["teams"][0]["owners"][0]
    assert out["members"][0]["firstName"] == "Mustafa"
    assert out["schedule"] == season["schedule"]
    assert find_swids(season) == 4  # input untouched


def test_scrub_season_drops_private_member_fields():
    out = scrub_season({"members": [{"id": SWID_A, "notificationSettings": [{"id": "x"}]}]}, KEY)
    assert out["members"] == [{"id": manager_id(SWID_A, KEY)}]
