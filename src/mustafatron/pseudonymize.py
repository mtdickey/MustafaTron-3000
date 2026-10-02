"""Replace ESPN SWIDs with stable opaque manager IDs before anything is written to disk.

A SWID is ESPN's account identifier and half of the login cookie pair, so it never goes
into git. Each one is mapped to ``m_`` + 16 hex chars of HMAC-SHA256(MANAGER_ID_KEY, SWID).
The same SWID always gives the same ID, so seasons stay joinable, but recovering the SWID
needs the key, which lives only in ``.env`` and GitHub Actions secrets.
"""

import hashlib
import hmac
import re
from typing import Any

SWID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
MANAGER_ID_RE = re.compile(r"^m_[0-9a-f]{16}$")


def manager_id(swid: str, key: bytes) -> str:
    digest = hmac.new(key, swid.strip().upper().encode(), hashlib.sha256).hexdigest()
    return "m_" + digest[:16]


def pseudonymize(obj: Any, key: bytes) -> Any:
    """Return a copy of a decoded JSON value with every SWID string replaced, at any depth."""
    if isinstance(obj, dict):
        return {k: pseudonymize(v, key) for k, v in obj.items()}
    if isinstance(obj, list):
        return [pseudonymize(v, key) for v in obj]
    if isinstance(obj, str) and SWID_RE.match(obj):
        return manager_id(obj, key)
    return obj


def scrub_season(data: dict, key: bytes) -> dict:
    """Make a fetched season safe to commit: pseudonymize SWIDs, drop private member fields."""
    data = pseudonymize(data, key)
    for member in data.get("members", []):
        member.pop("notificationSettings", None)  # private ESPN prefs, not league data
    return data


def find_swids(obj: Any) -> int:
    """Count SWID-shaped strings remaining anywhere in a decoded JSON value."""
    if isinstance(obj, dict):
        return sum(find_swids(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(find_swids(v) for v in obj)
    return int(isinstance(obj, str) and bool(SWID_RE.match(obj)))
