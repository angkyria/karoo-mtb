"""Grit / Flow / corners / segments computed from the samples."""
from __future__ import annotations

import math

from .model import Ride, Sample
from .scoring import MAX_LATERAL_G, G


# --------------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------------
def max_lateral_g(samples: list[Sample]) -> float:
    """Highest 3 s average lateral g (single-second peaks are steering wobble), capped."""
    best = 0.0
    vals = [(x.lat_g or 0.0) if x.moving else 0.0 for x in samples]
    for i in range(len(vals)):
        window = vals[max(0, i - 1):i + 2]
        best = max(best, sum(window) / len(window))
    return min(MAX_LATERAL_G, best)


def detect_corners(ride: Ride) -> list[dict]:
    """1 Hz port of CornerDetector.kt on the yaw rate (GPS bearing)."""
    enter, exit_rate, exit_hold, min_angle, min_dur, min_speed, stop_speed = 0.20, 0.10, 0.5, 35.0, 0.8, 2.0, 1.0
    corners: list[dict] = []
    state = None
    last_t = None

    def finish(end_t):
        nonlocal state
        c, state = state, None
        dur = end_t - c["start"]
        ang = math.degrees(c["angle"])
        if abs(ang) >= min_angle and dur >= min_dur:
            corners.append({
                "n": len(corners) + 1, "t": c["start"], "duration": dur, "angle": ang, "entry": c["entry"],
                "min": c["min"], "exit": c["last"], "max_lat_g": c["lat"],
                "radius": c["dist"] / abs(c["angle"]) if abs(c["angle"]) > 1e-3 else None,
            })

    for s in ride.samples:
        yaw, v, t = s.yaw or 0.0, s.speed, s.t
        dtt = 0.0 if last_t is None else min(1.5, max(0.0, t - last_t))
        last_t = t
        if state:
            if v < stop_speed or (math.copysign(1, yaw) != state["dir"] and abs(yaw) >= enter):
                finish(t)
            else:
                state["angle"] += yaw * dtt
                state["dist"] += v * dtt
                state["min"] = min(state["min"], v)
                state["lat"] = max(state["lat"], v * abs(yaw) / G)
                state["last"] = v
                if abs(yaw) < exit_rate:
                    state.setdefault("calm", t)
                    if t - state["calm"] >= exit_hold:
                        finish(state["calm"])
                else:
                    state.pop("calm", None)
        if state is None and abs(yaw) >= enter and v >= min_speed:
            state = {"start": t, "angle": yaw * dtt, "dir": math.copysign(1, yaw), "entry": v, "min": v, "last": v,
                     "lat": v * abs(yaw) / G, "dist": 0.0}
    if state:
        finish(last_t)
    return corners


def split_segments(samples: list[Sample], min_elev: float) -> list[tuple[str, int, int]]:
    """Zig-zag split on smoothed altitude (port of Segmenter.kt)."""
    if len(samples) < 2:
        return []
    raw = [s.alt for s in samples]
    first = next((a for a in raw if a is not None), None)
    if first is None:
        out, start = [], 0
        for i, s in enumerate(samples):
            if s.dist - samples[start].dist >= 2000 or i == len(samples) - 1:
                if i > start:
                    out.append(("FLAT", start, i))
                start = i
        return out
    filled, last = [], first
    for a in raw:
        last = a if a is not None else last
        filled.append(last)
    alt = []
    for i in range(len(filled)):
        lo, hi = max(0, i - 5), min(len(filled) - 1, i + 5)
        alt.append(sum(filled[lo:hi + 1]) / (hi - lo + 1))
    pivots, direction, hi_i, lo_i = [0], 0, 0, 0
    for i in range(1, len(alt)):
        if alt[i] > alt[hi_i]:
            hi_i = i
        if alt[i] < alt[lo_i]:
            lo_i = i
        if direction == 0:
            if alt[hi_i] - alt[lo_i] >= min_elev:
                if lo_i < hi_i:
                    if lo_i != 0:
                        pivots.append(lo_i)
                    direction = 1
                else:
                    if hi_i != 0:
                        pivots.append(hi_i)
                    direction = -1
        elif direction == 1:
            if alt[hi_i] - alt[i] >= min_elev:
                pivots.append(hi_i)
                direction, lo_i = -1, i
        elif alt[i] - alt[lo_i] >= min_elev:
            pivots.append(lo_i)
            direction, hi_i = 1, i
    if pivots[-1] != len(alt) - 1:
        pivots.append(len(alt) - 1)

    def classify(delta: float) -> str:
        return "CLIMB" if delta >= 0.6 * min_elev else "DESCENT" if delta <= -0.6 * min_elev else "FLAT"

    zig = [(classify(alt[b] - alt[a]), a, b) for a, b in zip(pivots, pivots[1:]) if b > a]

    # Cut long flat stretches out of climbs/descents (port of Segmenter.splitFlats).
    flat = []
    for i in range(len(samples)):
        a, b = max(0, i - 15), min(len(samples) - 1, i + 15)
        d = samples[b].dist - samples[a].dist
        flat.append(d > 20.0 and abs(100.0 * (alt[b] - alt[a]) / d) < 2.5)
    pieces: list[tuple[str, int, int]] = []
    for kind, a, b in zig:
        if kind == "FLAT":
            pieces.append((kind, a, b))
            continue
        cursor, i = a, a
        while i <= b:
            if not flat[i]:
                i += 1
                continue
            j = i
            while j + 1 <= b and flat[j + 1]:
                j += 1
            if samples[j].dist - samples[i].dist >= 400.0:
                if i > cursor:
                    pieces.append((classify(alt[i] - alt[cursor]), cursor, i))
                pieces.append(("FLAT", i, j))
                cursor = j
            i = j + 1
        if b > cursor:
            pieces.append((classify(alt[b] - alt[cursor]), cursor, b))

    ranges: list[tuple[str, int, int]] = []
    for kind, a, b in pieces:
        if ranges and ranges[-1][0] == kind:
            ranges[-1] = (kind, ranges[-1][1], b)
        else:
            ranges.append((kind, a, b))
    return ranges
