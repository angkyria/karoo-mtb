"""Jump ground truth: labels.csv in the ride folder, label precedence, review candidates and spots."""
from __future__ import annotations

import datetime as dt
import math
import os

from .imu import MIN_JUMP_SPEED, PRESETS, Thresholds, find_flights, labels_for, preset_thresholds, verdict
from .loaders import _index_at

LABELS_FILE = "labels.csv"
HEADER = "wall_ms,label,source\n"
# Which label wins when two refer to the same flight: a calm post-ride review beats a mid-trail press.
_RANK = {"review": 3, "file": 2, "button": 1}


def append_label(ride_dir: str, wall_ms: int, label: str, source: str) -> None:
    """Appends one label (written immediately, so a crash loses nothing). No positions are stored."""
    if label not in ("jump", "nojump"):
        raise ValueError(f"label must be jump or nojump, got {label!r}")
    path = os.path.join(ride_dir, LABELS_FILE)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    if not new:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            needs_newline = f.read(1) != b"\n"
    with open(path, "a") as f:
        if new:
            f.write(HEADER)
        elif needs_newline:
            f.write("\n")
        f.write(f"{wall_ms},{label},{source}\n")


def resolve(flights: list[dict], labels: list[dict]) -> list[tuple[dict, dict]]:
    """(flight, label) with one label per flight; labels that match no flight are dropped."""
    from .imu import match_label

    best: dict[int, tuple[dict, dict]] = {}
    for lab in labels:
        fl = match_label(flights, lab)
        if fl is None:
            continue
        cur = best.get(id(fl))
        if cur is None or _RANK.get(lab.get("source", "file"), 0) >= _RANK.get(cur[1].get("source", "file"), 0):
            best[id(fl)] = (fl, lab)
    return sorted(best.values(), key=lambda p: p[0]["t"])


# --------------------------------------------------------------------------------------------
# Review candidates: every flight the fit could ever count, grouped into spots
# --------------------------------------------------------------------------------------------
CANDIDATE = Thresholds(0.65, 0.12, 0.0, 9.0)   # widest take-off threshold of the fit grid, no other gate
MIN_CANDIDATE_AIR = 0.12
SPOT_RADIUS_M = 15.0


def _at(ride, t):
    if not ride or not ride.samples:
        return None
    return ride.samples[_index_at(ride.samples, t)]


def _speed(ride, t):
    """Median speed over the 3 s before take-off (as the --imu report does)."""
    if not ride or not ride.samples:
        return None
    i = _index_at(ride.samples, t)
    w = sorted(s.speed for s in ride.samples[max(0, i - 3):i + 1])
    return w[len(w) // 2] if w else None


def candidates(ride, accel) -> list[dict]:
    """Flights with ≥ 0.12 s air and take-off speed ≥ 2.2 m/s, with each preset's verdict."""
    per_preset = {name: find_flights(accel, name) for name in PRESETS}
    out = []
    for fl in find_flights(accel, CANDIDATE):
        if fl["air"] < MIN_CANDIDATE_AIR:
            continue
        v = _speed(ride, fl["t"])
        if v is not None and v < MIN_JUMP_SPEED:
            continue
        s = _at(ride, fl["t"])
        verdicts = {}
        for name, flights in per_preset.items():
            near = [f for f in flights if abs(f["t"] - fl["t"]) <= 0.3]
            own = min(near, key=lambda f: abs(f["t"] - fl["t"])) if near else None
            verdicts[name] = verdict(own, preset_thresholds(name), v) if own else "not a flight"
        out.append({**fl, "speed": v, "lap": getattr(s, "lap", None), "lat": getattr(s, "lat", None),
                    "lon": getattr(s, "lon", None), "verdicts": verdicts})
    return out


def _dist_m(a, b) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def spots(cands: list[dict], radius_m: float = SPOT_RADIUS_M) -> list[list[dict]]:
    """Groups passes over the same feature (take-offs within radius_m). No position → its own spot."""
    groups: list[list[dict]] = []
    for c in sorted(cands, key=lambda x: x["t"]):
        if c.get("lat") is None or c.get("lon") is None:
            groups.append([c])
            continue
        home = next((g for g in groups if g[0].get("lat") is not None and _dist_m(g[0], c) <= radius_m), None)
        if home is None:
            groups.append([c])
        else:
            home.append(c)
    return groups


# --------------------------------------------------------------------------------------------
# Review: label every candidate, one spot at a time (--review), or as a CSV to fill in (--dump)
# --------------------------------------------------------------------------------------------
def _hms(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%S")


def _save(ride_dir: str, c: dict, label: str) -> None:
    append_label(ride_dir, int(round(c["t"] * 1000)), label, "review")


def review(ride, ride_dir: str, accel, ask=input, out=print) -> int:
    """Interactive pass over every unlabelled candidate flight, spot by spot. Returns labels written."""
    cands = candidates(ride, accel)
    labels = labels_for(ride, None, 0)
    pairs = resolve(cands, labels)
    done = {id(fl) for fl, lab in pairs if lab.get("source") == "review"}
    button = {id(fl): lab["label"] for fl, lab in resolve(cands, [x for x in labels if x.get("source") == "button"])}
    groups = [g for g in ([c for c in g if id(c) not in done] for g in spots(cands)) if g]
    out(f"{sum(len(g) for g in groups)} unlabelled flights at {len(groups)} spots")
    written = 0
    for k, g in enumerate(groups, 1):
        speeds = [c["speed"] for c in g if c["speed"] is not None]
        out(f"\nSpot {k} · {len(g)} pass{'es' if len(g) > 1 else ''}"
            + (f" · ~{sum(speeds) / len(speeds) * 3.6:.0f} km/h" if speeds else ""))
        for c in g:
            marks = "  ".join(f"{p[:3]} {'✓' if not v else '✗'}" for p, v in c["verdicts"].items())
            out(f"  {_hms(c['t'])}  {c['air']:.2f} s air · mean {c['mean_g']:.2f} g · landing {c['landing_g']:.1f} g"
                f"   {marks}   [button: {button.get(id(c), '—')}]")
        while True:
            a = ask("[J]ump all · [N]ot a jump all · [e]ach pass · [s]kip · [q]uit > ").strip()
            if a in ("J", "N"):
                for c in g:
                    _save(ride_dir, c, "jump" if a == "J" else "nojump")
                    written += 1
                break
            if a == "e":
                for c in g:
                    b = ask(f"  {_hms(c['t'])} [j]ump / [n]ot / [s]kip > ").strip().lower()
                    if b in ("j", "n"):
                        _save(ride_dir, c, "jump" if b == "j" else "nojump")
                        written += 1
                break
            if a == "s":
                break
            if a == "q":
                return written
    return written


def dump_candidates(ride, accel, path: str) -> int:
    """The review list as CSV with an empty label column; fill it in and pass it back with --labels."""
    cands = candidates(ride, accel)
    with open(path, "w") as f:
        f.write("wall_ms,label,air_s,mean_g,landing_g,speed_kmh,spot,LOW,MEDIUM,HIGH\n")
        for k, g in enumerate(spots(cands), 1):
            for c in g:
                sp = "" if c["speed"] is None else f"{c['speed'] * 3.6:.0f}"
                yes = ["yes" if not c["verdicts"][p] else "no" for p in ("LOW", "MEDIUM", "HIGH")]
                f.write(f"{int(round(c['t'] * 1000))},,{c['air']:.2f},{c['mean_g']:.2f},{c['landing_g']:.2f},{sp},{k},"
                        + ",".join(yes) + "\n")
    return len(cands)
