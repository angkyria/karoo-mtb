"""Raw IMU debug log replay (jump sensitivity tuning)."""
from __future__ import annotations

import bisect
import datetime as dt
import gzip
import json
import math
import os
from dataclasses import dataclass

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
# Trail mode (mirror of TrailMode.kt and Sensitivity.trail*): take-off g, min airtime s per preset
TRAIL_PRESETS = {
    "LOW": (0.40, 0.30),
    "MEDIUM": (0.50, 0.23),
    "HIGH": (0.60, 0.15),
}
TRAIL_MAX_MEAN_AIR_G, TRAIL_ROUGH_G, TRAIL_WINDOW, TRAIL_MIN_SECONDS = 0.70, 0.9, 30, 10


@dataclass(frozen=True)
class Thresholds:
    """The tunable jump gates (a preset, or a point of the --fit search grid)."""
    takeoff_g: float
    min_air: float
    min_landing_g: float
    max_mean_air_g: float = MAX_MEAN_AIR_G


def preset_thresholds(name: str) -> Thresholds:
    t, a, land = PRESETS[name]
    return Thresholds(t, a, land, MAX_MEAN_AIR_G)


def trail_thresholds(name: str) -> Thresholds:
    t, a = TRAIL_PRESETS[name]
    return Thresholds(t, a, PRESETS[name][2], TRAIL_MAX_MEAN_AIR_G)


def thresholds_for(name: str, trail: bool) -> Thresholds:
    return trail_thresholds(name) if trail else preset_thresholds(name)


def trail_schedule(ride: Ride | None):
    """t -> on a trail, as TrailMode.kt decides it each second; None without per-second roughness."""
    if not ride or not ride.samples or all(s.rough is None for s in ride.samples):
        return None
    times, states, window = [], [], []
    for s in ride.samples:
        if s.rough is not None:
            window.append(s.rough)
            del window[:-TRAIL_WINDOW]
        times.append(s.t)
        states.append(len(window) >= TRAIL_MIN_SECONDS and sorted(window)[len(window) // 2] >= TRAIL_ROUGH_G)

    def at(t: float) -> bool:
        i = bisect.bisect_right(times, t) - 1
        return states[i] if i >= 0 else False
    return at


def verdict(fl: dict, th: Thresholds, speed: float | None) -> str:
    """Same checks, same order as JumpDetector.validate + MtbEngine's take-off speed check. Empty = a jump."""
    air, mean_g, peak = fl["air"], fl["mean_g"], fl["landing_g"]
    if air < th.min_air:
        return "airtime %.2f s < %.2f" % (air, th.min_air)
    if air > MAX_AIR:
        return "longer than %.1f s" % MAX_AIR
    if mean_g > th.max_mean_air_g:
        return "mean %.2f g in flight" % mean_g
    if peak < th.min_landing_g:
        return "landing %.2f g < %.2f" % (peak, th.min_landing_g)
    if speed is not None and speed < MIN_JUMP_SPEED:
        return "speed %.1f km/h" % (speed * 3.6)
    return ""


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


def find_flights(accel, preset: str | Thresholds, trail_at=None) -> list[dict]:
    """Port of ImuProcessor (|a| filter) + JumpDetector; also returns rejected flights with the reason.

    With [trail_at] (see trail_schedule) and a preset name, flights that take off on a trail are
    judged with the preset's trail gates, as on the Karoo."""
    base = preset_thresholds(preset) if isinstance(preset, str) else preset
    trail_th = trail_thresholds(preset) if isinstance(preset, str) and trail_at else None
    th, on_trail = base, False
    takeoff_g = th.takeoff_g
    out = []
    mag_lp, last_t = 1.0, None
    state, air_start, land_t, sum_g, n_g, peak, cooldown = "GROUND", 0.0, 0.0, 0.0, 0, 0.0, 0.0
    for t, x, y, z in accel:
        mag = math.sqrt(x * x + y * y + z * z) / G
        dt = 0.0 if last_t is None else min(0.2, max(0.0, t - last_t))
        last_t = t
        mag_lp = mag if dt <= 0 else mag_lp + dt / (0.03 + dt) * (mag - mag_lp)
        if state == "GROUND":
            if trail_th:
                on_trail = trail_at(t)
                th = trail_th if on_trail else base
                takeoff_g = th.takeoff_g
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
                reason = verdict({"air": air, "mean_g": mean_g, "landing_g": peak}, th, None)
                if air >= 0.08:
                    out.append({"t": air_start, "air": air, "mean_g": mean_g, "landing_g": peak, "reason": reason,
                                "trail": on_trail})
    return out


def imu_report(ride: Ride | None, path: str, labels_path: str | None = None) -> str:
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

    trail_at = trail_schedule(ride)
    from .mount import baro_drop, calibrate, flight_rotation, load_sensors
    sensors = load_sensors(path)
    cal = calibrate(ride, accel, sensors["g"]) if ride and ride.samples else None
    forward, up = (cal.forward, cal.up) if cal else (None, None)
    if cal:
        lines.append(f"Mount: forward axis {', '.join(f'{c:+.2f}' for c in forward)} from {cal.corners} corner seconds "
                     f"(agreement {cal.agreement:.2f})" if forward else f"Mount: not calibrated ({cal.corners} corner seconds, need 60)")
    lines.append(f"Barometer: {len(sensors['p'])} samples" if sensors["p"] else "Barometer: not in this log (app < 0.5)")
    for preset in ("LOW", "MEDIUM", "HIGH"):
        flights = find_flights(accel, preset, trail_at)
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
            tr = " · trail" if fl.get("trail") else ""
            extra = ""
            if preset == "HIGH":
                drop = baro_drop(sensors["p"], fl["t"], fl["t"] + fl["air"])
                rot = flight_rotation(sensors["g"], fl["t"], fl["t"] + fl["air"], forward, up)
                if drop is not None:
                    extra += f" · baro drop {drop:+.1f} m"
                if rot:
                    extra += f" · pitch {rot['pitch']:+.0f}° yaw {rot['yaw']:+.0f}° roll {rot['roll']:+.0f}°"
            lines.append(f"  {at}  {fl['air']:.2f} s air · mean {fl['mean_g']:.2f} g · landing {fl['landing_g']:.1f} g{sp}{tr}{extra}")
        if preset == "HIGH":
            near = sorted((fl for fl in flights if fl["reason"]), key=lambda f: -f["air"])[:10]
            if near:
                lines.append("  longest rejected flights:")
                for fl in near:
                    at = dt.datetime.fromtimestamp(fl["t"], dt.timezone.utc).strftime("%H:%M:%S")
                    lines.append(f"  {at}  {fl['air']:.2f} s · {fl['reason']}")
    labels = labels_for(ride, labels_path, _day_start(accel[0][0]))
    if labels:
        lines += labels_report(evaluate_labels(accel, labels, speed_at, trail_at), labels)
    return "\n".join(lines)


def _day_start(t: float) -> float:
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp()


# --------------------------------------------------------------------------------------------
# Labelled jumps: "Mark moment" presses and a labels file → detection rate per sensitivity,
# and short IMU snippets for app/src/test/resources/imu (replayed by JumpFixtureTest.kt)
# --------------------------------------------------------------------------------------------
MARKER_WINDOW_S = 15.0   # a marker labels the flight that landed up to this long before the press
LABEL_WINDOW_S = 3.0     # a labels-file time matches a take-off this close
SNIPPET_MARGIN_S = 3.0


def load_imu_all(path: str) -> list[tuple[str, float, float, float, float]]:
    """Every sample (sensor 'a' or 'g', wall seconds, x, y, z) from imu.csv.gz."""
    rows = []
    offset = 0.0
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                parts = dict(p.split("=") for p in line[1:].split())
                offset = int(parts["wall_ms"]) / 1000.0 - int(parts["elapsed_ms"]) / 1000.0
                continue
            if line[:2] not in ("a,", "g,"):
                continue
            sensor, t, x, y, z = line.rstrip().split(",")
            rows.append((sensor, float(t) / 1000.0 + offset, float(x), float(y), float(z)))
    return rows


def read_labels(path: str, day_start: float) -> list[dict]:
    """
    A labels file: one `time,label[,source]` per line, label `jump` or `nojump`; time as UTC clock
    time (HH:MM:SS, as the --imu report prints take-offs), epoch seconds or wall_ms (labels.csv
    written by --review). # starts a comment.
    """
    out = []
    with open(path) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line or line.startswith("wall_ms"):
                continue
            parts = [p.strip() for p in line.split(",")]
            when, label = parts[0], parts[1] if len(parts) > 1 else ""
            if label == "":
                continue   # a --dump row nobody filled in
            source = parts[2] if len(parts) > 2 and parts[2] in ("review", "button", "file") else "file"
            if ":" in when:
                h, m, s = when.split(":")
                t = day_start + int(h) * 3600 + int(m) * 60 + float(s)
            else:
                t = float(when)
                if t > 1e11:   # wall_ms
                    t /= 1000.0
            if label not in ("jump", "nojump"):
                raise ValueError(f"{path}: label must be jump or nojump, got {label!r}")
            out.append({"t": t, "label": label, "kind": "file", "source": source})
    return out


def labels_for(ride: Ride | None, labels_path: str | None, day_start: float) -> list[dict]:
    labels = [{"t": m["t"], "label": m.get("label", "jump"), "kind": "marker", "source": "button", "n": m["n"]}
              for m in (ride.markers if ride else [])]
    if labels_path is None and ride is not None and ride.folder:
        auto = os.path.join(ride.folder, "labels.csv")
        labels_path = auto if os.path.exists(auto) else None
    if labels_path:
        labels += read_labels(labels_path, day_start)
    return sorted(labels, key=lambda x: x["t"])


def match_label(flights: list[dict], label: dict) -> dict | None:
    """The flight a label refers to: for a marker the last landing before the press, else the nearest take-off."""
    if label["kind"] == "marker":
        before = [f for f in flights if label["t"] - MARKER_WINDOW_S <= f["t"] + f["air"] <= label["t"] + 1.0]
        return max(before, key=lambda f: f["t"]) if before else None
    near = [f for f in flights if abs(f["t"] - label["t"]) <= LABEL_WINDOW_S]
    return min(near, key=lambda f: abs(f["t"] - label["t"])) if near else None


def evaluate_labels(accel, labels: list[dict], speed_at=lambda t: None, trail_at=None) -> dict:
    """Per sensitivity: labelled jumps found, no-jump labels wrongly detected, detections without a label."""
    result = {}
    for preset in PRESETS:
        flights = find_flights(accel, preset, trail_at)
        for fl in flights:
            v = speed_at(fl["t"])
            if not fl["reason"] and v is not None and v < MIN_JUMP_SPEED:
                fl["reason"] = "speed %.1f km/h" % (v * 3.6)
        accepted = [f for f in flights if not f["reason"]]
        found = missed = false = 0
        used = set()
        from .groundtruth import resolve
        matched = {id(lab): fl for fl, lab in resolve(accepted, labels)}
        overruled = {id(lab) for lab in labels if match_label(accepted, lab) is not None and id(lab) not in matched}
        for lab in labels:
            if id(lab) in overruled:
                continue   # another label (a review) decided this flight
            hit = matched.get(id(lab))
            if hit:
                used.add(id(hit))
            if lab["label"] == "jump":
                found, missed = (found + 1, missed) if hit else (found, missed + 1)
            elif hit:
                false += 1
        result[preset] = {"found": found, "missed": missed, "false": false,
                          "unlabelled": sum(1 for f in accepted if id(f) not in used)}
    return result


def labels_report(evaluation: dict, labels: list[dict]) -> list[str]:
    jumps = sum(1 for x in labels if x["label"] == "jump")
    nojumps = len(labels) - jumps
    lines = ["", f"Labels: {jumps} jumps ({sum(1 for x in labels if x['kind'] == 'marker')} from markers), {nojumps} no-jump"]
    for preset, r in evaluation.items():
        recall = 100.0 * r["found"] / jumps if jumps else 0.0
        lines.append(f"  {preset:<6} {r['found']}/{jumps} jumps found ({recall:.0f} %)"
                     + (f" · {r['false']} of {nojumps} no-jumps detected" if nojumps else "")
                     + f" · {r['unlabelled']} detections without a label")
    if jumps:
        best = max(evaluation, key=lambda p: (evaluation[p]["found"] - 2 * evaluation[p]["false"], -evaluation[p]["unlabelled"]))
        lines.append(f"  → best fit: {best}" + ("" if evaluation[best]["missed"] == 0 else " (still misses some: export snippets and tune)"))
    return lines


def write_snippet(path: str, rows, header: dict) -> None:
    """A fixture CSV: '# key=value ...' then sensor,t_ms,x,y,z with time relative to the first row."""
    t0 = rows[0][1] if rows else 0.0
    with open(path, "w") as f:
        f.write("# " + " ".join(f"{k}={v}" for k, v in header.items()) + "\n")
        f.write("sensor,t_ms,x,y,z\n")
        for sensor, t, x, y, z in rows:
            f.write(f"{sensor},{(t - t0) * 1000:.2f},{x:.4f},{y:.4f},{z:.4f}\n")


def update_manifest(out_dir: str, entries: list[dict]) -> str:
    """Adds (or replaces, by file name) fixture entries in out_dir/manifest.json."""
    path = os.path.join(out_dir, "manifest.json")
    current = []
    if os.path.exists(path):
        with open(path) as f:
            current = json.load(f).get("fixtures", [])
    names = {e["file"] for e in entries}
    fixtures = [e for e in current if e["file"] not in names] + entries
    with open(path, "w") as f:
        json.dump({"comment": "IMU snippets replayed by JumpFixtureTest.kt: 'expect' per preset, or 'expectJump' at MEDIUM "
                              "(or at 'preset'). Write real ones with mtb_analyze.py --fit CORPUS --export-fixtures DIR.",
                   "fixtures": sorted(fixtures, key=lambda e: e["file"])}, f, indent=1)
        f.write("\n")
    return path


def export_snippets(path: str, labels: list[dict], out_dir: str, prefix: str) -> list[str]:
    """One snippet per label (the flight ± 3 s, or ± 3 s around the label when no flight was seen). No GPS."""
    rows = load_imu_all(path)
    accel = [(t, x, y, z) for s, t, x, y, z in rows if s == "a"]
    flights = find_flights(accel, "HIGH")   # the most permissive preset finds the flight to cut around
    os.makedirs(out_dir, exist_ok=True)
    entries, written = [], []
    for k, lab in enumerate(labels, 1):
        fl = match_label(flights, lab)
        t0, t1 = (fl["t"], fl["t"] + fl["air"]) if fl else (lab["t"] - (MARKER_WINDOW_S / 2 if lab["kind"] == "marker" else 0), lab["t"])
        window = [r for r in rows if t0 - SNIPPET_MARGIN_S <= r[1] <= t1 + SNIPPET_MARGIN_S]
        if not window:
            continue
        name = f"{prefix}{k:02d}_{lab['label']}.csv"
        air = round(fl["air"], 3) if fl else None
        write_snippet(os.path.join(out_dir, name), window, {"label": lab["label"], "source": "real", "air": air})
        entries.append({"file": name, "expectJump": lab["label"] == "jump", "source": "real", "airSec": air,
                        "note": dt.datetime.fromtimestamp(lab["t"], dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") + f" ({lab['kind']})"})
        written.append(name)
    if entries:
        written.append(os.path.basename(update_manifest(out_dir, entries)))
    return written
