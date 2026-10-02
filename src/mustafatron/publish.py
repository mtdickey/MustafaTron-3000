"""Publish the site's JSON: the entity model → the files in ``mustafatron.contract`` → ``web/public/data/``.

    uv run mustafatron publish                 # all seasons, the current one live from ESPN
    uv run mustafatron publish --offline       # finished seasons only, from data/raw/ (no cookies)
    uv run mustafatron publish --offline --check   # what CI runs: build, validate, schema up to date

The output is generated, never committed (``web/public/data/`` is gitignored); CI builds it.
"""

import json
import shutil
import tempfile
from pathlib import Path

from mustafatron import contract as c
from mustafatron.espn.cache import SeasonCache
from mustafatron.model import Game, League, Season
from mustafatron.rules import LeagueRules, load_rules
from mustafatron.stats.h2h import Meeting, all_pairs, notable_flags
from mustafatron.stats.records import records_book
from mustafatron.stats.standings import all_time_standings
from mustafatron.transform import load_league

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "web" / "public" / "data"
SCHEMA_DIR = REPO / "schema"


def game_row(g: Game) -> c.GameRow:
    return (
        g.season,
        g.week,
        c.TIERS.index(g.tier),
        g.home_id,
        g.away_id,
        g.home_score,
        g.away_score,
        g.winner_id,
    )


def _meeting(m: Meeting) -> c.MeetingOut:
    return c.MeetingOut(season=m.season, week=m.week, score=m.score, opponent_score=m.opponent_score)


def _week_status(season: Season) -> tuple[int | None, int | None]:
    """(last week with every game final, first week with a game still to play)."""
    weeks = sorted({g.week for g in season.games})
    done = [w for w in weeks if all(g.final for g in season.games if g.week == w)]
    todo = [w for w in weeks if w not in done]
    return (max(done) if done else None), (min(todo) if todo else None)


def build(league: League, rules: LeagueRules) -> dict[str, c.ContractFile]:
    """Every published file, keyed by its path under the output directory."""
    seasons = sorted(league.seasons)
    current = league.seasons[seasons[-1]]
    last_done, upcoming_week = _week_status(current)
    out: dict[str, c.ContractFile] = {}

    out["meta.json"] = c.Meta(
        league_name=current.settings.name,
        seasons=seasons,
        current_season=current.season,
        current_season_finished=current.finished,
        last_completed_week=last_done,
        upcoming_week=upcoming_week,
    )

    played: dict[str, list[int]] = {}
    for s in league.seasons.values():
        for t in s.teams:
            played.setdefault(t.manager_id, []).append(s.season)
    out["managers.json"] = c.ManagersFile(
        managers=[
            c.ManagerOut(
                id=m.id,
                name=m.name,
                short_name=m.short_name,
                first_season=m.first_season,
                last_season=m.last_season,
                seasons=played[m.id],
            )
            for m in league.managers_with_games()
        ]
    )

    out["games.json"] = c.GamesFile(
        games=[game_row(g) for g in league.games],
        upcoming=[(g.season, g.week, g.home_id, g.away_id) for g in current.games if g.week == upcoming_week],
    )

    pairs = all_pairs(league.games)
    out["h2h.json"] = c.H2HFile(
        pairs=[
            c.PairOut(
                a=p.a,
                b=p.b,
                games=p.games,
                wins=p.wins,
                losses=p.losses,
                ties=p.ties,
                points_for=p.points_for,
                points_against=p.points_against,
                playoff_wins=p.playoff_wins,
                playoff_losses=p.playoff_losses,
                results=p.results,
                current_streak=c.StreakOut(holder=p.current_streak.holder, length=p.current_streak.length),
                longest_streak_a=p.longest_streak(p.a),
                longest_streak_b=p.longest_streak(p.b),
                last_meeting=_meeting(p.meetings[-1]),
                closest=_meeting(p.closest),
                blowout=_meeting(p.blowout),
                rivalry=p.games >= rules.rivalry.min_matchups,
                flags=[
                    c.FlagOut(kind=f.kind, holder=f.holder, wins=f.wins, losses=f.losses)  # type: ignore[arg-type]
                    for f in notable_flags(p, rules.rivalry)
                ],
            )
            for p in pairs.values()
        ]
    )

    out["standings.json"] = c.StandingsFile(
        standings=[
            c.CareerOut(
                manager=s.manager_id,
                seasons=s.seasons,
                wins=s.wins,
                losses=s.losses,
                ties=s.ties,
                win_pct=round(s.win_pct, 4),
                points_for=s.points_for,
                points_against=s.points_against,
                playoff_appearances=s.playoff_appearances,
                championships=s.championships,
                runner_ups=s.runner_ups,
                third_places=s.third_places,
                best_finish=s.best_finish,
                avg_finish=s.avg_finish,
                net_payout=s.net_payout,
            )
            for s in all_time_standings(league, rules)
        ]
    )

    book = records_book(league)
    out["records.json"] = c.RecordsFile(
        game_records={
            k: [
                c.GameMarkOut(
                    season=m.season,
                    week=m.week,
                    manager=m.manager_id,
                    opponent=m.opponent_id,
                    score=m.score,
                    opponent_score=m.opponent_score,
                    playoff=m.playoff,
                )
                for m in v  # type: ignore[union-attr]
            ]
            for k, v in book.items()
            if not k.endswith("_season")
        },
        season_records={
            k: [
                c.SeasonMarkOut(
                    season=m.season,
                    manager=m.manager_id,
                    value=m.value,
                    wins=m.wins,
                    losses=m.losses,
                    ties=m.ties,
                    points_for=m.points_for,
                )
                for m in v  # type: ignore[union-attr]
            ]
            for k, v in book.items()
            if k.endswith("_season")
        },
    )

    for s in league.seasons.values():
        out[f"seasons/{s.season}.json"] = c.SeasonFile(
            season=s.season,
            finished=s.finished,
            champion=s.champion_id if s.finished else None,
            settings=c.SeasonSettingsOut(
                team_count=s.settings.team_count,
                regular_season_weeks=s.settings.regular_season_matchups,
                final_week=s.settings.final_matchup_period,
                playoff_team_count=s.settings.playoff_team_count,
                points_per_reception=s.settings.points_per_reception,
            ),
            teams=[
                c.TeamOut(
                    manager=t.manager_id,
                    team_id=t.team_id,
                    name=t.name,
                    abbrev=t.abbrev,
                    wins=t.wins,
                    losses=t.losses,
                    ties=t.ties,
                    points_for=t.points_for,
                    points_against=t.points_against,
                    playoff_seed=t.playoff_seed,
                    final_rank=t.final_rank,
                    acquisitions=t.acquisitions,
                    trades=t.trades,
                    co_managers=list(t.co_manager_ids),
                )
                for t in s.teams
            ],
            games=[game_row(g) for g in s.games],
        )
    return out


def write(files: dict[str, c.ContractFile], out_dir: Path) -> None:
    """Replace ``out_dir`` with exactly these files (compact JSON, one per path)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for relpath, model in files.items():
        path = out_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(model.model_dump_json() + "\n", encoding="utf-8")


def validate(out_dir: Path) -> list[str]:
    """Problems found re-reading published files through the contract (empty if all is well)."""
    errors = []
    found = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*.json"))
    for name in c.FILES:
        if name not in found:
            errors.append(f"{name}: missing")
    for relpath in found:
        try:
            text = (out_dir / relpath).read_text(encoding="utf-8")
            c.model_for(relpath).model_validate_json(text, strict=True)
        except (KeyError, ValueError) as e:
            errors.append(f"{relpath}: {e}")
    return errors


def schemas() -> dict[str, dict]:
    """JSON Schema for every published file, keyed by schema file name."""
    out = {f"{Path(name).stem}.schema.json": model.model_json_schema() for name, model in c.FILES.items()}
    out["season.schema.json"] = c.SEASON_FILE.model_json_schema()
    return out


def _dump_schema(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write_schemas(schema_dir: Path = SCHEMA_DIR) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas().items():
        (schema_dir / name).write_text(_dump_schema(schema), encoding="utf-8", newline="\n")


def stale_schemas(schema_dir: Path = SCHEMA_DIR) -> list[str]:
    """Committed schema files that don't match the contract models."""
    stale = []
    for name, schema in schemas().items():
        path = schema_dir / name
        if not path.exists() or path.read_text(encoding="utf-8").replace("\r\n", "\n") != _dump_schema(
            schema
        ):
            stale.append(name)
    return stale


def publish(out_dir: Path = OUT_DIR, *, offline: bool = False) -> dict[str, c.ContractFile]:
    cache = SeasonCache()
    seasons = None
    if offline:  # only what is committed and finished; needs no ESPN cookies
        seasons = sorted(
            int(p.name) for p in cache.raw_dir.iterdir() if p.is_dir() and cache.is_frozen(int(p.name))
        )
    league = load_league(seasons, cache=cache)
    files = build(league, load_rules())
    write(files, out_dir)
    return files


def check(*, offline: bool = True) -> list[str]:
    """Build into a temp dir and report contract violations and stale schemas (what CI runs)."""
    with tempfile.TemporaryDirectory() as tmp:
        publish(Path(tmp), offline=offline)
        errors = validate(Path(tmp))
    errors += [f"schema/{n} is stale: run `uv run mustafatron schema`" for n in stale_schemas()]
    return errors
