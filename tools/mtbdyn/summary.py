"""The ride summary: totals, segments, laps, bike systems."""
from __future__ import annotations

import datetime as dt
import sys
from dataclasses import asdict

from .analysis import detect_corners, max_lateral_g, split_segments
from .loaders import _num
from .model import Ride, Sample
from .scoring import WINDOW, air_score, difficulty_score, flow_score, mtb_score, smoothness_score
from .sram import _mean, _median, _shares, drivetrain_stats, power_stats, suspension_stats


def elevation_change(samples: list[Sample]) -> tuple[float, float]:
    gain = loss = 0.0
    ref = None
    for s in samples:
        if s.alt is None:
            continue
        if ref is None:
            ref = s.alt
            continue
        d = s.alt - ref
        if abs(d) >= 1.0:
            if d > 0:
                gain += d
            else:
                loss -= d
            ref = s.alt
    return gain, loss


def range_stats(ride: Ride, index: int, kind: str, name: str, a: int, b: int, corners: list[dict]) -> dict:
    sl = ride.samples[a:b + 1]
    t0, t1 = sl[0].t, sl[-1].t
    moving = [s for s in sl if s.moving]
    moving_sec = sum(s.dt for s in moving)
    distance = sum(s.d_dist for s in sl)
    grit = sum(s.grit or 0.0 for s in sl)
    flow = sum(s.flow or 0.0 for s in moving)
    flow_dist = sum(s.d_dist for s in moving)
    rough = [s.rough for s in moving if s.rough is not None]
    gain, loss = elevation_change(sl)
    alts = [s.alt for s in sl if s.alt is not None]
    jumps = [j for j in ride.jumps if t0 <= j.t <= t1 + 1]
    return {
        "index": index, "type": kind, "name": name,
        "start_offset_s": t0 - ride.start, "duration_s": t1 - t0 + sl[-1].dt, "distance_m": distance,
        "elev_gain_m": gain, "elev_loss_m": loss,
        "avg_grade_pct": 100.0 * (alts[-1] - alts[0]) / distance if alts and distance > 10 else 0.0,
        "avg_speed_ms": distance / moving_sec if moving_sec else 0.0,
        "max_speed_ms": max((s.speed for s in moving), default=0.0),
        "grit_k": grit / 1000.0, "grit_avg": grit / moving_sec if moving_sec else 0.0,
        "flow_score": flow_score(flow, flow_dist),
        "rough_avg": sum(rough) / len(rough) if rough else None,
        "jumps": len(jumps), "max_air_s": max((j.air for j in jumps), default=0.0),
        "braking_pct": 100.0 * sum(s.dt for s in moving if s.braking) / moving_sec if moving_sec else 0.0,
        "max_lat_g": max_lateral_g(sl),
        "corners": sum(1 for c in corners if t0 <= c["t"] <= t1 + 1),
        # SRAM / RockShox
        "avg_power": _mean([s.power for s in moving if s.power is not None]),
        "w_kg": (_mean([s.power for s in moving if s.power is not None]) or 0.0) / ride.weight if ride.weight else None,
        "vam": 3600.0 * gain / (t1 - t0) if kind == "CLIMB" and t1 > t0 else None,
        "cadence": _mean([s.cadence for s in moving if s.cadence]),
        "median_cog": _median([s.rear_teeth for s in moving if s.rear_teeth]),
        "fa": _shares([s.fa_front for s in moving if s.fa_front is not None]),
        "pedalling_pct": 100.0 * sum(1 for s in moving if (s.cadence or 0) > 0) / len(moving)
        if moving and any(s.cadence is not None for s in moving) else None,
        "shifts": sum(1 for sh in ride.shifts if t0 <= sh["t"] <= t1),
    }


def summarize(ride: Ride, min_elev: float = 15.0) -> dict:
    samples = ride.samples
    if not samples:
        sys.exit("no records in this file")
    moving = [s for s in samples if s.moving]
    moving_sec = sum(s.dt for s in moving)
    grit = sum(s.grit or 0.0 for s in samples)
    flow = sum(s.flow or 0.0 for s in moving)
    flow_dist = sum(s.d_dist for s in moving)
    rough = [s.rough for s in moving if s.rough is not None]
    corners = ride.karoo_corners if ride.karoo_corners is not None else detect_corners(ride)
    gain, loss = elevation_change(samples)

    desc = [s for s in samples if s.descending]
    desc_time = sum(s.dt for s in desc)
    desc_drop = 0.0
    prev_alt = None
    for s in samples:
        if s.alt is not None:
            if s.descending and prev_alt is not None and s.alt < prev_alt:
                desc_drop += prev_alt - s.alt
            prev_alt = s.alt

    def rolling(values: list[tuple[float, float]], min_den: float, scale: float = 1.0) -> float:
        best, num, den = 0.0, 0.0, 0.0
        for i, (n, d) in enumerate(values):
            num, den = num + n, den + d
            if i >= WINDOW:
                num, den = num - values[i - WINDOW][0], den - values[i - WINDOW][1]
            if den >= min_den and i >= WINDOW - 1:
                best = max(best, num / den)
        return best * scale

    total_air = sum(j.air for j in ride.jumps)
    avg_grit = grit / moving_sec if moving_sec else 0.0
    fscore = flow_score(flow, flow_dist)
    diff, smooth, air = difficulty_score(avg_grit), smoothness_score(fscore), air_score(total_air)
    names: dict[str, int] = {}
    segments = []
    seg_ranges = split_segments(samples, min_elev)
    kinds = ["FLAT"] * len(samples)
    for kind, a, b in seg_ranges:
        for i in range(a, b + 1):
            kinds[i] = kind
    for i, (kind, a, b) in enumerate(seg_ranges):
        names[kind] = names.get(kind, 0) + 1
        label = {"CLIMB": "Climb", "DESCENT": "Descent"}.get(kind, "Flat")
        segments.append(range_stats(ride, i + 1, kind, f"{label} {names[kind]}", a, b, corners))
    laps = []
    if len(ride.lap_starts) > 1:
        for n, a in enumerate(ride.lap_starts):
            b = (ride.lap_starts[n + 1] - 1) if n + 1 < len(ride.lap_starts) else len(samples) - 1
            if a <= b:
                laps.append(range_stats(ride, n + 1, "LAP", f"Lap {n + 1}", a, b, corners))
    kept = [100.0 * c["min"] / c["entry"] for c in corners if c["entry"] > 0.5]
    karoo_corners = _num(ride.session.get("mtb_corners"))
    jumps = sorted(ride.jumps, key=lambda j: j.t)
    return {
        "source": ride.source, "device": ride.device,
        "start": dt.datetime.fromtimestamp(samples[0].t, dt.timezone.utc).isoformat(),
        "estimated": ride.estimated, "imu": ride.has_imu,
        "elapsed_s": samples[-1].t - samples[0].t + samples[-1].dt, "moving_s": moving_sec,
        "distance_m": sum(s.d_dist for s in samples), "ascent_m": gain, "descent_m": loss,
        "avg_speed_ms": sum(s.d_dist for s in moving) / moving_sec if moving_sec else 0.0,
        "max_speed_ms": max((s.speed for s in samples), default=0.0),
        "grit": {"total_k": grit / 1000.0, "avg": avg_grit,
                 "peak60": rolling([(s.grit or 0.0, s.dt) for s in samples], 30.0)},
        "flow": {"score": fscore, "total_m": flow,
                 "worst60": rolling([((s.flow or 0.0) if s.moving else 0.0, s.d_dist if s.moving else 0.0) for s in samples], 200.0, 100.0),
                 "descent": flow_score(sum(s.flow or 0.0 for s in desc), sum(s.d_dist for s in desc))},
        "jumps": {
            "count": len(jumps), "total_air_s": total_air,
            "longest": asdict(max(jumps, key=lambda j: j.air)) if jumps else None,
            "farthest": asdict(max(jumps, key=lambda j: j.distance)) if jumps else None,
            "highest": asdict(max(jumps, key=lambda j: j.height)) if jumps else None,
            "list": [asdict(j) for j in jumps],
        },
        "cornering": {
            # The Karoo counts corners with its gyroscope; the list below comes from the GPS track.
            "count": int(karoo_corners) if karoo_corners is not None else len(corners),
            "source": "Karoo gyroscope" if karoo_corners is not None or ride.karoo_corners is not None else "GPS track",
            "list_from_karoo": ride.karoo_corners is not None,
            "gps_count": len(corners), "left": sum(1 for c in corners if c["angle"] > 0),
            "right": sum(1 for c in corners if c["angle"] < 0),
            "speed_kept_pct": sum(kept) / len(kept) if kept else 0.0,
            "max_lat_g": max_lateral_g(ride.samples),
            "list": corners,
        },
        "descending": {
            "time_s": desc_time, "distance_m": sum(s.d_dist for s in desc), "drop_m": desc_drop,
            "avg_speed_ms": sum(s.d_dist for s in desc) / desc_time if desc_time else 0.0,
            "max_speed_ms": max((s.speed for s in desc), default=0.0),
            "braking_pct": 100.0 * sum(s.dt for s in desc if s.braking) / desc_time if desc_time else 0.0,
            "grit_k": sum(s.grit or 0.0 for s in desc) / 1000.0,
        },
        "roughness_avg": sum(rough) / len(rough) if rough else None,
        "score": {"total": mtb_score(diff, smooth, air), "difficulty": diff, "smoothness": smooth, "air": air},
        "segments": segments, "laps": laps,
        "sram": {
            "suspension": suspension_stats(ride, kinds, seg_ranges),
            "drivetrain": drivetrain_stats(ride, kinds, seg_ranges),
            "power": power_stats(ride, kinds),
            "batteries": ride.devices,
        },
        "fit_session": {k: v for k, v in ride.session.items()
                        if k.startswith("mtb_") or k in ("total_grit", "avg_grit", "total_flow", "avg_flow", "jump_count")},
    }
