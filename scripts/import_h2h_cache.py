"""One-off: move the legacy .h2h_cache/{season}.json files into data/raw/{season}/matchups.json.

SWIDs are pseudonymized on the way in (see mustafatron.pseudonymize), so MANAGER_ID_KEY
must be set. Safe to re-run; it overwrites with identical output.

Usage:  uv run python scripts/import_h2h_cache.py [--src .h2h_cache] [--dest data/raw]
"""

import argparse
import json
from pathlib import Path

from mustafatron.config import get_settings
from mustafatron.pseudonymize import find_swids, scrub_season


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path(".h2h_cache"))
    ap.add_argument("--dest", type=Path, default=Path("data/raw"))
    args = ap.parse_args()

    key = get_settings().manager_key()
    files = sorted(args.src.glob("*.json"))
    if not files:
        raise SystemExit(f"no season files in {args.src}")
    for src in files:
        season = int(src.stem)
        data = scrub_season(json.loads(src.read_text(encoding="utf-8")), key)
        assert find_swids(data) == 0, f"{src}: SWIDs survived pseudonymization"
        out = args.dest / str(season) / "matchups.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{src} -> {out}")


if __name__ == "__main__":
    main()
