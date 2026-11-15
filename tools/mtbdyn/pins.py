"""Jump pins from the map (browser analyser, jump-spots.json): every pass over each pin and whether the Karoo counted it.

The same rules run in docs/analyser/pins.mjs; testdata/pins_fixture.json keeps the two in step.
"""
from __future__ import annotations

import json
import math

from .model import Ride

PASS_RADIUS_M = 15.0   # a pass = the track comes this close to the pin
PASS_GAP_S = 20.0      # closer moments further apart than this are separate passes
MATCH_S = 2.5          # a Karoo jump counts a pass when it takes off this close in time to the closest approach
M_PER_DEG = 111_320.0


def load_pins(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return [s for s in data.get("spots", []) if s.get("label") in ("jump", "nojump")]


def _xy(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    return (lon - lon0) * M_PER_DEG * math.cos(math.radians(lat0)), (lat - lat0) * M_PER_DEG


def passes(track: list[tuple[float, float, float]], pin: dict) -> list[dict]:
    """Passes over [pin] along [track] (t, lat, lon): closest approach time and distance."""
    lat0, lon0 = pin["lat"], pin["lon"]
    out: list[dict] = []
    cur = None
    for (ta, la, oa), (tb, lb, ob) in zip(track, track[1:]):
        ax, ay = _xy(la, oa, lat0, lon0)
        bx, by = _xy(lb, ob, lat0, lon0)
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        f = 0.0 if seg == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg))
        d = math.hypot(ax + f * dx, ay + f * dy)
        if d > PASS_RADIUS_M:
            continue
        t = ta + f * (tb - ta)
        if cur is not None and t - cur["last"] <= PASS_GAP_S:
            cur["last"] = t
            if d < cur["d"]:
                cur["d"], cur["t"] = d, t
        else:
            cur = {"t": t, "d": d, "last": t}
            out.append(cur)
    return [{"t": p["t"], "d": p["d"]} for p in out]


def ride_report(track, jumps: list[tuple[int, float]], pins: list[dict]) -> dict:
    """[jumps] = (n, take-off t) of the Karoo's jumps. Each jump counts at most one pass, the nearest in time."""
    rows = []
    for k, pin in enumerate(pins):
        for p in passes(track, pin):
            rows.append({"pin": k, "label": pin["label"], "t": p["t"], "d": p["d"], "jump": None})
    for n, t in sorted(jumps, key=lambda j: j[1]):
        near = [(abs(t - r["t"]), i) for i, r in enumerate(rows) if r["jump"] is None and abs(t - r["t"]) <= MATCH_S]
        if near:
            rows[min(near)[1]]["jump"] = n
    used = {r["jump"] for r in rows if r["jump"] is not None}
    rows.sort(key=lambda r: r["t"])
    jump_rows = [r for r in rows if r["label"] == "jump"]
    return {
        "passes": rows,
        "jump_passes": len(jump_rows),
        "counted": sum(1 for r in jump_rows if r["jump"] is not None),
        "nojump_counted": sum(1 for r in rows if r["label"] == "nojump" and r["jump"] is not None),
        "elsewhere": sorted(n for n, _ in jumps if n not in used),
    }


def track_of(ride: Ride) -> list[tuple[float, float, float]]:
    return [(s.t, s.lat, s.lon) for s in ride.samples if s.lat is not None and s.lon is not None and not (s.lat == 0 and s.lon == 0)]


def jumps_of(ride: Ride) -> list[tuple[int, float]]:
    return [(j.n, j.t) for j in ride.jumps]


def pins_text(rides: list[tuple[str, Ride]], pins: list[dict]) -> str:
    import datetime as dt
    lines = [f"{sum(p['label'] == 'jump' for p in pins)} jump pins, {sum(p['label'] == 'nojump' for p in pins)} not-a-jump pins "
             f"(pass = within {PASS_RADIUS_M:.0f} m; counted = a Karoo jump within {MATCH_S} s)"]
    total = counted = 0
    for name, ride in rides:
        r = ride_report(track_of(ride), jumps_of(ride), pins)
        if not r["passes"] and not r["elsewhere"]:
            continue
        start = ride.samples[0].t if ride.samples else 0
        day = dt.datetime.fromtimestamp(start).strftime("%a %d %b %H:%M")
        total += r["jump_passes"]
        counted += r["counted"]
        lines.append(f"\n{day}  {name}")
        lines.append(f"  jump pins: {r['jump_passes']} passes, counted {r['counted']}, missed {r['jump_passes'] - r['counted']}"
                     + (f"; not-a-jump pins counted {r['nojump_counted']}" if r["nojump_counted"] else "")
                     + (f"; Karoo jumps elsewhere: {', '.join('#%d' % n for n in r['elsewhere'])}" if r["elsewhere"] else ""))
        for p in r["passes"]:
            at = dt.datetime.fromtimestamp(p["t"]).strftime("%H:%M:%S")
            what = f"counted #{p['jump']}" if p["jump"] is not None else ("missed" if p["label"] == "jump" else "not counted")
            lines.append(f"    pin {p['pin'] + 1} ({p['label']})  {at}  {p['d']:4.1f} m  {what}")
    if total:
        lines.append(f"\nAll rides: {total} passes over jump pins, counted {counted} ({100 * counted / total:.0f} %)")
    return "\n".join(lines)
