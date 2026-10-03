#!/usr/bin/env python3
"""
MTB Dynamics analyser for Karoo (and Garmin) rides.

Inputs
  * a FIT file recorded on a Karoo with the MTB Dynamics extension (mtb_* developer fields)
  * a FIT file from a Garmin Edge with MTB Dynamics (native grit/flow fields + jump messages)
  * any other cycling FIT file (Grit/Flow are then estimated from GPS + altitude, no jumps)
  * a ride folder pulled from the Karoo (samples.csv + events.jsonl), see README
  * an intervals.icu activity (downloads the original FIT through the API)

Outputs
  * a console report, an interactive HTML report (map + charts), CSV / JSON exports
  * optionally: the MTB summary written back into the intervals.icu activity

Examples
  python3 mtb_analyze.py ride.fit --html report.html
  python3 mtb_analyze.py --karoo-dir rides/1790000000000 --csv out/ride
  INTERVALS_API_KEY=... python3 mtb_analyze.py --icu latest --html report.html --icu-update

Requires: pip install garmin-fit-sdk   (only for FIT input)
The formulas mirror app/src/main/kotlin/.../engine/Scoring.kt; keep both in sync.
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable

G = 9.80665
SEMICIRCLE_TO_DEG = 180.0 / 2 ** 31
FIT_EPOCH_OFFSET = 631065600  # seconds from 1970-01-01 to 1989-12-31

# --------------------------------------------------------------------------------------------
# Formulas (mirror of Scoring.kt)
# --------------------------------------------------------------------------------------------
MOVING_SPEED = 1.0
GRIT_SCALE, GRIT_W_GRADE, GRIT_W_TURN, GRIT_W_ROUGH = 1.25, 1.2, 1.0, 1.0
CRR, AIR_K = 0.02, 0.0035
BRAKE_MIN, BRAKE_FULL, BRAKING_THRESHOLD = 0.3, 1.5, 0.5
DESCENT_GRADE = -2.5
MAX_LATERAL_G = 1.5
DEFAULT_FLOW_LAG = 3
WINDOW = 60


def _nz(v: float | None) -> float:
    return 0.0 if v is None or isinstance(v, float) and math.isnan(v) else v


def grade_term(grade: float | None) -> float:
    return min(8.0, (abs(_nz(grade)) / 8.0) ** 1.6)


def turn_term(curvature: float | None) -> float:
    return min(6.0, (max(0.0, _nz(curvature)) * 15.0) ** 1.3)


def rough_term(rough: float | None) -> float:
    if rough is None or math.isnan(rough):
        return 0.0
    return min(6.0, (max(0.0, rough) / 0.6) ** 1.3)


def grit_per_second(grade, curvature, rough) -> float:
    return GRIT_SCALE * (1.0 + GRIT_W_GRADE * grade_term(grade) + GRIT_W_TURN * turn_term(curvature)
                         + GRIT_W_ROUGH * rough_term(rough))


def coasting_accel(speed: float, grade: float | None) -> float:
    theta = math.atan(_nz(grade) / 100.0)
    return -G * math.sin(theta) - CRR * G * math.cos(theta) - AIR_K * speed * speed


def braking_decel(observed: float, speed: float, grade) -> float:
    # Downhill only real slowing counts; flat/uphill: slowing beyond gravity + resistance.
    return max(0.0, min(0.0, coasting_accel(speed, grade)) - observed)


def brake_weight(decel: float) -> float:
    return min(1.0, max(0.0, (decel - BRAKE_MIN) / (BRAKE_FULL - BRAKE_MIN)))


def braking_necessity(speed: float, curvature, grade, rough) -> float:
    k = max(0.0, _nz(curvature))
    lateral = speed * speed * k
    n_lat = min(1.0, max(0.0, (lateral - 1.5) / 3.0))
    n_rad = min(1.0, max(0.0, (k - 1 / 20.0) / (1 / 6.0 - 1 / 20.0)))
    n_grade = min(1.0, max(0.0, (-_nz(grade) - 6.0) / 12.0))
    n_rough = 0.0 if rough is None or math.isnan(rough) else min(1.0, max(0.0, (rough - 1.0) / 1.0))
    return max(n_lat, n_rad, n_grade, n_rough)


def flow_score(flow_m: float, dist_m: float) -> float:
    return 0.0 if dist_m < 1.0 else 100.0 * flow_m / dist_m


def difficulty_score(avg_grit: float) -> float:
    return 100.0 * (1.0 - math.exp(-max(0.0, avg_grit - GRIT_SCALE) / 3.5))


def smoothness_score(flow: float) -> float:
    return 100.0 * math.exp(-max(0.0, flow) / 6.0)


def air_score(total_air: float) -> float:
    return 100.0 * (1.0 - math.exp(-max(0.0, total_air) / 6.0))


def mtb_score(d: float, s: float, a: float) -> float:
    return 0.45 * d + 0.40 * s + 0.15 * a


def jump_height(air: float, drop: float = 0.0) -> float:
    if air <= 0:
        return 0.0
    vz0 = (G * air * air / 2.0 - drop) / air
    apex = vz0 * vz0 / (2 * G) if vz0 > 0 else 0.0
    return apex + max(0.0, drop)


# --------------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------------
@dataclass
class Sample:
    t: float                     # epoch seconds
    dt: float = 1.0
    dist: float = 0.0            # cumulative metres
    d_dist: float = 0.0
    speed: float = 0.0
    alt: float | None = None
    lat: float | None = None
    lon: float | None = None
    grade: float | None = None
    hr: float | None = None
    power: float | None = None
    grit: float | None = None    # grit points this second
    flow: float | None = None    # unnecessary-braking metres this second (aligned)
    rough: float | None = None   # g
    lat_g: float | None = None   # g
    brake: float | None = None   # m/s² (aligned)
    curvature: float | None = None
    yaw: float | None = None     # rad/s, + = left
    jump_air: float = 0.0
    jump_dist: float = 0.0
    jump_height: float = 0.0
    lap: int = 0
    # SRAM / RockShox (Karoo records these when the components are paired)
    cadence: float | None = None
    balance: float | None = None   # left %, power meter estimate
    fa_front: int | None = None    # Flight Attendant fork: 0 Open, 1 Pedal, 2 Lock
    fa_rear: int | None = None
    effort_zone: int | None = None
    rear_gear: int | None = None   # 1 = largest (easiest) cog
    rear_teeth: int | None = None

    @property
    def moving(self) -> bool:
        return self.speed >= MOVING_SPEED

    @property
    def descending(self) -> bool:
        return self.moving and _nz(self.grade) <= DESCENT_GRADE

    @property
    def braking(self) -> bool:
        return self.moving and (self.brake or 0.0) >= BRAKING_THRESHOLD


@dataclass
class Jump:
    n: int
    t: float                 # take-off, epoch seconds
    air: float
    distance: float
    height: float
    speed: float
    drop: float | None = None
    landing_g: float | None = None
    rotations: int = 0
    score: float | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass
class Ride:
    samples: list[Sample]
    jumps: list[Jump] = field(default_factory=list)
    lap_starts: list[int] = field(default_factory=lambda: [0])
    session: dict = field(default_factory=dict)
    source: str = ""
    device: str = ""
    has_imu: bool = False          # roughness / jumps measured with the accelerometer
    estimated: bool = False        # grit / flow estimated from GPS + altitude
    flow_lag: int = DEFAULT_FLOW_LAG
    karoo_summary: dict | None = None
    karoo_corners: list[dict] | None = None   # gyroscope corners from a Karoo ride folder
    shifts: list[dict] = field(default_factory=list)    # {t, gear, teeth, from_teeth, power, cadence}
    devices: list[dict] = field(default_factory=list)   # SRAM components with battery level
    fa_mode: int | None = None
    fa_bias: int | None = None
    cassette: list[int] | None = None
    weight: float | None = None                          # rider kg, for W/kg

    @property
    def start(self) -> float:
        return self.samples[0].t if self.samples else 0.0


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
            def num(key):
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


# --------------------------------------------------------------------------------------------
# SRAM / RockShox analytics (Flight Attendant, AXS Transmission, power meter)
# --------------------------------------------------------------------------------------------
FA_NAMES = {0: "Open", 1: "Pedal", 2: "Lock"}  # Karoo FIT values, confirmed from ride data
LOCKED_ROUGH_G = 0.9      # Lock on ground at least this rough = harsh ride
HARD_CLIMB_W = 200.0      # Open while pushing this hard uphill = wasted energy
CLIMB_GRADE = 2.0
UNDER_LOAD_W = 250.0
STEEP_GRADE = 6.0


def terrain_kinds(samples: list[Sample], min_elev: float) -> list[str]:
    kinds = ["FLAT"] * len(samples)
    for kind, a, b in split_segments(samples, min_elev):
        for i in range(a, b + 1):
            kinds[i] = kind
    return kinds


def _shares(states: list[int]) -> dict | None:
    if not states:
        return None
    return {name: 100.0 * sum(1 for x in states if x == code) / len(states) for code, name in FA_NAMES.items()}


def suspension_stats(ride: Ride, kinds: list[str], segments: list[tuple[str, int, int]]) -> dict | None:
    rows = [(s, k) for s, k in zip(ride.samples, kinds) if s.moving and s.fa_front is not None]
    if not rows:
        return None
    by_terrain = {k: _shares([s.fa_front for s, kk in rows if kk == k]) for k in ("CLIMB", "DESCENT", "FLAT")}
    changes, prev = 0, None
    for s in ride.samples:
        if s.fa_front is None:
            continue
        if prev is not None and s.fa_front != prev:
            changes += 1
        prev = s.fa_front
    reactions = []
    for kind, a, b in segments:
        if kind != "DESCENT":
            continue
        for s in ride.samples[a:b + 1]:
            if s.fa_front == 0:
                reactions.append(s.t - ride.samples[a].t)
                break
    zones: dict[int, list[Sample]] = {}
    for s, _ in rows:
        if s.effort_zone is not None:
            zones.setdefault(s.effort_zone, []).append(s)
    km = max(0.001, sum(s.d_dist for s in ride.samples) / 1000.0)
    return {
        "overall": _shares([s.fa_front for s, _ in rows]),
        "by_terrain": by_terrain,
        "locked_rough_s": sum(s.dt for s, _ in rows if s.fa_front == 2 and (s.rough or 0.0) >= LOCKED_ROUGH_G),
        "open_hard_climb_s": sum(s.dt for s, _ in rows
                                 if s.fa_front == 0 and (s.power or 0.0) >= HARD_CLIMB_W and _nz(s.grade) >= CLIMB_GRADE),
        "fork_shock_differ_s": sum(s.dt for s, _ in rows if s.fa_rear is not None and s.fa_rear != s.fa_front),
        "changes": changes, "changes_per_km": changes / km,
        "descents_reaching_open": len(reactions), "descents": sum(1 for k, _, _ in segments if k == "DESCENT"),
        "reaction_s_median": sorted(reactions)[len(reactions) // 2] if reactions else None,
        "effort_zones": [{"zone": z, "minutes": sum(x.dt for x in v) / 60.0,
                          "avg_power": _mean([x.power for x in v if x.power is not None])} for z, v in sorted(zones.items())],
        "mode": ride.fa_mode, "bias": ride.fa_bias,
    }


def drivetrain_stats(ride: Ride, kinds: list[str], segments: list[tuple[str, int, int]]) -> dict | None:
    if not ride.shifts and all(s.rear_teeth is None for s in ride.samples):
        return None
    moving = [(s, k) for s, k in zip(ride.samples, kinds) if s.moving and s.rear_teeth]
    cog_s: dict[int, float] = {}
    for s, _ in moving:
        cog_s[s.rear_teeth] = cog_s.get(s.rear_teeth, 0.0) + s.dt
    used = sorted(t for t, sec in cog_s.items() if sec >= 10)
    by_terrain = {}
    for kind in ("CLIMB", "DESCENT", "FLAT"):
        teeth = sorted(s.rear_teeth for s, k in moving if k == kind)
        if teeth:
            by_terrain[kind] = {"median": teeth[len(teeth) // 2], "largest": teeth[-1]}
    # Shift anticipation: easier shifts in the 15 s before a climb vs. its first 30 s.
    before = after = 0
    for kind, a, b in segments:
        if kind != "CLIMB":
            continue
        t0 = ride.samples[a].t
        for sh in ride.shifts:
            if sh.get("from_teeth") and sh["teeth"] > sh["from_teeth"]:
                if t0 - 15 <= sh["t"] < t0:
                    before += 1
                elif t0 <= sh["t"] < t0 + 30:
                    after += 1
    steep = [s for s, _ in moving if _nz(s.grade) >= STEEP_GRADE and s.cadence and s.power]
    km = max(0.001, sum(s.d_dist for s in ride.samples) / 1000.0)
    return {
        "shifts": len(ride.shifts), "shifts_per_km": len(ride.shifts) / km,
        "cog_minutes": {t: sec / 60.0 for t, sec in sorted(cog_s.items())},
        "used": used, "unused": [t for t in (ride.cassette or []) if t not in cog_s] if ride.cassette else None,
        "cassette": ride.cassette, "by_terrain": by_terrain,
        "under_load": sum(1 for sh in ride.shifts if (sh.get("power") or 0.0) >= UNDER_LOAD_W),
        "climb_shifts_before": before, "climb_shifts_after": after,
        "steep_cadence": _median([s.cadence for s in steep]),
        "steep_torque": _median([s.power / (s.cadence * 2 * math.pi / 60.0) for s in steep]),
        "steep_low_cadence_s": sum(s.dt for s in steep if s.cadence < 60),
    }


def power_stats(ride: Ride, kinds: list[str]) -> dict | None:
    rows = [(s, k) for s, k in zip(ride.samples, kinds) if s.moving and s.power is not None]
    if not rows:
        return None
    terrain = {}
    for kind in ("CLIMB", "DESCENT", "FLAT"):
        sel = [s for s, k in rows if k == kind]
        if not sel:
            continue
        avg = _mean([s.power for s in sel])
        terrain[kind] = {
            "avg_w": avg, "w_kg": avg / ride.weight if ride.weight and avg else None,
            "pedalling_pct": 100.0 * sum(1 for s in sel if (s.cadence or 0) > 0 or (s.power or 0) > 0) / len(sel),
            "balance_left": _mean([s.balance for s in sel if s.balance]),
        }
    watts = [s.power or 0.0 for s in ride.samples]
    best5 = 0.0
    if len(watts) >= 300:
        run = sum(watts[:300])
        best5 = run / 300
        for i in range(300, len(watts)):
            run += watts[i] - watts[i - 300]
            best5 = max(best5, run / 300)
    return {"terrain": terrain, "avg_w": _mean([s.power for s, _ in rows]), "best_5min_w": best5 or None,
            "weight": ride.weight}


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _median(values) -> float | None:
    values = sorted(v for v in values if v is not None)
    return values[len(values) // 2] if values else None


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


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------
class Units:
    def __init__(self, imperial: bool = False):
        self.imperial = imperial

    def speed(self, ms):
        return f"{ms * 2.236936:.1f} mph" if self.imperial else f"{ms * 3.6:.1f} km/h"

    def dist(self, m):
        return f"{m / 1609.344:.1f} mi" if self.imperial else f"{m / 1000:.1f} km"

    def short(self, m):
        return f"{m * 3.28084:.1f} ft" if self.imperial else f"{m:.1f} m"

    def elev(self, m):
        return f"{m * 3.28084:.0f} ft" if self.imperial else f"{m:.0f} m"


def hms(sec: float) -> str:
    sec = int(max(0, sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def sram_text(sram: dict, u: Units) -> list[str]:
    """Report lines for Flight Attendant, AXS Transmission, power meter and batteries."""
    lines = []
    su = sram.get("suspension")
    if su:
        o = su["overall"]
        bias = f", bias {su['bias']:+d}" if su.get("bias") is not None else ""
        lines.append(f"  Suspension (Flight Attendant{bias}): Open {o['Open']:.0f}% · Pedal {o['Pedal']:.0f}% · Lock {o['Lock']:.0f}%")
        parts = []
        for kind, label in (("DESCENT", "descents"), ("CLIMB", "climbs"), ("FLAT", "flats")):
            sh = su["by_terrain"].get(kind)
            if sh:
                parts.append(f"{label} {sh['Open']:.0f}/{sh['Pedal']:.0f}/{sh['Lock']:.0f}")
        lines.append("        Open/Pedal/Lock % — " + " · ".join(parts))
        react = f" · reaches Open {su['reaction_s_median']:.0f} s into a descent ({su['descents_reaching_open']}/{su['descents']})" \
            if su.get("reaction_s_median") is not None else ""
        lines.append(f"        locked on rough ground {su['locked_rough_s']:.0f} s · open on hard climbs {su['open_hard_climb_s']:.0f} s"
                     f" · {su['changes']} changes ({su['changes_per_km']:.1f}/km){react}")
        if su["effort_zones"]:
            zones = " · ".join(f"{z['zone']}: {z['minutes']:.0f} min" + (f" {z['avg_power']:.0f} W" if z["avg_power"] else "")
                               for z in su["effort_zones"])
            lines.append(f"        effort zones {zones}")
    dr = sram.get("drivetrain")
    if dr:
        used = f"{dr['used'][0]}-{dr['used'][-1]}T" if dr["used"] else "–"
        top = sorted(dr["cog_minutes"].items(), key=lambda x: -x[1])[:2]
        unused = f" · never used {', '.join(f'{t}T' for t in dr['unused'])}" if dr.get("unused") else ""
        lines.append(f"  Drivetrain (AXS): {dr['shifts']} shifts ({dr['shifts_per_km']:.1f}/km) · cogs {used}"
                     f" (most {', '.join(f'{t}T' for t, _ in top)}){unused}")
        climb = dr["by_terrain"].get("CLIMB")
        details = []
        if climb:
            details.append(f"climbs on {climb['median']}T (largest {climb['largest']}T)")
        details.append(f"{dr['under_load']} shifts above {UNDER_LOAD_W:.0f} W")
        if dr["climb_shifts_before"] + dr["climb_shifts_after"]:
            details.append(f"easier shifts before / after climb start {dr['climb_shifts_before']}/{dr['climb_shifts_after']}")
        if dr.get("steep_cadence"):
            details.append(f"steep climbing {dr['steep_cadence']:.0f} rpm, {dr['steep_torque']:.0f} N·m, "
                           f"{dr['steep_low_cadence_s']:.0f} s under 60 rpm")
        lines.append("        " + " · ".join(details))
    pw = sram.get("power")
    if pw:
        parts = []
        for kind, label in (("CLIMB", "climbs"), ("FLAT", "flats"), ("DESCENT", "descents")):
            t = pw["terrain"].get(kind)
            if not t:
                continue
            txt = f"{label} {t['avg_w']:.0f} W"
            if t.get("w_kg"):
                txt += f" ({t['w_kg']:.1f} W/kg)"
            if kind == "DESCENT":
                txt += f", pedalling {t['pedalling_pct']:.0f}%"
            parts.append(txt)
        best = f" · best 5 min {pw['best_5min_w']:.0f} W" if pw.get("best_5min_w") else ""
        climb = pw["terrain"].get("CLIMB") or {}
        bal = f" · L/R {climb['balance_left']:.0f}/{100 - climb['balance_left']:.0f} on climbs" if climb.get("balance_left") else ""
        lines.append("  Power: " + " · ".join(parts) + best + bal)
    bats = sram.get("batteries")
    if bats:
        lines.append("  Batteries: " + " · ".join(
            f"{b['kind']} {b['battery_pct']:.0f}%" if b.get("battery_pct") is not None else f"{b['kind']} {b.get('battery_status')}"
            for b in bats))
    return lines


def report_text(s: dict, u: Units) -> str:
    lines = []
    sc = s["score"]
    lines.append(f"MTB Dynamics — {s['start'][:16].replace('T', ' ')} UTC  ({s['device'] or s['source']})")
    if s["estimated"]:
        lines.append("  (no MTB Dynamics data in the file: Grit/Flow estimated from GPS + altitude, no jumps/roughness)")
    lines.append(f"  MTB score {sc['total']:.0f}   difficulty {sc['difficulty']:.0f} · smoothness {sc['smoothness']:.0f} · air {sc['air']:.0f}")
    lines.append(f"  Ride  {hms(s['elapsed_s'])} (moving {hms(s['moving_s'])}) · {u.dist(s['distance_m'])} · ↗ {u.elev(s['ascent_m'])} · avg {u.speed(s['avg_speed_ms'])}")
    g, f = s["grit"], s["flow"]
    lines.append(f"  Grit  {g['total_k']:.1f} kGrit · avg {g['avg']:.2f}/s · peak 60 s {g['peak60']:.1f}")
    lines.append(f"  Flow  {f['score']:.2f} (lower = smoother) · descents {f['descent']:.2f} · worst 60 s {f['worst60']:.1f}")
    j = s["jumps"]
    lines.append(f"  Jumps {j['count']} · total air {j['total_air_s']:.1f} s")
    if j["longest"]:
        lj = j["longest"]
        lines.append(f"        longest {lj['air']:.2f} s · {u.short(lj['distance'])} · {u.speed(lj['speed'])};"
                     f" farthest {u.short(j['farthest']['distance'])}; highest ~{u.short(j['highest']['height'])}")
    c = s["cornering"]
    from_list = c["source"] == "GPS track" or c.get("list_from_karoo")
    track = f"{c['left']} L / {c['right']} R" if from_list else f"GPS track {c['gps_count']}: {c['left']} L / {c['right']} R"
    lines.append(f"  Corners {c['count']} ({c['source']}; {track}) · speed kept {c['speed_kept_pct']:.0f} % · max {c['max_lat_g']:.2f} g")
    d = s["descending"]
    lines.append(f"  Descents {hms(d['time_s'])} · {u.elev(d['drop_m'])} ↓ · avg {u.speed(d['avg_speed_ms'])} · max {u.speed(d['max_speed_ms'])} · braking {d['braking_pct']:.0f} %")
    if s["roughness_avg"] is not None:
        lines.append(f"  Roughness avg {s['roughness_avg']:.2f} g")
    lines.extend(sram_text(s.get("sram") or {}, u))

    def table(rows: list[dict], title: str):
        if not rows:
            return
        lines.append("")
        lines.append(title)
        bike = any(r.get("avg_power") is not None or r.get("fa") for r in rows)
        extra = f" {'W':>5} {'FA O/P/L %':>11} {'cog':>4}" if bike else ""
        lines.append(f"  {'#':>2} {'name':<12} {'dist':>8} {'time':>8} {'elev':>8} {'grade':>6} {'speed':>11} {'kGrit':>6} {'flow':>5} {'brake':>6} {'jumps':>5}" + extra)
        for r in rows:
            elev = r["elev_gain_m"] if r["type"] == "CLIMB" else -r["elev_loss_m"] if r["type"] == "DESCENT" else r["elev_gain_m"] - r["elev_loss_m"]
            more = ""
            if bike:
                fa = r.get("fa")
                fa_txt = f"{fa['Open']:.0f}/{fa['Pedal']:.0f}/{fa['Lock']:.0f}" if fa else "–"
                watts = f"{r['avg_power']:.0f}" if r.get("avg_power") is not None else "–"
                cog = f"{r['median_cog']:.0f}T" if r.get("median_cog") else "–"
                more = f" {watts:>5} {fa_txt:>11} {cog:>4}"
            lines.append(f"  {r['index']:>2} {r['name']:<12} {u.dist(r['distance_m']):>8} {hms(r['duration_s']):>8} {elev:>+7.0f}m "
                         f"{r['avg_grade_pct']:>5.1f}% {u.speed(r['avg_speed_ms']):>11} {r['grit_k']:>6.1f} {r['flow_score']:>5.1f} "
                         f"{r['braking_pct']:>5.0f}% {r['jumps']:>5}" + more)

    table(s["segments"], "Trail segments")
    table(s["laps"], "Laps")
    if j["list"]:
        lines.append("")
        lines.append("Jumps")
        for jj in j["list"]:
            at = dt.datetime.fromtimestamp(jj["t"], dt.timezone.utc).strftime("%H:%M:%S")
            drop = f" · drop {jj['drop']:.1f} m" if jj.get("drop") else ""
            lines.append(f"  {jj['n']:>3}. {at}  {jj['air']:.2f} s · {u.short(jj['distance'])} · ~{u.short(jj['height'])} high · {u.speed(jj['speed'])}{drop}")
    return "\n".join(lines)


def write_csv(ride: Ride, s: dict, prefix: str) -> list[str]:
    os.makedirs(os.path.dirname(os.path.abspath(prefix)), exist_ok=True)
    out = []
    path = f"{prefix}_seconds.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "elapsed_s", "distance_m", "speed_kmh", "altitude_m", "grade_pct", "lat", "lon",
                    "grit", "flow_m", "rough_g", "lat_g", "brake_ms2", "jump_air_s", "lap"])
        for x in ride.samples:
            w.writerow([dt.datetime.fromtimestamp(x.t, dt.timezone.utc).isoformat(), round(x.t - ride.start, 1),
                        round(x.dist, 1), round(x.speed * 3.6, 2), x.alt, x.grade, x.lat, x.lon,
                        _r(x.grit), _r(x.flow), _r(x.rough), _r(x.lat_g), _r(x.brake), x.jump_air or "", x.lap + 1])
    out.append(path)
    for key, rows in (("segments", s["segments"]), ("laps", s["laps"]), ("jumps", s["jumps"]["list"]), ("corners", s["cornering"]["list"])):
        if not rows:
            continue
        path = f"{prefix}_{key}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        out.append(path)
    return out


def _r(v, n=4):
    return "" if v is None else round(v, n)


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MTB Dynamics</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
 :root{--bg:#fff;--fg:#1b1b1b;--muted:#66727a;--card:#f3f5f6;--accent:#ff6d00;--line:#e2e6e8}
 @media (prefers-color-scheme:dark){:root{--bg:#121416;--fg:#e9ecee;--muted:#98a3aa;--card:#1d2124;--line:#2c3236}}
 body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 main{max-width:1100px;margin:0 auto;padding:16px}
 h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:26px 0 8px}
 .muted{color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:14px}
 .card{background:var(--card);border-radius:10px;padding:10px 12px}.card b{display:block;font-size:24px}
 .card span{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 #map{height:420px;border-radius:10px;margin-top:6px}.chart{height:300px}
 table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}.tw{overflow-x:auto}
 .seg-CLIMB{color:#d84315}.seg-DESCENT{color:#1565c0}
 .toggle button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;padding:4px 10px;margin-right:4px;cursor:pointer}
 .toggle button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
</style></head>
<body><main>
<h1>🚵 MTB Dynamics</h1><div class="muted" id="sub"></div>
<div class="cards" id="cards"></div>
<h2>Map</h2><div class="toggle" id="colorBy"></div><div id="map"></div>
<h2>Profile</h2><div class="chart" id="profile"></div>
<h2>Grit &amp; Flow (60 s)</h2><div class="chart" id="gritflow"></div>
<h2>Speed &amp; braking</h2><div class="chart" id="brakes"></div>
<h2>Jumps</h2><div class="chart" id="jumps"></div>
<div id="bike"><h2>Suspension &amp; gears</h2><div class="chart" id="fagears"></div>
<h2>Cog usage by terrain</h2><div class="chart" id="cogs"></div></div>
<h2>Trail segments</h2><div class="tw"><table id="segments"></table></div>
<h2>Laps</h2><div class="tw"><table id="laps"></table></div>
<p class="muted" id="note"></p>
</main>
<script>
const D = __DATA__;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const fg = dark ? '#e9ecee' : '#1b1b1b', grid = dark ? '#2c3236' : '#e2e6e8';
const base = {paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)', font:{color:fg}, margin:{l:50,r:50,t:10,b:40},
  xaxis:{title:'Distance ('+D.u.dist+')', gridcolor:grid}, legend:{orientation:'h', y:1.12}};
const S = D.summary, R = D.rows;
document.getElementById('sub').textContent = S.start.slice(0,16).replace('T',' ') + ' UTC · ' + (S.device || S.source) +
  (S.estimated ? ' · Grit/Flow estimated from GPS (no MTB Dynamics data in file)' : '');
const card = (label, value) => `<div class="card"><span>${label}</span><b>${value}</b></div>`;
const f1 = v => (v ?? 0).toFixed(1), f2 = v => (v ?? 0).toFixed(2);
document.getElementById('cards').innerHTML = [
  card('MTB score', S.score.total.toFixed(0)), card('Grit (kGrit)', f1(S.grit.total_k)), card('Flow', f2(S.flow.score)),
  card('Jumps', S.jumps.count), card('Max airtime', S.jumps.longest ? f2(S.jumps.longest.air)+' s' : '–'),
  card('Corners', S.cornering.count), card('Max corner g', f2(S.cornering.max_lat_g)),
  card('Descent braking', S.descending.braking_pct.toFixed(0)+' %'),
  card('Distance', (S.distance_m*D.u.distF).toFixed(1)+' '+D.u.dist), card('Ascent', (S.ascent_m*D.u.elevF).toFixed(0)+' '+D.u.elev),
].concat(bikeCards()).join('');
function bikeCards() {
  const sr = S.sram || {}, out = [];
  const su = sr.suspension, dr = sr.drivetrain, pw = sr.power;
  if (su && su.by_terrain.DESCENT) out.push(card('FA Open on descents', su.by_terrain.DESCENT.Open.toFixed(0)+' %'));
  if (su) out.push(card('Locked on rough', su.locked_rough_s.toFixed(0)+' s'));
  if (dr) out.push(card('Shifts', dr.shifts+' ('+dr.shifts_per_km.toFixed(1)+'/km)'));
  if (pw && pw.terrain.CLIMB) out.push(card('Climb power', pw.terrain.CLIMB.avg_w.toFixed(0)+' W'+(pw.terrain.CLIMB.w_kg ? ' · '+pw.terrain.CLIMB.w_kg.toFixed(1)+' W/kg' : '')));
  return out;
}

// Map coloured by a metric
const pts = R.filter(r => r.lat != null && r.lon != null);
if (pts.length) {
  const map = L.map('map'); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(map);
  let layer = null;
  const ramp = t => { t = Math.max(0, Math.min(1, t)); const h = (1 - t) * 120; return `hsl(${h},85%,45%)`; };
  const metrics = {grit: ['Grit 60 s', r => r.grit60, 12], flow: ['Flow 60 s', r => r.flow60, 10], speed: ['Speed', r => r.speed, null], rough: ['Roughness', r => r.rough, 1]};
  const draw = key => {
    if (layer) map.removeLayer(layer);
    layer = L.layerGroup();
    const [, get, fixedMax] = metrics[key];
    const vals = pts.map(get).filter(v => v != null);
    const max = fixedMax || Math.max(...vals, 1);
    for (let i = 1; i < pts.length; i++) {
      const v = get(pts[i]);
      L.polyline([[pts[i-1].lat, pts[i-1].lon], [pts[i].lat, pts[i].lon]], {color: v == null ? '#888' : ramp(v / max), weight: 5, opacity: .9}).addTo(layer);
    }
    for (const j of S.jumps.list) if (j.lat != null) L.circleMarker([j.lat, j.lon], {radius: 5 + j.air * 6, color: '#ff6d00', fillOpacity: .8})
      .bindPopup(`<b>Jump ${j.n}</b><br>${j.air.toFixed(2)} s air<br>${(j.distance*D.u.shortF).toFixed(1)} ${D.u.short}<br>~${(j.height*D.u.shortF).toFixed(1)} ${D.u.short} high`).addTo(layer);
    layer.addTo(map);
    document.querySelectorAll('#colorBy button').forEach(b => b.classList.toggle('on', b.dataset.k === key));
  };
  document.getElementById('colorBy').innerHTML = Object.entries(metrics).map(([k, m]) => `<button data-k="${k}">${m[0]}</button>`).join('');
  document.querySelectorAll('#colorBy button').forEach(b => b.onclick = () => draw(b.dataset.k));
  map.fitBounds(pts.map(p => [p.lat, p.lon]));
  draw('grit');
} else document.getElementById('map').outerHTML = '<p class="muted">No GPS track.</p>';

const x = R.map(r => r.dist * D.u.distF);
const segShapes = S.segments.filter(s => s.type !== 'FLAT').map(s => {
  const a = R.findIndex(r => r.off >= s.start_offset_s), b = R.findIndex(r => r.off >= s.start_offset_s + s.duration_s);
  return {type:'rect', xref:'x', yref:'paper', x0:x[Math.max(0,a)], x1:x[b < 0 ? x.length-1 : b], y0:0, y1:1, line:{width:0},
          fillcolor: s.type === 'CLIMB' ? 'rgba(216,67,21,.08)' : 'rgba(21,101,192,.10)'};
});
Plotly.newPlot('profile', [
  {x, y: R.map(r => r.alt == null ? null : r.alt * D.u.elevF), name: 'Altitude', fill: 'tozeroy', line: {color: '#78909c'}},
  {x: S.jumps.list.map(j => { const i = R.findIndex(r => r.t >= j.t); return x[Math.max(0, i)]; }),
   y: S.jumps.list.map(j => { const i = R.findIndex(r => r.t >= j.t); const a = R[Math.max(0, i)].alt; return a == null ? null : a * D.u.elevF; }),
   mode: 'markers', name: 'Jumps', marker: {color: '#ff6d00', size: S.jumps.list.map(j => 6 + j.air * 10)}},
], {...base, shapes: segShapes, yaxis: {title: 'Altitude ('+D.u.elev+')', gridcolor: grid}}, {responsive: true, displaylogo: false});
Plotly.newPlot('gritflow', [
  {x, y: R.map(r => r.grit60), name: 'Grit 60 s (grit/s)', line: {color: '#d84315'}},
  {x, y: R.map(r => r.flow60), name: 'Flow 60 s', yaxis: 'y2', line: {color: '#1565c0'}},
], {...base, yaxis: {title: 'Grit / s', gridcolor: grid}, yaxis2: {title: 'Flow', overlaying: 'y', side: 'right', showgrid: false}}, {responsive: true, displaylogo: false});
Plotly.newPlot('brakes', [
  {x, y: R.map(r => r.speed * D.u.speedF), name: 'Speed ('+D.u.speed+')', line: {color: '#455a64'}},
  {x, y: R.map(r => r.brake), name: 'Braking (m/s²)', yaxis: 'y2', type: 'bar', marker: {color: R.map(r => r.flow > 0 ? '#ff6d00' : '#90a4ae')}},
], {...base, bargap: 0, yaxis: {title: 'Speed', gridcolor: grid}, yaxis2: {title: 'm/s² (orange = unnecessary)', overlaying: 'y', side: 'right', showgrid: false}}, {responsive: true, displaylogo: false});
if (S.jumps.list.length) Plotly.newPlot('jumps', [{
  x: S.jumps.list.map(j => '#' + j.n), y: S.jumps.list.map(j => j.air), type: 'bar', marker: {color: S.jumps.list.map(j => j.height), colorscale: 'Oranges', showscale: true, colorbar: {title: 'height'}},
  text: S.jumps.list.map(j => `${(j.distance*D.u.shortF).toFixed(1)} ${D.u.short} · ~${(j.height*D.u.shortF).toFixed(1)} ${D.u.short} · ${(j.speed*D.u.speedF).toFixed(0)} ${D.u.speed}`),
  hovertemplate: '%{x}: %{y:.2f} s<br>%{text}<extra></extra>'}], {...base, xaxis: {title: 'Jump'}, yaxis: {title: 'Airtime (s)', gridcolor: grid}}, {responsive: true, displaylogo: false});
else document.getElementById('jumps').outerHTML = '<p class="muted">No jumps.</p>';

// Suspension & gears
if (R.some(r => r.fa != null || r.cog != null)) {
  const faNames = ['Open', 'Pedal', 'Lock'], faColors = ['#2e7d32', '#f9a825', '#c62828'];
  const traces = [];
  for (let code = 0; code < 3; code++) traces.push({x, y: R.map(r => r.fa === code ? 1 : null), type: 'bar', name: 'FA ' + faNames[code],
    marker: {color: faColors[code]}, hoverinfo: 'name', yaxis: 'y'});
  if (R.some(r => r.cog != null)) traces.push({x, y: R.map(r => r.cog), name: 'Rear cog (T)', yaxis: 'y2', line: {shape: 'hv', color: '#455a64', width: 1.5}});
  Plotly.newPlot('fagears', traces, {...base, barmode: 'stack', bargap: 0, yaxis: {visible: false, range: [0, 1]},
    yaxis2: {title: 'Cog teeth', overlaying: 'y', side: 'right', autorange: 'reversed'}}, {responsive: true, displaylogo: false});
  const kinds = ['CLIMB', 'FLAT', 'DESCENT'], kindColor = {CLIMB: '#d84315', FLAT: '#90a4ae', DESCENT: '#1565c0'};
  const cogs = [...new Set(R.filter(r => r.cog != null).map(r => r.cog))].sort((a, b) => a - b);
  if (cogs.length) Plotly.newPlot('cogs', kinds.map(k => ({x: cogs.map(c => c + 'T'), type: 'bar', name: k.toLowerCase(),
    marker: {color: kindColor[k]}, y: cogs.map(c => R.filter(r => r.cog === c && r.kind === k && r.speed >= 1).length / 60)})),
    {...base, barmode: 'stack', xaxis: {title: 'Rear cog'}, yaxis: {title: 'Minutes', gridcolor: grid}}, {responsive: true, displaylogo: false});
  else document.getElementById('cogs').outerHTML = '<p class="muted">No gear data.</p>';
} else document.getElementById('bike').style.display = 'none';

const elevCell = r => r.type === 'CLIMB' ? '+' + (r.elev_gain_m*D.u.elevF).toFixed(0)
  : r.type === 'DESCENT' ? '−' + (r.elev_loss_m*D.u.elevF).toFixed(0)
  : '+' + (r.elev_gain_m*D.u.elevF).toFixed(0) + ' / −' + (r.elev_loss_m*D.u.elevF).toFixed(0);
const bikeCols = rows => rows.some(r => r.avg_power != null || r.fa);
const bikeHead = rows => bikeCols(rows) ? '<th>W</th><th>W/kg</th><th>FA O/P/L %</th><th>Cog</th><th>Shifts</th>' : '';
const bikeCells = (rows, r) => !bikeCols(rows) ? '' :
  `<td>${r.avg_power != null ? r.avg_power.toFixed(0) : '–'}</td><td>${r.w_kg ? r.w_kg.toFixed(1) : '–'}</td>` +
  `<td>${r.fa ? r.fa.Open.toFixed(0)+'/'+r.fa.Pedal.toFixed(0)+'/'+r.fa.Lock.toFixed(0) : '–'}</td>` +
  `<td>${r.median_cog ? r.median_cog+'T' : '–'}</td><td>${r.shifts ?? '–'}</td>`;
const tableHtml = rows => rows.length ? '<tr><th>#</th><th>Name</th><th>Dist</th><th>Time</th><th>Elev</th><th>Grade</th><th>Speed</th><th>kGrit</th><th>Flow</th><th>Braking</th><th>Jumps</th><th>Corners</th>' + bikeHead(rows) + '</tr>' +
  rows.map(r => `<tr><td>${r.index}</td><td class="seg-${r.type}">${r.name}</td><td>${(r.distance_m*D.u.distF).toFixed(2)}</td>` +
    `<td>${new Date(r.duration_s*1000).toISOString().substr(11,8)}</td><td>${elevCell(r)}</td>` +
    `<td>${r.avg_grade_pct.toFixed(1)}%</td><td>${(r.avg_speed_ms*D.u.speedF).toFixed(1)}</td><td>${r.grit_k.toFixed(1)}</td>` +
    `<td>${r.flow_score.toFixed(1)}</td><td>${r.braking_pct.toFixed(0)}%</td><td>${r.jumps}</td><td>${r.corners}</td>` + bikeCells(rows, r) + '</tr>').join('') : '<tr><td class="muted">none</td></tr>';
document.getElementById('segments').innerHTML = tableHtml(S.segments);
document.getElementById('laps').innerHTML = tableHtml(S.laps);
document.getElementById('note').textContent = 'Grit: difficulty from grade, turns and roughness (higher = harder). Flow: unnecessary braking per 100 m (lower = smoother). Generated by tools/mtb_analyze.py.';
</script></body></html>
"""


def write_html(ride: Ride, s: dict, path: str, u: Units) -> None:
    rows = []
    grit_win, flow_win, dist_win = [], [], []
    kinds = terrain_kinds(ride.samples, 15.0)
    for x, kind in zip(ride.samples, kinds):
        grit_win.append((x.grit or 0.0, x.dt))
        flow_win.append(((x.flow or 0.0) if x.moving else 0.0, x.d_dist if x.moving else 0.0))
        g = sum(a for a, _ in grit_win[-WINDOW:]) / max(1e-9, sum(b for _, b in grit_win[-WINDOW:]))
        fl, fd = sum(a for a, _ in flow_win[-WINDOW:]), sum(b for _, b in flow_win[-WINDOW:])
        rows.append({
            "t": x.t, "off": round(x.t - ride.start, 1), "dist": round(x.dist, 1), "speed": round(x.speed, 2),
            "alt": None if x.alt is None else round(x.alt, 1), "lat": None if x.lat is None else round(x.lat, 6),
            "lon": None if x.lon is None else round(x.lon, 6), "grit60": round(g, 2),
            "flow60": round(flow_score(fl, fd), 2) if fd >= 50 else None, "brake": _r(x.brake, 2),
            "flow": _r(x.flow, 3), "rough": _r(x.rough, 3),
            "fa": x.fa_front, "cog": x.rear_teeth, "kind": kind, "power": x.power,
        })
    unit = {"dist": "mi" if u.imperial else "km", "distF": 1 / 1609.344 if u.imperial else 1 / 1000,
            "elev": "ft" if u.imperial else "m", "elevF": 3.28084 if u.imperial else 1,
            "short": "ft" if u.imperial else "m", "shortF": 3.28084 if u.imperial else 1,
            "speed": "mph" if u.imperial else "km/h", "speedF": 2.236936 if u.imperial else 3.6}
    data = json.dumps({"summary": s, "rows": rows, "u": unit}, separators=(",", ":"), default=str)
    with open(path, "w") as f:
        f.write(HTML_TEMPLATE.replace("__DATA__", data.replace("</", "<\\/")))



# --------------------------------------------------------------------------------------------
# Raw IMU debug log (Karoo setting "Debug: save raw sensor data")
# --------------------------------------------------------------------------------------------
PRESETS = {  # mirror of MtbConfig.kt Sensitivity: take-off g, min airtime s, min landing g
    "LOW": (0.35, 0.35, 1.3),
    "MEDIUM": (0.45, 0.28, 1.15),
    "HIGH": (0.55, 0.20, 1.05),
}
LAND_G, MAX_AIR, MAX_MEAN_AIR_G, GLITCH, LANDING_WINDOW, COOLDOWN, MIN_JUMP_SPEED = 0.80, 3.0, 0.6, 0.05, 0.35, 0.25, 2.2


def load_imu(path: str) -> tuple[list[tuple[float, float, float, float]], float]:
    """Accelerometer samples (wall seconds, x, y, z) from imu.csv.gz."""
    accel = []
    offset = None  # wall_s - elapsed_s
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                parts = dict(p.split("=") for p in line[1:].split())
                offset = int(parts["wall_ms"]) / 1000.0 - int(parts["elapsed_ms"]) / 1000.0
                continue
            if not line.startswith("a,"):
                continue
            _, t, x, y, z = line.rstrip().split(",")
            accel.append((float(t) / 1000.0 + (offset or 0.0), float(x), float(y), float(z)))
    return accel, offset or 0.0


def find_flights(accel, preset: str) -> list[dict]:
    """Port of ImuProcessor (|a| filter) + JumpDetector; also returns rejected flights with the reason."""
    takeoff_g, min_air, min_landing = PRESETS[preset]
    out = []
    mag_lp, last_t = 1.0, None
    state, air_start, land_t, sum_g, n_g, peak, cooldown = "GROUND", 0.0, 0.0, 0.0, 0, 0.0, 0.0
    for t, x, y, z in accel:
        mag = math.sqrt(x * x + y * y + z * z) / G
        dt = 0.0 if last_t is None else min(0.2, max(0.0, t - last_t))
        last_t = t
        mag_lp = mag if dt <= 0 else mag_lp + dt / (0.03 + dt) * (mag - mag_lp)
        if state == "GROUND":
            if t >= cooldown and mag_lp < takeoff_g:
                state, air_start, sum_g, n_g = "AIR", t, 0.0, 0
        elif state == "AIR":
            sum_g += mag_lp
            n_g += 1
            if mag_lp > LAND_G:
                state, land_t, peak = "LANDING", t, mag
            elif t - air_start > MAX_AIR:
                state, cooldown = "GROUND", t + 1.0
        else:
            peak = max(peak, mag)
            if mag_lp < takeoff_g and t - land_t < GLITCH:
                state = "AIR"
            elif t - land_t >= LANDING_WINDOW:
                state, cooldown = "GROUND", t + COOLDOWN
                air = land_t - air_start
                mean_g = sum_g / n_g if n_g else 1.0
                reason = ("airtime %.2f s < %.2f" % (air, min_air) if air < min_air else
                          "mean %.2f g in flight" % mean_g if mean_g > MAX_MEAN_AIR_G else
                          "landing %.2f g < %.2f" % (peak, min_landing) if peak < min_landing else "")
                if air >= 0.08:
                    out.append({"t": air_start, "air": air, "mean_g": mean_g, "landing_g": peak, "reason": reason})
    return out


def imu_report(ride: Ride | None, path: str) -> str:
    accel, _ = load_imu(path)
    if not accel:
        return f"{path}: no accelerometer samples"
    span = accel[-1][0] - accel[0][0]
    lines = [f"Raw IMU: {len(accel)} accelerometer samples over {hms(span)} ({len(accel) / max(span, 1):.0f} Hz)"]

    def speed_at(t):
        if not ride or not ride.samples:
            return None
        i = _index_at(ride.samples, t)
        window = [s.speed for s in ride.samples[max(0, i - 3):i + 1]]
        return sorted(window)[len(window) // 2] if window else None

    for preset in ("LOW", "MEDIUM", "HIGH"):
        flights = find_flights(accel, preset)
        accepted = []
        for fl in flights:
            v = speed_at(fl["t"])
            if not fl["reason"] and v is not None and v < MIN_JUMP_SPEED:
                fl["reason"] = "speed %.1f km/h" % (v * 3.6)
            fl["speed"] = v
            if not fl["reason"]:
                accepted.append(fl)
        lines.append(f"\n{preset}: {len(accepted)} jumps")
        for fl in accepted:
            at = dt.datetime.fromtimestamp(fl["t"], dt.timezone.utc).strftime("%H:%M:%S")
            sp = "" if fl["speed"] is None else f" · {fl['speed'] * 3.6:.0f} km/h"
            lines.append(f"  {at}  {fl['air']:.2f} s air · mean {fl['mean_g']:.2f} g · landing {fl['landing_g']:.1f} g{sp}")
        if preset == "HIGH":
            near = sorted((fl for fl in flights if fl["reason"]), key=lambda f: -f["air"])[:10]
            if near:
                lines.append("  longest rejected flights:")
                for fl in near:
                    at = dt.datetime.fromtimestamp(fl["t"], dt.timezone.utc).strftime("%H:%M:%S")
                    lines.append(f"  {at}  {fl['air']:.2f} s · {fl['reason']}")
    return "\n".join(lines)

# --------------------------------------------------------------------------------------------
# intervals.icu
# --------------------------------------------------------------------------------------------
RIDE_TYPES = {"Ride", "MountainBikeRide", "GravelRide", "EBikeRide", "EMountainBikeRide"}
DESCRIPTION_MARKER = "🚵 MTB Dynamics"


# --------------------------------------------------------------------------------------------
# Across rides: service hours, shifts, batteries (mirrors ServiceTracker.kt on the Karoo)
# --------------------------------------------------------------------------------------------
SERVICE_ROUGH_G = 0.6
# id, name, basis, default interval: RockShox / SRAM service guides for SID / SIDLuxe and an Eagle chain.
# Check the manual of your parts.
SERVICE_ITEMS = [
    ("fork_lowers", "Fork lower-leg service", "fork_h", 50.0),
    ("fork_damper", "Fork damper & spring service", "fork_h", 200.0),
    ("shock_aircan", "Shock air-can service", "shock_h", 50.0),
    ("shock_damper", "Shock damper service", "shock_h", 200.0),
    ("chain", "Chain wear check", "drivetrain_km", 1500.0),
]
SERVICE_JSON_TOTALS = {"fork_h": "forkHours", "shock_h": "shockHours", "drivetrain_km": "drivetrainKm"}
BATTERY_LOW_PCT = 15.0   # BatteryStatus.fromPercentage: 15 % and below is critical
BATTERY_MIN_READINGS = 3  # since the last charge, before a drain rate is shown
BATTERY_MIN_HOURS = 1.0   # of riding in between


def ride_usage(ride: Ride, s: dict) -> dict:
    """What one ride adds to the service totals (same rules as ServiceTracker.kt)."""
    fork = [x for x in ride.samples if x.moving and x.fa_front is not None]
    shock = [x for x in ride.samples if x.moving and x.fa_rear is not None]
    axs = [x for x in ride.samples if x.moving and x.rear_teeth]
    cogs: dict[int, float] = {}
    for x in axs:
        cogs[x.rear_teeth] = cogs.get(x.rear_teeth, 0.0) + x.dt / 3600.0
    sram = s.get("sram") or {}
    su, dr, pw = sram.get("suspension"), sram.get("drivetrain"), sram.get("power")
    climb = ((pw or {}).get("terrain") or {}).get("CLIMB") or {}
    descent = ((su or {}).get("by_terrain") or {}).get("DESCENT") or {}
    return {
        "start": s["start"], "source": s["source"], "moving_h": s["moving_s"] / 3600.0, "distance_km": s["distance_m"] / 1000.0,
        "on_bike": bool(fork or axs),
        "fork_h": sum(x.dt for x in fork) / 3600.0,
        "shock_h": sum(x.dt for x in shock) / 3600.0,
        "rough_h": sum(x.dt for x in fork if (x.rough or 0.0) >= SERVICE_ROUGH_G) / 3600.0,
        "fa_changes": su["changes"] if su else 0,
        "fa_open_desc": descent.get("Open"),
        "locked_rough_s": su["locked_rough_s"] if su else None,
        "shifts": dr["shifts"] if dr else 0,
        "shifts_km": dr["shifts_per_km"] if dr else None,
        "drivetrain_km": sum(x.d_dist for x in axs) / 1000.0,
        "cog_h": cogs,
        "climb_w": climb.get("avg_w"), "climb_wkg": climb.get("w_kg"),
        "batteries": [{"kind": b.get("kind"), "pct": b.get("battery_pct"), "status": b.get("battery_status")}
                      for b in sram.get("batteries") or [] if b.get("kind")],
    }


def ride_paths(paths: list[str]) -> list[str]:
    """FIT files and Karoo ride folders, also inside the given folders (e.g. a pulled rides/ folder)."""
    found = []
    for path in paths:
        if os.path.isfile(path):
            found.append(path)
        elif os.path.exists(os.path.join(path, "samples.csv")):
            found.append(path)
        elif os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                sub = os.path.join(path, name)
                if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "samples.csv")):
                    found.append(sub)
                elif name.lower().endswith((".fit", ".fit.gz", ".zip")):
                    found.append(sub)
    return found


def load_any(path: str) -> Ride:
    if os.path.isdir(path):
        return load_karoo_dir(path)
    with open(path, "rb") as f:
        return load_fit(f.read(), os.path.basename(path))


def dedupe_rides(rows: list[dict]) -> tuple[list[dict], int]:
    """The same ride as FIT file and as Karoo ride folder counts once: keep the version with more bike data."""
    def ts(r):
        return dt.datetime.fromisoformat(r["start"]).timestamp()

    def richness(r):
        return (r["on_bike"], sum(1 for b in r["batteries"] if b["pct"] is not None), r["fork_h"] + r["drivetrain_km"])

    out: list[dict] = []
    skipped = 0
    for r in sorted(rows, key=ts):
        prev = out[-1] if out else None
        if prev and abs(ts(r) - ts(prev)) < 300 and abs(r["distance_km"] - prev["distance_km"]) <= max(0.3, 0.1 * prev["distance_km"]):
            if richness(r) > richness(prev):
                out[-1] = r
            skipped += 1
            continue
        out.append(r)
    return out, skipped


def battery_trends(rows: list[dict]) -> list[dict]:
    """Battery level per component over the rides, with the drain per ride and per riding hour."""
    series: dict[str, list[tuple[dict, dict]]] = {}
    for r in rows:
        for b in r["batteries"]:
            series.setdefault(b["kind"], []).append((r, b))
    out = []
    for kind, points in series.items():
        pct = [(r, b["pct"]) for r, b in points if b["pct"] is not None]
        trend = {"kind": kind, "points": [{"start": r["start"], "pct": b["pct"], "status": b["status"]} for r, b in points],
                 "last_status": points[-1][1]["status"], "last_pct": points[-1][1]["pct"]}
        # Drain since the last charge (the level went up by more than the reporting noise).
        since = pct
        for i in range(len(pct) - 1, 0, -1):
            if pct[i][1] > pct[i - 1][1] + 2:
                since = pct[i:]
                break
        # A level is reported at the end of a ride: the drop happens during the following rides.
        hours = sum(r["moving_h"] for r, _ in since[1:])
        if len(since) >= BATTERY_MIN_READINGS and hours >= BATTERY_MIN_HOURS:
            drop = since[0][1] - since[-1][1]
            trend["per_ride"] = drop / (len(since) - 1)
            trend["per_hour"] = drop / hours
            trend["since_charge"] = since[0][0]["start"]
            if drop > 0:
                trend["rides_left"] = max(0.0, (since[-1][1] - BATTERY_LOW_PCT) / trend["per_ride"])
        out.append(trend)
    return out


def service_status(totals: dict, state: dict | None = None) -> list[dict]:
    """Usage per service item: from the Karoo's service.json when given, else the totals of these rides."""
    marks = (state or {}).get("marks") or {}
    intervals = (state or {}).get("intervals") or {}
    json_totals = (state or {}).get("totals") or {}
    out = []
    for item, name, basis, default in SERVICE_ITEMS:
        total = json_totals.get(SERVICE_JSON_TOTALS[basis], 0.0) if state else totals[basis]
        used = max(0.0, total - (marks.get(item) or {}).get("atValue", 0.0))
        interval = intervals.get(item, default)
        out.append({"id": item, "name": name, "basis": basis, "used": used, "interval": interval,
                    "progress": used / interval if interval else 0.0,
                    "last_service_ms": (marks.get(item) or {}).get("wallMs") or None})
    return out


def history(sources: list[tuple[str, Callable[[], Ride]]], min_elev: float = 15.0,
            service_json: str | None = None, quiet: bool = False) -> dict:
    """[sources]: (name, loader) per ride, loaded one at a time."""
    rows = []
    for name, load in sources:
        try:
            ride = load()
            if not ride.samples:
                continue
            rows.append(ride_usage(ride, summarize(ride, min_elev)))
            if not quiet:
                print(f"  {name}", file=sys.stderr)
        except (Exception, SystemExit) as e:  # one broken file must not stop the report
            if not quiet:
                print(f"skipped {name}: {e}", file=sys.stderr)
    rows, duplicates = dedupe_rides(rows)
    bike = [r for r in rows if r["on_bike"]]
    cogs: dict[int, float] = {}
    for r in bike:
        for t, h in r["cog_h"].items():
            cogs[t] = cogs.get(t, 0.0) + h
    totals = {
        "rides": len(rows), "bike_rides": len(bike),
        "fork_h": sum(r["fork_h"] for r in bike), "shock_h": sum(r["shock_h"] for r in bike),
        "rough_h": sum(r["rough_h"] for r in bike), "fa_changes": sum(r["fa_changes"] for r in bike),
        "shifts": sum(r["shifts"] for r in bike), "drivetrain_km": sum(r["drivetrain_km"] for r in bike),
        "cog_h": dict(sorted(cogs.items())),
    }
    state = None
    if service_json:
        with open(service_json) as f:
            state = json.load(f)
    totals["duplicates_skipped"] = duplicates
    return {"rides": rows, "totals": totals, "service": service_status(totals, state),
            "service_source": "Karoo service.json" if state else "these rides",
            "batteries": battery_trends(rows)}


def history_text(h: dict, u: Units) -> str:
    rows, t = h["rides"], h["totals"]
    lines = [f"MTB Dynamics history — {t['rides']} rides, {t['bike_rides']} with Flight Attendant / AXS data", ""]
    lines.append(f"{'date':<11} {'dist':>8} {'moving':>7} {'fork h':>6} {'rough':>6} {'FA chg':>6} {'open↓':>6} "
                 f"{'shifts':>6} {'/km':>5} {'climb W':>8}")
    def opt(v, f, suffix=""):
        return format(v, f) + suffix if v is not None else "–"

    for r in rows:
        lines.append(f"{r['start'][:10]:<11} {u.dist(r['distance_km'] * 1000):>8} {hms(r['moving_h'] * 3600):>7} "
                     f"{r['fork_h']:>6.1f} {r['rough_h']:>6.1f} {r['fa_changes']:>6} {opt(r['fa_open_desc'], '.0f', '%'):>6} "
                     f"{r['shifts']:>6} {opt(r['shifts_km'], '.1f'):>5} {opt(r['climb_w'], '.0f', ' W'):>8}")
    if t["duplicates_skipped"]:
        lines.append(f"({t['duplicates_skipped']} duplicate{'s' if t['duplicates_skipped'] > 1 else ''} skipped: "
                     f"the same ride as FIT file and Karoo ride folder)")
    lines.append("")
    lines.append(f"Totals on this bike: fork {t['fork_h']:.1f} h ({t['rough_h']:.1f} h rough) · shock {t['shock_h']:.1f} h · "
                 f"{t['fa_changes']:,} Flight Attendant changes · {t['shifts']:,} shifts · drivetrain {u.dist(t['drivetrain_km'] * 1000)}")
    if t["cog_h"]:
        top = sorted(t["cog_h"].items(), key=lambda x: -x[1])[:6]
        lines.append("Most used cogs: " + ", ".join(f"{teeth}T {hours:.1f} h" for teeth, hours in top))
    lines.append("")
    lines.append(f"Service (usage from {h['service_source']}; default intervals: check the manual of your parts)")
    for sv in h["service"]:
        unit = "km" if sv["basis"] == "drivetrain_km" else "h"
        used, interval = sv["used"], sv["interval"]
        if unit == "km" and u.imperial:
            used, interval, unit = used / 1.609344, interval / 1.609344, "mi"
        flag = "DUE " if sv["progress"] >= 1 else "soon" if sv["progress"] >= 0.9 else "    "
        lines.append(f"  {flag} {sv['name']:<30} {used:7.1f} / {interval:.0f} {unit}  ({100 * sv['progress']:.0f}%)")
    if h["batteries"]:
        lines.append("")
        lines.append("Batteries")
        for b in h["batteries"]:
            levels = [f"{p['pct']:.0f}%" if p["pct"] is not None else (p["status"] or "?").lower() for p in b["points"]]
            shown = levels if len(levels) <= 8 else levels[:3] + ["…"] + levels[-4:]
            line = f"  {b['kind']}: " + " → ".join(shown)
            if b.get("per_ride"):
                line += f"  (−{b['per_ride']:.1f}%/ride"
                line += f", −{b['per_hour']:.1f}%/h" if b.get("per_hour") else ""
                line += " since the last charge)"
            if b.get("rides_left") is not None:
                line += f"  ~{b['rides_left']:.0f} rides until {BATTERY_LOW_PCT:.0f}%"
            lines.append(line)
    return "\n".join(lines)


def write_history_csv(h: dict, path: str) -> None:
    keys = ["start", "source", "distance_km", "moving_h", "fork_h", "shock_h", "rough_h", "fa_changes", "fa_open_desc",
            "locked_rough_s", "shifts", "shifts_km", "drivetrain_km", "climb_w", "climb_wkg"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys + ["batteries"])
        for r in h["rides"]:
            w.writerow([_r(r[k]) if isinstance(r[k], float) else r[k] for k in keys] +
                       ["; ".join(f"{b['kind']} {b['pct'] if b['pct'] is not None else b['status']}" for b in r["batteries"])])


HISTORY_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>MTB Dynamics history</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>:root{--bg:#fff;--fg:#1b1b1b;--muted:#5f6b70;--accent:#ff6d00;--card:#f1f4f5}
@media (prefers-color-scheme:dark){:root{--bg:#121416;--fg:#e8eaeb;--muted:#9fb3bd;--card:#1d2124}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:16px}h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:22px 0 6px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.card{background:var(--card);border-radius:10px;padding:10px 12px}.card b{display:block;font-size:20px}
.bar{height:8px;border-radius:4px;background:#0002;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--accent)}
.due i{background:#c62828}.chart{height:340px}</style></head><body><main>
<h1>MTB Dynamics history</h1><p class="muted" id="sub"></p>
<h2>Service</h2><div class="grid" id="service"></div>
<h2>Suspension &amp; drivetrain hours</h2><div class="chart" id="hours"></div>
<h2>Batteries</h2><div class="chart" id="bat"></div>
<h2>Per ride</h2><div class="chart" id="rides"></div>
</main><script>
const H = __DATA__;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const base = {paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)', font:{color: dark ? '#e8eaeb' : '#1b1b1b'},
  margin:{l:50,r:50,t:30,b:80}, legend:{orientation:'h', x:0, y:1.12}};
const t = H.totals;
document.getElementById('sub').textContent = `${t.rides} rides, ${t.bike_rides} with Flight Attendant / AXS data · ` +
  `fork ${t.fork_h.toFixed(1)} h (${t.rough_h.toFixed(1)} h rough) · ${t.shifts.toLocaleString()} shifts · usage from ${H.service_source}`;
document.getElementById('service').innerHTML = H.service.map(s => {
  const unit = s.basis === 'drivetrain_km' ? 'km' : 'h', pct = Math.min(100, 100 * s.progress);
  return `<div class="card ${s.progress >= 1 ? 'due' : ''}">${s.name}<b>${s.used.toFixed(1)} / ${s.interval} ${unit}</b>` +
    `<div class="bar"><i style="width:${pct}%"></i></div></div>`;
}).join('');
// One category per ride (several rides a day must not stack).
const label = r => r.start.slice(0, 16).replace('T', ' ');
const bike = H.rides.filter(r => r.on_bike), x = bike.map(label);
const cat = {type: 'category', tickangle: -30};
let fork = 0, rough = 0, km = 0;
const cumFork = bike.map(r => fork += r.fork_h), cumRough = bike.map(r => rough += r.rough_h), cumKm = bike.map(r => km += r.drivetrain_km);
Plotly.newPlot('hours', [
  {x, y: cumFork, name: 'fork hours', mode: 'lines+markers', line: {color: '#ff6d00'}},
  {x, y: cumRough, name: 'of it rough', mode: 'lines', line: {color: '#c62828', dash: 'dot'}},
  {x, y: cumKm, name: 'drivetrain km', mode: 'lines', yaxis: 'y2', line: {color: '#1565c0'}},
], {...base, xaxis: cat, yaxis: {title: 'h', rangemode: 'tozero'}, yaxis2: {title: 'km', overlaying: 'y', side: 'right', rangemode: 'tozero'},
  // Service intervals (h) once the hours get near them.
  shapes: [...new Set(H.service.filter(s => s.basis !== 'drivetrain_km').map(s => s.interval))].filter(v => fork >= 0.4 * v)
    .map(v => ({type: 'line', xref: 'paper', x0: 0, x1: 1, y0: v, y1: v, line: {color: '#9fb3bd', dash: 'dash', width: 1}}))},
  {displayModeBar: false, responsive: true});
const bats = H.batteries.map(b => ({x: b.points.map(label), y: b.points.map(p => p.pct), name: b.kind, mode: 'lines+markers'}))
  .filter(tr => tr.y.some(v => v !== null));
const allX = [...new Set(H.batteries.flatMap(b => b.points.map(label)))].sort();
if (bats.length) Plotly.newPlot('bat', bats, {...base, xaxis: {...cat, categoryorder: 'array', categoryarray: allX},
  yaxis: {title: '%', range: [0, 105]}}, {displayModeBar: false, responsive: true});
else document.getElementById('bat').outerHTML = '<p class="muted">No battery levels in these rides (the Karoo writes them into the FIT file).</p>';
Plotly.newPlot('rides', [
  {x, y: bike.map(r => r.fa_open_desc), name: 'FA open on descents %', type: 'bar', marker: {color: '#ff6d00'}},
  {x, y: bike.map(r => r.shifts_km), name: 'shifts / km', mode: 'lines+markers', yaxis: 'y2', line: {color: '#1565c0'}},
], {...base, xaxis: cat, yaxis: {title: '%', range: [0, 100]}, yaxis2: {title: '/km', overlaying: 'y', side: 'right', rangemode: 'tozero'}},
  {displayModeBar: false, responsive: true});
</script></body></html>"""


def write_history_html(h: dict, path: str) -> None:
    with open(path, "w") as f:
        f.write(HISTORY_HTML.replace("__DATA__", json.dumps(h, default=str).replace("</", "<\\/")))


class IntervalsIcu:
    """Minimal client for https://intervals.icu/api/v1 (Settings → Developer Settings → API key)."""

    def __init__(self, api_key: str, athlete: str = "0", base: str = "https://intervals.icu"):
        token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "User-Agent": "karoo-mtb/1.0"}
        self.athlete = athlete
        self.base = base.rstrip("/")

    def _request(self, method: str, path: str, body: dict | None = None) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            sys.exit(f"intervals.icu {method} {path}: HTTP {e.code} {e.read()[:200]!r}")

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
        if skipping and (line.startswith("Grit ") or " corners · " in line):
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


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MTB Dynamics analyser (Karoo / Garmin FIT, Karoo ride folders, intervals.icu)")
    p.add_argument("fit", nargs="?", help="FIT file (.fit, .fit.gz or .zip)")
    p.add_argument("--karoo-dir", help="ride folder pulled from the Karoo (samples.csv, events.jsonl)")
    p.add_argument("--imu", nargs="?", const="auto", metavar="IMU_CSV_GZ",
                   help="inspect a raw sensor log (default: imu.csv.gz in --karoo-dir) with every jump sensitivity")
    p.add_argument("--icu", metavar="ID|latest", help="analyse an intervals.icu activity (needs INTERVALS_API_KEY)")
    p.add_argument("--icu-athlete", default=os.environ.get("INTERVALS_ATHLETE_ID", "0"), help="athlete id (default 0 = you)")
    p.add_argument("--icu-key", default=os.environ.get("INTERVALS_API_KEY"), help="intervals.icu API key")
    p.add_argument("--icu-update", action="store_true", help="write the MTB summary into the activity description")
    p.add_argument("--icu-fields", help="also set custom activity fields, e.g. 'MtbGrit=grit.total_k,MtbFlow=flow.score'")
    p.add_argument("--save-fit", help="keep the FIT file downloaded from intervals.icu")
    p.add_argument("--html", help="write an interactive HTML report")
    p.add_argument("--open", action="store_true", help="open the HTML report in the browser")
    p.add_argument("--csv", metavar="PREFIX", help="write per-second, segment, lap, jump and corner CSV files")
    p.add_argument("--json", help="write the full analysis as JSON")
    p.add_argument("--segment-elev", type=float, default=15.0, help="elevation change (m) that splits segments")
    p.add_argument("--rescore", action="store_true",
                   help="recompute Grit/Flow with the current formulas (rides recorded by older app versions)")
    p.add_argument("--imperial", action="store_true", help="miles / feet")
    p.add_argument("--weight", type=float, help="rider weight in kg for W/kg (default: intervals.icu athlete weight)")
    p.add_argument("--quiet", action="store_true", help="no console report")
    p.add_argument("--history", nargs="+", metavar="PATH",
                   help="report across rides (service hours, shifts, batteries): FIT files, Karoo ride folders "
                        "or folders containing them, e.g. a pulled rides/ folder")
    p.add_argument("--icu-history", type=int, metavar="DAYS", help="the same across the rides of the last DAYS on intervals.icu")
    p.add_argument("--service-json", help="service.json pulled from the Karoo: service status from the Karoo's tracker")
    a = p.parse_args(argv)
    units = Units(a.imperial)

    if a.history or a.icu_history:
        sources: list[tuple[str, Callable[[], Ride]]] = [(path, (lambda path=path: load_any(path))) for path in ride_paths(a.history or [])]
        if a.icu_history:
            if not a.icu_key:
                sys.exit("set INTERVALS_API_KEY or --icu-key (intervals.icu → Settings → Developer Settings)")
            client = IntervalsIcu(a.icu_key, a.icu_athlete)
            for rid in client.ride_ids(a.icu_history):
                sources.append((f"intervals.icu {rid}",
                                lambda rid=rid: load_fit(read_fit_bytes(client.original_file(rid)), f"intervals.icu {rid}")))
        if not sources:
            p.error("no FIT files or Karoo ride folders found")
        h = history(sources, a.segment_elev, a.service_json, a.quiet)
        if not a.quiet:
            print(history_text(h, units))
        if a.json:
            with open(a.json, "w") as f:
                json.dump(h, f, indent=1, default=str)
            print(f"wrote {a.json}")
        if a.csv:
            write_history_csv(h, a.csv + "_history.csv")
            print(f"wrote {a.csv}_history.csv")
        if a.html:
            write_history_html(h, a.html)
            print(f"wrote {a.html}")
            if a.open:
                webbrowser.open("file://" + os.path.abspath(a.html))
        return 0

    icu = None
    activity_id = None
    if a.icu:
        if not a.icu_key:
            sys.exit("set INTERVALS_API_KEY or --icu-key (intervals.icu → Settings → Developer Settings)")
        icu = IntervalsIcu(a.icu_key, a.icu_athlete)
        activity_id = icu.latest_ride_id() if a.icu == "latest" else a.icu
        raw = read_fit_bytes(icu.original_file(activity_id))
        if a.save_fit:
            with open(a.save_fit, "wb") as f:
                f.write(raw)
        ride = load_fit(raw, f"intervals.icu {activity_id}")
    elif a.karoo_dir:
        ride = load_karoo_dir(a.karoo_dir)
    elif a.fit:
        with open(a.fit, "rb") as f:
            ride = load_fit(f.read(), os.path.basename(a.fit))
    else:
        p.error("give a FIT file, --karoo-dir or --icu")

    if a.weight:
        ride.weight = a.weight
    elif icu and activity_id and not ride.weight:
        ride.weight = _num(icu.activity(activity_id).get("icu_weight"))
    if a.rescore:
        rescore(ride)
    summary = summarize(ride, a.segment_elev)
    if not a.quiet:
        print(report_text(summary, units))
    if a.imu:
        imu_path = a.imu if a.imu != "auto" else os.path.join(a.karoo_dir or "", "imu.csv.gz")
        if os.path.exists(imu_path):
            print("\n" + imu_report(ride, imu_path))
        else:
            print(f"\nno raw sensor log at {imu_path} (enable 'Debug: save raw sensor data' on the Karoo)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(summary, f, indent=1, default=str)
        print(f"wrote {a.json}")
    if a.csv:
        for path in write_csv(ride, summary, a.csv):
            print(f"wrote {path}")
    if a.html:
        write_html(ride, summary, a.html, units)
        print(f"wrote {a.html}")
        if a.open:
            webbrowser.open("file://" + os.path.abspath(a.html))
    if icu and (a.icu_update or a.icu_fields):
        act = icu.activity(activity_id)
        body: dict = {}
        if a.icu_update:
            body["description"] = merged_description(act.get("description"), description_block(summary, units))
        for code, path in parse_field_map(a.icu_fields).items():
            value = summary_value(summary, path)
            if value is not None:
                body[code] = round(value, 3) if isinstance(value, float) else value
        icu.update(activity_id, body)
        print(f"updated intervals.icu activity {activity_id}: {', '.join(body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
