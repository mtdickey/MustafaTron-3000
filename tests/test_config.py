import pytest

from mustafatron.config import DEFAULT_LEAGUE_ID, MissingSecretError, Settings

SWID = "{11111111-2222-3333-4444-555555555555}"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("LEAGUE_ID", "ESPN_SWID", "ESPN_S2", "MANAGER_ID_KEY"):
        monkeypatch.delenv(var, raising=False)


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_defaults_to_the_hub_league():
    assert settings().league_id == DEFAULT_LEAGUE_ID


def test_league_id_from_env(monkeypatch):
    monkeypatch.setenv("LEAGUE_ID", "651125867")
    assert settings().league_id == 651125867


def test_reads_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"ESPN_SWID={SWID}\nESPN_S2=abc\nLEAGUE_ID=1158588190\n")
    s = Settings(_env_file=env)
    assert s.league_id == 1158588190
    assert s.espn_cookies() == {"swid": SWID, "espn_s2": "abc"}


@pytest.mark.parametrize("raw", ["AE%2Bqw7O%2Fg3%3D", "AE+qw7O/g3="])
def test_espn_s2_is_url_decoded_once(raw):
    s = settings(espn_swid=SWID, espn_s2=raw)
    assert s.espn_cookies()["espn_s2"] == "AE+qw7O/g3="


def test_swid_gets_braces_and_upper_case():
    s = settings(espn_swid=SWID.strip("{}").lower(), espn_s2="x")
    assert s.espn_cookies()["swid"] == SWID


def test_missing_cookies_raise_a_helpful_error():
    with pytest.raises(MissingSecretError, match=".env.example"):
        settings().espn_cookies()


def test_secrets_are_masked_in_repr():
    s = settings(espn_swid=SWID, espn_s2="supersecret", manager_id_key="k")
    assert "supersecret" not in repr(s)
    assert SWID not in repr(s)
