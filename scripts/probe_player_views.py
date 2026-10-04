"""Probe which player-level ESPN views a season serves, and print what comes back.

The M3 spike (issue #26): the ``leagueHistory`` endpoint (seasons before 2018) turned out to serve
drafts and season totals but no weekly player scores, bench or transactions. The findings are
written up in data/README.md ("Player-level data by era"). Rerun this if ESPN's retention looks
like it has changed. Needs ESPN cookies in .env; writes nothing.

Usage:  uv run python scripts/probe_player_views.py [--seasons 2015-2018] [--period 3]
"""

import argparse
import json

from mustafatron.cli import parse_seasons
from mustafatron.espn.client import EspnClient, season_endpoint


def get(client: EspnClient, season: int, params: dict, headers: dict | None = None) -> dict:
    url, base = season_endpoint(client.league_id, season)
    r = client.session.get(url, params={**base, **params}, headers=headers or {}, timeout=60)
    r.raise_for_status()
    data = r.json()
    return (data[0] if data else {}) if isinstance(data, list) else data


def box_scores(data: dict) -> str:
    """Per-side roster entries in the requested week's matchups, and whether they add up."""
    sides = []
    for m in data.get("schedule", []):
        for side in (m.get("home", {}), m.get("away", {})):
            for key in ("rosterForCurrentScoringPeriod", "rosterForMatchupPeriod"):
                if key in side:
                    entries = side[key]["entries"]
                    total = sum(e["playerPoolEntry"].get("appliedStatTotal", 0) for e in entries)
                    slots = {e["lineupSlotId"] for e in entries}
                    sides.append((key, len(entries), abs(total - side.get("totalPoints", 0)) < 0.01, slots))
    if not sides:
        return "no rosters in the schedule"
    keys = {k for k, *_ in sides}
    sums = sum(ok for _, _, ok, _ in sides)
    bench = any(20 in s for *_, s in sides)
    return (
        f"{keys}, {[n for _, n, *_ in sides]} entries per side, {sums}/{len(sides)} sides sum to the "
        f"team's points, bench {'present' if bench else 'absent'}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2015-2018")
    ap.add_argument("--period", type=int, default=3, help="NFL week to ask for")
    args = ap.parse_args()
    client = EspnClient.from_settings()

    for season in parse_seasons(args.seasons):
        print(f"--- {season}")
        draft = get(client, season, {"view": "mDraftDetail"}).get("draftDetail", {})
        picks = draft.get("picks", [])
        print(f"mDraftDetail: {len(picks)} picks, {sum(bool(p.get('keeper')) for p in picks)} keeper-flagged")

        box = get(client, season, {"view": ["mBoxscore", "mMatchupScore"], "scoringPeriodId": args.period})
        print(f"mBoxscore week {args.period}: {box_scores(box)}")

        week = get(client, season, {"view": "mRoster", "scoringPeriodId": args.period})
        final = get(client, season, {"view": "mRoster"})

        def ids(d: dict) -> list:
            return [sorted(e["playerId"] for e in t["roster"]["entries"]) for t in d.get("teams", [])]

        same = ids(week) == ids(final)
        print(f"mRoster week {args.period}: {'the final roster (week ignored)' if same else 'that week'}")

        tx = get(client, season, {"view": "mTransactions2", "scoringPeriodId": args.period})
        found = len(tx["transactions"]) if "transactions" in tx else "none"
        print(f"mTransactions2 week {args.period}: {found}")

        sample = [p["playerId"] for p in picks[:3]]
        flt = {
            "players": {
                "filterIds": {"value": sample},
                "filterStatsForTopScoringPeriodIds": {"value": 18, "additionalValue": [f"00{season}"]},
            }
        }
        kona = get(client, season, {"view": "kona_player_info"}, {"x-fantasy-filter": json.dumps(flt)})
        for p in kona.get("players", []):
            stats = [s for s in p["player"].get("stats", []) if s.get("statSourceId") == 0]
            weekly = sum(s.get("scoringPeriodId", 0) > 0 for s in stats)
            total = next((s["appliedTotal"] for s in stats if s.get("scoringPeriodId") == 0), None)
            print(f"kona_player_info {p['player']['fullName']}: season total {total}, {weekly} weekly lines")


if __name__ == "__main__":
    main()
