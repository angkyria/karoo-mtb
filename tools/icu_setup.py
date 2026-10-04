#!/usr/bin/env python3
"""
Sets up MTB Dynamics in intervals.icu through the API instead of by hand: creates (or updates)
every custom stream, activity field, interval field and chart of the setup guide, and finds the
older rides that need reprocessing to get the data. The items come from tools/make_site_guide.py,
the same list the website guide shows.

  export INTERVALS_API_KEY=...                       # intervals.icu → Settings → Developer Settings
  python3 tools/icu_setup.py --dry-run               # show what would be created / updated
  python3 tools/icu_setup.py                         # create / update the custom items
  python3 tools/icu_setup.py --no-items --reprocess 365 --snippet reprocess.js

Items are matched by type and code (charts by name), so re-running only updates what changed.
Colours and other display settings changed in intervals.icu are kept.

intervals.icu only lets its website reprocess files (the API answers 404 to an API key), so
--reprocess lists the rides of the last DAYS days whose FIT file has MTB Dynamics or Flight
Attendant / AXS data. Reprocess them in the activity list (select, Reprocess File, keep intervals),
or paste the --snippet file into the browser console of a logged-in intervals.icu tab.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_site_guide as guide  # noqa: E402

from mtbdyn.icu import RIDE_TYPES, IcuError, IntervalsIcu  # noqa: E402
from mtbdyn.loaders import read_fit_bytes  # noqa: E402

GUIDE_URL = "https://angkyria.github.io/karoo-mtb/intervals-icu.html"

# Units that are labels rather than units get no suffix after the value.
LABEL_UNITS = {"jumps", "corners", "flow", "score", "shifts", "state", "zone"}

# Set when an item is created, left alone on updates (the rider may have changed them in intervals.icu).
DISPLAY_KEYS = {"color", "line_opacity", "area_opacity", "legend", "legend_pos", "no_nulls", "domain_zero", "pos",
                "icon", "gauge", "prefix", "suffix", "text_align", "text_wrap", "example", "width", "link"}

# Developer field names in a FIT file that has data for these items: MTB Dynamics, or the
# Flight Attendant / AXS fields the Karoo writes itself.
FIT_MARKERS = (b"mtb_total_grit", b"mtb_grit", b"front_suspension", b"rear_suspension", b"suspension_effort_zone", b"rear_gear")


def script(path: str) -> str:
    return guide.read_script(path).strip()


def describe(text: str) -> str:
    return (text + " " if text else "") + f"MTB Dynamics for Karoo, see {GUIDE_URL}"


def stream_item(s: guide.Stream) -> dict:
    # The script wins when there is one: it also reads Garmin rides (Grit) or realigns lagged values.
    content = {
        "code": s.code, "short_description": "", "type": "numeric", "units": s.units, "convert": "",
        "number_format": s.number_format, "color": s.color, "line_opacity": 0.7, "area_opacity": 0.05,
        "legend": "", "legend_pos": "topLeft", "no_nulls": False, "domain_zero": False, "pos": False, "link": "",
        "script": script(s.script) if s.script else "",
        "fit_record_field": "" if s.script else (s.fit_field or ""),
        "processes_fit_messages": bool(s.script),
    }
    if s.script and s.fit_field:
        about = f"Script: FIT record field {s.fit_field}, or the Garmin field."
    elif s.fit_field:
        about = f"FIT record field {s.fit_field}. {s.note}".strip()
    else:
        about = s.note
    return {"name": s.name, "type": "ACTIVITY_STREAM", "description": describe(about), "visibility": "PRIVATE",
            "hide_script": False, "content": content}


def _field_content(code: str, units: str, number_format: str, source: str, fit_messages: bool) -> dict:
    return {
        "code": code, "type": "numeric", "units": units, "convert": "", "pace_units": None, "min": None, "max": None,
        "gauge": True, "prefix": "", "number_format": number_format, "suffix": "" if units in LABEL_UNITS else units,
        "icon": "", "color": "#333333", "text_align": "center", "text_wrap": "no", "link": "", "example": 42,
        "options": [], "script": source, "processes_fit_messages": fit_messages,
    }


def activity_field_item(a: guide.ActivityField) -> dict:
    # Scripts rather than the plain session field: they also compute the values for older rides
    # (Flight Attendant / AXS from the Karoo's own records) and read Garmin rides.
    content = {**_field_content(a.code, a.units, a.number_format, script(a.script), True),
               "aggregate": a.aggregate, "fit_session_field": ""}
    return {"name": a.name, "type": "ACTIVITY_FIELD", "description": describe(f"FIT session field {a.session_field}."),
            "visibility": "PRIVATE", "hide_script": False, "content": content}


def interval_field_item(i: guide.IntervalField) -> dict:
    # Interval fields have total / average rows instead of an aggregate, and no session field.
    content = {**_field_content(i.code, i.units, i.number_format, script(i.script), False), "total": True, "average": True}
    return {"name": i.name, "type": "INTERVAL_FIELD", "description": describe(f"Needs the stream {', '.join(i.needs)}."),
            "visibility": "PRIVATE", "hide_script": False, "content": content}


def chart_item(c: guide.Chart) -> dict:
    # The height goes with the script's layout (two-panel charts draw 600 px), so it is not a display setting.
    content = {"link": "", "script": script(c.script), "width": "100%", "height": c.height}
    return {"name": c.name, "type": "ACTIVITY_CHART", "description": describe(c.shows), "visibility": "PRIVATE",
            "hide_script": False, "content": content}


def wanted_items() -> list[dict]:
    """Every item of the guide. Script streams first: intervals.icu computes them first anyway, and
    the guide asks to keep them on top."""
    streams = sorted(guide.STREAMS, key=lambda s: not s.script)
    return ([stream_item(s) for s in streams] + [activity_field_item(a) for a in guide.ACTIVITY_FIELDS]
            + [interval_field_item(i) for i in guide.INTERVAL_FIELDS] + [chart_item(c) for c in guide.CHARTS])


def key_of(item: dict) -> tuple[str, str]:
    content = item.get("content") or {}
    return (item["type"], content["code"]) if content.get("code") else (item["type"], "name:" + item.get("name", ""))


def merged(existing: dict, item: dict) -> dict:
    """The item to PUT: ours, with the display settings of the existing one."""
    content = dict(item["content"])
    for k, v in (existing.get("content") or {}).items():
        if k in DISPLAY_KEYS or k not in content:
            content[k] = v
    return {**item, "visibility": existing.get("visibility", item["visibility"]), "content": content}


def differs(existing: dict, item: dict) -> list[str]:
    changed = [k for k in ("name", "description") if existing.get(k) != item.get(k)]
    old = existing.get("content") or {}
    changed += [k for k, v in item["content"].items() if old.get(k) != v]
    return changed


def plan(existing: list[dict], wanted: list[dict]) -> list[tuple[str, dict, dict | None, list[str]]]:
    """(action, item, existing item, changed keys) with action create / update / ok."""
    by_key = {key_of(e): e for e in existing}
    out = []
    for item in wanted:
        old = by_key.get(key_of(item))
        if old is None:
            out.append(("create", item, None, []))
            continue
        new = merged(old, item)
        changed = differs(old, new)
        out.append(("update" if changed else "ok", new, old, changed))
    return out


def lookalikes(existing: list[dict], wanted: list[dict]) -> list[str]:
    """Items with one of our names but another code, e.g. made by hand with intervals.icu's suggested code."""
    ours = {key_of(w) for w in wanted}
    names = {(w["type"], w["name"]): (w.get("content") or {}).get("code") for w in wanted}
    out = []
    for e in existing:
        code = names.get((e.get("type"), e.get("name")))
        if code and key_of(e) not in ours:
            out.append(f"{e['type']} '{e['name']}' (id {e.get('id')}, code {(e.get('content') or {}).get('code')}): "
                       f"not touched, the setup uses code {code}; delete it if it is a manual copy")
    return out


def apply(client: IntervalsIcu, steps: list, dry_run: bool, log: Callable[[str], None] = print) -> int:
    """Creates / updates the items; returns the number of failures."""
    next_index: dict[str, int] = {}
    for e in client.custom_items() if not dry_run else []:
        next_index[e["type"]] = max(next_index.get(e["type"], 0), e.get("index") or 0)
    failed = 0
    for action, item, old, changed in steps:
        label = f"{item['type']:<15} {key_of(item)[1]:<18} {item['name']}"
        if action == "ok":
            log(f"  ok      {label}")
            continue
        log(f"  {action:<7} {label}" + (f"  ({', '.join(changed)})" if changed else ""))
        if dry_run:
            continue
        try:
            if action == "create":
                next_index[item["type"]] = next_index.get(item["type"], 0) + 1
                client.create_custom_item({**item, "index": next_index[item["type"]]})
            else:
                client.update_custom_item(old["id"], {**item, "id": old["id"], "index": old.get("index")})
        except IcuError as e:
            failed += 1
            log(f"          FAILED: {e}")
    return failed


# --------------------------------------------------------------------------------------------
def has_mtb_data(fit: bytes) -> bool:
    return any(m in fit for m in FIT_MARKERS)


def candidate_rides(client: IntervalsIcu, days: int) -> list[dict]:
    """Rides with a file intervals.icu can re-read (Strava imports have none), oldest first."""
    today = dt.date.today()
    acts = client.activities((today - dt.timedelta(days=days)).isoformat(), (today + dt.timedelta(days=1)).isoformat())
    rides = [a for a in acts if a.get("type") in RIDE_TYPES and a.get("source") != "STRAVA" and not a.get("deleted")]
    return sorted(rides, key=lambda a: a.get("start_date_local") or "")


def rides_with_data(client: IntervalsIcu, days: int, log: Callable[[str], None] = print) -> list[dict]:
    """Rides of the last [days] days whose original file has MTB Dynamics / Flight Attendant / AXS fields."""
    rides = candidate_rides(client, days)
    log(f"{len(rides)} rides in the last {days} days; checking which files have MTB Dynamics / Flight Attendant / AXS data")
    found = []
    for a in rides:
        rid, title = str(a["id"]), f"{(a.get('start_date_local') or '')[:10]} {a.get('name') or ''}".strip()
        try:
            fit = read_fit_bytes(client.call("GET", f"/api/v1/activity/{rid}/file"))
        except IcuError as e:
            log(f"  skip    {rid} {title}: no file ({e.status})")
            continue
        if has_mtb_data(fit):
            found.append(a)
            log(f"  {rid:<12} {title}  https://intervals.icu/activities/{rid}")
    log(f"{len(found)} rides to reprocess: select them in intervals.icu's activity list and choose Reprocess File"
        " (keep intervals), or use --snippet")
    return found


SNIPPET = """// Reprocesses {n} rides on intervals.icu (Actions → Reprocess File, keeping intervals and manual
// custom field values) so they get the MTB Dynamics streams and fields. Written by tools/icu_setup.py.
// Paste into the browser console of a logged-in intervals.icu tab and leave the tab open until "done".
(async () => {{
  const ids = {ids}
  for (const [n, id] of ids.entries()) {{
    const r = await fetch(`/api/activity/${{id}}/reprocess-file`, {{method: 'PUT', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{keepIntervals: true, keepCustomFields: true}})}})
    console.log(`${{n + 1}}/${{ids.length}} ${{id}}: ${{r.ok ? 'ok' : 'HTTP ' + r.status}}`)
    await new Promise(done => setTimeout(done, 600))
  }}
  console.log('done')
}})()
"""


def write_snippet(path: str, rides: list[dict]) -> None:
    with open(path, "w") as f:
        f.write(SNIPPET.format(n=len(rides), ids=json.dumps([str(a["id"]) for a in rides])))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    p.add_argument("--reprocess", metavar="DAYS", type=int, help="list the rides of the last DAYS days that need reprocessing")
    p.add_argument("--snippet", metavar="FILE", help="with --reprocess: write a script that reprocesses them from the browser")
    p.add_argument("--no-items", action="store_true", help="skip creating / updating the custom items")
    p.add_argument("--athlete", default=os.environ.get("INTERVALS_ATHLETE_ID", "0"), help="athlete id (default 0 = you)")
    p.add_argument("--key-file", help="read the API key from this file instead of INTERVALS_API_KEY")
    a = p.parse_args(argv)

    key = os.environ.get("INTERVALS_API_KEY")
    if a.key_file:
        with open(os.path.expanduser(a.key_file)) as f:
            key = f.read().strip()
    if not key:
        p.error("set INTERVALS_API_KEY or --key-file (intervals.icu → Settings → Developer Settings)")
    client = IntervalsIcu(key, a.athlete)
    wanted = wanted_items()

    failed = 0
    if not a.no_items:
        existing = client.custom_items()
        steps = plan(existing, wanted)
        print(f"{'Dry run: ' if a.dry_run else ''}{len(wanted)} items, {len(existing)} custom items on intervals.icu")
        failed += apply(client, steps, a.dry_run)
        for line in lookalikes(existing, wanted):
            print("  note:", line)
    if a.reprocess:
        rides = rides_with_data(client, a.reprocess)
        if a.snippet:
            write_snippet(a.snippet, rides)
            print(f"wrote {a.snippet}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
