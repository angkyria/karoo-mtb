"""Jump threshold tuning: a private corpus of labelled flights, the fit, and fixture export."""
from __future__ import annotations

import json
import os

from .groundtruth import candidates, resolve, spots
from .imu import SNIPPET_MARGIN_S, labels_for, load_imu, load_imu_all, write_snippet

DEFAULT_CORPUS = os.path.expanduser("~/karoo-mtb-corpus")
FIT_RESULT = "fit-result.json"


# --------------------------------------------------------------------------------------------
# Corpus: one ±3 s raw IMU clip + JSON per labelled flight, across rides (no GPS, no date)
# --------------------------------------------------------------------------------------------
def add_ride(ride, imu_path: str, corpus: str) -> int:
    """Writes this ride's labelled flights into the corpus, replacing its earlier clips. Returns their count."""
    os.makedirs(corpus, exist_ok=True)
    accel, _ = load_imu(imu_path)
    cands = candidates(ride, accel)
    spot_of = {id(c): k for k, g in enumerate(spots(cands), 1) for c in g}
    pairs = resolve(cands, labels_for(ride, None, 0))
    rows = load_imu_all(imu_path)
    rate = len(accel) / max(1e-9, accel[-1][0] - accel[0][0]) if len(accel) > 1 else 0.0
    rid = int(round(ride.start * 1000))
    for name in os.listdir(corpus):
        if name.startswith(f"{rid}_"):
            os.remove(os.path.join(corpus, name))
    written = 0
    for fl, lab in pairs:
        t0, t1 = fl["t"] - SNIPPET_MARGIN_S, fl["t"] + fl["air"] + SNIPPET_MARGIN_S
        window = [r for r in rows if t0 <= r[1] <= t1]
        if not window:
            continue
        base = f"{rid}_{int(round(fl['t'] * 1000))}"
        source = lab.get("source", "file")
        write_snippet(os.path.join(corpus, base + ".csv"), window, {"label": lab["label"], "source": source})
        meta = {"file": base + ".csv", "label": lab["label"], "source": source, "speed": fl.get("speed"),
                "rate_hz": round(rate, 1), "ride": str(rid), "spot": f"{rid}:{spot_of.get(id(fl), 0)}",
                "air": round(fl["air"], 3)}
        with open(os.path.join(corpus, base + ".json"), "w") as f:
            json.dump(meta, f, indent=1)
        written += 1
    return written


def load_corpus(corpus: str) -> list[dict]:
    clips = []
    for name in sorted(os.listdir(corpus)):
        if name.endswith(".json") and name != FIT_RESULT:
            with open(os.path.join(corpus, name)) as f:
                clips.append(json.load(f))
    return clips
