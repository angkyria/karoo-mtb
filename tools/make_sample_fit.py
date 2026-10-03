#!/usr/bin/env python3
"""
Writes a synthetic 40-minute MTB ride as a FIT file, shaped like what the Karoo writes with the
MTB Dynamics extension: a climb, two descents with corners, braking and jumps, two laps.

  python3 make_sample_fit.py sample-karoo.fit            # mtb_* developer fields (Karoo extension)
  python3 make_sample_fit.py sample-garmin.fit --garmin  # Garmin-native grit/flow + jump messages
  python3 make_sample_fit.py sample-plain.fit --plain    # GPS/altitude only (estimation path)

Handy for trying tools/mtb_analyze.py and the intervals.icu custom fields before a real ride
(upload the file to intervals.icu with the "+" → Upload activity button).
"""
from __future__ import annotations

import argparse
import datetime
import math
import random
import time

from garmin_fit_sdk import Encoder
from garmin_fit_sdk.fit import BASE_TYPE
from garmin_fit_sdk.profile import Profile

import mtb_analyze as mtb

FIT_EPOCH = 631065600
LAG = 3

# Same names/units/order as app/.../fit/MtbFitFields.kt
RECORD_FIELDS = [
    ("mtb_grit", "grit"), ("mtb_flow", "m"), ("mtb_rough", "g"), ("mtb_lat_g", "g"), ("mtb_brake", "m/s2"),
    ("mtb_jump_air", "s"), ("mtb_jump_dist", "m"), ("mtb_jump_height", "m"),
]
SESSION_FIELDS = [
    ("mtb_total_grit", "kGrit"), ("mtb_avg_grit", "grit/s"), ("mtb_flow_score", "flow"), ("mtb_total_flow", "m"),
    ("mtb_jumps", "jumps"), ("mtb_max_air", "s"), ("mtb_total_air", "s"), ("mtb_max_jump_dist", "m"),
    ("mtb_max_jump_height", "m"), ("mtb_score", "score"), ("mtb_difficulty", "score"), ("mtb_smoothness", "score"),
    ("mtb_air_score", "score"), ("mtb_corners", "corners"), ("mtb_max_lat_g", "g"), ("mtb_corner_speed_kept", "%"),
    ("mtb_descent_time", "s"), ("mtb_descent_braking", "%"), ("mtb_descent_speed", "m/s"), ("mtb_descent_flow", "flow"),
    ("mtb_avg_rough", "g"), ("mtb_flow_lag", "s"),
]
INTEGER_FIELDS = {"mtb_jumps": "UINT16", "mtb_corners": "UINT16", "mtb_flow_lag": "UINT8"}

# (start s, end s, speed m/s, grade %, roughness g, turning)
PHASES = [
    (0, 900, 3.2, 8.0, 0.15, False),      # climb
    (900, 1300, 7.0, -11.0, 0.45, True),  # descent 1
    (1300, 1700, 5.0, 0.0, 0.20, False),  # rolling
    (1700, 2100, 7.5, -10.0, 0.50, True),  # descent 2
    (2100, 2400, 4.5, 1.0, 0.15, False),  # back to the car
]
JUMPS = [(1010, 0.55), (1120, 0.80), (1210, 0.45), (1800, 0.95), (1950, 0.60)]


def simulate(seed: int = 7):
    rnd = random.Random(seed)
    rows = []
    lat, lon, heading, alt, dist = 38.1650, 23.7150, 30.0, 320.0, 0.0  # Mount Parnitha, Athens
    for t in range(2400):
        start, end, v_base, grade, rough, turning = next(p for p in PHASES if p[0] <= t < p[1])
        yaw = 0.0
        speed = v_base
        if turning:
            # A corner every 20 s: brake (necessary) before it, then turn.
            phase = (t - start) % 20
            if phase in (8, 9):
                speed = v_base - 2.5 * (phase - 7)
            elif 10 <= phase <= 13:
                speed, yaw = v_base - 4.0, 0.9 if (t // 20) % 2 else -0.9
            elif phase in (14, 15):
                speed = v_base - 2.0
            # Now and then a pointless brake on a smooth straight (costs Flow).
            if (t - start) % 97 in (3, 4):
                speed = v_base - 2.0
        else:
            yaw = 0.05 * math.sin(t / 30.0)
        speed = max(0.0, speed + rnd.gauss(0, 0.1))
        heading = (heading - math.degrees(yaw)) % 360.0
        dist += speed
        alt += speed * grade / 100.0
        lat += speed * math.cos(math.radians(heading)) / 111_320.0
        lon += speed * math.sin(math.radians(heading)) / (111_320.0 * math.cos(math.radians(lat)))
        climbing, descending = grade > 3, grade < -3
        pedalling = not descending or (t % 10) < 3
        power = (230 if climbing else 60 if descending else 150) + rnd.gauss(0, 15) if pedalling else 0.0
        rows.append({
            "t": t, "speed": speed, "grade": grade, "alt": alt, "dist": dist, "lat": lat, "lon": lon,
            "rough": max(0.03, rough + rnd.gauss(0, 0.05)), "yaw": yaw,
            # Flight Attendant: Open downhill (Lock for 20 s on a rough bit), Pedal/Lock climbing, Lock on the flat
            "fa": 0 if descending and not 1100 <= t < 1120 else 2 if descending else (1 if (t // 60) % 2 else 2) if climbing else 2,
            "power": max(0.0, power), "cadence": (78 if climbing else 85) if pedalling and not descending else 70 if pedalling else 0,
            "cog": 32 if climbing else 18 if descending else 21,
        })
        if descending and 1100 <= t < 1120:
            rows[-1]["rough"] = 1.1

    # Per-second MTB values exactly as the Karoo engine computes them.
    jumps_at = {t: air for t, air in JUMPS}
    for i, r in enumerate(rows):
        curv = abs(r["yaw"]) / r["speed"] if r["speed"] >= 1.5 else 0.0
        r["curv"] = curv
        r["lat_g"] = r["speed"] * abs(r["yaw"]) / mtb.G
        r["grit"] = mtb.grit_per_second(r["grade"], curv, r["rough"]) if r["speed"] >= mtb.MOVING_SPEED else 0.0
        air = jumps_at.get(i, 0.0)
        r["jump_air"] = air
        r["jump_dist"] = air * rows[max(0, i - 2)]["speed"] if air else 0.0
        r["jump_height"] = mtb.jump_height(air) if air else 0.0
        r["grit"] += 4.0 * air  # Scoring.GRIT_PER_AIR_SECOND
    for i, r in enumerate(rows):
        prev, nxt = rows[max(0, i - 1)], rows[min(len(rows) - 1, i + 1)]
        accel = (nxt["speed"] - prev["speed"]) / 2.0
        b = mtb.braking_decel(accel, r["speed"], r["grade"]) if r["speed"] >= mtb.MOVING_SPEED else 0.0
        w = mtb.brake_weight(b) if r["speed"] >= 2.0 else 0.0
        nec = max(mtb.braking_necessity(r["speed"], q["curv"], q["grade"], q["rough"]) for q in rows[max(0, i - 1):i + LAG + 1])
        r["brake"], r["flow"] = b, r["speed"] * w * (1 - nec)
    return rows


def build(path: str, mode: str, seed: int = 7, start_unix: int | None = None, fa_battery: int = 95) -> None:
    """[start_unix]: ride start (default 3 h ago); [fa_battery]: Flight Attendant battery % (karoo mode)."""
    rows = simulate(seed)
    start = (start_unix if start_unix is not None else int(time.time()) - 3 * 3600) - FIT_EPOCH
    dev_id = {
        "mesg_num": Profile["mesg_num"]["DEVELOPER_DATA_ID"],
        "application_id": list(b"karoo-mtb-sample"),
        "application_version": 1,
        "developer_data_index": 0,
    }
    descriptions = {}
    mesgs = []
    if mode == "karoo":
        mesgs.append(dev_id)
        for key, (name, units) in enumerate(RECORD_FIELDS + SESSION_FIELDS):
            desc = {
                "mesg_num": Profile["mesg_num"]["FIELD_DESCRIPTION"],
                "developer_data_index": 0,
                "field_definition_number": key,
                "fit_base_type_id": BASE_TYPE[INTEGER_FIELDS.get(name, "FLOAT32")],
                "field_name": name,
                "units": units,
            }
            descriptions[key] = {"developer_data_id_mesg": dev_id, "field_description_mesg": desc}
            mesgs.append(desc)
    key_of = {name: key for key, (name, _) in enumerate(RECORD_FIELDS + SESSION_FIELDS)}
    karoo_keys = {}
    if mode == "karoo":
        # Karoo OS writes Flight Attendant state as its own developer fields (developer index 1).
        karoo_id = {"mesg_num": Profile["mesg_num"]["DEVELOPER_DATA_ID"], "application_id": list(b"karoo-os-sample!"),
                    "application_version": 1, "developer_data_index": 1}
        mesgs.append(karoo_id)
        for n, (name, base) in enumerate([("front_suspension", "UINT8"), ("rear_suspension", "UINT8"),
                                          ("suspension_effort_zone", "UINT8"), ("suspension_mode", "UINT8"),
                                          ("suspension_bias", "SINT8")]):
            key = 100 + n
            desc = {"mesg_num": Profile["mesg_num"]["FIELD_DESCRIPTION"], "developer_data_index": 1,
                    "field_definition_number": 11 + n, "fit_base_type_id": BASE_TYPE[base], "field_name": name}
            descriptions[key] = {"developer_data_id_mesg": karoo_id, "field_description_mesg": desc}
            karoo_keys[name] = key
            mesgs.append(desc)

    mesgs.insert(0, {"mesg_num": Profile["mesg_num"]["FILE_ID"], "type": "activity", "manufacturer": "hammerhead",
                     "product": 1, "time_created": start, "serial_number": 4242})
    mesgs.append({"mesg_num": Profile["mesg_num"]["EVENT"], "timestamp": start, "event": "timer", "event_type": "start"})
    if mode == "karoo":
        mesgs.append({"mesg_num": Profile["mesg_num"]["DEVICE_INFO"], "timestamp": start, "device_index": 1,
                      "manufacturer": "sram", "product_name": "Kilo", "battery_level": fa_battery,
                      "battery_status": "good" if fa_battery > 45 else "low",
                      "source_type": "bluetooth_low_energy"})
        mesgs.append({"mesg_num": Profile["mesg_num"]["DEVICE_INFO"], "timestamp": start, "device_index": 3,
                      "manufacturer": "sram", "device_type": 34, "battery_status": "new",
                      "source_type": "antplus"})
    n = len(rows)
    for i, r in enumerate(rows):
        rec = {
            "mesg_num": Profile["mesg_num"]["RECORD"], "timestamp": start + r["t"],
            "position_lat": round(r["lat"] / mtb.SEMICIRCLE_TO_DEG), "position_long": round(r["lon"] / mtb.SEMICIRCLE_TO_DEG),
            "distance": r["dist"], "enhanced_speed": r["speed"], "enhanced_altitude": r["alt"],
            "heart_rate": int(120 + 30 * (r["grade"] > 3) + 10 * math.sin(i / 50)),
            "power": round(r["power"]), "cadence": r["cadence"],
        }
        if mode == "karoo":
            lagged = rows[i - LAG] if i >= LAG else None  # flow/brake are written LAG seconds late
            rec["developer_fields"] = {
                key_of["mtb_grit"]: r["grit"], key_of["mtb_flow"]: lagged["flow"] if lagged else 0.0,
                key_of["mtb_rough"]: r["rough"], key_of["mtb_lat_g"]: r["lat_g"],
                key_of["mtb_brake"]: lagged["brake"] if lagged else 0.0,
                key_of["mtb_jump_air"]: r["jump_air"], key_of["mtb_jump_dist"]: r["jump_dist"],
                key_of["mtb_jump_height"]: r["jump_height"],
            }
        if mode in ("karoo", "garmin"):
            rec["grit"] = r["grit"]
            rec["flow"] = r["flow"]
        if mode == "karoo":
            rec["developer_fields"].update({
                karoo_keys["front_suspension"]: r["fa"], karoo_keys["rear_suspension"]: r["fa"],
                karoo_keys["suspension_effort_zone"]: 0 if r["power"] < 120 else 1 if r["power"] < 180 else 2,
                karoo_keys["suspension_mode"]: 1, karoo_keys["suspension_bias"]: 2,
            })
        if mode != "plain" and (i == 0 or r["cog"] != rows[i - 1]["cog"]):
            # AXS rear shift: packed like the Karoo writes it (rear gear #, rear teeth, front gear #, front teeth)
            gear_num = {32: 3, 21: 7, 18: 8}[r["cog"]]
            mesgs.append({"mesg_num": Profile["mesg_num"]["EVENT"], "timestamp": start + r["t"], "event": "rear_gear_change",
                          "event_type": "marker", "data": gear_num | r["cog"] << 8 | 1 << 16 | 36 << 24})
        mesgs.append(rec)
        if mode == "garmin" and r["jump_air"]:
            mesgs.append({"mesg_num": 285, "timestamp": start + r["t"], "hang_time": r["jump_air"], "distance": r["jump_dist"],
                          "height": r["jump_height"], "rotations": 0, "score": 100 * r["jump_air"],
                          "position_lat": rec["position_lat"], "position_long": rec["position_long"], "enhanced_speed": r["speed"]})
    end = start + n
    mesgs.append({"mesg_num": Profile["mesg_num"]["EVENT"], "timestamp": end, "event": "timer", "event_type": "stop_all"})
    for idx, (a, b) in enumerate([(0, 1300), (1300, n)]):
        mesgs.append({"mesg_num": Profile["mesg_num"]["LAP"], "message_index": idx, "timestamp": start + b,
                      "start_time": start + a, "total_elapsed_time": b - a, "total_timer_time": b - a,
                      "total_distance": rows[b - 1]["dist"] - (rows[a - 1]["dist"] if a else 0.0)})

    total_grit = sum(r["grit"] for r in rows)
    flow_m = sum(r["flow"] for r in rows)
    dist = rows[-1]["dist"]
    jumps = [r for r in rows if r["jump_air"]]
    session = {
        "mesg_num": Profile["mesg_num"]["SESSION"], "message_index": 0, "timestamp": end, "start_time": start,
        "total_elapsed_time": n, "total_timer_time": n, "total_distance": dist, "sport": "cycling",
        "sub_sport": "mountain", "first_lap_index": 0, "num_laps": 2,
    }
    if mode in ("karoo", "garmin"):
        session.update({"total_grit": total_grit / 1000.0, "total_flow": flow_m, "jump_count": len(jumps),
                        "avg_grit": total_grit / n, "avg_flow": mtb.flow_score(flow_m, dist)})
    if mode == "karoo":
        avg_grit = total_grit / n
        fs = mtb.flow_score(flow_m, dist)
        total_air = sum(r["jump_air"] for r in jumps)
        d, s, a = mtb.difficulty_score(avg_grit), mtb.smoothness_score(fs), mtb.air_score(total_air)
        values = {
            "mtb_total_grit": total_grit / 1000.0, "mtb_avg_grit": avg_grit, "mtb_flow_score": fs, "mtb_total_flow": flow_m,
            "mtb_jumps": len(jumps), "mtb_max_air": max(r["jump_air"] for r in jumps), "mtb_total_air": total_air,
            "mtb_max_jump_dist": max(r["jump_dist"] for r in jumps), "mtb_max_jump_height": max(r["jump_height"] for r in jumps),
            "mtb_score": mtb.mtb_score(d, s, a), "mtb_difficulty": d, "mtb_smoothness": s, "mtb_air_score": a,
            "mtb_corners": 40, "mtb_max_lat_g": max(r["lat_g"] for r in rows), "mtb_corner_speed_kept": 62.0,
            "mtb_descent_time": 800.0, "mtb_descent_braking": 30.0, "mtb_descent_speed": 6.4, "mtb_descent_flow": fs,
            "mtb_avg_rough": sum(r["rough"] for r in rows) / n, "mtb_flow_lag": LAG,
        }
        session["developer_fields"] = {key_of[k]: v for k, v in values.items()}
    mesgs.append(session)
    mesgs.append({"mesg_num": Profile["mesg_num"]["ACTIVITY"], "timestamp": end, "num_sessions": 1, "total_timer_time": n})

    encoder = Encoder(field_descriptions=descriptions)
    for m in mesgs:
        encoder.write_mesg(m)
    with open(path, "wb") as f:
        f.write(encoder.close())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("out")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--garmin", action="store_true", help="Garmin-native MTB Dynamics fields and jump messages")
    g.add_argument("--plain", action="store_true", help="no MTB data at all")
    p.add_argument("--seed", type=int, default=7, help="noise seed (different rides)")
    p.add_argument("--start", help="ride start, e.g. 2026-09-20T09:00 (UTC; default 3 hours ago)")
    p.add_argument("--fa-battery", type=int, default=95, help="Flight Attendant battery level in %%")
    a = p.parse_args()
    start = None
    if a.start:
        start = int(datetime.datetime.fromisoformat(a.start).replace(tzinfo=datetime.timezone.utc).timestamp())
    build(a.out, "garmin" if a.garmin else "plain" if a.plain else "karoo", a.seed, start, a.fa_battery)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
