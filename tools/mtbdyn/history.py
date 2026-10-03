"""Across rides: service hours, shifts, batteries (mirrors ServiceTracker.kt)."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
from typing import Callable

from .loaders import load_fit, load_karoo_dir
from .model import Ride
from .report import Units, _r, hms
from .summary import summarize

# --------------------------------------------------------------------------------------------
# Across rides: service hours, shifts, batteries (mirrors ServiceTracker.kt on the Karoo)
# --------------------------------------------------------------------------------------------
SERVICE_ROUGH_G = 0.6
# id, name, basis, default interval: RockShox / SRAM service guides for SID / SIDLuxe and an Eagle chain.
# Check the manual of your parts.
SERVICE_ITEMS = [
    ("fork_lowers", "Fork lower-leg service", "fork_h", 50.0),
    ("fork_damper", "Fork damper & spring service", "fork_h", 200.0),
    ("shock_aircan", "Shock air-can service", "shock_h", 50.0),
    ("shock_damper", "Shock damper service", "shock_h", 200.0),
    ("chain", "Chain wear check", "drivetrain_km", 1500.0),
]
SERVICE_JSON_TOTALS = {"fork_h": "forkHours", "shock_h": "shockHours", "drivetrain_km": "drivetrainKm"}
BATTERY_LOW_PCT = 15.0   # BatteryStatus.fromPercentage: 15 % and below is critical
BATTERY_MIN_READINGS = 3  # since the last charge, before a drain rate is shown
BATTERY_MIN_HOURS = 1.0   # of riding in between


def trails_text(path: str, u: Units) -> str:
    """The Karoo's trail library (trails.json): runs, best time and smoothest Flow per trail."""
    with open(path) as f:
        state = json.load(f)
    trails = sorted(state.get("trails", []), key=lambda t: -len(t.get("runs", [])))
    lines = [f"Trails ({len(trails)}), most ridden first"]
    for t in trails:
        runs = t.get("runs", [])
        if not runs:
            continue
        best = min(runs, key=lambda r: r["timeSec"])
        when = dt.datetime.fromtimestamp(best["rideStartWallMs"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        smooth = min(r["flowScore"] for r in runs)
        last = runs[-1]
        lines.append(f"  {t['name']:<20} {u.dist(t['distanceM']):>8} · −{u.elev(t['dropM'])} · {len(runs):>3} runs · "
                     f"best {hms(best['timeSec'])} ({when}) · last {hms(last['timeSec'])} · smoothest Flow {smooth:.1f}")
    return "\n".join(lines)


def ride_usage(ride: Ride, s: dict) -> dict:
    """What one ride adds to the service totals (same rules as ServiceTracker.kt)."""
    fork = [x for x in ride.samples if x.moving and x.fa_front is not None]
    shock = [x for x in ride.samples if x.moving and x.fa_rear is not None]
    axs = [x for x in ride.samples if x.moving and x.rear_teeth]
    cogs: dict[int, float] = {}
    for x in axs:
        cogs[x.rear_teeth] = cogs.get(x.rear_teeth, 0.0) + x.dt / 3600.0
    sram = s.get("sram") or {}
    su, dr, pw = sram.get("suspension"), sram.get("drivetrain"), sram.get("power")
    climb = ((pw or {}).get("terrain") or {}).get("CLIMB") or {}
    descent = ((su or {}).get("by_terrain") or {}).get("DESCENT") or {}
    return {
        "start": s["start"], "source": s["source"], "moving_h": s["moving_s"] / 3600.0, "distance_km": s["distance_m"] / 1000.0,
        "on_bike": bool(fork or axs),
        "fork_h": sum(x.dt for x in fork) / 3600.0,
        "shock_h": sum(x.dt for x in shock) / 3600.0,
        "rough_h": sum(x.dt for x in fork if (x.rough or 0.0) >= SERVICE_ROUGH_G) / 3600.0,
        "fa_changes": su["changes"] if su else 0,
        "fa_open_desc": descent.get("Open"),
        "locked_rough_s": su["locked_rough_s"] if su else None,
        "shifts": dr["shifts"] if dr else 0,
        "shifts_km": dr["shifts_per_km"] if dr else None,
        "drivetrain_km": sum(x.d_dist for x in axs) / 1000.0,
        "cog_h": cogs,
        "climb_w": climb.get("avg_w"), "climb_wkg": climb.get("w_kg"),
        "batteries": [{"kind": b.get("kind"), "pct": b.get("battery_pct"), "status": b.get("battery_status")}
                      for b in sram.get("batteries") or [] if b.get("kind")],
    }


def ride_paths(paths: list[str]) -> list[str]:
    """FIT files and Karoo ride folders, also inside the given folders (e.g. a pulled rides/ folder)."""
    found = []
    for path in paths:
        if os.path.isfile(path):
            found.append(path)
        elif os.path.exists(os.path.join(path, "samples.csv")):
            found.append(path)
        elif os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                sub = os.path.join(path, name)
                if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "samples.csv")):
                    found.append(sub)
                elif name.lower().endswith((".fit", ".fit.gz", ".zip")):
                    found.append(sub)
    return found


def load_any(path: str) -> Ride:
    if os.path.isdir(path):
        return load_karoo_dir(path)
    with open(path, "rb") as f:
        return load_fit(f.read(), os.path.basename(path))


def dedupe_rides(rows: list[dict]) -> tuple[list[dict], int]:
    """The same ride as FIT file and as Karoo ride folder counts once: keep the version with more bike data."""
    def ts(r):
        return dt.datetime.fromisoformat(r["start"]).timestamp()

    def richness(r):
        return (r["on_bike"], sum(1 for b in r["batteries"] if b["pct"] is not None), r["fork_h"] + r["drivetrain_km"])

    out: list[dict] = []
    skipped = 0
    for r in sorted(rows, key=ts):
        prev = out[-1] if out else None
        if prev and abs(ts(r) - ts(prev)) < 300 and abs(r["distance_km"] - prev["distance_km"]) <= max(0.3, 0.1 * prev["distance_km"]):
            if richness(r) > richness(prev):
                out[-1] = r
            skipped += 1
            continue
        out.append(r)
    return out, skipped


def battery_trends(rows: list[dict]) -> list[dict]:
    """Battery level per component over the rides, with the drain per ride and per riding hour."""
    series: dict[str, list[tuple[dict, dict]]] = {}
    for r in rows:
        for b in r["batteries"]:
            series.setdefault(b["kind"], []).append((r, b))
    out = []
    for kind, points in series.items():
        pct = [(r, b["pct"]) for r, b in points if b["pct"] is not None]
        trend = {"kind": kind, "points": [{"start": r["start"], "pct": b["pct"], "status": b["status"]} for r, b in points],
                 "last_status": points[-1][1]["status"], "last_pct": points[-1][1]["pct"]}
        # Drain since the last charge (the level went up by more than the reporting noise).
        since = pct
        for i in range(len(pct) - 1, 0, -1):
            if pct[i][1] > pct[i - 1][1] + 2:
                since = pct[i:]
                break
        # A level is reported at the end of a ride: the drop happens during the following rides.
        hours = sum(r["moving_h"] for r, _ in since[1:])
        if len(since) >= BATTERY_MIN_READINGS and hours >= BATTERY_MIN_HOURS:
            drop = since[0][1] - since[-1][1]
            trend["per_ride"] = drop / (len(since) - 1)
            trend["per_hour"] = drop / hours
            trend["since_charge"] = since[0][0]["start"]
            if drop > 0:
                trend["rides_left"] = max(0.0, (since[-1][1] - BATTERY_LOW_PCT) / trend["per_ride"])
        out.append(trend)
    return out


def service_status(totals: dict, state: dict | None = None) -> list[dict]:
    """Usage per service item: from the Karoo's service.json when given, else the totals of these rides."""
    marks = (state or {}).get("marks") or {}
    intervals = (state or {}).get("intervals") or {}
    json_totals = (state or {}).get("totals") or {}
    out = []
    for item, name, basis, default in SERVICE_ITEMS:
        total = json_totals.get(SERVICE_JSON_TOTALS[basis], 0.0) if state else totals[basis]
        used = max(0.0, total - (marks.get(item) or {}).get("atValue", 0.0))
        interval = intervals.get(item, default)
        out.append({"id": item, "name": name, "basis": basis, "used": used, "interval": interval,
                    "progress": used / interval if interval else 0.0,
                    "last_service_ms": (marks.get(item) or {}).get("wallMs") or None})
    return out


def history(sources: list[tuple[str, Callable[[], Ride]]], min_elev: float = 15.0,
            service_json: str | None = None, quiet: bool = False) -> dict:
    """[sources]: (name, loader) per ride, loaded one at a time."""
    rows = []
    for name, load in sources:
        try:
            ride = load()
            if not ride.samples:
                continue
            rows.append(ride_usage(ride, summarize(ride, min_elev)))
            if not quiet:
                print(f"  {name}", file=sys.stderr)
        except (Exception, SystemExit) as e:  # one broken file must not stop the report
            if not quiet:
                print(f"skipped {name}: {e}", file=sys.stderr)
    rows, duplicates = dedupe_rides(rows)
    bike = [r for r in rows if r["on_bike"]]
    cogs: dict[int, float] = {}
    for r in bike:
        for t, h in r["cog_h"].items():
            cogs[t] = cogs.get(t, 0.0) + h
    totals = {
        "rides": len(rows), "bike_rides": len(bike),
        "fork_h": sum(r["fork_h"] for r in bike), "shock_h": sum(r["shock_h"] for r in bike),
        "rough_h": sum(r["rough_h"] for r in bike), "fa_changes": sum(r["fa_changes"] for r in bike),
        "shifts": sum(r["shifts"] for r in bike), "drivetrain_km": sum(r["drivetrain_km"] for r in bike),
        "cog_h": dict(sorted(cogs.items())),
    }
    state = None
    if service_json:
        with open(service_json) as f:
            state = json.load(f)
    totals["duplicates_skipped"] = duplicates
    return {"rides": rows, "totals": totals, "service": service_status(totals, state),
            "service_source": "Karoo service.json" if state else "these rides",
            "batteries": battery_trends(rows)}


def history_text(h: dict, u: Units) -> str:
    rows, t = h["rides"], h["totals"]
    lines = [f"MTB Dynamics history — {t['rides']} rides, {t['bike_rides']} with Flight Attendant / AXS data", ""]
    lines.append(f"{'date':<11} {'dist':>8} {'moving':>7} {'fork h':>6} {'rough':>6} {'FA chg':>6} {'open↓':>6} "
                 f"{'shifts':>6} {'/km':>5} {'climb W':>8}")
    def opt(v, f, suffix=""):
        return format(v, f) + suffix if v is not None else "–"

    for r in rows:
        lines.append(f"{r['start'][:10]:<11} {u.dist(r['distance_km'] * 1000):>8} {hms(r['moving_h'] * 3600):>7} "
                     f"{r['fork_h']:>6.1f} {r['rough_h']:>6.1f} {r['fa_changes']:>6} {opt(r['fa_open_desc'], '.0f', '%'):>6} "
                     f"{r['shifts']:>6} {opt(r['shifts_km'], '.1f'):>5} {opt(r['climb_w'], '.0f', ' W'):>8}")
    if t["duplicates_skipped"]:
        lines.append(f"({t['duplicates_skipped']} duplicate{'s' if t['duplicates_skipped'] > 1 else ''} skipped: "
                     f"the same ride as FIT file and Karoo ride folder)")
    lines.append("")
    lines.append(f"Totals on this bike: fork {t['fork_h']:.1f} h ({t['rough_h']:.1f} h rough) · shock {t['shock_h']:.1f} h · "
                 f"{t['fa_changes']:,} Flight Attendant changes · {t['shifts']:,} shifts · drivetrain {u.dist(t['drivetrain_km'] * 1000)}")
    if t["cog_h"]:
        top = sorted(t["cog_h"].items(), key=lambda x: -x[1])[:6]
        lines.append("Most used cogs: " + ", ".join(f"{teeth}T {hours:.1f} h" for teeth, hours in top))
    lines.append("")
    lines.append(f"Service (usage from {h['service_source']}; default intervals: check the manual of your parts)")
    for sv in h["service"]:
        unit = "km" if sv["basis"] == "drivetrain_km" else "h"
        used, interval = sv["used"], sv["interval"]
        if unit == "km" and u.imperial:
            used, interval, unit = used / 1.609344, interval / 1.609344, "mi"
        flag = "DUE " if sv["progress"] >= 1 else "soon" if sv["progress"] >= 0.9 else "    "
        lines.append(f"  {flag} {sv['name']:<30} {used:7.1f} / {interval:.0f} {unit}  ({100 * sv['progress']:.0f}%)")
    if h["batteries"]:
        lines.append("")
        lines.append("Batteries")
        for b in h["batteries"]:
            levels = [f"{p['pct']:.0f}%" if p["pct"] is not None else (p["status"] or "?").lower() for p in b["points"]]
            shown = levels if len(levels) <= 8 else levels[:3] + ["…"] + levels[-4:]
            line = f"  {b['kind']}: " + " → ".join(shown)
            if b.get("per_ride"):
                line += f"  (−{b['per_ride']:.1f}%/ride"
                line += f", −{b['per_hour']:.1f}%/h" if b.get("per_hour") else ""
                line += " since the last charge)"
            if b.get("rides_left") is not None:
                line += f"  ~{b['rides_left']:.0f} rides until {BATTERY_LOW_PCT:.0f}%"
            lines.append(line)
    return "\n".join(lines)


def write_history_csv(h: dict, path: str) -> None:
    keys = ["start", "source", "distance_km", "moving_h", "fork_h", "shock_h", "rough_h", "fa_changes", "fa_open_desc",
            "locked_rough_s", "shifts", "shifts_km", "drivetrain_km", "climb_w", "climb_wkg"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys + ["batteries"])
        for r in h["rides"]:
            w.writerow([_r(r[k]) if isinstance(r[k], float) else r[k] for k in keys] +
                       ["; ".join(f"{b['kind']} {b['pct'] if b['pct'] is not None else b['status']}" for b in r["batteries"])])


HISTORY_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>MTB Dynamics history</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>:root{--bg:#fff;--fg:#1b1b1b;--muted:#5f6b70;--accent:#ff6d00;--card:#f1f4f5}
@media (prefers-color-scheme:dark){:root{--bg:#121416;--fg:#e8eaeb;--muted:#9fb3bd;--card:#1d2124}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:16px}h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:22px 0 6px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.card{background:var(--card);border-radius:10px;padding:10px 12px}.card b{display:block;font-size:20px}
.bar{height:8px;border-radius:4px;background:#0002;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--accent)}
.due i{background:#c62828}.chart{height:340px}</style></head><body><main>
<h1>MTB Dynamics history</h1><p class="muted" id="sub"></p>
<h2>Service</h2><div class="grid" id="service"></div>
<h2>Suspension &amp; drivetrain hours</h2><div class="chart" id="hours"></div>
<h2>Batteries</h2><div class="chart" id="bat"></div>
<h2>Per ride</h2><div class="chart" id="rides"></div>
</main><script>
const H = __DATA__;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const base = {paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)', font:{color: dark ? '#e8eaeb' : '#1b1b1b'},
  margin:{l:50,r:50,t:30,b:80}, legend:{orientation:'h', x:0, y:1.12}};
const t = H.totals;
document.getElementById('sub').textContent = `${t.rides} rides, ${t.bike_rides} with Flight Attendant / AXS data · ` +
  `fork ${t.fork_h.toFixed(1)} h (${t.rough_h.toFixed(1)} h rough) · ${t.shifts.toLocaleString()} shifts · usage from ${H.service_source}`;
document.getElementById('service').innerHTML = H.service.map(s => {
  const unit = s.basis === 'drivetrain_km' ? 'km' : 'h', pct = Math.min(100, 100 * s.progress);
  return `<div class="card ${s.progress >= 1 ? 'due' : ''}">${s.name}<b>${s.used.toFixed(1)} / ${s.interval} ${unit}</b>` +
    `<div class="bar"><i style="width:${pct}%"></i></div></div>`;
}).join('');
// One category per ride (several rides a day must not stack).
const label = r => r.start.slice(0, 16).replace('T', ' ');
const bike = H.rides.filter(r => r.on_bike), x = bike.map(label);
const cat = {type: 'category', tickangle: -30};
let fork = 0, rough = 0, km = 0;
const cumFork = bike.map(r => fork += r.fork_h), cumRough = bike.map(r => rough += r.rough_h), cumKm = bike.map(r => km += r.drivetrain_km);
Plotly.newPlot('hours', [
  {x, y: cumFork, name: 'fork hours', mode: 'lines+markers', line: {color: '#ff6d00'}},
  {x, y: cumRough, name: 'of it rough', mode: 'lines', line: {color: '#c62828', dash: 'dot'}},
  {x, y: cumKm, name: 'drivetrain km', mode: 'lines', yaxis: 'y2', line: {color: '#1565c0'}},
], {...base, xaxis: cat, yaxis: {title: 'h', rangemode: 'tozero'}, yaxis2: {title: 'km', overlaying: 'y', side: 'right', rangemode: 'tozero'},
  // Service intervals (h) once the hours get near them.
  shapes: [...new Set(H.service.filter(s => s.basis !== 'drivetrain_km').map(s => s.interval))].filter(v => fork >= 0.4 * v)
    .map(v => ({type: 'line', xref: 'paper', x0: 0, x1: 1, y0: v, y1: v, line: {color: '#9fb3bd', dash: 'dash', width: 1}}))},
  {displayModeBar: false, responsive: true});
const bats = H.batteries.map(b => ({x: b.points.map(label), y: b.points.map(p => p.pct), name: b.kind, mode: 'lines+markers'}))
  .filter(tr => tr.y.some(v => v !== null));
const allX = [...new Set(H.batteries.flatMap(b => b.points.map(label)))].sort();
if (bats.length) Plotly.newPlot('bat', bats, {...base, xaxis: {...cat, categoryorder: 'array', categoryarray: allX},
  yaxis: {title: '%', range: [0, 105]}}, {displayModeBar: false, responsive: true});
else document.getElementById('bat').outerHTML = '<p class="muted">No battery levels in these rides (the Karoo writes them into the FIT file).</p>';
Plotly.newPlot('rides', [
  {x, y: bike.map(r => r.fa_open_desc), name: 'FA open on descents %', type: 'bar', marker: {color: '#ff6d00'}},
  {x, y: bike.map(r => r.shifts_km), name: 'shifts / km', mode: 'lines+markers', yaxis: 'y2', line: {color: '#1565c0'}},
], {...base, xaxis: cat, yaxis: {title: '%', range: [0, 100]}, yaxis2: {title: '/km', overlaying: 'y', side: 'right', rangemode: 'tozero'}},
  {displayModeBar: false, responsive: true});
</script></body></html>"""


def write_history_html(h: dict, path: str) -> None:
    with open(path, "w") as f:
        f.write(HISTORY_HTML.replace("__DATA__", json.dumps(h, default=str).replace("</", "<\\/")))
