#!/usr/bin/env python3
"""
Builds docs/intervals-icu.html, the step-by-step intervals.icu setup guide of the website, with
every script from intervals-icu/ embedded (copy buttons). The items below are the single source of
the names, codes and units shown in the guide.

  python3 tools/make_site_guide.py           # write the page
  python3 tools/make_site_guide.py --check   # exit 1 if the page is out of date (CI)
"""
from __future__ import annotations

import html
import os
import sys
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "intervals-icu")
OUT = os.path.join(ROOT, "docs", "intervals-icu.html")
REPO = "https://github.com/angkyria/karoo-mtb"
FORUM = {
    "streams": "https://forum.intervals.icu/t/custom-activity-streams-with-javascript/46416",
    "fields": "https://forum.intervals.icu/t/computed-activity-fields/25673",
    "intervals": "https://forum.intervals.icu/t/custom-interval-fields/25942",
    "charts": "https://forum.intervals.icu/t/custom-activity-charts/28627",
}


@dataclass
class Stream:
    name: str
    code: str
    units: str
    fit_field: str | None = None      # FIT record field to pick (no script)
    script: str | None = None         # script path, "Processes fit file messages"
    note: str = ""
    quick: bool = False
    bike: bool = False


@dataclass
class ActivityField:
    name: str
    code: str
    units: str
    session_field: str
    script: str
    quick: bool = False
    bike: bool = False


@dataclass
class IntervalField:
    name: str
    code: str
    units: str
    script: str
    needs: list[str] = field(default_factory=list)
    bike: bool = False


@dataclass
class Chart:
    name: str
    script: str
    needs: list[str]
    shows: str
    quick: bool = False
    bike: bool = False


STREAMS = [
    Stream("MTB Grit", "mtb_grit", "grit", fit_field="mtb_grit", script="streams/mtb_grit.js", quick=True,
           note="Pick the record field, or use the script to include Garmin rides too."),
    Stream("MTB Flow", "mtb_flow", "m", script="streams/mtb_flow.js", quick=True,
           note="Script: moves the values back by the 3 s the Karoo writes them late."),
    Stream("MTB Braking", "mtb_brake", "m/s2", script="streams/mtb_brake.js", note="Script: realigned like Flow."),
    Stream("MTB Roughness", "mtb_rough", "g", fit_field="mtb_rough"),
    Stream("MTB Corner G", "mtb_lat_g", "g", fit_field="mtb_lat_g"),
    Stream("MTB Jump Airtime", "mtb_jump_air", "s", fit_field="mtb_jump_air", quick=True),
    Stream("MTB Jump Distance", "mtb_jump_dist", "m", fit_field="mtb_jump_dist"),
    Stream("MTB Jump Height", "mtb_jump_height", "m", fit_field="mtb_jump_height"),
    Stream("FA Fork", "fa_front", "state", fit_field="front_suspension", bike=True,
           note="Recorded by the Karoo itself: 0 Open, 1 Pedal, 2 Lock."),
    Stream("FA Shock", "fa_rear", "state", fit_field="rear_suspension", bike=True),
    Stream("FA Effort Zone", "fa_effort", "zone", fit_field="suspension_effort_zone", bike=True),
    Stream("Rear Cog", "rear_cog", "T", script="streams/rear_cog.js", bike=True,
           note="Script: turns the AXS shift events into the cog in use."),
]

ACTIVITY_FIELDS = [
    ActivityField("MTB Grit", "MtbGrit", "kGrit", "mtb_total_grit", "activity-fields/mtb_grit.js", quick=True),
    ActivityField("MTB Flow", "MtbFlow", "flow", "mtb_flow_score", "activity-fields/mtb_flow.js", quick=True),
    ActivityField("MTB Jumps", "MtbJumps", "jumps", "mtb_jumps", "activity-fields/mtb_jumps.js", quick=True),
    ActivityField("MTB Max Airtime", "MtbMaxAir", "s", "mtb_max_air", "activity-fields/mtb_max_air.js"),
    ActivityField("MTB Total Airtime", "MtbTotalAir", "s", "mtb_total_air", "activity-fields/mtb_total_air.js"),
    ActivityField("MTB Score", "MtbScore", "score", "mtb_score", "activity-fields/mtb_score.js"),
    ActivityField("MTB Descent Braking", "MtbDescentBraking", "%", "mtb_descent_braking", "activity-fields/mtb_descent_braking.js"),
    ActivityField("MTB Corners", "MtbCorners", "corners", "mtb_corners", "activity-fields/mtb_corners.js"),
    ActivityField("MTB Max Corner G", "MtbMaxCornerG", "g", "mtb_max_lat_g", "activity-fields/mtb_max_corner_g.js"),
    ActivityField("FA Open on descents", "MtbFaOpenDesc", "%", "mtb_fa_open_desc", "activity-fields/mtb_fa_open_desc.js", bike=True),
    ActivityField("FA locked on rough ground", "MtbFaLockRough", "s", "mtb_fa_lock_rough", "activity-fields/mtb_fa_lock_rough.js", bike=True),
    ActivityField("Shifts per km", "MtbShiftsKm", "/km", "mtb_shifts_km", "activity-fields/mtb_shifts_km.js", bike=True),
    ActivityField("Climbing power", "MtbClimbPower", "W", "mtb_climb_power", "activity-fields/mtb_climb_power.js", bike=True),
    ActivityField("Pedalling on descents", "MtbDescPedal", "%", "mtb_desc_pedal", "activity-fields/mtb_desc_pedal.js", bike=True),
]

INTERVAL_FIELDS = [
    IntervalField("Grit", "IntMtbGrit", "kGrit", "interval-fields/interval_grit.js", ["mtb_grit"]),
    IntervalField("Flow", "IntMtbFlow", "flow", "interval-fields/interval_flow.js", ["mtb_flow"]),
    IntervalField("Jumps", "IntMtbJumps", "jumps", "interval-fields/interval_jumps.js", ["mtb_jump_air"]),
    IntervalField("Max airtime", "IntMtbMaxAir", "s", "interval-fields/interval_max_air.js", ["mtb_jump_air"]),
    IntervalField("Braking", "IntMtbBraking", "%", "interval-fields/interval_braking.js", ["mtb_brake"]),
    IntervalField("Roughness", "IntMtbRough", "g", "interval-fields/interval_roughness.js", ["mtb_rough"]),
    IntervalField("FA Open", "IntFaOpen", "%", "interval-fields/interval_fa_open.js", ["fa_front"], bike=True),
    IntervalField("FA Lock", "IntFaLock", "%", "interval-fields/interval_fa_lock.js", ["fa_front"], bike=True),
    IntervalField("Shifts", "IntShifts", "shifts", "interval-fields/interval_shifts.js", ["rear_cog"], bike=True),
    IntervalField("Main cog", "IntCog", "T", "interval-fields/interval_cog.js", ["rear_cog"], bike=True),
]

CHARTS = [
    Chart("MTB Dynamics", "charts/mtb_dynamics.js", ["mtb_grit", "mtb_flow", "mtb_jump_air"],
          "Altitude profile with Grit (60 s) and Flow (60 s) on top and every jump marked.", quick=True),
    Chart("MTB Jumps", "charts/mtb_jumps.js", ["mtb_jump_air", "mtb_jump_dist", "mtb_jump_height"],
          "One bar per jump: airtime, coloured by height; hover shows distance and speed."),
    Chart("MTB Trail Segments", "charts/mtb_segments.js", ["mtb_grit", "mtb_flow", "mtb_brake", "mtb_jump_air"],
          "Climbs, descents and flats with Grit, Flow, braking and jumps for each."),
    Chart("Suspension & gears", "charts/mtb_bike.js", ["fa_front", "rear_cog"],
          "Flight Attendant state as a coloured band with the rear cog on top, and minutes per cog by terrain.", bike=True),
]


# ----------------------------------------------------------------------------------------------
def esc(text: str) -> str:
    return html.escape(text, quote=True)


def chip(value: str) -> str:
    return f'<code class="chip" data-copy-text="{esc(value)}" title="Click to copy">{esc(value)}</code>'


def script_id(path: str) -> str:
    return "s-" + path.replace("/", "-").replace(".js", "")


def read_script(path: str) -> str:
    with open(os.path.join(SCRIPTS, path), encoding="utf-8") as f:
        return f.read().rstrip() + "\n"


def script_block(path: str, label: str) -> str:
    sid = script_id(path)
    code = esc(read_script(path))
    return (f'<details class="script" id="{sid}"><summary><span>{esc(label)}</span>'
            f'<span class="file">{esc(path)}</span>'
            f'<button type="button" class="copy" data-copy="{sid}-code">Copy script</button></summary>'
            f'<pre><code id="{sid}-code">{code}</code></pre></details>')


def script_link(path: str, label: str = "script") -> str:
    return f'<a href="#{script_id(path)}" class="scriptref">{label} ↓</a>'


def stream_rows(items: list[Stream]) -> str:
    rows = []
    for s in items:
        if s.fit_field and s.script:
            source = f"FIT record field {chip(s.fit_field)} or {script_link(s.script)}"
        elif s.fit_field:
            source = f"FIT record field {chip(s.fit_field)}"
        else:
            source = f"{script_link(s.script, 'Script')} <span class='tick'>✓ Processes fit file messages</span>"
        note = f'<div class="note">{esc(s.note)}</div>' if s.note else ""
        rows.append(f"<tr><td>{esc(s.name)}</td><td>{chip(s.code)}</td><td>{chip(s.units)}</td><td>{source}{note}</td></tr>")
    return "\n".join(rows)


def activity_rows(items: list[ActivityField]) -> str:
    return "\n".join(
        f"<tr><td>{esc(a.name)}</td><td>{chip(a.code)}</td><td>{chip(a.units)}</td>"
        f"<td>{chip(a.session_field)}</td><td>{script_link(a.script)}</td></tr>" for a in items)


def interval_rows(items: list[IntervalField]) -> str:
    return "\n".join(
        f"<tr><td>{esc(i.name)}</td><td>{chip(i.code)}</td><td>{chip(i.units)}</td>"
        f"<td>{', '.join(chip(n) for n in i.needs)}</td><td>{script_link(i.script)}</td></tr>" for i in items)


def chart_cards(items: list[Chart]) -> str:
    return "\n".join(
        f'<div class="card"><h3>{esc(c.name)}{" <span class=tag>bike</span>" if c.bike else ""}</h3><p>{esc(c.shows)}</p>'
        f'<p class="needs">Needs the streams {", ".join(chip(n) for n in c.needs)}</p>{script_block(c.script, "Chart script")}</div>'
        for c in items)


def scripts_section(paths: list[tuple[str, str]]) -> str:
    return "\n".join(script_block(p, label) for p, label in paths)


def build() -> str:
    core_streams = [s for s in STREAMS if not s.bike]
    bike_streams = [s for s in STREAMS if s.bike]
    core_fields = [a for a in ACTIVITY_FIELDS if not a.bike]
    bike_fields = [a for a in ACTIVITY_FIELDS if a.bike]
    core_ints = [i for i in INTERVAL_FIELDS if not i.bike]
    bike_ints = [i for i in INTERVAL_FIELDS if i.bike]
    quick_streams = [s for s in STREAMS if s.quick]
    quick_fields = [a for a in ACTIVITY_FIELDS if a.quick]
    quick_chart = next(c for c in CHARTS if c.quick)

    stream_scripts = [(s.script, f"{s.name} stream ({s.code})") for s in STREAMS if s.script]
    field_scripts = [(a.script, f"{a.name} field ({a.code})") for a in ACTIVITY_FIELDS]
    interval_scripts = [(i.script, f"{i.name} interval field ({i.code})") for i in INTERVAL_FIELDS]

    quick_stream_list = "".join(
        f"<li>{chip(s.code)}: {('FIT record field ' + chip(s.fit_field)) if s.fit_field else 'script ' + script_link(s.script) + ' (tick Processes fit file messages)'}"
        f", units {chip(s.units)}</li>" for s in quick_streams)
    quick_field_list = "".join(
        f"<li>{esc(a.name)}: code {chip(a.code)}, units {chip(a.units)}, FIT session field {chip(a.session_field)}</li>"
        for a in quick_fields)

    return PAGE.format(
        repo=REPO,
        forum_streams=FORUM["streams"], forum_fields=FORUM["fields"],
        forum_intervals=FORUM["intervals"], forum_charts=FORUM["charts"],
        quick_streams=quick_stream_list, quick_fields=quick_field_list,
        quick_chart=esc(quick_chart.name), quick_chart_link=f'#{script_id(quick_chart.script)}',
        core_stream_rows=stream_rows(core_streams), bike_stream_rows=stream_rows(bike_streams),
        stream_scripts=scripts_section(stream_scripts),
        core_field_rows=activity_rows(core_fields), bike_field_rows=activity_rows(bike_fields),
        field_scripts=scripts_section(field_scripts),
        core_interval_rows=interval_rows(core_ints), bike_interval_rows=interval_rows(bike_ints),
        interval_scripts=scripts_section(interval_scripts),
        chart_cards=chart_cards(CHARTS),
        n_streams=len(STREAMS), n_fields=len(ACTIVITY_FIELDS), n_intervals=len(INTERVAL_FIELDS), n_charts=len(CHARTS),
    )


def main(argv: list[str]) -> int:
    page = build()
    if "--check" in argv:
        current = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if current != page:
            print(f"{os.path.relpath(OUT, ROOT)} is out of date: run python3 tools/make_site_guide.py", file=sys.stderr)
            return 1
        print("intervals.icu guide is up to date")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
    return 0


# Doubled braces are literal braces for str.format.
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MTB Dynamics in intervals.icu</title>
<meta name="description" content="Step-by-step guide: show Grit, Flow, jumps, Flight Attendant and AXS data from MTB Dynamics for Karoo in intervals.icu with custom streams, fields and charts.">
<link rel="icon" href="img/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="site.css">
<style>
.guide h2 {{ margin-top: 4px; }}
.steps-ui {{ margin: 0 0 18px; padding-left: 22px; }}
.steps-ui li {{ margin: 6px 0; }}
.table-wrap {{ margin: 14px 0; }}
.table-wrap td {{ font-size: 14.5px; }}
.table-wrap td:first-child {{ white-space: normal; }}
.chip {{ cursor: copy; white-space: nowrap; }}
.chip:hover {{ border-color: var(--accent); }}
.chip.copied {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.note {{ color: var(--muted); font-size: 13px; margin-top: 3px; }}
.tick {{ display: inline-block; font-size: 12.5px; color: var(--green); margin-left: 4px; }}
.scriptref {{ white-space: nowrap; font-size: 14px; }}
.group {{ font-weight: 700; margin: 22px 0 4px; }}
details.script {{ border: 1px solid var(--line); border-radius: 12px; background: var(--card); margin: 10px 0; }}
details.script summary {{ display: flex; align-items: center; gap: 10px; padding: 10px 14px; cursor: pointer; list-style: none; flex-wrap: wrap; }}
details.script summary::-webkit-details-marker {{ display: none; }}
details.script summary::before {{ content: "▸"; color: var(--muted); }}
details.script[open] summary::before {{ content: "▾"; }}
details.script summary span:first-of-type {{ font-weight: 600; }}
details.script .file {{ color: var(--muted); font-size: 13px; font-family: ui-monospace, Menlo, monospace; }}
details.script pre {{ margin: 0 12px 12px; max-height: 420px; }}
button.copy {{ margin-left: auto; font: inherit; font-size: 13px; font-weight: 600; padding: 5px 11px; border-radius: 8px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; }}
button.copy.copied {{ background: var(--green); border-color: var(--green); }}
.callout {{ border-left: 4px solid var(--accent); background: var(--accent-soft); border-radius: 0 12px 12px 0; padding: 12px 16px; margin: 16px 0; }}
.callout p {{ margin: 4px 0; }}
.needs {{ font-size: 14px; }}
.quick ol {{ padding-left: 22px; }}
.quick li {{ margin: 8px 0; }}
.quick ul {{ margin: 6px 0; padding-left: 20px; }}
.toc {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 0; }}
.toc a {{ border: 1px solid var(--line); border-radius: 999px; padding: 5px 12px; font-size: 14px; color: var(--fg); background: var(--card); }}
.toc a:hover {{ border-color: var(--accent); text-decoration: none; }}
.grid.charts {{ grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }}
.grid.charts details.script pre {{ max-height: 300px; }}
</style>
</head>
<body class="guide">
<nav>
  <div class="wrap">
    <a class="brand" href="./"><img src="img/icon.svg" alt="">MTB Dynamics</a>
    <div class="links">
      <a href="#quick">Quick start</a>
      <a href="#streams">Streams</a>
      <a href="#fields">Fields</a>
      <a class="opt" href="#intervals">Intervals</a>
      <a href="#charts">Charts</a>
      <a class="opt" href="#help">Troubleshooting</a>
      <a href="{repo}">GitHub</a>
    </div>
  </div>
</nav>

<header class="hero" style="padding-bottom:28px">
  <div class="wrap">
    <span class="pill">Setup guide · about 15 minutes, once</span>
    <h1 style="font-size:clamp(32px,5vw,50px)">MTB Dynamics in <span>intervals.icu</span></h1>
    <p style="max-width:760px">Every Karoo ride with MTB Dynamics carries its data in the FIT file as <code>mtb_*</code> fields.
      intervals.icu only reads such fields once you tell it which ones, so there is a one-time setup: custom
      <strong>streams</strong> for the per-second data, <strong>activity fields</strong> for ride totals, <strong>interval
      fields</strong> for laps and selected trail sections, and <strong>charts</strong>. After that, every new ride shows them automatically.</p>
    <div class="toc">
      <a href="#before">Before you start</a><a href="#quick">Quick start (5 min)</a><a href="#streams">1 · {n_streams} streams</a>
      <a href="#fields">2 · {n_fields} activity fields</a><a href="#intervals">3 · {n_intervals} interval fields</a>
      <a href="#charts">4 · {n_charts} charts</a><a href="#old">5 · Older rides</a><a href="#use">Where to look</a><a href="#help">Troubleshooting</a>
    </div>
  </div>
</header>

<section id="before">
  <div class="wrap">
    <h2>Before you start</h2>
    <ul class="check">
      <li>An intervals.icu account with your Karoo rides syncing to it (Hammerhead dashboard → integrations, or upload the FIT file).</li>
      <li>At least one ride recorded with MTB Dynamics. <strong>Do the setup while viewing that ride</strong>: the lists of FIT fields only
        offer the <code>mtb_*</code> fields when the open ride has them.</li>
      <li>No ride yet? Download the synthetic <a href="sample/mtb-dynamics-sample.fit" download>sample ride (FIT)</a>, upload it in intervals.icu
        (<strong>+</strong> → <strong>Upload</strong>), do the setup on it and delete it afterwards.</li>
      <li>The Flight Attendant / AXS items need those parts paired with the Karoo. Skip them otherwise.</li>
    </ul>
    <div class="callout"><p><strong>Codes matter.</strong> Use the codes exactly as shown (click any <code>grey value</code> to copy it).
      The interval fields and charts find the streams by these codes.</p>
      <p>intervals.icu's menus change now and then. If a label differs slightly, the official forum posts linked in each step have screenshots.</p></div>
  </div>
</section>

<section id="quick" class="quick">
  <div class="wrap">
    <h2>Quick start (5 minutes)</h2>
    <p class="lead">The minimum to see Grit, Flow and jumps. You can add the rest later.</p>
    <ol>
      <li><strong>Three streams</strong> (activity → <strong>Charts</strong> under the activity chart → <strong>Custom Streams</strong> → <strong>Add Stream</strong>):
        <ul>{quick_streams}</ul></li>
      <li><strong>Three activity fields</strong>, each reading a FIT session field directly (no script):
        <ul>{quick_fields}</ul></li>
      <li><strong>The {quick_chart} chart</strong>: <strong>Charts</strong> → add a custom chart → paste <a href="{quick_chart_link}">its script</a> → save.</li>
      <li>On that ride: <strong>Actions → Reprocess File</strong>. New rides get everything automatically.</li>
    </ol>
  </div>
</section>

<section id="streams">
  <div class="wrap">
    <h2>Step 1 · Custom streams</h2>
    <p class="lead">Per-second data on the activity chart. The interval fields and charts are built on these.</p>
    <ol class="steps-ui">
      <li>Open a ride recorded with MTB Dynamics.</li>
      <li>Under the activity chart click <strong>Charts</strong> → <strong>Custom Streams</strong> → <strong>Add Stream</strong>
        (<a href="{forum_streams}">forum post with screenshots</a>).</li>
      <li>Enter the <strong>name</strong>, <strong>code</strong> and <strong>units</strong> from the table. intervals.icu needs units for every stream.</li>
      <li>Source: for a <em>FIT record field</em>, pick it from the list. For a <em>script</em>, tick <strong>Processes fit file messages</strong> and paste the script.</li>
      <li>Save, and repeat for each row. Keep the script streams at the top of the list, because they are computed first.</li>
    </ol>
    <div class="group">MTB Dynamics</div>
    <div class="table-wrap"><table>
      <tr><th>Name</th><th>Code</th><th>Units</th><th>Source</th></tr>
      {core_stream_rows}
    </table></div>
    <div class="group">Flight Attendant / AXS <span class="muted small">(the Karoo records these itself when the parts are paired)</span></div>
    <div class="table-wrap"><table>
      <tr><th>Name</th><th>Code</th><th>Units</th><th>Source</th></tr>
      {bike_stream_rows}
    </table></div>
    <p class="muted small">Power, cadence and L/R balance from the power meter are standard intervals.icu streams already.</p>
    {stream_scripts}
  </div>
</section>

<section id="fields">
  <div class="wrap">
    <h2>Step 2 · Activity fields</h2>
    <p class="lead">Ride totals: shown in the activity summary, as columns in the activity list, and plottable over time on the Fitness and Compare pages.</p>
    <ol class="steps-ui">
      <li>On the same ride, open the custom fields editor from the activity page (the <strong>Custom</strong> / <strong>Fields</strong> button by the activity chart) and add a new <strong>activity field</strong>
        (<a href="{forum_fields}">forum post with screenshots</a>).</li>
      <li>Enter the <strong>name</strong>, <strong>code</strong> and <strong>units</strong> from the table.</li>
      <li>Then either:
        <ul>
          <li><strong>Simple:</strong> let the field read the <strong>FIT session field</strong> from the table. This works for Karoo rides with MTB Dynamics.</li>
          <li><strong>Script:</strong> tick <strong>Processes fit file messages</strong> and paste the script. It also reads Garmin MTB Dynamics rides, and
            for the bike fields it computes the value from the Karoo's own records on rides recorded before MTB Dynamics 0.2.</li>
        </ul></li>
    </ol>
    <div class="group">MTB Dynamics</div>
    <div class="table-wrap"><table>
      <tr><th>Name</th><th>Code</th><th>Units</th><th>FIT session field</th><th>Script</th></tr>
      {core_field_rows}
    </table></div>
    <div class="group">Flight Attendant / AXS / power meter</div>
    <div class="table-wrap"><table>
      <tr><th>Name</th><th>Code</th><th>Units</th><th>FIT session field</th><th>Script</th></tr>
      {bike_field_rows}
    </table></div>
    <p class="muted small">More session fields you can add the same way: <code>mtb_avg_grit</code>, <code>mtb_total_flow</code>, <code>mtb_max_jump_dist</code>,
      <code>mtb_max_jump_height</code>, <code>mtb_difficulty</code>, <code>mtb_smoothness</code>, <code>mtb_air_score</code>, <code>mtb_corner_speed_kept</code>,
      <code>mtb_descent_time</code>, <code>mtb_descent_speed</code>, <code>mtb_descent_flow</code>, <code>mtb_avg_rough</code>, <code>mtb_fa_open_climb</code>,
      <code>mtb_fa_changes</code>, <code>mtb_fa_reaction</code>, <code>mtb_shifts</code>, <code>mtb_climb_wkg</code>, <code>mtb_cog_max</code>.</p>
    {field_scripts}
  </div>
</section>

<section id="intervals">
  <div class="wrap">
    <h2>Step 3 · Interval fields</h2>
    <p class="lead">Grit, Flow, jumps and more for every lap, and for any stretch you select on the activity chart. Handy for comparing runs down the same trail.</p>
    <ol class="steps-ui">
      <li>Add a field of type <strong>interval field</strong> in the same custom fields editor (<a href="{forum_intervals}">forum post</a>).</li>
      <li>Enter the name, code and units, then paste the script. Each needs the stream shown in the table, from step 1.</li>
      <li>The values appear as columns in the intervals table and in the summary when you drag across the chart. Karoo laps become intervals automatically.</li>
    </ol>
    <div class="group">MTB Dynamics</div>
    <div class="table-wrap"><table>
      <tr><th>Name</th><th>Code</th><th>Units</th><th>Needs stream</th><th>Script</th></tr>
      {core_interval_rows}
    </table></div>
    <div class="group">Flight Attendant / AXS</div>
    <div class="table-wrap"><table>
      <tr><th>Name</th><th>Code</th><th>Units</th><th>Needs stream</th><th>Script</th></tr>
      {bike_interval_rows}
    </table></div>
    {interval_scripts}
  </div>
</section>

<section id="charts">
  <div class="wrap">
    <h2>Step 4 · Activity charts</h2>
    <p class="lead">On the activity page click <strong>Charts</strong>, add a custom chart, paste the script and save
      (<a href="{forum_charts}">forum post</a>). Charts are stored per sport, so they show on every ride of that sport.</p>
    <div class="grid charts">
      {chart_cards}
    </div>
  </div>
</section>

<section id="old">
  <div class="wrap">
    <h2>Step 5 · Older rides</h2>
    <p class="lead">New rides get everything automatically. Rides uploaded before the setup have to read their FIT file again.</p>
    <ul class="check">
      <li>One ride: <strong>Actions → Reprocess File</strong>. This re-reads the FIT file; <em>Re-analyse</em> only recomputes from data already imported.</li>
      <li>Many rides: <strong>Calendar</strong> → switch to the activity list → tick the rides → edit them and reprocess / re-analyse in one go.</li>
    </ul>
  </div>
</section>

<section id="use">
  <div class="wrap">
    <h2>Where to look</h2>
    <div class="grid">
      <div class="card"><h3>Activity page</h3><p>The MTB streams in the chart's stream selector, the custom charts below it, and the fields in the summary.</p></div>
      <div class="card"><h3>Activity list</h3><p>Add <code>MtbGrit</code>, <code>MtbFlow</code>, <code>MtbJumps</code> or <code>MtbScore</code> as columns to compare rides at a glance.</p></div>
      <div class="card"><h3>Fitness &amp; Compare</h3><p>Plot <code>MtbFlow</code> (average) over months to see whether your descending gets smoother, or <code>MtbGrit</code> (sum) per week.</p></div>
      <div class="card"><h3>Laps &amp; selections</h3><p>Grit, Flow and jumps per lap, or drag across one trail and compare it with last week's run.</p></div>
    </div>
  </div>
</section>

<section id="help">
  <div class="wrap">
    <h2>Troubleshooting</h2>
    <div class="table-wrap"><table>
      <tr><th>Problem</th><th>Fix</th></tr>
      <tr><td>A stream or field stays empty</td><td>Check the ride was recorded with MTB Dynamics, that the code is spelled exactly, and run <strong>Actions → Reprocess File</strong>.
        Locally, <code>python3 tools/mtb_analyze.py ride.fit</code> lists the MTB fields a FIT file contains.</td></tr>
      <tr><td>A chart is blank</td><td>It needs its streams with these exact codes (see each chart). Add the missing stream, then reprocess the ride.</td></tr>
      <tr><td>A script returns nothing</td><td><strong>Processes fit file messages</strong> must be ticked for every script that reads the FIT file.</td></tr>
      <tr><td>Flow / braking peaks a few seconds late</td><td>Use the <code>mtb_flow</code> / <code>mtb_brake</code> scripts rather than the raw record fields. The Karoo writes those 3 s late, because Flow looks ahead.</td></tr>
      <tr><td>Flight Attendant / AXS fields empty</td><td>The parts must be paired with the Karoo. The session fields need MTB Dynamics 0.2 or later; the scripts also work on older rides.</td></tr>
      <tr><td>Values differ a little from the ntfy summary</td><td>The FIT session fields are the Karoo's numbers. Scripts that recompute from records use intervals.icu's moving time and smoothing.</td></tr>
    </table></div>
    <p class="muted small">Still stuck? <a href="{repo}/issues/new/choose">Open an issue</a>. This page is generated from the scripts in
      <a href="{repo}/tree/main/intervals-icu">intervals-icu/</a> (also described in its <a href="{repo}/blob/main/intervals-icu/README.md">README</a>).</p>
  </div>
</section>

<footer>
  <div class="wrap">
    <div><a href="./">MTB Dynamics for Karoo</a> · intervals.icu setup guide<br>Not affiliated with intervals.icu, Garmin, Hammerhead or SRAM.</div>
    <div><a href="{repo}">GitHub</a> · <a href="{repo}/blob/main/LICENSE">Apache-2.0</a></div>
  </div>
</footer>
<script>
(function () {{
  function flash(el, cls, text) {{
    var old = el.textContent; el.classList.add(cls); if (text) el.textContent = text;
    setTimeout(function () {{ el.classList.remove(cls); if (text) el.textContent = old; }}, 1400);
  }}
  function copy(text, el, label) {{
    function done() {{ flash(el, 'copied', label); }}
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(text).then(done, function () {{ fallback(text); done(); }});
    }} else {{ fallback(text); done(); }}
  }}
  function fallback(text) {{
    var t = document.createElement('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0';
    document.body.appendChild(t); t.select(); try {{ document.execCommand('copy'); }} catch (e) {{}} document.body.removeChild(t);
  }}
  document.addEventListener('click', function (e) {{
    var b = e.target.closest('button.copy');
    if (b) {{ e.preventDefault(); copy(document.getElementById(b.dataset.copy).textContent, b, 'Copied ✓'); return; }}
    var c = e.target.closest('[data-copy-text]');
    if (c) copy(c.dataset.copyText, c, null);
    var a = e.target.closest('a.scriptref');
    if (a) {{ var d = document.querySelector(a.getAttribute('href')); if (d) d.open = true; }}
  }});
  if (location.hash) {{ var d = document.querySelector(location.hash); if (d && d.tagName === 'DETAILS') d.open = true; }}
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
