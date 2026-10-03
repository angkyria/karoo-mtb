#!/usr/bin/env python3
"""
Writes synthetic IMU snippets to app/src/test/resources/imu (manifest.json + CSV), the same
format as `mtb_analyze.py --imu --export-snippets` produces from real rides. JumpFixtureTest.kt
replays every snippet through ImuProcessor + JumpDetector.

The synthetic ones only keep the test harness honest; real snippets of your own jumps (and of
rough ground that is not a jump) are what tune the detector. See README → Tuning.

  python3 tools/make_imu_fixtures.py
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mtbdyn.imu import update_manifest, write_snippet  # noqa: E402
from mtbdyn.scoring import G  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "test", "resources", "imu")
RATE = 100


def ride(seconds: float, flight: tuple[float, float] | None, landing_g: float, vibration_g: float, seed: int):
    """Accelerometer + gyroscope rows of a Karoo mounted upright (gravity on z)."""
    rnd = random.Random(seed)
    rows = []
    for k in range(int(seconds * RATE)):
        t = k / RATE
        in_air = flight is not None and flight[0] <= t < flight[0] + flight[1]
        landed = flight is not None and flight[0] + flight[1] <= t < flight[0] + flight[1] + 0.06
        if in_air:
            az = 0.05 * G + rnd.gauss(0, 0.02 * G)
        elif landed:
            az = landing_g * G
        else:
            az = G + rnd.gauss(0, vibration_g * G)
        ax, ay = rnd.gauss(0, vibration_g * 0.5 * G), rnd.gauss(0, vibration_g * 0.5 * G)
        rows.append(("a", t, ax, ay, az))
        rows.append(("g", t, rnd.gauss(0, 0.01), rnd.gauss(0, 0.01), 0.3 * math.sin(t)))
    return rows


CASES = [
    # name, flight (start, air), landing g, vibration g, expected jump at MEDIUM, note
    ("synthetic_jump", (3.0, 0.6), 3.0, 0.05, True, "clean 0.6 s jump"),
    ("synthetic_drop", (3.0, 1.1), 2.5, 0.08, True, "1.1 s step-down"),
    ("synthetic_hop", (3.0, 0.15), 1.8, 0.05, False, "0.15 s bunny hop (below MEDIUM's 0.28 s)"),
    ("synthetic_rough", None, 1.0, 0.45, False, "rough ground, no flight"),
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    entries = []
    for i, (name, flight, landing, vibration, expect, note) in enumerate(CASES):
        file = name + ".csv"
        write_snippet(os.path.join(OUT, file), ride(8.0, flight, landing, vibration, seed=100 + i),
                      {"label": "jump" if expect else "nojump", "source": "synthetic"})
        entries.append({"file": file, "expectJump": expect, "source": "synthetic", "airSec": flight[1] if flight else None, "note": note})
        print("wrote", os.path.normpath(os.path.join(OUT, file)))
    print("wrote", os.path.normpath(update_manifest(OUT, entries)))


if __name__ == "__main__":
    main()
