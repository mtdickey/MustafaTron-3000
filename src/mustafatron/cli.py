"""Command line entry point: ``uv run mustafatron <command>``.

mustafatron fetch                       # backfill missing finished seasons, load the current one
mustafatron fetch --seasons 2019-2021   # just these
mustafatron fetch --refresh 2019        # ESPN corrected 2019: refetch and overwrite it
"""

import argparse
import logging
import sys

from mustafatron.espn.cache import DATASETS, SeasonCache, latest_season

FIRST_SEASON = 2015


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
    }
    for season, dataset, outcome in report:
        print(f"{season} {dataset:<9} {labels.get(outcome, outcome)}")
    return 1 if any(o.startswith("error") for *_, o in report) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mustafatron", description="MustafaTron-3000 data tools.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="load seasons through the data/raw cache")
    fetch.add_argument("--seasons", help=f"e.g. 2019 or 2015-2018 (default: {FIRST_SEASON} to the latest)")
    fetch.add_argument("--refresh", metavar="SEASONS", help="refetch and overwrite these finished seasons")
    fetch.add_argument("--dataset", action="append", choices=sorted(DATASETS), help="default: all")
    fetch.set_defaults(func=cmd_fetch)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
