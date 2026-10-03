"""
MTB Dynamics analyser for Karoo (and Garmin) rides.

Inputs
  * a FIT file recorded on a Karoo with the MTB Dynamics extension (mtb_* developer fields)
  * a FIT file from a Garmin Edge with MTB Dynamics (native grit/flow fields + jump messages)
  * any other cycling FIT file (Grit/Flow are then estimated from GPS + altitude, no jumps)
  * a ride folder pulled from the Karoo (samples.csv + events.jsonl), see README
  * an intervals.icu activity (downloads the original FIT through the API)

Outputs
  * a console report, an interactive HTML report (map + charts), CSV / JSON exports
  * optionally: the MTB summary written back into the intervals.icu activity

Examples
  python3 tools/mtb_analyze.py ride.fit --html report.html
  python3 tools/mtb_analyze.py --karoo-dir rides/1790000000000 --csv out/ride
  INTERVALS_API_KEY=... python3 tools/mtb_analyze.py --icu latest --html report.html --icu-update

Requires: pip install garmin-fit-sdk   (only for FIT input)
The formulas mirror app/src/main/kotlin/.../engine/Scoring.kt; testdata/scoring_vectors.json keeps both in sync.

Modules
  scoring   formulas and constants          model     Sample / Jump / Ride
  loaders   FIT files, Karoo ride folders   analysis  Grit / Flow / corners / segments
  sram      Flight Attendant, AXS, power    summary   the ride summary
  report    console, CSV, HTML              imu       raw sensor log replay
  history   across rides, service           icu       intervals.icu client
  insights  laps, braking spots, corner sides
  cli       command line (tools/mtb_analyze.py)
"""
from __future__ import annotations

from . import analysis, cli, history, icu, imu, insights, loaders, model, report, scoring, sram, summary  # noqa: F401

__all__: list[str] = []
for _module in (scoring, model, loaders, analysis, insights, sram, summary, report, imu, history, icu, cli):
    for _name, _value in vars(_module).items():
        if not _name.startswith("__") and not isinstance(_value, type(_module)):
            globals()[_name] = _value
            __all__.append(_name)
del _module, _name, _value
