"""Post-ride insights (mirror of Insights.kt): comparable laps, braking spots, left vs right corners."""
from __future__ import annotations

from .model import Ride

LAP_DISTANCE_TOLERANCE = 0.15
MIN_SPOT_FLOW_M = 3.0
MAX_SPOTS = 3
SPOT_GAP_SEC = 2
MIN_CORNERS_PER_SIDE = 5
SIDE_DIFFERENCE_PCT = 5.0


def lap_comparison(laps: list[dict]) -> dict | None:
    """Laps within 15 % of the median lap distance: fastest, smoothest, first third vs last third."""
    if len(laps) < 2:
        return None
    distances = sorted(lap["distance_m"] for lap in laps)
    median = distances[len(distances) // 2]
    if median < 100.0:
        return None
    comparable = [lap for lap in laps if abs(lap["distance_m"] - median) <= LAP_DISTANCE_TOLERANCE * median]
    if len(comparable) < 2:
        return None
    fastest = min(comparable, key=lambda lap: lap["duration_s"])
    smoothest = min(comparable, key=lambda lap: lap["flow_score"])
    trend = None
    if len(comparable) >= 4:
        third = len(comparable) // 3
        first = sum(lap["duration_s"] for lap in comparable[:third]) / third
        last = sum(lap["duration_s"] for lap in comparable[-third:]) / third
        trend = 100.0 * (last - first) / first
    times = sorted(lap["duration_s"] for lap in comparable)
    return {
        "comparable": len(comparable), "laps": len(laps),
        "fastest_lap": fastest["index"], "fastest_s": fastest["duration_s"], "median_s": times[len(times) // 2],
        "smoothest_lap": smoothest["index"], "smoothest_flow": smoothest["flow_score"], "trend_pct": trend,
    }


def braking_spots(ride: Ride, segments: list[dict]) -> list[dict]:
    """Runs of seconds with unnecessary braking (gaps up to 2 s joined), the 3 with the most braking metres."""
    samples = ride.samples

    def counts(s) -> bool:
        return s.moving and (s.flow or 0.0) > 0.05

    spots = []
    i = 0
    while i < len(samples):
        if not counts(samples[i]):
            i += 1
            continue
        end, j = i, i + 1
        while j < len(samples) and j - end <= SPOT_GAP_SEC + 1:
            if counts(samples[j]):
                end = j
            j += 1
        run = samples[i:end + 1]
        flow = sum(s.flow or 0.0 for s in run)
        if flow >= MIN_SPOT_FLOW_M:
            first = run[0]
            offset = first.t - ride.start
            located = next((s for s in run if s.lat is not None and s.lon is not None), None)
            segment = next((sg["name"] for sg in segments if sg["type"] != "FLAT"
                            and sg["start_offset_s"] <= offset < sg["start_offset_s"] + sg["duration_s"]), None)
            spots.append({
                "offset_s": offset, "distance_m": first.dist - first.d_dist, "flow_m": flow,
                "duration_s": sum(s.dt for s in run),
                "speed_before_ms": max(samples[max(0, i - 1)].speed, first.speed),
                "speed_after_ms": min(s.speed for s in run),
                "lat": located.lat if located else None, "lon": located.lon if located else None, "segment": segment,
            })
        i = end + 1
    return sorted(spots, key=lambda s: -s["flow_m"])[:MAX_SPOTS]


def corner_sides(corners: list[dict]) -> tuple[float | None, float | None]:
    """Speed kept (apex / entry) in left and right corners; None with fewer than 5 on a side."""
    def kept(side: list[dict]) -> float | None:
        valid = [c for c in side if c["entry"] > 0.5]
        if len(valid) < MIN_CORNERS_PER_SIDE:
            return None
        return sum(100.0 * c["min"] / c["entry"] for c in valid) / len(valid)

    return kept([c for c in corners if c["angle"] > 0]), kept([c for c in corners if c["angle"] < 0])


def corner_side_hint(left: float | None, right: float | None) -> str | None:
    if left is None or right is None:
        return None
    if abs(left - right) < SIDE_DIFFERENCE_PCT:
        return f"Left and right corners alike ({left:.0f}% / {right:.0f}% speed kept)"
    weak, worse, better = ("left", left, right) if left < right else ("right", right, left)
    return f"You lose more speed in {weak}-handers ({worse:.0f}% vs {better:.0f}% kept)"
