"""HTTP client for ESPN's fantasy football v3 API.

Raw ``requests`` against ``lm-api-reads.fantasy.espn.com`` rather than the ``espn-api`` package:
the v3 API has been stable, while ``espn-api``'s object model churns between releases (its
``team.owner`` / ``team.owners`` change is what the legacy code monkey-patches around).

ESPN serves a season from one of two endpoints:

- 2018 onward: ``seasons/{season}/segments/0/leagues/{league_id}``, which returns an object.
- Before 2018: ``leagueHistory/{league_id}?seasonId={season}``, which returns a one-element list.

:meth:`EspnClient.season` hides that difference and always returns the season object.
"""

import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any, cast

import requests

from mustafatron.config import Settings, get_settings
from mustafatron.espn.raw import RawSeason

try:  # Use the OS certificate store, so requests work behind a TLS-inspecting proxy.
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover - truststore is a dependency, but nothing breaks without it
    pass

log = logging.getLogger(__name__)

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
LEAGUE_HISTORY_BEFORE = 2018
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Minimum gap between requests from a configured client. A full player-level backfill is a few hundred
# requests against an undocumented API, so it goes at a polite pace rather than as fast as possible.
REQUEST_INTERVAL = 0.5


class View(StrEnum):
    """ESPN ``view`` parameters. Each one adds a slice of the league to the response."""

    TEAM = "mTeam"
    MATCHUP_SCORE = "mMatchupScore"
    SETTINGS = "mSettings"
    BOXSCORE = "mBoxscore"
    ROSTER = "mRoster"
    DRAFT_DETAIL = "mDraftDetail"
    TRANSACTIONS = "mTransactions2"
    PLAYER_INFO = "kona_player_info"


class EspnError(RuntimeError):
    """ESPN could not be reached or returned something unusable."""


class EspnAuthError(EspnError):
    """ESPN rejected the login cookies, which almost always means they expired."""


class SeasonNotFoundError(EspnError):
    """The league has no such season (or these cookies cannot see it)."""


def season_endpoint(league_id: int, season: int) -> tuple[str, dict[str, Any]]:
    """URL and base query parameters for one season of a league."""
    if season >= LEAGUE_HISTORY_BEFORE:
        return f"{BASE_URL}/seasons/{season}/segments/0/leagues/{league_id}", {}
    return f"{BASE_URL}/leagueHistory/{league_id}", {"seasonId": season}


class EspnClient:
    """Fetches league data from ESPN, with retries and an actionable error when cookies expire."""

    def __init__(
        self,
        league_id: int,
        cookies: Mapping[str, str] | None,
        *,
        session: requests.Session | None = None,
        retries: int = 3,
        backoff: float = 1.0,
        timeout: float = 30.0,
        min_interval: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.league_id = league_id
        self.session = session or requests.Session()
        if cookies:
            self.session.cookies.update(cookies)
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kwargs: Any) -> "EspnClient":
        """A client for the configured league, authenticated with the cookies from ``.env``."""
        settings = settings or get_settings()
        kwargs.setdefault("min_interval", REQUEST_INTERVAL)
        return cls(settings.league_id, settings.espn_cookies(), **kwargs)

    def season(
        self,
        season: int,
        views: Iterable[View | str],
        *,
        scoring_period: int | None = None,
        player_filter: Mapping[str, Any] | None = None,
    ) -> RawSeason:
        """One season of the league with the given views, as ESPN returns it (SWIDs not yet scrubbed).

        ``scoring_period`` asks for one NFL week: box scores and transactions are served a week at a
        time. ``player_filter`` is ESPN's ``x-fantasy-filter`` header, which ``kona_player_info`` needs
        to say which players and which stat lines to return.
        """
        url, params = season_endpoint(self.league_id, season)
        params = {**params, "view": [str(v) for v in views]}
        what = f"season {season}"
        if scoring_period is not None:
            params["scoringPeriodId"] = scoring_period
            what += f" week {scoring_period}"
        headers = {"x-fantasy-filter": json.dumps(player_filter)} if player_filter is not None else None
        data = self._get(url, params, what=what, headers=headers)
        if isinstance(data, list):  # leagueHistory wraps the season in a list
            if not data:
                raise SeasonNotFoundError(f"ESPN has no {season} season for league {self.league_id}.")
            data = data[0]
        if not isinstance(data, dict):
            raise EspnError(f"Unexpected response for season {season}: {type(data).__name__}")
        return cast(RawSeason, data)

    def _pace(self) -> None:
        """Wait out whatever is left of ``min_interval`` since the previous request."""
        now = self._clock()
        if self._last_request is not None and self.min_interval > 0:
            wait = self._last_request + self.min_interval - now
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_request = now

    def _get(self, url: str, params: dict[str, Any], *, what: str, headers: dict | None = None) -> Any:
        last_error: str = ""
        extra = {"headers": headers} if headers else {}
        for attempt in range(self.retries + 1):
            if attempt:
                delay = self.backoff * 2 ** (attempt - 1)
                log.warning("ESPN %s: %s; retrying in %.1fs", what, last_error, delay)
                self._sleep(delay)
            self._pace()
            try:
                r = self.session.get(url, params=params, timeout=self.timeout, **extra)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_error = f"{type(e).__name__}: {e}"
                continue
            if r.status_code in RETRY_STATUSES:
                last_error = f"HTTP {r.status_code}"
                continue
            if r.status_code in (401, 403):
                raise EspnAuthError(
                    f"ESPN rejected the login cookies (HTTP {r.status_code}) fetching {what} of league "
                    f"{self.league_id}. espn_s2 expires every few months: log in at "
                    "https://fantasy.espn.com, copy fresh SWID and espn_s2 cookies, and update ESPN_SWID / "
                    "ESPN_S2 in .env (local) or the repository's Actions secrets (CI). See .env.example for "
                    "where to find them."
                )
            if r.status_code == 404:
                raise SeasonNotFoundError(f"ESPN has no {what} for league {self.league_id} (HTTP 404).")
            if r.status_code != 200:
                raise EspnError(f"ESPN returned HTTP {r.status_code} for {what}: {r.text[:200]}")
            try:
                return r.json()
            except ValueError as e:
                raise EspnError(f"ESPN returned a non-JSON response for {what}: {r.text[:200]}") from e
        raise EspnError(f"ESPN {what} still failing after {self.retries + 1} attempts ({last_error}).")
