"""Jump ground truth: labels.csv in the ride folder, label precedence, review candidates and spots."""
from __future__ import annotations

import os

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
