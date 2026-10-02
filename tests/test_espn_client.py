import pytest
import requests
from requests.cookies import RequestsCookieJar

from mustafatron.espn.client import (
    BASE_URL,
    EspnAuthError,
    EspnClient,
    EspnError,
    SeasonNotFoundError,
    View,
    season_endpoint,
)

LEAGUE = 763471


class FakeResponse:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Plays back a scripted list of responses (or exceptions) and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []
        self.cookies = RequestsCookieJar()

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(*responses, **kwargs) -> tuple[EspnClient, FakeSession, list[float]]:
    session, sleeps = FakeSession(*responses), []
    c = EspnClient(LEAGUE, {"swid": "{X}", "espn_s2": "s2"}, session=session, sleep=sleeps.append, **kwargs)
    return c, session, sleeps


def test_endpoint_cutover_at_2018():
    assert season_endpoint(LEAGUE, 2018) == (f"{BASE_URL}/seasons/2018/segments/0/leagues/{LEAGUE}", {})
    assert season_endpoint(LEAGUE, 2017) == (f"{BASE_URL}/leagueHistory/{LEAGUE}", {"seasonId": 2017})


def test_season_requests_views_and_sets_cookies():
    c, session, _ = client(FakeResponse(200, {"seasonId": 2024, "teams": []}))
    assert c.season(2024, [View.TEAM, "mMatchupScore"]) == {"seasonId": 2024, "teams": []}
    url, params = session.calls[0]
    assert url.endswith(f"/seasons/2024/segments/0/leagues/{LEAGUE}")
    assert params == {"view": ["mTeam", "mMatchupScore"]}
    assert session.cookies.get("espn_s2") == "s2"


def test_league_history_list_is_unwrapped():
    c, session, _ = client(FakeResponse(200, [{"seasonId": 2016}]))
    assert c.season(2016, [View.SETTINGS]) == {"seasonId": 2016}
    assert session.calls[0][1] == {"seasonId": 2016, "view": ["mSettings"]}


def test_empty_league_history_is_not_found():
    c, *_ = client(FakeResponse(200, []))
    with pytest.raises(SeasonNotFoundError):
        c.season(2014, [View.TEAM])


def test_404_is_not_found():
    c, *_ = client(FakeResponse(404, {}))
    with pytest.raises(SeasonNotFoundError):
        c.season(2030, [View.TEAM])


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_cookies_raise_an_actionable_error_without_retrying(status):
    c, session, sleeps = client(FakeResponse(status, {"messages": ["not authorized"]}))
    with pytest.raises(EspnAuthError, match="espn_s2 expires") as e:
        c.season(2025, [View.TEAM])
    assert "ESPN_S2" in str(e.value)
    assert len(session.calls) == 1 and sleeps == []


def test_server_errors_and_dropped_connections_are_retried_with_backoff():
    c, session, sleeps = client(
        FakeResponse(503),
        requests.ConnectionError("reset"),
        FakeResponse(500),
        FakeResponse(200, {"seasonId": 2025}),
        backoff=0.5,
    )
    assert c.season(2025, [View.TEAM]) == {"seasonId": 2025}
    assert len(session.calls) == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_gives_up_after_the_retry_budget():
    c, session, _ = client(*[FakeResponse(502)] * 3, retries=2)
    with pytest.raises(EspnError, match="after 3 attempts"):
        c.season(2025, [View.TEAM])
    assert len(session.calls) == 3


def test_other_errors_are_not_retried():
    c, session, _ = client(FakeResponse(400, text="bad view"))
    with pytest.raises(EspnError, match="HTTP 400"):
        c.season(2025, ["mNope"])
    assert len(session.calls) == 1


def test_non_json_body_is_an_error():
    c, *_ = client(FakeResponse(200, None, text="<html>login</html>"))
    with pytest.raises(EspnError, match="non-JSON"):
        c.season(2025, [View.TEAM])
