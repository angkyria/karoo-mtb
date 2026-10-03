"""Console, CSV and HTML output."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os

from .insights import corner_side_hint
from .model import Ride
from .scoring import WINDOW, flow_score
from .sram import UNDER_LOAD_W, terrain_kinds


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------
class Units:
    def __init__(self, imperial: bool = False):
        self.imperial = imperial

    def speed(self, ms):
        return f"{ms * 2.236936:.1f} mph" if self.imperial else f"{ms * 3.6:.1f} km/h"

    def dist(self, m):
        return f"{m / 1609.344:.1f} mi" if self.imperial else f"{m / 1000:.1f} km"

    def short(self, m):
        return f"{m * 3.28084:.1f} ft" if self.imperial else f"{m:.1f} m"

    def elev(self, m):
        return f"{m * 3.28084:.0f} ft" if self.imperial else f"{m:.0f} m"


def hms(sec: float) -> str:
    sec = int(max(0, sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def sram_text(sram: dict, u: Units) -> list[str]:
    """Report lines for Flight Attendant, AXS Transmission, power meter and batteries."""
    lines = []
    su = sram.get("suspension")
    if su:
        o = su["overall"]
        bias = f", bias {su['bias']:+d}" if su.get("bias") is not None else ""
        lines.append(f"  Suspension (Flight Attendant{bias}): Open {o['Open']:.0f}% · Pedal {o['Pedal']:.0f}% · Lock {o['Lock']:.0f}%")
        parts = []
        for kind, label in (("DESCENT", "descents"), ("CLIMB", "climbs"), ("FLAT", "flats")):
            sh = su["by_terrain"].get(kind)
            if sh:
                parts.append(f"{label} {sh['Open']:.0f}/{sh['Pedal']:.0f}/{sh['Lock']:.0f}")
        lines.append("        Open/Pedal/Lock % — " + " · ".join(parts))
        react = f" · reaches Open {su['reaction_s_median']:.0f} s into a descent ({su['descents_reaching_open']}/{su['descents']})" \
            if su.get("reaction_s_median") is not None else ""
        lines.append(f"        locked on rough ground {su['locked_rough_s']:.0f} s · open on hard climbs {su['open_hard_climb_s']:.0f} s"
                     f" · {su['changes']} changes ({su['changes_per_km']:.1f}/km){react}")
        if su["effort_zones"]:
            zones = " · ".join(f"{z['zone']}: {z['minutes']:.0f} min" + (f" {z['avg_power']:.0f} W" if z["avg_power"] else "")
                               for z in su["effort_zones"])
            lines.append(f"        effort zones {zones}")
    dr = sram.get("drivetrain")
    if dr:
        used = f"{dr['used'][0]}-{dr['used'][-1]}T" if dr["used"] else "–"
        top = sorted(dr["cog_minutes"].items(), key=lambda x: -x[1])[:2]
        unused = f" · never used {', '.join(f'{t}T' for t in dr['unused'])}" if dr.get("unused") else ""
        lines.append(f"  Drivetrain (AXS): {dr['shifts']} shifts ({dr['shifts_per_km']:.1f}/km) · cogs {used}"
                     f" (most {', '.join(f'{t}T' for t, _ in top)}){unused}")
        climb = dr["by_terrain"].get("CLIMB")
        details = []
        if climb:
            details.append(f"climbs on {climb['median']}T (largest {climb['largest']}T)")
        details.append(f"{dr['under_load']} shifts above {UNDER_LOAD_W:.0f} W")
        if dr["climb_shifts_before"] + dr["climb_shifts_after"]:
            details.append(f"easier shifts before / after climb start {dr['climb_shifts_before']}/{dr['climb_shifts_after']}")
        if dr.get("steep_cadence"):
            details.append(f"steep climbing {dr['steep_cadence']:.0f} rpm, {dr['steep_torque']:.0f} N·m, "
                           f"{dr['steep_low_cadence_s']:.0f} s under 60 rpm")
        lines.append("        " + " · ".join(details))
    pw = sram.get("power")
    if pw:
        parts = []
        for kind, label in (("CLIMB", "climbs"), ("FLAT", "flats"), ("DESCENT", "descents")):
            t = pw["terrain"].get(kind)
            if not t:
                continue
            txt = f"{label} {t['avg_w']:.0f} W"
            if t.get("w_kg"):
                txt += f" ({t['w_kg']:.1f} W/kg)"
            if kind == "DESCENT":
                txt += f", pedalling {t['pedalling_pct']:.0f}%"
            parts.append(txt)
        best = f" · best 5 min {pw['best_5min_w']:.0f} W" if pw.get("best_5min_w") else ""
        climb = pw["terrain"].get("CLIMB") or {}
        bal = f" · L/R {climb['balance_left']:.0f}/{100 - climb['balance_left']:.0f} on climbs" if climb.get("balance_left") else ""
        lines.append("  Power: " + " · ".join(parts) + best + bal)
    bats = sram.get("batteries")
    if bats:
        lines.append("  Batteries: " + " · ".join(
            f"{b['kind']} {b['battery_pct']:.0f}%" if b.get("battery_pct") is not None else f"{b['kind']} {b.get('battery_status')}"
            for b in bats))
    return lines


def report_text(s: dict, u: Units) -> str:
    lines = []
    sc = s["score"]
    lines.append(f"MTB Dynamics — {s['start'][:16].replace('T', ' ')} UTC  ({s['device'] or s['source']})")
    if s["estimated"]:
        lines.append("  (no MTB Dynamics data in the file: Grit/Flow estimated from GPS + altitude, no jumps/roughness)")
    lines.append(f"  MTB score {sc['total']:.0f}   difficulty {sc['difficulty']:.0f} · smoothness {sc['smoothness']:.0f} · air {sc['air']:.0f}")
    lines.append(f"  Ride  {hms(s['elapsed_s'])} (moving {hms(s['moving_s'])}) · {u.dist(s['distance_m'])} · ↗ {u.elev(s['ascent_m'])} · avg {u.speed(s['avg_speed_ms'])}")
    g, f = s["grit"], s["flow"]
    lines.append(f"  Grit  {g['total_k']:.1f} kGrit · avg {g['avg']:.2f}/s · peak 60 s {g['peak60']:.1f}")
    lines.append(f"  Flow  {f['score']:.2f} (lower = smoother) · descents {f['descent']:.2f} · worst 60 s {f['worst60']:.1f}")
    j = s["jumps"]
    lines.append(f"  Jumps {j['count']} · total air {j['total_air_s']:.1f} s")
    if j["longest"]:
        lj = j["longest"]
        lines.append(f"        longest {lj['air']:.2f} s · {u.short(lj['distance'])} · {u.speed(lj['speed'])};"
                     f" farthest {u.short(j['farthest']['distance'])}; highest ~{u.short(j['highest']['height'])}")
    c = s["cornering"]
    from_list = c["source"] == "GPS track" or c.get("list_from_karoo")
    track = f"{c['left']} L / {c['right']} R" if from_list else f"GPS track {c['gps_count']}: {c['left']} L / {c['right']} R"
    lines.append(f"  Corners {c['count']} ({c['source']}; {track}) · speed kept {c['speed_kept_pct']:.0f} % · max {c['max_lat_g']:.2f} g")
    hint = corner_side_hint(c.get("speed_kept_left_pct"), c.get("speed_kept_right_pct"))
    if hint:
        lines.append(f"        {hint}")
    d = s["descending"]
    lines.append(f"  Descents {hms(d['time_s'])} · {u.elev(d['drop_m'])} ↓ · avg {u.speed(d['avg_speed_ms'])} · max {u.speed(d['max_speed_ms'])} · braking {d['braking_pct']:.0f} %")
    if s["roughness_avg"] is not None:
        lines.append(f"  Roughness avg {s['roughness_avg']:.2f} g")
    lines.extend(sram_text(s.get("sram") or {}, u))

    def table(rows: list[dict], title: str):
        if not rows:
            return
        lines.append("")
        lines.append(title)
        bike = any(r.get("avg_power") is not None or r.get("fa") for r in rows)
        extra = f" {'W':>5} {'FA O/P/L %':>11} {'cog':>4}" if bike else ""
        lines.append(f"  {'#':>2} {'name':<12} {'dist':>8} {'time':>8} {'elev':>8} {'grade':>6} {'speed':>11} {'kGrit':>6} {'flow':>5} {'brake':>6} {'jumps':>5}" + extra)
        for r in rows:
            elev = r["elev_gain_m"] if r["type"] == "CLIMB" else -r["elev_loss_m"] if r["type"] == "DESCENT" else r["elev_gain_m"] - r["elev_loss_m"]
            more = ""
            if bike:
                fa = r.get("fa")
                fa_txt = f"{fa['Open']:.0f}/{fa['Pedal']:.0f}/{fa['Lock']:.0f}" if fa else "–"
                watts = f"{r['avg_power']:.0f}" if r.get("avg_power") is not None else "–"
                cog = f"{r['median_cog']:.0f}T" if r.get("median_cog") else "–"
                more = f" {watts:>5} {fa_txt:>11} {cog:>4}"
            lines.append(f"  {r['index']:>2} {r['name']:<12} {u.dist(r['distance_m']):>8} {hms(r['duration_s']):>8} {elev:>+7.0f}m "
                         f"{r['avg_grade_pct']:>5.1f}% {u.speed(r['avg_speed_ms']):>11} {r['grit_k']:>6.1f} {r['flow_score']:>5.1f} "
                         f"{r['braking_pct']:>5.0f}% {r['jumps']:>5}" + more)

    spots = s.get("braking_spots") or []
    if spots:
        lines.append("")
        lines.append("Where Flow was lost (most unnecessary braking)")
        for n, b in enumerate(spots, 1):
            where = " · ".join(x for x in (b["segment"], f"at {u.dist(b['distance_m'])} ({hms(b['offset_s'])})") if x)
            pos = f" · {b['lat']:.5f}, {b['lon']:.5f}" if b.get("lat") is not None else ""
            lines.append(f"  {n}. {where} · {u.short(b['flow_m'])} braking · {u.speed(b['speed_before_ms'])} → {u.speed(b['speed_after_ms'])}{pos}")

    markers = s.get("markers") or []
    if markers:
        lines.append("")
        lines.append("Marked moments (Karoo 'Mark moment' button)")
        for m in markers:
            at = dt.datetime.fromtimestamp(m["t"], dt.timezone.utc).strftime("%H:%M:%S")
            if m.get("flight_air") is None:
                what = "no flight seen" if "verdict" in m else ""
            elif m.get("verdict"):
                what = f"flight {m['flight_air']:.2f} s not counted: {m['verdict']}"
            else:
                what = f"jump {m['flight_air']:.2f} s counted"
            lines.append(f"  #{m['n']}  {at} UTC  {what}".rstrip())
        lines.append("  (check them with --imu; --export-snippets turns them into test fixtures)")

    table(s["segments"], "Trail segments")
    table(s["laps"], "Laps")
    lc = s.get("lap_comparison")
    if lc:
        trend = ""
        if lc["trend_pct"] is not None:
            t = lc["trend_pct"]
            trend = f" · last laps {t:.0f}% slower" if t > 2 else f" · last laps {-t:.0f}% faster" if t < -2 else " · steady pace"
        lines.append(f"  {lc['comparable']} of {lc['laps']} laps comparable · fastest Lap {lc['fastest_lap']} {hms(lc['fastest_s'])} · "
                     f"median {hms(lc['median_s'])} · smoothest Lap {lc['smoothest_lap']} (Flow {lc['smoothest_flow']:.1f}){trend}")
    if j["list"]:
        lines.append("")
        lines.append("Jumps")
        for jj in j["list"]:
            at = dt.datetime.fromtimestamp(jj["t"], dt.timezone.utc).strftime("%H:%M:%S")
            drop = f" · drop {jj['drop']:.1f} m" if jj.get("drop") else ""
            lines.append(f"  {jj['n']:>3}. {at}  {jj['air']:.2f} s · {u.short(jj['distance'])} · ~{u.short(jj['height'])} high · {u.speed(jj['speed'])}{drop}")
    return "\n".join(lines)


def write_csv(ride: Ride, s: dict, prefix: str) -> list[str]:
    os.makedirs(os.path.dirname(os.path.abspath(prefix)), exist_ok=True)
    out = []
    path = f"{prefix}_seconds.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", "elapsed_s", "distance_m", "speed_kmh", "altitude_m", "grade_pct", "lat", "lon",
                    "grit", "flow_m", "rough_g", "lat_g", "brake_ms2", "jump_air_s", "lap"])
        for x in ride.samples:
            w.writerow([dt.datetime.fromtimestamp(x.t, dt.timezone.utc).isoformat(), round(x.t - ride.start, 1),
                        round(x.dist, 1), round(x.speed * 3.6, 2), x.alt, x.grade, x.lat, x.lon,
                        _r(x.grit), _r(x.flow), _r(x.rough), _r(x.lat_g), _r(x.brake), x.jump_air or "", x.lap + 1])
    out.append(path)
    for key, rows in (("segments", s["segments"]), ("laps", s["laps"]), ("jumps", s["jumps"]["list"]), ("corners", s["cornering"]["list"])):
        if not rows:
            continue
        path = f"{prefix}_{key}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        out.append(path)
    return out


def _r(v, n=4):
    return "" if v is None else round(v, n)


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MTB Dynamics</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
 :root{--bg:#fff;--fg:#1b1b1b;--muted:#66727a;--card:#f3f5f6;--accent:#ff6d00;--line:#e2e6e8}
 @media (prefers-color-scheme:dark){:root{--bg:#121416;--fg:#e9ecee;--muted:#98a3aa;--card:#1d2124;--line:#2c3236}}
 body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 main{max-width:1100px;margin:0 auto;padding:16px}
 h1{font-size:22px;margin:4px 0}h2{font-size:17px;margin:26px 0 8px}
 .muted{color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:14px}
 .card{background:var(--card);border-radius:10px;padding:10px 12px}.card b{display:block;font-size:24px}
 .card span{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
 #map{height:420px;border-radius:10px;margin-top:6px}.chart{height:300px}
 table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 6px;border-bottom:1px solid var(--line);text-align:right}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}.tw{overflow-x:auto}
 .seg-CLIMB{color:#d84315}.seg-DESCENT{color:#1565c0}
 .toggle button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:6px;padding:4px 10px;margin-right:4px;cursor:pointer}
 .toggle button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
</style></head>
<body><main>
<h1>🚵 MTB Dynamics</h1><div class="muted" id="sub"></div>
<div class="cards" id="cards"></div>
<h2>Map</h2><div class="toggle" id="colorBy"></div><div id="map"></div>
<h2>Profile</h2><div class="chart" id="profile"></div>
<h2>Grit &amp; Flow (60 s)</h2><div class="chart" id="gritflow"></div>
<h2>Speed &amp; braking</h2><div class="chart" id="brakes"></div>
<h2>Jumps</h2><div class="chart" id="jumps"></div>
<div id="bike"><h2>Suspension &amp; gears</h2><div class="chart" id="fagears"></div>
<h2>Cog usage by terrain</h2><div class="chart" id="cogs"></div></div>
<h2>Trail segments</h2><div class="tw"><table id="segments"></table></div>
<h2>Where Flow was lost</h2><div class="tw"><table id="spots"></table></div>
<h2>Laps</h2><p class="muted" id="lapcmp"></p><div class="tw"><table id="laps"></table></div>
<p class="muted" id="note"></p>
</main>
<script>
const D = __DATA__;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const fg = dark ? '#e9ecee' : '#1b1b1b', grid = dark ? '#2c3236' : '#e2e6e8';
const base = {paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)', font:{color:fg}, margin:{l:50,r:50,t:10,b:40},
  xaxis:{title:'Distance ('+D.u.dist+')', gridcolor:grid}, legend:{orientation:'h', y:1.12}};
const S = D.summary, R = D.rows;
const plot = (...args) => window.Plotly && Plotly.newPlot(...args);
document.getElementById('sub').textContent = S.start.slice(0,16).replace('T',' ') + ' UTC · ' + (S.device || S.source) +
  (S.estimated ? ' · Grit/Flow estimated from GPS (no MTB Dynamics data in file)' : '');
const card = (label, value) => `<div class="card"><span>${label}</span><b>${value}</b></div>`;
const f1 = v => (v ?? 0).toFixed(1), f2 = v => (v ?? 0).toFixed(2);
document.getElementById('cards').innerHTML = [
  card('MTB score', S.score.total.toFixed(0)), card('Grit (kGrit)', f1(S.grit.total_k)), card('Flow', f2(S.flow.score)),
  card('Jumps', S.jumps.count), card('Max airtime', S.jumps.longest ? f2(S.jumps.longest.air)+' s' : '–'),
  card('Corners', S.cornering.count), card('Max corner g', f2(S.cornering.max_lat_g)),
  ...(S.cornering.speed_kept_left_pct != null && S.cornering.speed_kept_right_pct != null
    ? [card('Speed kept L / R', S.cornering.speed_kept_left_pct.toFixed(0)+' / '+S.cornering.speed_kept_right_pct.toFixed(0)+' %')] : []),
  card('Descent braking', S.descending.braking_pct.toFixed(0)+' %'),
  card('Distance', (S.distance_m*D.u.distF).toFixed(1)+' '+D.u.dist), card('Ascent', (S.ascent_m*D.u.elevF).toFixed(0)+' '+D.u.elev),
].concat(bikeCards()).join('');
function bikeCards() {
  const sr = S.sram || {}, out = [];
  const su = sr.suspension, dr = sr.drivetrain, pw = sr.power;
  if (su && su.by_terrain.DESCENT) out.push(card('FA Open on descents', su.by_terrain.DESCENT.Open.toFixed(0)+' %'));
  if (su) out.push(card('Locked on rough', su.locked_rough_s.toFixed(0)+' s'));
  if (dr) out.push(card('Shifts', dr.shifts+' ('+dr.shifts_per_km.toFixed(1)+'/km)'));
  if (pw && pw.terrain.CLIMB) out.push(card('Climb power', pw.terrain.CLIMB.avg_w.toFixed(0)+' W'+(pw.terrain.CLIMB.w_kg ? ' · '+pw.terrain.CLIMB.w_kg.toFixed(1)+' W/kg' : '')));
  return out;
}

// Map coloured by a metric
const pts = R.filter(r => r.lat != null && r.lon != null);
if (pts.length && window.L) {  // tables still render when the map library cannot load (offline)
  const map = L.map('map'); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(map);
  let layer = null;
  const ramp = t => { t = Math.max(0, Math.min(1, t)); const h = (1 - t) * 120; return `hsl(${h},85%,45%)`; };
  const metrics = {grit: ['Grit 60 s', r => r.grit60, 12], flow: ['Flow 60 s', r => r.flow60, 10], speed: ['Speed', r => r.speed, null], rough: ['Roughness', r => r.rough, 1]};
  const draw = key => {
    if (layer) map.removeLayer(layer);
    layer = L.layerGroup();
    const [, get, fixedMax] = metrics[key];
    const vals = pts.map(get).filter(v => v != null);
    const max = fixedMax || Math.max(...vals, 1);
    for (let i = 1; i < pts.length; i++) {
      const v = get(pts[i]);
      L.polyline([[pts[i-1].lat, pts[i-1].lon], [pts[i].lat, pts[i].lon]], {color: v == null ? '#888' : ramp(v / max), weight: 5, opacity: .9}).addTo(layer);
    }
    for (const j of S.jumps.list) if (j.lat != null) L.circleMarker([j.lat, j.lon], {radius: 5 + j.air * 6, color: '#ff6d00', fillOpacity: .8})
      .bindPopup(`<b>Jump ${j.n}</b><br>${j.air.toFixed(2)} s air<br>${(j.distance*D.u.shortF).toFixed(1)} ${D.u.short}<br>~${(j.height*D.u.shortF).toFixed(1)} ${D.u.short} high`).addTo(layer);
    (S.braking_spots || []).forEach((b, i) => { if (b.lat != null) L.circleMarker([b.lat, b.lon], {radius: 9, color: '#c62828', fillOpacity: .5})
      .bindPopup(`<b>Braking spot ${i + 1}</b><br>${(b.flow_m*D.u.shortF).toFixed(0)} ${D.u.short} unnecessary braking`).addTo(layer); });
    layer.addTo(map);
    document.querySelectorAll('#colorBy button').forEach(b => b.classList.toggle('on', b.dataset.k === key));
  };
  document.getElementById('colorBy').innerHTML = Object.entries(metrics).map(([k, m]) => `<button data-k="${k}">${m[0]}</button>`).join('');
  document.querySelectorAll('#colorBy button').forEach(b => b.onclick = () => draw(b.dataset.k));
  map.fitBounds(pts.map(p => [p.lat, p.lon]));
  draw('grit');
} else document.getElementById('map').outerHTML = '<p class="muted">No GPS track.</p>';

const x = R.map(r => r.dist * D.u.distF);
const segShapes = S.segments.filter(s => s.type !== 'FLAT').map(s => {
  const a = R.findIndex(r => r.off >= s.start_offset_s), b = R.findIndex(r => r.off >= s.start_offset_s + s.duration_s);
  return {type:'rect', xref:'x', yref:'paper', x0:x[Math.max(0,a)], x1:x[b < 0 ? x.length-1 : b], y0:0, y1:1, line:{width:0},
          fillcolor: s.type === 'CLIMB' ? 'rgba(216,67,21,.08)' : 'rgba(21,101,192,.10)'};
});
plot('profile', [
  {x, y: R.map(r => r.alt == null ? null : r.alt * D.u.elevF), name: 'Altitude', fill: 'tozeroy', line: {color: '#78909c'}},
  {x: S.jumps.list.map(j => { const i = R.findIndex(r => r.t >= j.t); return x[Math.max(0, i)]; }),
   y: S.jumps.list.map(j => { const i = R.findIndex(r => r.t >= j.t); const a = R[Math.max(0, i)].alt; return a == null ? null : a * D.u.elevF; }),
   mode: 'markers', name: 'Jumps', marker: {color: '#ff6d00', size: S.jumps.list.map(j => 6 + j.air * 10)}},
], {...base, shapes: segShapes, yaxis: {title: 'Altitude ('+D.u.elev+')', gridcolor: grid}}, {responsive: true, displaylogo: false});
plot('gritflow', [
  {x, y: R.map(r => r.grit60), name: 'Grit 60 s (grit/s)', line: {color: '#d84315'}},
  {x, y: R.map(r => r.flow60), name: 'Flow 60 s', yaxis: 'y2', line: {color: '#1565c0'}},
], {...base, yaxis: {title: 'Grit / s', gridcolor: grid}, yaxis2: {title: 'Flow', overlaying: 'y', side: 'right', showgrid: false}}, {responsive: true, displaylogo: false});
plot('brakes', [
  {x, y: R.map(r => r.speed * D.u.speedF), name: 'Speed ('+D.u.speed+')', line: {color: '#455a64'}},
  {x, y: R.map(r => r.brake), name: 'Braking (m/s²)', yaxis: 'y2', type: 'bar', marker: {color: R.map(r => r.flow > 0 ? '#ff6d00' : '#90a4ae')}},
], {...base, bargap: 0, yaxis: {title: 'Speed', gridcolor: grid}, yaxis2: {title: 'm/s² (orange = unnecessary)', overlaying: 'y', side: 'right', showgrid: false}}, {responsive: true, displaylogo: false});
if (S.jumps.list.length) plot('jumps', [{
  x: S.jumps.list.map(j => '#' + j.n), y: S.jumps.list.map(j => j.air), type: 'bar', marker: {color: S.jumps.list.map(j => j.height), colorscale: 'Oranges', showscale: true, colorbar: {title: 'height'}},
  text: S.jumps.list.map(j => `${(j.distance*D.u.shortF).toFixed(1)} ${D.u.short} · ~${(j.height*D.u.shortF).toFixed(1)} ${D.u.short} · ${(j.speed*D.u.speedF).toFixed(0)} ${D.u.speed}`),
  hovertemplate: '%{x}: %{y:.2f} s<br>%{text}<extra></extra>'}], {...base, xaxis: {title: 'Jump'}, yaxis: {title: 'Airtime (s)', gridcolor: grid}}, {responsive: true, displaylogo: false});
else document.getElementById('jumps').outerHTML = '<p class="muted">No jumps.</p>';

// Suspension & gears
if (R.some(r => r.fa != null || r.cog != null)) {
  const faNames = ['Open', 'Pedal', 'Lock'], faColors = ['#2e7d32', '#f9a825', '#c62828'];
  const traces = [];
  for (let code = 0; code < 3; code++) traces.push({x, y: R.map(r => r.fa === code ? 1 : null), type: 'bar', name: 'FA ' + faNames[code],
    marker: {color: faColors[code]}, hoverinfo: 'name', yaxis: 'y'});
  if (R.some(r => r.cog != null)) traces.push({x, y: R.map(r => r.cog), name: 'Rear cog (T)', yaxis: 'y2', line: {shape: 'hv', color: '#455a64', width: 1.5}});
  plot('fagears', traces, {...base, barmode: 'stack', bargap: 0, yaxis: {visible: false, range: [0, 1]},
    yaxis2: {title: 'Cog teeth', overlaying: 'y', side: 'right', autorange: 'reversed'}}, {responsive: true, displaylogo: false});
  const kinds = ['CLIMB', 'FLAT', 'DESCENT'], kindColor = {CLIMB: '#d84315', FLAT: '#90a4ae', DESCENT: '#1565c0'};
  const cogs = [...new Set(R.filter(r => r.cog != null).map(r => r.cog))].sort((a, b) => a - b);
  if (cogs.length) plot('cogs', kinds.map(k => ({x: cogs.map(c => c + 'T'), type: 'bar', name: k.toLowerCase(),
    marker: {color: kindColor[k]}, y: cogs.map(c => R.filter(r => r.cog === c && r.kind === k && r.speed >= 1).length / 60)})),
    {...base, barmode: 'stack', xaxis: {title: 'Rear cog'}, yaxis: {title: 'Minutes', gridcolor: grid}}, {responsive: true, displaylogo: false});
  else document.getElementById('cogs').outerHTML = '<p class="muted">No gear data.</p>';
} else document.getElementById('bike').style.display = 'none';

const elevCell = r => r.type === 'CLIMB' ? '+' + (r.elev_gain_m*D.u.elevF).toFixed(0)
  : r.type === 'DESCENT' ? '−' + (r.elev_loss_m*D.u.elevF).toFixed(0)
  : '+' + (r.elev_gain_m*D.u.elevF).toFixed(0) + ' / −' + (r.elev_loss_m*D.u.elevF).toFixed(0);
const bikeCols = rows => rows.some(r => r.avg_power != null || r.fa);
const bikeHead = rows => bikeCols(rows) ? '<th>W</th><th>W/kg</th><th>FA O/P/L %</th><th>Cog</th><th>Shifts</th>' : '';
const bikeCells = (rows, r) => !bikeCols(rows) ? '' :
  `<td>${r.avg_power != null ? r.avg_power.toFixed(0) : '–'}</td><td>${r.w_kg ? r.w_kg.toFixed(1) : '–'}</td>` +
  `<td>${r.fa ? r.fa.Open.toFixed(0)+'/'+r.fa.Pedal.toFixed(0)+'/'+r.fa.Lock.toFixed(0) : '–'}</td>` +
  `<td>${r.median_cog ? r.median_cog+'T' : '–'}</td><td>${r.shifts ?? '–'}</td>`;
const tableHtml = rows => rows.length ? '<tr><th>#</th><th>Name</th><th>Dist</th><th>Time</th><th>Elev</th><th>Grade</th><th>Speed</th><th>kGrit</th><th>Flow</th><th>Braking</th><th>Jumps</th><th>Corners</th>' + bikeHead(rows) + '</tr>' +
  rows.map(r => `<tr><td>${r.index}</td><td class="seg-${r.type}">${r.name}</td><td>${(r.distance_m*D.u.distF).toFixed(2)}</td>` +
    `<td>${new Date(r.duration_s*1000).toISOString().substr(11,8)}</td><td>${elevCell(r)}</td>` +
    `<td>${r.avg_grade_pct.toFixed(1)}%</td><td>${(r.avg_speed_ms*D.u.speedF).toFixed(1)}</td><td>${r.grit_k.toFixed(1)}</td>` +
    `<td>${r.flow_score.toFixed(1)}</td><td>${r.braking_pct.toFixed(0)}%</td><td>${r.jumps}</td><td>${r.corners}</td>` + bikeCells(rows, r) + '</tr>').join('') : '<tr><td class="muted">none</td></tr>';
document.getElementById('segments').innerHTML = tableHtml(S.segments);
document.getElementById('laps').innerHTML = tableHtml(S.laps);
const hms = s => new Date(s*1000).toISOString().substr(11,8);
const lc = S.lap_comparison;
document.getElementById('lapcmp').textContent = lc ? `${lc.comparable} of ${lc.laps} laps comparable · fastest Lap ${lc.fastest_lap} ${hms(lc.fastest_s)} · median ${hms(lc.median_s)} · smoothest Lap ${lc.smoothest_lap} (Flow ${lc.smoothest_flow.toFixed(1)})` +
  (lc.trend_pct == null ? '' : lc.trend_pct > 2 ? ` · last laps ${lc.trend_pct.toFixed(0)}% slower` : lc.trend_pct < -2 ? ` · last laps ${(-lc.trend_pct).toFixed(0)}% faster` : ' · steady pace') : '';
const spots = S.braking_spots || [];
document.getElementById('spots').innerHTML = spots.length ? '<tr><th>#</th><th>Where</th><th>Dist</th><th>Time</th><th>Braking</th><th>Speed</th><th>Map</th></tr>' +
  spots.map((b, i) => `<tr><td>${i + 1}</td><td>${b.segment || ''}</td><td>${(b.distance_m*D.u.distF).toFixed(2)}</td><td>${hms(b.offset_s)}</td>` +
    `<td>${(b.flow_m*D.u.shortF).toFixed(0)} ${D.u.short}</td><td>${(b.speed_before_ms*D.u.speedF).toFixed(0)} → ${(b.speed_after_ms*D.u.speedF).toFixed(0)}</td>` +
    `<td>${b.lat != null ? `<a href="https://www.openstreetmap.org/?mlat=${b.lat}&mlon=${b.lon}#map=18/${b.lat}/${b.lon}">map</a>` : ''}</td></tr>`).join('') : '<tr><td class="muted">none</td></tr>';
document.getElementById('note').textContent = 'Grit: difficulty from grade, turns and roughness (higher = harder). Flow: unnecessary braking per 100 m (lower = smoother). Generated by tools/mtb_analyze.py.';
</script></body></html>
"""


def write_html(ride: Ride, s: dict, path: str, u: Units) -> None:
    rows = []
    grit_win, flow_win = [], []
    kinds = terrain_kinds(ride.samples, 15.0)
    for x, kind in zip(ride.samples, kinds):
        grit_win.append((x.grit or 0.0, x.dt))
        flow_win.append(((x.flow or 0.0) if x.moving else 0.0, x.d_dist if x.moving else 0.0))
        g = sum(a for a, _ in grit_win[-WINDOW:]) / max(1e-9, sum(b for _, b in grit_win[-WINDOW:]))
        fl, fd = sum(a for a, _ in flow_win[-WINDOW:]), sum(b for _, b in flow_win[-WINDOW:])
        rows.append({
            "t": x.t, "off": round(x.t - ride.start, 1), "dist": round(x.dist, 1), "speed": round(x.speed, 2),
            "alt": None if x.alt is None else round(x.alt, 1), "lat": None if x.lat is None else round(x.lat, 6),
            "lon": None if x.lon is None else round(x.lon, 6), "grit60": round(g, 2),
            "flow60": round(flow_score(fl, fd), 2) if fd >= 50 else None, "brake": _r(x.brake, 2),
            "flow": _r(x.flow, 3), "rough": _r(x.rough, 3),
            "fa": x.fa_front, "cog": x.rear_teeth, "kind": kind, "power": x.power,
        })
    unit = {"dist": "mi" if u.imperial else "km", "distF": 1 / 1609.344 if u.imperial else 1 / 1000,
            "elev": "ft" if u.imperial else "m", "elevF": 3.28084 if u.imperial else 1,
            "short": "ft" if u.imperial else "m", "shortF": 3.28084 if u.imperial else 1,
            "speed": "mph" if u.imperial else "km/h", "speedF": 2.236936 if u.imperial else 3.6}
    data = json.dumps({"summary": s, "rows": rows, "u": unit}, separators=(",", ":"), default=str)
    with open(path, "w") as f:
        f.write(HTML_TEMPLATE.replace("__DATA__", data.replace("</", "<\\/")))
