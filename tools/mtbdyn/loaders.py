"""Loading FIT files and Karoo ride folders."""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import sys
import zipfile
from typing import Iterable

from .model import Jump, Ride, Sample
from .scoring import (
    DEFAULT_FLOW_LAG,
    FIT_EPOCH_OFFSET,
    MAX_LATERAL_G,
    SEMICIRCLE_TO_DEG,
    G,
    brake_weight,
    braking_decel,
    braking_necessity,
    grit_per_second,
    jump_height,
)


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------
def _ts(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value) + FIT_EPOCH_OFFSET if value < 1_000_000_000 else float(value)
    return None


def _num(value) -> float | None:
    if value is None or isinstance(value, (list, tuple, str, bytes)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def read_fit_bytes(raw: bytes) -> bytes:
    """Unwraps .gz / .zip containers (intervals.icu may return either)."""
    if raw[:2] == b"\x1f\x8b":
        return read_fit_bytes(gzip.decompress(raw))
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".fit")), z.namelist()[0])
            return read_fit_bytes(z.read(name))
    return raw


def load_fit(raw: bytes, source: str = "") -> Ride:
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError:
        sys.exit("FIT input needs the Garmin FIT SDK:  pip install garmin-fit-sdk")
    decoder = Decoder(Stream.from_byte_array(bytearray(read_fit_bytes(raw))))
    if not decoder.is_fit():
        sys.exit(f"{source}: not a FIT file")
    messages, errors = decoder.read(convert_datetimes_to_dates=True, merge_heart_rates=True)
    if errors:
        print(f"warning: FIT decode reported {len(errors)} problem(s): {errors[0]}", file=sys.stderr)

    names: dict[int, str] = {}
    for fd in messages.get("field_description_mesgs", []):
        if fd.get("field_name") is not None:
            names[fd.get("key")] = str(fd["field_name"]).strip()

    def dev(mesg: dict) -> dict:
        return {names.get(k, str(k)): v for k, v in (mesg.get("developer_fields") or {}).items()}

    samples: list[Sample] = []
    last_t = None
    fa_mode_seen: list[int] = []
    fa_bias_seen: list[int] = []
    for r in messages.get("record_mesgs", []):
        t = _ts(r.get("timestamp"))
        if t is None or (last_t is not None and t <= last_t):
            continue
        d = dev(r)
        lat, lon = _num(r.get("position_lat")), _num(r.get("position_long"))
        s = Sample(
            t=t,
            dt=1.0 if last_t is None else min(5.0, max(0.2, t - last_t)),
            dist=_num(r.get("distance")) or 0.0,
            speed=_num(r.get("enhanced_speed")) or _num(r.get("speed")) or 0.0,
            alt=_num(r.get("enhanced_altitude")) if r.get("enhanced_altitude") is not None else _num(r.get("altitude")),
            lat=lat * SEMICIRCLE_TO_DEG if lat is not None else None,
            lon=lon * SEMICIRCLE_TO_DEG if lon is not None else None,
            grade=_num(r.get("grade")),
            hr=_num(r.get("heart_rate")),
            power=_num(r.get("power")),
        )
        # Karoo MTB Dynamics developer fields, else Garmin's native fields.
        s.grit = _num(d.get("mtb_grit")) if "mtb_grit" in d else _num(r.get("grit"))
        s.flow = _num(d.get("mtb_flow")) if "mtb_flow" in d else _num(r.get("flow"))
        s.rough = _num(d.get("mtb_rough"))
        s.lat_g = _num(d.get("mtb_lat_g"))
        s.brake = _num(d.get("mtb_brake"))
        s.jump_air = _num(d.get("mtb_jump_air")) or 0.0
        s.jump_dist = _num(d.get("mtb_jump_dist")) or 0.0
        s.jump_height = _num(d.get("mtb_jump_height")) or 0.0
        s.cadence = _num(r.get("cadence"))
        bal = _num(r.get("left_right_balance"))
        s.balance = bal % 128 if bal is not None and 0 < bal % 128 < 100 else None
        for attr, key in (("fa_front", "front_suspension"), ("fa_rear", "rear_suspension"), ("effort_zone", "suspension_effort_zone")):
            v = _num(d.get(key))
            setattr(s, attr, int(v) if v is not None else None)
        if d.get("suspension_mode") is not None:
            fa_mode_seen.append(int(_num(d.get("suspension_mode")) or 0))
        if d.get("suspension_bias") is not None:
            fa_bias_seen.append(int(_num(d.get("suspension_bias")) or 0))
        samples.append(s)
        last_t = t

    session_msg = (messages.get("session_mesgs") or [{}])[0]
    session = {k: v for k, v in session_msg.items() if k != "developer_fields" and not isinstance(v, (bytes, bytearray))}
    session.update(dev(session_msg))
    has_mtb = any("mtb_grit" in dev(r) for r in messages.get("record_mesgs", [])[:50])
    ride = Ride(samples=samples, session=session, source=source)
    ride.has_imu = has_mtb and any(s.rough for s in samples)
    ride.flow_lag = int(_num(session.get("mtb_flow_lag")) or DEFAULT_FLOW_LAG) if has_mtb else 0
    fid = (messages.get("file_id_mesgs") or [{}])[0]
    ride.device = " ".join(str(x) for x in (fid.get("manufacturer"), fid.get("product_name") or fid.get("garmin_product") or fid.get("product")) if x)
    ride.fa_mode = fa_mode_seen[-1] if fa_mode_seen else None
    ride.fa_bias = fa_bias_seen[-1] if fa_bias_seen else None
    cassette = session.get("rear_gear")
    ride.cassette = sorted(int(x) for x in cassette) if isinstance(cassette, (list, tuple)) else None
    _load_gears(ride, messages.get("event_mesgs", []))
    ride.devices = _sram_devices(messages.get("device_info_mesgs", []))

    # Laps -> sample index where each lap starts.
    starts = []
    for lap in messages.get("lap_mesgs", []):
        lt = _ts(lap.get("start_time"))
        if lt is not None:
            starts.append(_index_at(samples, lt))
    ride.lap_starts = sorted(set([0] + starts)) if samples else [0]
    _assign_laps(ride)

    _finish_samples(ride)
    if has_mtb:
        _realign_lagged(ride)
        ride.jumps = _jumps_from_records(ride)
    else:
        ride.jumps = _jumps_from_garmin(messages.get("jump_mesgs", []), samples)
        if all(s.grit is None for s in samples):
            estimate_from_gps(ride)
        else:
            estimate_braking(ride)  # Garmin files carry grit/flow but no braking trace
    _refine_jump_heights(ride)
    return ride


def _load_gears(ride: Ride, events: Iterable[dict]) -> None:
    """Rear shifts from FIT gear-change events; every second gets the cog in use."""
    shifts = []
    for e in events:
        if e.get("event") != "rear_gear_change":
            continue
        t = _ts(e.get("timestamp"))
        teeth, gear = _num(e.get("rear_gear")), _num(e.get("rear_gear_num"))
        if t is not None and teeth:
            shifts.append({"t": t, "teeth": int(teeth), "gear": int(gear) if gear else None})
    shifts.sort(key=lambda x: x["t"])
    _apply_shifts(ride, shifts)


def _apply_shifts(ride: Ride, shifts: list[dict]) -> None:
    samples = ride.samples
    k, teeth, gear = 0, None, None
    previous = None
    for sh in shifts:
        sh["from_teeth"] = previous
        previous = sh["teeth"]
    for s in samples:
        while k < len(shifts) and shifts[k]["t"] <= s.t:
            teeth, gear = shifts[k]["teeth"], shifts[k]["gear"]
            k += 1
        if teeth is not None and s.rear_teeth is None:
            s.rear_teeth, s.rear_gear = teeth, gear
    for sh in shifts:
        i = _index_at(samples, sh["t"]) if samples else 0
        if samples:
            sh["power"] = samples[i].power
            sh["cadence"] = samples[i].cadence
    ride.shifts = shifts


def _sram_devices(infos: Iterable[dict]) -> list[dict]:
    """Paired components with a battery level (latest report per device)."""
    latest: dict = {}
    for d in infos:
        idx = d.get("device_index")
        if idx in (None, 0, "creator"):
            continue
        level, status = d.get("battery_level"), d.get("battery_status")
        if level is None and status is None:
            continue
        ble = d.get("ble_device_type")
        name = str(d.get("product_name") or "").strip() or None
        kind = ("Flight Attendant" if name and name.lower().startswith("kilo") else
                "AXS shifting" if d.get("antplus_device_type") == "shifting" else
                f"BLE device (type {ble})" if ble is not None else d.get("antplus_device_type") or "ANT+ sensor")
        latest[idx] = {"index": idx, "manufacturer": d.get("manufacturer"), "name": name, "kind": kind,
                       "battery_pct": level, "battery_status": status}
    return list(latest.values())


def load_karoo_dir(path: str) -> Ride:
    """A ride folder from the Karoo (adb pull .../files/rides/<start>)."""
    samples: list[Sample] = []
    with open(os.path.join(path, "samples.csv"), newline="") as f:
        for row in csv.DictReader(f):
            def num(key, row=row):
                v = row.get(key, "")
                return float(v) if v not in ("", None) else None
            samples.append(Sample(
                t=int(row["wall_ms"]) / 1000.0, dt=num("dt") or 1.0, dist=num("distance_m") or 0.0,
                d_dist=num("d_dist_m") or 0.0, speed=num("speed_ms") or 0.0, alt=num("altitude_m"),
                lat=num("lat"), lon=num("lon"), grade=num("grade_pct"), grit=num("grit"), flow=num("flow_m"),
                rough=num("rough_g"), lat_g=num("lat_g"), brake=num("brake_ms2"), curvature=num("curvature"),
                yaw=num("yaw_rate"), lap=int(row.get("lap") or 0), power=num("power_w"), cadence=num("cadence_rpm"),
                balance=num("balance_left"),
                fa_front=_int(num("fa_front")), fa_rear=_int(num("fa_rear")), effort_zone=_int(num("effort_zone")),
                rear_gear=_int(num("rear_gear")), rear_teeth=_int(num("rear_teeth")),
            ))
    ride = Ride(samples=samples, source=path, device="Karoo (ride folder)")
    ride.has_imu = any(s.rough is not None for s in samples)
    ride.flow_lag = 0  # the CSV already holds aligned values
    laps = sorted({s.lap for s in samples})
    ride.lap_starts = [next(i for i, s in enumerate(samples) if s.lap == lap) for lap in laps] or [0]
    start_wall = samples[0].t if samples else 0.0
    meta_path = os.path.join(path, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            start_wall = json.load(f).get("startWallMs", start_wall * 1000) / 1000.0
    summary = os.path.join(path, "summary.json")
    if os.path.exists(summary):
        with open(summary) as f:
            ride.karoo_summary = json.load(f)
    corners: list[dict] = []
    jumps: list[dict] = []
    shifts: list[dict] = []
    events = os.path.join(path, "events.jsonl")
    if os.path.exists(events):
        with open(events) as f:
            for line in f:
                e = json.loads(line) if line.strip() else {}
                if e.get("jump"):
                    jumps.append(e["jump"])
                sh = e.get("shift")
                if sh:
                    shifts.append({"t": sh["wallMs"] / 1000.0, "gear": sh.get("gear"), "teeth": sh.get("teeth"),
                                   "from_teeth": sh.get("fromTeeth"), "power": sh.get("powerW"), "cadence": sh.get("cadenceRpm")})
                c = e.get("corner")
                if c:
                    corners.append({
                        "n": c["n"], "t": start_wall + c["offsetSec"], "duration": c["durationSec"], "angle": c["angleDeg"],
                        "entry": c["entrySpeedMs"], "min": c["minSpeedMs"], "exit": c["exitSpeedMs"],
                        "max_lat_g": min(MAX_LATERAL_G, c["maxLateralG"]), "radius": c.get("radiusM") or None,
                    })
    # Rides recorded with app 0.1.0 have no jump events; their summary.json still lists them.
    if not jumps and ride.karoo_summary:
        jumps = ride.karoo_summary.get("jumps", {}).get("list", [])
    for j in jumps:
        ride.jumps.append(Jump(
            n=j["n"], t=j["takeoffWallMs"] / 1000.0, air=j["airSec"], distance=j["distanceM"],
            height=j["heightM"], speed=j["speedMs"], drop=j.get("dropM"), landing_g=j.get("landingG"),
            rotations=j.get("rotations", 0), score=j.get("score"), lat=j.get("lat"), lon=j.get("lon"),
        ))
    ride.karoo_corners = corners or None
    ride.shifts = shifts
    if ride.karoo_summary:
        bike = ride.karoo_summary.get("bike") or {}
        ride.fa_mode, ride.fa_bias = bike.get("faMode"), bike.get("faBias")
        ride.devices = [{"kind": b.get("component"), "battery_status": b.get("status"), "battery_pct": b.get("percent")}
                        for b in bike.get("batteries", [])]
    return ride


def _int(v):
    return None if v is None else int(v)


def _index_at(samples: list[Sample], t: float) -> int:
    lo, hi = 0, len(samples) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if samples[mid].t < t:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _assign_laps(ride: Ride) -> None:
    for n, start in enumerate(ride.lap_starts):
        end = ride.lap_starts[n + 1] if n + 1 < len(ride.lap_starts) else len(ride.samples)
        for s in ride.samples[start:end]:
            s.lap = n


def _finish_samples(ride: Ride) -> None:
    """Distance deltas, grade (when the file has none) and yaw / curvature from GPS bearing."""
    samples = ride.samples
    prev = None
    for s in samples:
        if prev is not None:
            dd = s.dist - prev.dist
            s.d_dist = dd if 0 <= dd <= s.speed * s.dt + 25 else s.speed * s.dt
        prev = s
    if all(s.grade is None for s in samples):
        for i, s in enumerate(samples):
            a, b = samples[max(0, i - 5)], samples[min(len(samples) - 1, i + 5)]
            if a.alt is not None and b.alt is not None and b.dist - a.dist > 10:
                s.grade = 100.0 * (b.alt - a.alt) / (b.dist - a.dist)
    # Turn rate from GPS bearing (only where the file has no gyroscope data), smoothed over 3 s
    # because 1 Hz GPS positions jitter by a metre or two.
    gps_yaw: list[float | None] = [None] * len(samples)
    bearing_prev = None
    for i, s in enumerate(samples):
        if i == 0 or s.lat is None or samples[i - 1].lat is None:
            continue
        p = samples[i - 1]
        b = _bearing(p.lat, p.lon, s.lat, s.lon)
        if bearing_prev is not None and s.speed >= 2.5 and s.d_dist > 0.5:
            gps_yaw[i] = -math.radians((b - bearing_prev + 540.0) % 360.0 - 180.0) / s.dt
        if s.d_dist > 0.5:
            bearing_prev = b
    for i, s in enumerate(samples):
        window = [y for y in gps_yaw[max(0, i - 1):i + 2] if y is not None]
        if gps_yaw[i] is None or not window:
            continue
        yaw = sum(window) / len(window)
        if s.yaw is None:
            s.yaw = yaw
        if s.curvature is None:
            s.curvature = abs(yaw) / s.speed if s.speed >= 1.5 else 0.0


def _bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _realign_lagged(ride: Ride) -> None:
    """mtb_flow / mtb_brake are written flow_lag seconds late (Flow needs look-ahead)."""
    lag = ride.flow_lag
    if lag <= 0:
        return
    samples = ride.samples
    flows = [(s.t - lag, s.flow, s.brake) for s in samples]
    for s in samples:
        s.flow, s.brake = 0.0, 0.0
    for t, f, b in flows:
        i = _index_at(samples, t)
        if 0 <= i < len(samples) and abs(samples[i].t - t) <= 1.0:
            samples[i].flow = (samples[i].flow or 0.0) + (f or 0.0)
            samples[i].brake = max(samples[i].brake or 0.0, b or 0.0)


def _jumps_from_records(ride: Ride) -> list[Jump]:
    jumps = []
    for s in ride.samples:
        if s.jump_air > 0:
            jumps.append(Jump(
                n=len(jumps) + 1, t=s.t - s.jump_air, air=s.jump_air, distance=s.jump_dist,
                height=s.jump_height or jump_height(s.jump_air), speed=s.jump_dist / s.jump_air if s.jump_air else 0.0,
                lat=s.lat, lon=s.lon,
            ))
    return jumps


def _jumps_from_garmin(mesgs: Iterable[dict], samples: list[Sample]) -> list[Jump]:
    jumps = []
    for m in mesgs:
        t = _ts(m.get("timestamp"))
        air = _num(m.get("hang_time"))
        if t is None or not air:
            continue
        lat, lon = _num(m.get("position_lat")), _num(m.get("position_long"))
        speed = _num(m.get("enhanced_speed")) or _num(m.get("speed")) or 0.0
        jumps.append(Jump(
            n=len(jumps) + 1, t=t, air=air, distance=_num(m.get("distance")) or speed * air,
            height=_num(m.get("height")) or jump_height(air), speed=speed, rotations=int(_num(m.get("rotations")) or 0),
            score=_num(m.get("score")), lat=lat * SEMICIRCLE_TO_DEG if lat is not None else None,
            lon=lon * SEMICIRCLE_TO_DEG if lon is not None else None,
        ))
    return jumps


def _alt_trend_at(samples: list[Sample], t_from: float, t_to: float, at: float) -> float | None:
    pts = [(s.t, s.alt) for s in samples if t_from <= s.t <= t_to and s.alt is not None]
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0][1]
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx > 0 else 0.0
    return my + slope * (at - mx)


def _refine_jump_heights(ride: Ride) -> None:
    """Same step-down correction as the Karoo engine (barometric drop over the flight)."""
    for j in ride.jumps:
        if j.drop is not None or j.air < 0.45:
            continue
        land = j.t + j.air
        before = _alt_trend_at(ride.samples, j.t - 3, j.t, j.t)
        after = _alt_trend_at(ride.samples, land, land + 3, land)
        if before is None or after is None:
            continue
        max_drop = G * j.air * j.air / 2 + 0.5
        drop = max(-max_drop, min(max_drop, before - after))
        if abs(drop) >= 1.0:
            j.drop = drop
            j.height = jump_height(j.air, drop)


def estimate_braking(ride: Ride) -> None:
    """Braking deceleration from the speed trace (same definition as the Karoo engine)."""
    samples = ride.samples
    for i, s in enumerate(samples):
        prev, nxt = samples[max(0, i - 1)], samples[min(len(samples) - 1, i + 1)]
        span = nxt.t - prev.t
        accel = (nxt.speed - prev.speed) / span if span >= 0.5 else 0.0
        s.brake = braking_decel(accel, s.speed, s.grade) if s.moving else 0.0


def estimate_from_gps(ride: Ride, lag: int = DEFAULT_FLOW_LAG) -> None:
    """Grit and Flow from GPS + altitude only (no roughness, no jumps)."""
    ride.estimated = True
    for s in ride.samples:
        s.lat_g = min(MAX_LATERAL_G, s.speed * abs(s.yaw or 0.0) / G)
    compute_grit_flow(ride, use_rough=False, lag=lag)


def rescore(ride: Ride) -> None:
    """Recompute Grit / Flow / braking with the current formulas from the recorded inputs
    (roughness, gyroscope lateral g, grade, speed): compare rides recorded with older versions."""
    for s in ride.samples:
        if s.lat_g is not None and s.speed >= 1.5:
            s.curvature = s.lat_g * G / (s.speed * s.speed)  # lat_g = v·|yaw|/g, curvature = |yaw|/v
    compute_grit_flow(ride, use_rough=True, lag=DEFAULT_FLOW_LAG)
    jump_bonus = {round(j.t + j.air): j.air for j in ride.jumps}
    for s in ride.samples:
        s.grit = (s.grit or 0.0) + 4.0 * jump_bonus.get(round(s.t), 0.0)


def compute_grit_flow(ride: Ride, use_rough: bool, lag: int) -> None:
    samples = ride.samples
    for s in samples:
        curv = s.curvature if s.speed >= 1.5 else 0.0
        rough = s.rough if use_rough else None
        s.grit = grit_per_second(s.grade, curv, rough) * s.dt if s.moving else 0.0
    for i, s in enumerate(samples):
        prev, nxt = samples[max(0, i - 1)], samples[min(len(samples) - 1, i + 1)]
        span = nxt.t - prev.t
        accel = (nxt.speed - prev.speed) / span if span >= 0.5 else 0.0
        b = braking_decel(accel, s.speed, s.grade) if s.moving else 0.0
        w = brake_weight(b) if s.speed >= 2.0 else 0.0
        nec = max(braking_necessity(s.speed, q.curvature, q.grade, q.rough if use_rough else None)
                  for q in samples[max(0, i - 1):min(len(samples), i + lag + 1)])
        s.brake = b
        s.flow = s.d_dist * w * (1.0 - nec)
