"""Mount calibration and in-flight rotation (MountCalibrator.kt), barometric drop (PressureTrack.kt), from the raw sensor log."""
from __future__ import annotations

import bisect
import gzip
import math

G = 9.80665
MIN_SECONDS, MIN_SPEED, MIN_PUSH, MAX_PUSH = 60, 3.0, 0.8, 8.0
BARO_BEFORE, BARO_GAP, BARO_SETTLE, BARO_AFTER, BARO_MIN_SAMPLES = 1.0, 0.1, 0.3, 1.0, 3


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(v):
    n = math.sqrt(_dot(v, v))
    return [c / n for c in v] if n > 1e-9 else None


def load_sensors(path: str) -> dict[str, list[tuple]]:
    """All raw log lines by sensor ('a', 'g', 'p'), times in wall seconds."""
    out: dict[str, list[tuple]] = {"a": [], "g": [], "p": []}
    offset = 0.0
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                parts = dict(p.split("=") for p in line[1:].split())
                offset = int(parts["wall_ms"]) / 1000.0 - int(parts["elapsed_ms"]) / 1000.0
                continue
            kind = line[:2]
            if kind not in ("a,", "g,", "p,"):
                continue
            _, t, x, y, z = line.rstrip().split(",")
            out[kind[0]].append((float(t) / 1000.0 + offset, float(x), float(y), float(z)))
    return out


class MountCalibrator:
    """Same sums as MountCalibrator.kt: forward = left × up, left from corner pushes (speed × turn rate)."""

    def __init__(self):
        self.accel_sum = [0.0, 0.0, 0.0]
        self.riding = 0
        self.push_accel = [0.0, 0.0, 0.0]
        self.push_sum = self.push_sq = self.corner_sq = 0.0
        self.corner_accel = [0.0, 0.0, 0.0]
        self.corners = 0

    def on_second(self, mean_accel, yaw_rate: float | None, speed: float) -> None:
        if speed < MIN_SPEED:
            return
        self.accel_sum = [s + a for s, a in zip(self.accel_sum, mean_accel)]
        self.riding += 1
        if yaw_rate is None:
            return
        push = speed * yaw_rate
        if not MIN_PUSH <= abs(push) <= MAX_PUSH:
            return
        self.push_accel = [s + push * a for s, a in zip(self.push_accel, mean_accel)]
        self.corner_accel = [s + a for s, a in zip(self.corner_accel, mean_accel)]
        self.push_sum += push
        self.push_sq += push * push
        self.corner_sq += _dot(mean_accel, mean_accel)
        self.corners += 1

    @property
    def up(self):
        return _unit(self.accel_sum) if self.riding else None

    def _horizontal_push(self, u):
        d = [self.push_accel[i] - G * u[i] * self.push_sum for i in range(3)]
        along = _dot(d, u)
        return [d[i] - along * u[i] for i in range(3)]

    @property
    def forward(self):
        u = self.up
        if self.corners < MIN_SECONDS or u is None:
            return None
        left = _unit(self._horizontal_push(u))
        return _cross(left, u) if left else None

    @property
    def agreement(self) -> float:
        u = self.up
        if u is None or not self.push_sq:
            return 0.0
        left = _unit(self._horizontal_push(u))
        dyn_sq = self.corner_sq - 2 * G * _dot(u, self.corner_accel) + self.corners * G * G
        if not left or dyn_sq <= 0:
            return 0.0
        return max(0.0, min(1.0, _dot(self._horizontal_push(u), left) / math.sqrt(self.push_sq * dyn_sq)))


def calibrate(ride, accel, gyro) -> MountCalibrator:
    """Feeds every riding second of [ride] (per-second speed) with the raw log's mean accel and turn rate."""
    cal = MountCalibrator()
    ts = [s.t for s in ride.samples]
    acc: dict[int, list[float]] = {}
    for t, x, y, z in accel:
        i = bisect.bisect_left(ts, t)
        if i < len(ts):
            b = acc.setdefault(i, [0.0, 0.0, 0.0, 0])
            b[0] += x
            b[1] += y
            b[2] += z
            b[3] += 1
    mean = {i: [b[0] / b[3], b[1] / b[3], b[2] / b[3]] for i, b in acc.items() if b[3] >= 5}
    # Turn rate about the long-run up of the moving seconds (the Karoo uses its lean-corrected yaw).
    up = _unit([sum(m[k] for i, m in mean.items() if ride.samples[i].speed >= MIN_SPEED) for k in range(3)])
    gyr: dict[int, list[float]] = {}
    if up:
        for t, x, y, z in gyro:
            i = bisect.bisect_left(ts, t)
            if i < len(ts):
                b = gyr.setdefault(i, [0.0, 0])
                b[0] += x * up[0] + y * up[1] + z * up[2]
                b[1] += 1
    for i in sorted(mean):
        s = ride.samples[i]
        if getattr(s, "jump_air", 0.0):
            continue
        g = gyr.get(i)
        cal.on_second(mean[i], g[0] / g[1] if g and g[1] >= 5 else None, s.speed)
    return cal


def flight_rotation(gyro, t0: float, t1: float, forward, up) -> dict | None:
    """Integrated gyro from take-off to landing split along the bike: pitch (+ nose down), yaw (+ left), roll (+ right)."""
    if not forward or not up:
        return None
    rot, last = [0.0, 0.0, 0.0], None
    i = bisect.bisect_left(gyro, (t0,))
    while i < len(gyro) and gyro[i][0] <= t1:
        t, x, y, z = gyro[i]
        if last is not None:
            dt = min(0.2, max(0.0, t - last))
            rot = [rot[0] + x * dt, rot[1] + y * dt, rot[2] + z * dt]
        last = t
        i += 1
    u = _unit(up)
    f = _unit([forward[k] - _dot(forward, u) * u[k] for k in range(3)])
    left = _cross(u, f)
    return {"pitch": math.degrees(_dot(rot, left)), "yaw": math.degrees(_dot(rot, u)), "roll": math.degrees(_dot(rot, f))}


def altitude_m(hpa: float) -> float:
    return 44330.0 * (1.0 - (hpa / 1013.25) ** (1.0 / 5.255))


def baro_drop(pressure, takeoff: float, land: float) -> float | None:
    """Height lost (m) from take-off to landing from raw pressure samples (t, hPa, …); + = landed lower."""
    def median_alt(lo, hi):
        w = sorted(p[1] for p in pressure if lo <= p[0] <= hi)
        return altitude_m(w[len(w) // 2]) if len(w) >= BARO_MIN_SAMPLES else None
    before = median_alt(takeoff - BARO_BEFORE, takeoff - BARO_GAP)
    after = median_alt(land + BARO_SETTLE, land + BARO_SETTLE + BARO_AFTER)
    return None if before is None or after is None else before - after
