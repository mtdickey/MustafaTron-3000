"""Export one season's draft picks from ESPN as CSV, for keeper planning.

Standalone (Python 3.10+ standard library only), so it runs from any machine that has the league's
ESPN cookies. It prints every pick with the player's name, position, current fantasy team (0 = free
agent) and injury status. No SWIDs or member ids are written.

Cookies come from the environment, or from a .env file in the current directory or the repo root:
    ESPN_SWID={...}   ESPN_S2=...

    python scripts/export_draft_picks.py                  # 2026 draft to stdout
    python scripts/export_draft_picks.py --season 2026 --out draft_2026.csv
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LEAGUE_ID = 763471
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}"
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
FIELDS = [
    "season", "round", "round_pick", "overall", "keeper", "drafting_team_id", "drafting_team",
    "player_id", "player", "position", "nfl_team_id", "current_team_id", "current_team",
    "injury_status",
]


def read_dotenv() -> dict[str, str]:
    here = Path(__file__).resolve().parent
    for path in (Path.cwd() / ".env", here.parent / ".env"):
        if path.is_file():
            out = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
            return out
    return {}


def cookies() -> str:
    env = {**read_dotenv(), **os.environ}
    swid, s2 = env.get("ESPN_SWID", ""), env.get("ESPN_S2", "")
    if not swid or not s2:
        sys.exit("Set ESPN_SWID and ESPN_S2 (environment or .env); see .env.example.")
    if not swid.startswith("{"):
        swid = "{" + swid + "}"
    s2 = urllib.parse.unquote(s2)  # accept it pasted URL-encoded or not
    return f"SWID={swid}; espn_s2={s2}"


def get(season: int, views: list[str], cookie: str, fantasy_filter: dict | None = None) -> dict:
    query = urllib.parse.urlencode([("view", v) for v in views])
    url = BASE.format(season=season, league=LEAGUE_ID) + "?" + query
    req = urllib.request.Request(url, headers={"Cookie": cookie, "Accept": "application/json"})
    if fantasy_filter is not None:
        req.add_header("x-fantasy-filter", json.dumps(fantasy_filter))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit(f"ESPN returned {e.code}: the cookies are missing, wrong or expired.")
        raise


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--out", help="CSV path (default: stdout)")
    args = ap.parse_args()
    cookie = cookies()

    league = get(args.season, ["mDraftDetail", "mTeam"], cookie)
    picks = league.get("draftDetail", {}).get("picks", [])
    if not picks:
        sys.exit(f"No draft picks returned for {args.season}.")
    teams = {t["id"]: (t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}").strip()
             for t in league.get("teams", [])}

    ids = sorted({p["playerId"] for p in picks})
    players = {}
    for i in range(0, len(ids), 100):
        batch = ids[i : i + 100]
        raw = get(args.season, ["kona_player_info"], cookie,
                  {"players": {"filterIds": {"value": batch}, "limit": len(batch)}})
        for entry in raw.get("players", []):
            p = entry.get("player", {})
            players[p.get("id")] = (entry, p)

    rows = []
    for pk in sorted(picks, key=lambda p: p["overallPickNumber"]):
        entry, p = players.get(pk["playerId"], ({}, {}))
        on_team = entry.get("onTeamId", 0)
        rows.append({
            "season": args.season,
            "round": pk.get("roundId"),
            "round_pick": pk.get("roundPickNumber"),
            "overall": pk.get("overallPickNumber"),
            "keeper": bool(pk.get("keeper") or pk.get("reservedForKeeper")),
            "drafting_team_id": pk.get("teamId"),
            "drafting_team": teams.get(pk.get("teamId"), ""),
            "player_id": pk["playerId"],
            "player": p.get("fullName", ""),
            "position": POSITIONS.get(p.get("defaultPositionId"), p.get("defaultPositionId", "")),
            "nfl_team_id": p.get("proTeamId", ""),
            "current_team_id": on_team,
            "current_team": teams.get(on_team, "FREE AGENT" if on_team == 0 else ""),
            "injury_status": p.get("injuryStatus", ""),
        })

    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            write(f, rows)
        print(f"Wrote {len(rows)} picks to {args.out}", file=sys.stderr)
    else:
        write(sys.stdout, rows)


def write(f, rows: list[dict]) -> None:
    w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)


if __name__ == "__main__":
    main()
