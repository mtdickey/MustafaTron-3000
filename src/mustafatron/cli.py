"""Command line entry point: ``uv run mustafatron <command>``.

mustafatron fetch                       # backfill missing finished seasons, load the current one
mustafatron fetch --seasons 2019-2021   # just these
mustafatron fetch --refresh 2019        # ESPN corrected 2019: refetch and overwrite it
mustafatron fetch --dataset draft       # just one dataset (repeatable)
mustafatron publish [--offline]         # write the site JSON to web/public/data/
mustafatron publish --offline --check   # CI: build, validate against the contract, schema current
mustafatron schema                      # regenerate schema/*.schema.json from mustafatron.contract

Exit codes: 0 ok, 1 failed (see output), 2 a secret is not configured, 3 ESPN rejected the cookies
(they expired: refresh ESPN_SWID / ESPN_S2). The ETL workflow keys its alerting on 3.
"""

import argparse
import logging
import sys
from pathlib import Path

from mustafatron import publish
from mustafatron.config import MissingSecretError
from mustafatron.espn.cache import DATASETS, SeasonCache, latest_season
from mustafatron.espn.client import EspnAuthError

FIRST_SEASON = 2015
EXIT_MISSING_SECRET = 2
EXIT_AUTH = 3


def parse_seasons(spec: str) -> list[int]:
    """``2019``, ``2015-2018`` or ``2015,2017-2019`` → sorted list of seasons."""
    out: set[int] = set()
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return sorted(out)


def cmd_fetch(args: argparse.Namespace) -> int:
    seasons = parse_seasons(args.seasons) if args.seasons else list(range(FIRST_SEASON, latest_season() + 1))
    refresh = parse_seasons(args.refresh) if args.refresh else []
    seasons = sorted(set(seasons) | set(refresh))
    datasets = [DATASETS[d] for d in args.dataset] if args.dataset else list(DATASETS.values())
    report = SeasonCache().backfill(seasons, datasets, refresh=refresh)
    labels = {
        "cached": "cached (finished, from data/raw)",
        "fetched": "fetched and written",
        "live": "live (in progress, not written)",
        "unavailable": "not served by ESPN for this season",
    }
    for season, dataset, outcome in report:
        print(f"{season} {dataset:<12} {labels.get(outcome, outcome)}")
    return 1 if any(o.startswith("error") for *_, o in report) else 0


def cmd_publish(args: argparse.Namespace) -> int:
    if args.check:
        errors = publish.check(offline=args.offline)
        for e in errors:
            print(f"error: {e}")
        print("contract check failed" if errors else "published output matches the contract")
        return 1 if errors else 0
    files = publish.publish(args.out, offline=args.offline)
    print(f"wrote {len(files)} files to {args.out}")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    if args.check:
        stale = publish.stale_schemas()
        for name in stale:
            print(f"stale: schema/{name}")
        return 1 if stale else 0
    publish.write_schemas()
    print(f"wrote {publish.SCHEMA_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mustafatron", description="MustafaTron-3000 data tools.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="load seasons through the data/raw cache")
    fetch.add_argument("--seasons", help=f"e.g. 2019 or 2015-2018 (default: {FIRST_SEASON} to the latest)")
    fetch.add_argument("--refresh", metavar="SEASONS", help="refetch and overwrite these finished seasons")
    fetch.add_argument("--dataset", action="append", choices=sorted(DATASETS), help="default: all")
    fetch.set_defaults(func=cmd_fetch)

    pub = sub.add_parser("publish", help="write the site JSON")
    pub.add_argument("--out", type=Path, default=publish.OUT_DIR)
    pub.add_argument("--offline", action="store_true", help="finished seasons from data/raw/ only")
    pub.add_argument("--check", action="store_true", help="build to a temp dir and validate; write nothing")
    pub.set_defaults(func=cmd_publish)

    schema = sub.add_parser("schema", help="regenerate schema/ from the contract models")
    schema.add_argument("--check", action="store_true", help="fail if schema/ is out of date")
    schema.set_defaults(func=cmd_schema)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    try:
        return args.func(args)
    except EspnAuthError as e:  # its message already says how to refresh the cookies
        print(f"error: {e}", file=sys.stderr)
        return EXIT_AUTH
    except MissingSecretError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_MISSING_SECRET


if __name__ == "__main__":
    sys.exit(main())
