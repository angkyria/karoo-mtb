"""Raw IMU debug log replay (jump sensitivity tuning)."""
from __future__ import annotations

import datetime as dt
import gzip
import math

from .loaders import _index_at
from .model import Ride
from .report import hms
from .scoring import G

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
