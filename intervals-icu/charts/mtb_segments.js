// intervals.icu custom activity chart: MTB Trail Segments
// Splits the ride into climbs, descents and flat sections (same rules as the Karoo app: 15 m
// elevation reversals, long flat stretches cut out) and shows Grit, Flow, braking and jumps for each.
// Needs the custom streams mtb_grit, mtb_flow, mtb_brake and mtb_jump_air.
{
  const H = 15
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const imperial = !!(icu.athlete && icu.athlete.measurement_preference === 'feet')
  const dist = stream('distance') || [], rawAlt = stream('altitude') || stream('fixed_altitude') || []
  const time = stream('time') || [], vel = stream('velocity_smooth') || []
  const grit = stream('mtb_grit') || [], flow = stream('mtb_flow') || [], brake = stream('mtb_brake') || [], air = stream('mtb_jump_air') || []
  const n = dist.length
  // Smoothed altitude (±5 samples), gaps filled.
  const filled = []
  let last = rawAlt.find(a => a != null)
  for (let i = 0; i < n; i++) { if (rawAlt[i] != null) last = rawAlt[i]; filled.push(last == null ? 0 : last) }
  const alt = filled.map((_, i) => {
    let s = 0, c = 0
    for (let j = Math.max(0, i - 5); j <= Math.min(n - 1, i + 5); j++) { s += filled[j]; c++ }
    return s / c
  })
  const classify = d => d >= 0.6 * H ? 'Climb' : d <= -0.6 * H ? 'Descent' : 'Flat'
  // Zig-zag pivots.
  const piv = [0]
  let dir = 0, hi = 0, lo = 0
  for (let i = 1; i < n; i++) {
    if (alt[i] > alt[hi]) hi = i
    if (alt[i] < alt[lo]) lo = i
    if (dir === 0 && alt[hi] - alt[lo] >= H) {
      if (lo < hi) { if (lo) piv.push(lo); dir = 1 } else { if (hi) piv.push(hi); dir = -1 }
    } else if (dir === 1 && alt[hi] - alt[i] >= H) { piv.push(hi); dir = -1; lo = i }
    else if (dir === -1 && alt[i] - alt[lo] >= H) { piv.push(lo); dir = 1; hi = i }
  }
  if (piv[piv.length - 1] !== n - 1) piv.push(n - 1)
  // Flat runs (grade < 2.5 % over ±15 samples, >= 400 m) are cut out of climbs / descents.
  const flat = []
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, i - 15), b = Math.min(n - 1, i + 15), d = (dist[b] || 0) - (dist[a] || 0)
    flat.push(d > 20 && Math.abs(100 * (alt[b] - alt[a]) / d) < 2.5)
  }
  const pieces = []
  for (let k = 0; k + 1 < piv.length; k++) {
    const a = piv[k], b = piv[k + 1]
    if (b <= a) continue
    const kind = classify(alt[b] - alt[a])
    if (kind === 'Flat') { pieces.push([kind, a, b]); continue }
    let cursor = a, i = a
    while (i <= b) {
      if (!flat[i]) { i++; continue }
      let j = i
      while (j + 1 <= b && flat[j + 1]) j++
      if ((dist[j] || 0) - (dist[i] || 0) >= 400) {
        if (i > cursor) pieces.push([classify(alt[i] - alt[cursor]), cursor, i])
        pieces.push(['Flat', i, j]); cursor = j
      }
      i = j + 1
    }
    if (b > cursor) pieces.push([classify(alt[b] - alt[cursor]), cursor, b])
  }
  const segs = []
  for (const p of pieces) {
    const prev = segs[segs.length - 1]
    if (prev && prev[0] === p[0]) prev[2] = p[2]; else segs.push(p.slice())
  }
  // Stats per segment.
  const count = {}
  const rows = { name: [], dist: [], time: [], elev: [], grade: [], grit: [], flow: [], brake: [], jumps: [] }
  const colors = []
  for (const [kind, a, b] of segs) {
    count[kind] = (count[kind] || 0) + 1
    let g = 0, f = 0, fd = 0, mov = 0, br = 0, j = 0
    for (let i = a + 1; i <= b; i++) {
      const step = Math.max(0, (dist[i] || 0) - (dist[i - 1] || 0))
      g += grit[i] || 0
      if ((air[i] || 0) > 0) j++
      if ((vel[i] || 0) >= 1) { mov++; f += flow[i] || 0; fd += step; if ((brake[i] || 0) >= 0.6) br++ }
    }
    const d = (dist[b] || 0) - (dist[a] || 0), dz = alt[b] - alt[a], secs = (time[b] || b) - (time[a] || a)
    rows.name.push(kind + ' ' + count[kind])
    rows.dist.push(imperial ? (d / 1609.344).toFixed(2) + ' mi' : (d / 1000).toFixed(2) + ' km')
    rows.time.push(Math.floor(secs / 60) + ':' + String(Math.round(secs % 60)).padStart(2, '0'))
    rows.elev.push((dz >= 0 ? '+' : '') + (imperial ? (dz * 3.28084).toFixed(0) + ' ft' : dz.toFixed(0) + ' m'))
    rows.grade.push((d > 10 ? 100 * dz / d : 0).toFixed(1) + ' %')
    rows.grit.push(grit.length ? (g / 1000).toFixed(1) : '–')
    rows.flow.push(flow.length && fd >= 50 ? (100 * f / fd).toFixed(1) : '–')
    rows.brake.push(brake.length && mov ? (100 * br / mov).toFixed(0) + ' %' : '–')
    rows.jumps.push(air.length ? String(j) : '–')
    colors.push(kind === 'Climb' ? 'rgba(216,67,21,0.12)' : kind === 'Descent' ? 'rgba(21,101,192,0.12)' : 'rgba(0,0,0,0)')
  }
  const cols = ['name', 'dist', 'time', 'elev', 'grade', 'grit', 'flow', 'brake', 'jumps']
  const data = [{
    type: 'table',
    header: { values: ['Segment', 'Distance', 'Time', 'Elevation', 'Grade', 'Grit (k)', 'Flow', 'Braking', 'Jumps'], align: 'left', font: { size: 12 } },
    cells: { values: cols.map(c => rows[c]), align: 'left', fill: { color: [colors] }, height: 24 },
  }]
  const layout = { title: { text: 'Trail segments' }, margin: { t: 40, l: 10, r: 10, b: 10 } }
  chart = { data, layout }
}
