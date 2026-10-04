"""intervals.icu API client and description block."""
from __future__ import annotations

import base64
import datetime as dt
import json
import sys
import urllib.request

from .report import Units, hms

# --------------------------------------------------------------------------------------------
# intervals.icu
# --------------------------------------------------------------------------------------------
RIDE_TYPES = {"Ride", "MountainBikeRide", "GravelRide", "EBikeRide", "EMountainBikeRide"}
DESCRIPTION_MARKER = "🚵 MTB Dynamics"

class IcuError(Exception):
    def __init__(self, method: str, path: str, status: int, body: bytes):
        super().__init__(f"intervals.icu {method} {path}: HTTP {status} {body[:300]!r}")
        self.status = status


class IntervalsIcu:
    """Minimal client for https://intervals.icu/api/v1 (Settings → Developer Settings → API key)."""

    def __init__(self, api_key: str, athlete: str = "0", base: str = "https://intervals.icu"):
        token = base64.b64encode(f"API_KEY:{api_key.strip()}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "User-Agent": "karoo-mtb/1.0"}
        self.athlete = athlete
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: dict | list | None = None, timeout: float = 60) -> bytes:
        """Raises IcuError on an HTTP error."""
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise IcuError(method, path, e.code, e.read()) from None

    def _request(self, method: str, path: str, body: dict | None = None) -> bytes:
        try:
            return self.call(method, path, body)
        except IcuError as e:
            sys.exit(str(e))

    def latest_ride_id(self, days: int = 30) -> str:
        today = dt.date.today()
        q = urllib.parse.urlencode({"oldest": (today - dt.timedelta(days=days)).isoformat(), "newest": today.isoformat()})
        acts = json.loads(self._request("GET", f"/api/v1/athlete/{self.athlete}/activities?{q}"))
        rides = [a for a in acts if a.get("type") in RIDE_TYPES]
        if not rides:
            sys.exit(f"no ride on intervals.icu in the last {days} days")
        rides.sort(key=lambda a: a.get("start_date_local") or "", reverse=True)
        return str(rides[0]["id"])

    def ride_ids(self, days: int) -> list[str]:
        """Rides of the last [days], oldest first."""
        today = dt.date.today()
        q = urllib.parse.urlencode({"oldest": (today - dt.timedelta(days=days)).isoformat(), "newest": today.isoformat()})
        acts = json.loads(self._request("GET", f"/api/v1/athlete/{self.athlete}/activities?{q}"))
        rides = sorted((a for a in acts if a.get("type") in RIDE_TYPES), key=lambda a: a.get("start_date_local") or "")
        return [str(a["id"]) for a in rides]

    def activity(self, activity_id: str) -> dict:
        return json.loads(self._request("GET", f"/api/v1/activity/{activity_id}"))

    def original_file(self, activity_id: str) -> bytes:
        return self._request("GET", f"/api/v1/activity/{activity_id}/file")

    def update(self, activity_id: str, fields: dict) -> None:
        self._request("PUT", f"/api/v1/activity/{activity_id}", fields)

    # Custom streams, fields and charts (tools/icu_setup.py). The content of an item is not in the
    # API docs; tools/icu_setup.py sends what intervals.icu's own editors save.
    def activities(self, oldest: str, newest: str) -> list[dict]:
        q = urllib.parse.urlencode({"oldest": oldest, "newest": newest})
        return json.loads(self.call("GET", f"/api/v1/athlete/{self.athlete}/activities?{q}"))

    def custom_items(self) -> list[dict]:
        return json.loads(self.call("GET", f"/api/v1/athlete/{self.athlete}/custom-item"))

    def create_custom_item(self, item: dict) -> dict:
        return json.loads(self.call("POST", f"/api/v1/athlete/{self.athlete}/custom-item", item))

    def update_custom_item(self, item_id: int, item: dict) -> dict:
        return json.loads(self.call("PUT", f"/api/v1/athlete/{self.athlete}/custom-item/{item_id}", item))


def description_block(s: dict, u: Units) -> str:
    j, c, d = s["jumps"], s["cornering"], s["descending"]
    parts = [
        f"{DESCRIPTION_MARKER} · score {s['score']['total']:.0f}",
        f"Grit {s['grit']['total_k']:.1f} kGrit · Flow {s['flow']['score']:.2f} · {j['count']} jumps"
        + (f" (longest {j['longest']['air']:.2f} s / {u.short(j['longest']['distance'])})" if j["longest"] else ""),
        f"{c['count']} corners · max {c['max_lat_g']:.2f} g · descents {hms(d['time_s'])}, braking {d['braking_pct']:.0f} %",
    ]
    return "\n".join(parts)


def merged_description(old: str | None, block: str) -> str:
    """Replaces a previous MTB block (idempotent re-runs) and keeps the rest of the description."""
    old = old or ""
    kept, skipping = [], False
    for line in old.splitlines():
        if line.startswith(DESCRIPTION_MARKER):
            skipping = True
            continue
        if skipping and (line.startswith("Grit ") or " corners · " in line or line.startswith("PB ")):
            continue
        skipping = False
        kept.append(line)
    text = "\n".join(kept).rstrip()
    return (text + "\n\n" if text else "") + block


def parse_field_map(spec: str | None) -> dict[str, str]:
    """'MtbGrit=grit.total_k,MtbFlow=flow.score' -> {code: summary path}."""
    out = {}
    for part in (spec or "").split(","):
        if "=" in part:
            code, path = part.split("=", 1)
            out[code.strip()] = path.strip()
    return out


def summary_value(s: dict, path: str):
    cur = s
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur
