"""Read-only ESPN trade probe. Save only allowlisted, non-member transaction fields."""

import argparse
import json
import ssl
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import certifi
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2022)
    parser.add_argument("--view", default="mTransactions2")
    parser.add_argument("--weeks", default="0-18")
    parser.add_argument("--filter", default=None)
    parser.add_argument("--communication", action="store_true")
    parser.add_argument("--playercards", action="store_true")
    args = parser.parse_args()
    config = {}
    for line in Path(".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            config[key.strip().lower()] = value.strip().strip('"').strip("'")
    cache = Path(".h2h_cache")
    cache.mkdir(exist_ok=True)
    bundle = cache / "windows-ca.pem"
    certificates = [certifi.contents()]
    for store in ("ROOT", "CA"):
        for certificate, encoding, trust in ssl.enum_certificates(store):
            if encoding == "x509_asn" and (trust is True or ssl.Purpose.SERVER_AUTH.oid in trust):
                certificates.append(ssl.DER_cert_to_PEM_cert(certificate))
    bundle.write_text("\n".join(certificates))
    session = requests.Session()
    session.verify = str(bundle)
    session.cookies.update({"swid": config["espn_swid"], "espn_s2": unquote(config["espn_s2"])})
    url = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{args.season}/segments/0/leagues/"
        + config.get("league_id", "763471")
    )
    every = {}
    if args.playercards:
        players = json.loads(Path(f"data/raw/{args.season}/players.json").read_text())["players"]
        ids = [p["id"] for p in players]
        for start in range(0, len(ids), 100):
            filters = {"players": {"filterIds": {"value": ids[start : start + 100]}}}
            response = session.get(
                url,
                params={"view": "kona_playercard"},
                headers={"x-fantasy-filter": json.dumps(filters)},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            print("Playercard batch", start, "keys", sorted(data), flush=True)

            def visit(value):
                if isinstance(value, dict):
                    if "id" in value and "type" in value and "TRADE" in str(value["type"]):
                        every[value["id"]] = value
                    for child in value.values():
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)

            visit(data)
            time.sleep(0.5)
        args.weeks = ""
        args.view = "kona_playercard"
    if args.communication:
        topics = []
        offset = 0
        while True:
            filters = {
                "topics": {
                    "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
                    "limit": 100,
                    "limitPerMessageSet": {"value": 100},
                    "offset": offset,
                    "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                    "sortFor": {"sortPriority": 2, "sortAsc": False},
                    "filterIncludeMessageTypeIds": {"value": [244]},
                }
            }
            for host in ("lm-api-reads.fantasy.espn.com", "lm-api-communication.fantasy.espn.com"):
                for suffix in ("/communication", "/communication/"):
                    endpoint = url.replace("lm-api-reads.fantasy.espn.com", host) + suffix
                    response = session.get(
                        endpoint,
                        params={"view": "kona_league_communication"},
                        headers={"x-fantasy-filter": json.dumps(filters)},
                        timeout=30,
                    )
                    print(host, suffix, response.status_code, flush=True)
                    if response.ok:
                        break
                if response.ok:
                    break
            response.raise_for_status()
            data = response.json()
            batch = data.get("topics") or []
            print("Communication keys", sorted(data), "offset", offset, "topics", len(batch))
            for topic in batch:
                safe_topic = {key: topic[key] for key in ("id", "date", "type") if key in topic}
                safe_topic["messages"] = [
                    {
                        key: message[key]
                        for key in ("id", "messageTypeId", "targetId", "from", "to", "for", "date")
                        if key in message
                    }
                    for message in topic.get("messages") or []
                ]
                topics.append(safe_topic)
            if len(batch) < 100:
                break
            offset += len(batch)
            time.sleep(0.5)
        path = cache / f"{args.season}-trade-communication.json"
        path.write_text(json.dumps(topics, indent=2))
        print(json.dumps(topics, indent=2))
        print("Saved", path)
        return
    weeks = []
    for part in args.weeks.split(","):
        if not part:
            continue
        if "-" in part:
            first, last = map(int, part.split("-"))
            weeks.extend(range(first, last + 1))
        else:
            weeks.append(int(part))
    for week in weeks:
        headers = {"x-fantasy-filter": args.filter} if args.filter else {}
        response = session.get(
            url, params={"view": args.view, "scoringPeriodId": week}, headers=headers, timeout=30
        )
        response.raise_for_status()
        data = response.json()
        transactions = data.get("transactions") or []
        print("week", week, "transactions", len(transactions), flush=True)
        every.update({t["id"]: t for t in transactions})
        time.sleep(0.5)
    print("ALL TYPES", dict(Counter(t.get("type") for t in every.values())))
    trades = [t for t in every.values() if "TRADE" in t.get("type", "")]
    safe = []
    keys = (
        "id",
        "type",
        "status",
        "scoringPeriodId",
        "teamId",
        "relatedTransactionId",
        "proposedDate",
        "processDate",
        "executionDate",
        "isPending",
    )
    for trade in trades:
        record = {key: trade[key] for key in keys if key in trade}
        record["items"] = [
            {key: item[key] for key in ("type", "playerId", "fromTeamId", "toTeamId") if key in item}
            for item in trade.get("items") or []
        ]
        safe.append(record)
    path = cache / f"{args.season}-trade-probe-{args.view}.json"
    path.write_text(json.dumps(safe, indent=2))
    print("TRADE TYPES", dict(Counter(t["type"] for t in safe)))
    print("TRADE RAW KEYS", sorted({key for t in trades for key in t}))
    for trade in safe:
        if trade.get("scoringPeriodId") in (10, 13):
            print(json.dumps(trade))
    print("Saved", path)


if __name__ == "__main__":
    main()
