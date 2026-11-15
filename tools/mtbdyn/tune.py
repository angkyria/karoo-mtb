"""Jump threshold tuning: a private corpus of labelled flights, the fit, and fixture export."""
from __future__ import annotations

import json
import os

from .groundtruth import candidates, resolve, spots
from .imu import (
    MAX_AIR,
    MIN_JUMP_SPEED,
    SNIPPET_MARGIN_S,
    Thresholds,
    find_flights,
    labels_for,
    load_imu,
    load_imu_all,
    preset_thresholds,
    write_snippet,
)

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


# --------------------------------------------------------------------------------------------
# Fit: per preset, the thresholds with the best recall that meet its precision target
# --------------------------------------------------------------------------------------------
TARGETS = {"MEDIUM": 0.95, "LOW": 0.99, "HIGH": 0.85}
MIN_JUMPS, MIN_NOJUMPS, MIN_RIDES = 20, 20, 3
PRESET_ORDER = ("LOW", "MEDIUM", "HIGH")


def _frange(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [round(lo + i * step, 4) for i in range(n + 1)]


def grid() -> dict[str, list[float]]:
    return {"takeoff_g": _frange(0.30, 0.65, 0.05), "min_air": _frange(0.12, 0.45, 0.02),
            "min_landing_g": _frange(1.0, 1.6, 0.05), "max_mean_air_g": _frange(0.45, 0.70, 0.05)}


def _span(values):
    return (values[-1] - values[0]) or 1.0


def _read_clip(corpus, clip):
    accel = []
    with open(os.path.join(corpus, clip["file"])) as f:
        for line in f:
            if line.startswith("a,"):
                _, t, x, y, z = line.rstrip().split(",")
                accel.append((float(t) / 1000.0, float(x), float(y), float(z)))
    return accel


def clip_flights(corpus, clip, takeoff_g) -> list[dict]:
    """Flights in a clip. Only the take-off threshold changes the segmentation; detected() applies the rest."""
    return find_flights(_read_clip(corpus, clip), Thresholds(takeoff_g, 0.0, 0.0, 99.0))


def detected(flights, th: Thresholds, speed) -> bool:
    """Would the Karoo count a jump in this clip (same gates as imu.verdict, without the strings)?"""
    if speed is not None and speed < MIN_JUMP_SPEED:
        return False
    return any(th.min_air <= fl["air"] <= MAX_AIR and fl["mean_g"] <= th.max_mean_air_g and fl["landing_g"] >= th.min_landing_g
               for fl in flights)


def weights(clips) -> list[float]:
    """Passes over the same spot share one unit of weight, so a roller ridden every lap counts once."""
    count: dict[str, int] = {}
    for c in clips:
        count[c["spot"]] = count.get(c["spot"], 0) + 1
    return [1.0 / count[c["spot"]] for c in clips]


def _score(rows, th: Thresholds, w) -> tuple[float, float, float]:
    """rows: [(clip, flights at th.takeoff_g)] → (precision, recall, margin)."""
    g = grid()
    sa, sl, sm = _span(g["min_air"]), _span(g["min_landing_g"]), _span(g["max_mean_air_g"])
    tp = fp = pos = 0.0
    margin = float("inf")
    for (clip, flights), wi in zip(rows, w):
        hit = detected(flights, th, clip.get("speed"))
        if clip["label"] == "jump":
            pos += wi
            if hit:
                tp += wi
        elif hit:
            fp += wi
        for fl in flights:
            if fl["air"] <= MAX_AIR:
                margin = min(margin, abs(fl["air"] - th.min_air) / sa, abs(fl["landing_g"] - th.min_landing_g) / sl,
                             abs(fl["mean_g"] - th.max_mean_air_g) / sm)
    precision = tp / (tp + fp) if tp + fp > 0 else 1.0
    recall = tp / pos if pos > 0 else 0.0
    return precision, recall, margin


def _change(th: Thresholds, ref: Thresholds) -> float:
    """How far th moves from the current preset, in grid-normalised units."""
    g = grid()
    return (abs(th.takeoff_g - ref.takeoff_g) / _span(g["takeoff_g"]) + abs(th.min_air - ref.min_air) / _span(g["min_air"])
            + abs(th.min_landing_g - ref.min_landing_g) / _span(g["min_landing_g"])
            + abs(th.max_mean_air_g - ref.max_mean_air_g) / _span(g["max_mean_air_g"]))


def _search(by_takeoff, clips, w, target, ref: Thresholds, fixed_mean=None) -> Thresholds | None:
    """
    Highest recall meeting the precision target; ties go to the largest margin (furthest from any
    labelled flight, to 0.001 of the grid span), then to the smallest move from the current preset
    [ref], so a threshold the labels say nothing about keeps its value.
    """
    g = grid()
    means = [fixed_mean] if fixed_mean is not None else g["max_mean_air_g"]
    best, best_key = None, None
    for tg in g["takeoff_g"]:
        rows = list(zip(clips, by_takeoff[tg]))
        for ma in g["min_air"]:
            for ml in g["min_landing_g"]:
                for mm in means:
                    th = Thresholds(tg, ma, ml, mm)
                    p, r, m = _score(rows, th, w)
                    if p + 1e-9 < target:
                        continue
                    key = (round(r, 9), round(m, 3), -_change(th, ref))
                    if best_key is None or key > best_key:
                        best, best_key = th, key
    return best


def _fit_all(clips, by_takeoff) -> dict[str, Thresholds] | None:
    """MEDIUM picks jumpMaxMeanAirG (global in MtbConfig); LOW and HIGH are fitted with it fixed."""
    w = weights(clips)
    med = _search(by_takeoff, clips, w, TARGETS["MEDIUM"], preset_thresholds("MEDIUM"))
    if med is None:
        return None
    out = {"MEDIUM": med}
    for name in ("LOW", "HIGH"):
        out[name] = _search(by_takeoff, clips, w, TARGETS[name], preset_thresholds(name), fixed_mean=med.max_mean_air_g) or med
    return out


def _loro(clips, by_takeoff, rides) -> dict:
    """Leave-one-ride-out: fit on the other rides, score the held-out one, summed over folds."""
    acc = {n: [0.0, 0.0, 0.0] for n in TARGETS}   # tp, fp, positives
    for held in rides:
        train = [i for i, c in enumerate(clips) if c["ride"] != held]
        test = [i for i, c in enumerate(clips) if c["ride"] == held]
        proposed = _fit_all([clips[i] for i in train], {tg: [v[i] for i in train] for tg, v in by_takeoff.items()})
        if proposed is None:
            continue
        w = weights([clips[i] for i in test])
        for n, th in proposed.items():
            for i, wi in zip(test, w):
                hit = detected(by_takeoff[th.takeoff_g][i], th, clips[i].get("speed"))
                if clips[i]["label"] == "jump":
                    acc[n][2] += wi
                    acc[n][0] += wi if hit else 0.0
                elif hit:
                    acc[n][1] += wi
    return {n: {"precision": tp / (tp + fp) if tp + fp > 0 else 1.0, "recall": tp / pos if pos > 0 else 0.0}
            for n, (tp, fp, pos) in acc.items()}


def _nearest_takeoff(value: float) -> float:
    return min(grid()["takeoff_g"], key=lambda t: abs(t - value))


def fit(corpus: str, out=print) -> dict | None:
    """Proposes LOW/MEDIUM/HIGH from the corpus and writes fit-result.json; None (and only a report) below the guard."""
    clips = load_corpus(corpus) if os.path.isdir(corpus) else []
    jumps = sum(1 for c in clips if c["label"] == "jump")
    nojumps = len(clips) - jumps
    rides = sorted({c["ride"] for c in clips})
    out(f"Corpus: {jumps} jumps, {nojumps} not-a-jump, {len(rides)} rides")
    by_takeoff = {tg: [clip_flights(corpus, c, tg) for c in clips] for tg in grid()["takeoff_g"]}
    w = weights(clips)
    if clips:
        for name in PRESET_ORDER:
            th = preset_thresholds(name)
            p, r, _ = _score(list(zip(clips, by_takeoff[_nearest_takeoff(th.takeoff_g)])), th, w)
            out(f"  current {name:<6} precision {p:.0%} · recall {r:.0%}")
    if jumps < MIN_JUMPS or nojumps < MIN_NOJUMPS or len(rides) < MIN_RIDES:
        out(f"need ≥ {MIN_JUMPS} jumps, ≥ {MIN_NOJUMPS} not-a-jump and ≥ {MIN_RIDES} rides before proposing presets "
            f"(missing: {max(0, MIN_JUMPS - jumps)} jumps, {max(0, MIN_NOJUMPS - nojumps)} not-a-jump, "
            f"{max(0, MIN_RIDES - len(rides))} rides)")
        return None
    proposed = _fit_all(clips, by_takeoff)
    if proposed is None:
        out("no threshold combination reaches MEDIUM's 95 % precision: label more, or check the not-a-jump clips")
        return None
    validation = _loro(clips, by_takeoff, rides)
    result = {
        "proposed": {n: {"takeoffG": th.takeoff_g, "minAirSec": th.min_air, "minLandingG": th.min_landing_g}
                     for n, th in proposed.items()},
        "jumpMaxMeanAirG": proposed["MEDIUM"].max_mean_air_g,
        "targets": TARGETS,
        "validation": validation,
        "clips": [{"file": c["file"], "label": c["label"], "speed": c.get("speed"), "weight": wi,
                   "verdicts": {n: detected(by_takeoff[th.takeoff_g][i], th, c.get("speed")) for n, th in proposed.items()}}
                  for i, (c, wi) in enumerate(zip(clips, w))],
    }
    with open(os.path.join(corpus, FIT_RESULT), "w") as f:
        json.dump(result, f, indent=1)
    out("\nProposed (leave-one-ride-out precision / recall):")
    for n in PRESET_ORDER:
        th, v = proposed[n], validation[n]
        out(f"  {n:<6} takeoffG {th.takeoff_g:.2f} · minAirSec {th.min_air:.2f} · minLandingG {th.min_landing_g:.2f}"
            f"   precision {v['precision']:.0%} · recall {v['recall']:.0%}")
    out(f"  jumpMaxMeanAirG {proposed['MEDIUM'].max_mean_air_g:.2f}")
    out("\nMtbConfig.kt Sensitivity (and imu.PRESETS):")
    for n in PRESET_ORDER:
        th = proposed[n]
        out(f"    {n}(takeoffG = {th.takeoff_g:.2f}, minAirSec = {th.min_air:.2f}, minLandingG = {th.min_landing_g:.2f}),")
    wrong = [c for c in result["clips"] if c["verdicts"]["MEDIUM"] != (c["label"] == "jump")]
    if wrong:
        out("\nStill wrong at MEDIUM:")
        for c in wrong:
            out(f"  {c['file']}  labelled {c['label']}")
    return result


# --------------------------------------------------------------------------------------------
# Fixture export: the clips nearest each preset's boundary, for JumpFixtureTest (public repo)
# --------------------------------------------------------------------------------------------
def export_fixtures(corpus: str, result: dict, out_dir: str, limit: int = 30) -> list[str]:
    """Copies boundary clips (both sides of each preset's minAirSec) plus clear examples, with per-preset expectations."""
    from .imu import update_manifest
    clips = {c["file"]: c for c in load_corpus(corpus)}
    rows = [{**clips[r["file"]], **r} for r in result["clips"] if r["file"] in clips]
    picked: list[dict] = []

    def take(c):
        if all(c["file"] != p["file"] for p in picked) and len(picked) < limit:
            picked.append(c)

    for th in result["proposed"].values():
        below = sorted((c for c in rows if c["air"] < th["minAirSec"]), key=lambda c: th["minAirSec"] - c["air"])[:3]
        above = sorted((c for c in rows if c["air"] >= th["minAirSec"]), key=lambda c: c["air"] - th["minAirSec"])[:3]
        for pair in zip(below, above):   # alternate sides so a small limit still covers both
            for c in pair:
                take(c)
    for label in ("jump", "nojump"):
        clear = sorted((c for c in rows if c["label"] == label), key=lambda c: -c["air"] if label == "jump" else c["air"])
        if clear:
            take(clear[0])
    os.makedirs(out_dir, exist_ok=True)
    k = len([n for n in os.listdir(out_dir) if n.startswith("real_")])
    entries, written = [], []
    for c in picked:
        k += 1
        name = f"real_{k:03d}_{c['label']}.csv"   # no ride id or take-off time: nothing dates the ride
        with open(os.path.join(corpus, c["file"])) as src, open(os.path.join(out_dir, name), "w") as dst:
            for line in src:
                dst.write(f"# label={c['label']} source=real\n" if line.startswith("#") else line)
        entries.append({"file": name, "expect": c["verdicts"], "source": "real", "airSec": c["air"],
                        "note": f"labelled {c['label']} ({c.get('source', 'file')})"})
        written.append(name)
    if entries:
        written.append(os.path.basename(update_manifest(out_dir, entries)))
    return written
