"""Read-through cache of ESPN seasons over ``data/raw/``.

The rule: **a finished season is immutable, an unfinished one is always fresh.**

- A season is *finished* when every matchup in its schedule has a result (no ``UNDECIDED``).
  That is decided from the data itself, not the calendar or ``rankFinal`` (which is 0 for every
  team in every season of this league; ``rankCalculatedFinal`` holds the real finish). So the
  offseason needs no special case: last season stays finished, and the next one only becomes
  "current" once ESPN has a schedule for it.
- A finished season is fetched once, scrubbed (see ``mustafatron.pseudonymize``) and written to
  ``data/raw/{season}/{dataset}.json``, where it is committed and never refetched.
- An unfinished season is fetched on every run (once per ``SeasonCache``) and never written, so
  in-progress numbers never land in git.
- ``refresh=True`` refetches a season and overwrites its files, for when ESPN corrects history
  (a late stat correction, a commissioner edit).

Each file is written atomically, so an interrupted backfill leaves only whole files behind and a
rerun picks up with the seasons and datasets that are still missing.

Datasets that ESPN only serves from some season on (``Dataset.since``: weekly box scores and
transactions start in 2018) are reported as unavailable for earlier seasons, never fetched.
The player-level datasets and how they are fetched live in ``mustafatron.espn.player_data``.
"""

import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from mustafatron.config import get_settings
from mustafatron.espn import player_data
from mustafatron.espn.client import EspnAuthError, EspnClient, EspnError, View
from mustafatron.espn.player_data import FetchContext
from mustafatron.pseudonymize import find_swids, scrub_season

log = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
DECIDED = frozenset({"HOME", "AWAY", "TIE"})


@dataclass(frozen=True)
class Dataset:
    """One committed file per season: which ESPN views fill it and which top-level keys it keeps.

    By default a dataset is one request for ``views``, keeping ``keys``. A dataset that needs more
    (one request per NFL week, trimming, other datasets first) supplies ``fetch`` instead.
    """

    name: str
    views: tuple[View, ...]
    keys: tuple[str, ...]
    since: int | None = None  # first season ESPN serves it; None = every season
    fetch: Callable[[FetchContext], dict] | None = None

    def available(self, season: int) -> bool:
        return self.since is None or season >= self.since


MATCHUPS = Dataset("matchups", (View.TEAM, View.MATCHUP_SCORE), ("members", "teams", "schedule"))
SETTINGS = Dataset("settings", (View.SETTINGS,), ("settings", "status"))
DRAFT = Dataset("draft", (View.DRAFT_DETAIL,), ("draftDetail",), fetch=player_data.fetch_draft)
BOXSCORES = Dataset(
    "boxscores",
    (View.BOXSCORE, View.MATCHUP_SCORE),
    ("periods",),
    since=player_data.WEEKLY_SINCE,
    fetch=player_data.fetch_boxscores,
)
TRANSACTIONS = Dataset(
    "transactions",
    (View.TRANSACTIONS,),
    ("transactions",),
    since=player_data.WEEKLY_SINCE,
    fetch=player_data.fetch_transactions,
)
PLAYERS = Dataset("players", (View.PLAYER_INFO,), ("players",), fetch=player_data.fetch_players)
DATASETS = {d.name: d for d in (MATCHUPS, SETTINGS, DRAFT, BOXSCORES, TRANSACTIONS, PLAYERS)}
PLAYER_DATASETS = (DRAFT, BOXSCORES, TRANSACTIONS, PLAYERS)

Source = Literal["cached", "fetched", "live", "unavailable"]


def is_complete(matchups: dict) -> bool:
    """True once every scheduled matchup has a result, i.e. the season can never change again."""
    schedule = matchups.get("schedule") or []
    return bool(schedule) and all(m.get("winner") in DECIDED for m in schedule)


def latest_season(today: date | None = None) -> int:
    """The most recent season worth asking ESPN about: this year's from August (draft month) on."""
    today = today or date.today()
    return today.year if today.month >= 8 else today.year - 1


class SeasonCache:
    """Loads season datasets from ``data/raw/`` when finished, otherwise from ESPN."""

    def __init__(
        self,
        raw_dir: Path = RAW_DIR,
        client: Callable[[], EspnClient] = EspnClient.from_settings,
        manager_key: Callable[[], bytes] = lambda: get_settings().manager_key(),
    ):
        # Both are factories so reading finished seasons needs no cookies and no key.
        self.raw_dir = Path(raw_dir)
        self._client_factory = client
        self._key_factory = manager_key
        self._client: EspnClient | None = None
        self._live: dict[tuple[int, str], dict] = {}
        self._refreshed: set[tuple[int, str]] = set()  # refetched this run: a refresh happens once

    def path(self, season: int, dataset: Dataset = MATCHUPS) -> Path:
        return self.raw_dir / str(season) / f"{dataset.name}.json"

    def is_frozen(self, season: int) -> bool:
        """True if the season's matchups are on disk and finished."""
        path = self.path(season, MATCHUPS)
        return path.exists() and is_complete(_read(path))

    def load(self, season: int, dataset: Dataset = MATCHUPS, *, refresh: bool = False) -> dict:
        """The dataset for a season; ``{}`` if ESPN does not serve it that far back."""
        return self.load_with_source(season, dataset, refresh=refresh)[0]

    def load_with_source(
        self, season: int, dataset: Dataset = MATCHUPS, *, refresh: bool = False
    ) -> tuple[dict, Source]:
        """The dataset for a season, plus where it came from (for progress output)."""
        if not dataset.available(season):
            return {}, "unavailable"
        refresh = refresh and (season, dataset.name) not in self._refreshed
        path = self.path(season, dataset)
        if not refresh:
            if path.exists() and self.is_frozen(season):
                return _read(path), "cached"
            if (season, dataset.name) in self._live:
                return self._live[(season, dataset.name)], "live"

        if dataset is MATCHUPS:
            data = self._fetch(season, dataset, finished=False)
            finished = is_complete(data)
        else:  # other datasets freeze together with the season's matchups
            finished = is_complete(self.load(season, MATCHUPS, refresh=refresh))
            data = self._fetch(season, dataset, finished=finished, refresh=refresh)
        if refresh:
            self._refreshed.add((season, dataset.name))
        if not finished:
            self._live[(season, dataset.name)] = data
            return data, "live"
        _write_atomic(path, data)
        self._live.pop((season, dataset.name), None)
        log.info("wrote %s", path)
        return data, "fetched"

    def backfill(
        self,
        seasons: Iterable[int],
        datasets: Iterable[Dataset] = (MATCHUPS,),
        *,
        refresh: Iterable[int] = (),
    ) -> list[tuple[int, str, str]]:
        """Load every (season, dataset), writing finished ones. Resumable: frozen files are skipped.

        Returns ``(season, dataset, outcome)`` rows; a season ESPN cannot serve is reported, not raised,
        so one missing season does not stop the rest. Expired cookies (:class:`EspnAuthError`) do
        raise: every later request would fail the same way, and the caller has to say so loudly.
        """
        refresh, report = set(refresh), []
        datasets = list(datasets)
        for season in seasons:
            for dataset in datasets:
                try:
                    _, source = self.load_with_source(season, dataset, refresh=season in refresh)
                    report.append((season, dataset.name, source))
                except EspnAuthError:
                    raise
                except EspnError as e:
                    report.append((season, dataset.name, f"error: {e}"))
                    break
        return report

    def _fetch(self, season: int, dataset: Dataset, *, finished: bool, refresh: bool = False) -> dict:
        if self._client is None:
            self._client = self._client_factory()
        if dataset.fetch is not None:
            ctx = FetchContext(
                self._client,
                season,
                finished,
                lambda name: self.load(season, DATASETS[name], refresh=refresh),
            )
            raw = dataset.fetch(ctx)
        else:
            raw = self._client.season(season, dataset.views)
        empty = {k: [] for k in MATCHUPS.keys}  # list-valued keys default to [], the rest to {}
        data = scrub_season({k: raw.get(k, empty.get(k, {})) for k in dataset.keys}, self._key_factory())
        if find_swids(data):
            raise RuntimeError(f"{season} {dataset.name}: SWIDs survived pseudonymization; not caching")
        return data


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, data: dict) -> None:
    """Write via a temp file and rename, so readers never see a half-written season."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
