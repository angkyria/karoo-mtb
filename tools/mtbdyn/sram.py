"""RockShox Flight Attendant, SRAM AXS and power meter analytics."""
from __future__ import annotations

import math

from .analysis import split_segments
from .model import Ride, Sample
from .scoring import _nz

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
    for kind, a, _b in segments:
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
