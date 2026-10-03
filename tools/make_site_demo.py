#!/usr/bin/env python3
"""
Rebuilds the demo reports of the project website (docs/demo/) from synthetic rides only:

  docs/demo/report.html             analysis report of one synthetic 40-minute ride (Flight Attendant, AXS, power)
  docs/demo/history.html            history across eight synthetic rides (service hours, battery drain and a recharge)
  docs/sample/mtb-dynamics-sample.fit   that ride as a FIT file, to try the intervals.icu setup without riding

  python3 tools/make_site_demo.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import make_sample_fit  # noqa: E402
import mtb_analyze as mtb  # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "docs", "demo")
SAMPLE = os.path.join(os.path.dirname(HERE), "docs", "sample", "mtb-dynamics-sample.fit")
FIRST_RIDE = dt.datetime(2026, 9, 6, 8, 30, tzinfo=dt.timezone.utc)
# Flight Attendant battery per ride: drains, gets charged after the fifth ride.
BATTERY = [95, 88, 80, 73, 66, 100, 93, 86]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rides = []
        for i, battery in enumerate(BATTERY):
            start = FIRST_RIDE + dt.timedelta(days=3 * i, hours=i % 3)
            path = os.path.join(tmp, f"ride-{i + 1}.fit")
            make_sample_fit.build(path, "karoo", seed=11 + i, start_unix=int(start.timestamp()), fa_battery=battery)
            rides.append(path)

        with open(rides[-1], "rb") as f:
            ride = mtb.load_fit(f.read(), "synthetic demo ride")
        ride.weight = 75.0
        mtb.write_html(ride, mtb.summarize(ride), os.path.join(OUT, "report.html"), mtb.Units())

        sources = [(p, (lambda p=p: mtb.load_any(p))) for p in rides]
        h = mtb.history(sources, quiet=True)
        for r in h["rides"]:
            r["source"] = "synthetic"
        mtb.write_history_html(h, os.path.join(OUT, "history.html"))
        os.makedirs(os.path.dirname(SAMPLE), exist_ok=True)
        with open(rides[-1], "rb") as src, open(SAMPLE, "wb") as dst:
            dst.write(src.read())
    print(f"wrote {OUT}/report.html, {OUT}/history.html and {SAMPLE}")


if __name__ == "__main__":
    main()
