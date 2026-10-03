"""Command line interface."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import webbrowser
from typing import Callable

from .history import history, history_text, load_any, ride_paths, trails_text, write_history_csv, write_history_html
from .icu import IntervalsIcu, description_block, merged_description, parse_field_map, summary_value
from .imu import _day_start, export_snippets, imu_report, labels_for
from .loaders import _num, load_fit, load_karoo_dir, read_fit_bytes, rescore
from .model import Ride
from .report import Units, report_text, write_csv, write_html
from .summary import summarize


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MTB Dynamics analyser (Karoo / Garmin FIT, Karoo ride folders, intervals.icu)")
    p.add_argument("fit", nargs="?", help="FIT file (.fit, .fit.gz or .zip)")
    p.add_argument("--karoo-dir", help="ride folder pulled from the Karoo (samples.csv, events.jsonl)")
    p.add_argument("--imu", nargs="?", const="auto", metavar="IMU_CSV_GZ",
                   help="inspect a raw sensor log (default: imu.csv.gz in --karoo-dir) with every jump sensitivity")
    p.add_argument("--labels", help="with --imu: CSV of 'HH:MM:SS,jump|nojump' (UTC) to rate each jump sensitivity; "
                   "the Karoo's 'Mark moment' presses count as jump labels too")
    p.add_argument("--export-snippets", metavar="DIR",
                   help="with --imu: write each labelled flight (± 3 s of raw IMU, no GPS) as a test fixture, e.g. app/src/test/resources/imu")
    p.add_argument("--icu", metavar="ID|latest", help="analyse an intervals.icu activity (needs INTERVALS_API_KEY)")
    p.add_argument("--icu-athlete", default=os.environ.get("INTERVALS_ATHLETE_ID", "0"), help="athlete id (default 0 = you)")
    p.add_argument("--icu-key", default=os.environ.get("INTERVALS_API_KEY"), help="intervals.icu API key")
    p.add_argument("--icu-update", action="store_true", help="write the MTB summary into the activity description")
    p.add_argument("--icu-fields", help="also set custom activity fields, e.g. 'MtbGrit=grit.total_k,MtbFlow=flow.score'")
    p.add_argument("--save-fit", help="keep the FIT file downloaded from intervals.icu")
    p.add_argument("--html", help="write an interactive HTML report")
    p.add_argument("--open", action="store_true", help="open the HTML report in the browser")
    p.add_argument("--csv", metavar="PREFIX", help="write per-second, segment, lap, jump and corner CSV files")
    p.add_argument("--json", help="write the full analysis as JSON")
    p.add_argument("--segment-elev", type=float, default=15.0, help="elevation change (m) that splits segments")
    p.add_argument("--rescore", action="store_true",
                   help="recompute Grit/Flow with the current formulas (rides recorded by older app versions)")
    p.add_argument("--imperial", action="store_true", help="miles / feet")
    p.add_argument("--weight", type=float, help="rider weight in kg for W/kg (default: intervals.icu athlete weight)")
    p.add_argument("--quiet", action="store_true", help="no console report")
    p.add_argument("--history", nargs="+", metavar="PATH",
                   help="report across rides (service hours, shifts, batteries): FIT files, Karoo ride folders "
                        "or folders containing them, e.g. a pulled rides/ folder")
    p.add_argument("--icu-history", type=int, metavar="DAYS", help="the same across the rides of the last DAYS on intervals.icu")
    p.add_argument("--service-json", help="service.json pulled from the Karoo: service status from the Karoo's tracker")
    p.add_argument("--trails-json", help="trails.json pulled from the Karoo: trails with runs and personal bests")
    a = p.parse_args(argv)
    units = Units(a.imperial)

    if a.trails_json:
        print(trails_text(a.trails_json, units))
        if not (a.history or a.icu_history or a.fit or a.karoo_dir or a.icu):
            return 0

    if a.history or a.icu_history:
        sources: list[tuple[str, Callable[[], Ride]]] = [(path, (lambda path=path: load_any(path))) for path in ride_paths(a.history or [])]
        if a.icu_history:
            if not a.icu_key:
                sys.exit("set INTERVALS_API_KEY or --icu-key (intervals.icu → Settings → Developer Settings)")
            client = IntervalsIcu(a.icu_key, a.icu_athlete)
            for rid in client.ride_ids(a.icu_history):
                sources.append((f"intervals.icu {rid}",
                                lambda rid=rid: load_fit(read_fit_bytes(client.original_file(rid)), f"intervals.icu {rid}")))
        if not sources:
            p.error("no FIT files or Karoo ride folders found")
        h = history(sources, a.segment_elev, a.service_json, a.quiet)
        if not a.quiet:
            print(history_text(h, units))
        if a.json:
            with open(a.json, "w") as f:
                json.dump(h, f, indent=1, default=str)
            print(f"wrote {a.json}")
        if a.csv:
            write_history_csv(h, a.csv + "_history.csv")
            print(f"wrote {a.csv}_history.csv")
        if a.html:
            write_history_html(h, a.html)
            print(f"wrote {a.html}")
            if a.open:
                webbrowser.open("file://" + os.path.abspath(a.html))
        return 0

    icu = None
    activity_id = None
    if a.icu:
        if not a.icu_key:
            sys.exit("set INTERVALS_API_KEY or --icu-key (intervals.icu → Settings → Developer Settings)")
        icu = IntervalsIcu(a.icu_key, a.icu_athlete)
        activity_id = icu.latest_ride_id() if a.icu == "latest" else a.icu
        raw = read_fit_bytes(icu.original_file(activity_id))
        if a.save_fit:
            with open(a.save_fit, "wb") as f:
                f.write(raw)
        ride = load_fit(raw, f"intervals.icu {activity_id}")
    elif a.karoo_dir:
        ride = load_karoo_dir(a.karoo_dir)
    elif a.fit:
        with open(a.fit, "rb") as f:
            ride = load_fit(f.read(), os.path.basename(a.fit))
    else:
        p.error("give a FIT file, --karoo-dir or --icu")

    if a.weight:
        ride.weight = a.weight
    elif icu and activity_id and not ride.weight:
        ride.weight = _num(icu.activity(activity_id).get("icu_weight"))
    if a.rescore:
        rescore(ride)
    summary = summarize(ride, a.segment_elev)
    if not a.quiet:
        print(report_text(summary, units))
    if a.imu:
        imu_path = a.imu if a.imu != "auto" else os.path.join(a.karoo_dir or "", "imu.csv.gz")
        if os.path.exists(imu_path):
            print("\n" + imu_report(ride, imu_path, a.labels))
            if a.export_snippets:
                labels = labels_for(ride, a.labels, _day_start(ride.start))
                if not labels:
                    print("no labels: press 'Mark moment' after jumps on the Karoo, or pass --labels")
                prefix = dt.datetime.fromtimestamp(ride.start, dt.timezone.utc).strftime("%Y%m%d_%H%M_")
                for name in export_snippets(imu_path, labels, a.export_snippets, prefix):
                    print(f"wrote {os.path.join(a.export_snippets, name)}")
        else:
            print(f"\nno raw sensor log at {imu_path} (enable 'Debug: save raw sensor data' on the Karoo)")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(summary, f, indent=1, default=str)
        print(f"wrote {a.json}")
    if a.csv:
        for path in write_csv(ride, summary, a.csv):
            print(f"wrote {path}")
    if a.html:
        write_html(ride, summary, a.html, units)
        print(f"wrote {a.html}")
        if a.open:
            webbrowser.open("file://" + os.path.abspath(a.html))
    if icu and (a.icu_update or a.icu_fields):
        act = icu.activity(activity_id)
        body: dict = {}
        if a.icu_update:
            body["description"] = merged_description(act.get("description"), description_block(summary, units))
        for code, path in parse_field_map(a.icu_fields).items():
            value = summary_value(summary, path)
            if value is not None:
                body[code] = round(value, 3) if isinstance(value, float) else value
        icu.update(activity_id, body)
        print(f"updated intervals.icu activity {activity_id}: {', '.join(body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
