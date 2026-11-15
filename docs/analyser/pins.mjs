// Jump pins: every pass over each pin and whether the Karoo counted it.
// Same rules as tools/mtbdyn/pins.py; testdata/pins_fixture.json keeps the two in step.

export const PASS_RADIUS_M = 15   // a pass = the track comes this close to the pin
export const PASS_GAP_S = 20      // closer moments further apart than this are separate passes
export const MATCH_S = 2.5        // a Karoo jump counts a pass when it takes off this close in time to the closest approach
export const M_PER_DEG = 111320

function xy (lat, lon, lat0, lon0) {
  return [(lon - lon0) * M_PER_DEG * Math.cos(lat0 * Math.PI / 180), (lat - lat0) * M_PER_DEG]
}

/** Passes over `pin` along `track` ([t, lat, lon], t in s): closest approach time and distance. */
export function passes (track, pin) {
  const out = []
  let cur = null
  for (let i = 1; i < track.length; i++) {
    const [ta, la, oa] = track[i - 1]
    const [tb, lb, ob] = track[i]
    const [ax, ay] = xy(la, oa, pin.lat, pin.lon)
    const [bx, by] = xy(lb, ob, pin.lat, pin.lon)
    const dx = bx - ax, dy = by - ay
    const seg = dx * dx + dy * dy
    const f = seg === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / seg))
    const d = Math.hypot(ax + f * dx, ay + f * dy)
    if (d > PASS_RADIUS_M) continue
    const t = ta + f * (tb - ta)
    if (cur && t - cur.last <= PASS_GAP_S) {
      cur.last = t
      if (d < cur.d) { cur.d = d; cur.t = t }
    } else {
      cur = { t, d, last: t }
      out.push(cur)
    }
  }
  return out.map(p => ({ t: p.t, d: p.d }))
}

/** `jumps` = [n, take-off t] of the Karoo's jumps. Each jump counts at most one pass, the nearest in time. */
export function rideReport (track, jumps, pins) {
  const rows = []
  pins.forEach((pin, k) => {
    for (const p of passes(track, pin)) rows.push({ pin: k, label: pin.label, t: p.t, d: p.d, jump: null })
  })
  for (const [n, t] of [...jumps].sort((a, b) => a[1] - b[1])) {
    let best = -1, bestDt = Infinity
    rows.forEach((r, i) => {
      const dt = Math.abs(t - r.t)
      if (r.jump === null && dt <= MATCH_S && dt < bestDt) { best = i; bestDt = dt }
    })
    if (best >= 0) rows[best].jump = n
  }
  const used = new Set(rows.filter(r => r.jump !== null).map(r => r.jump))
  rows.sort((a, b) => a.t - b.t)
  const jumpRows = rows.filter(r => r.label === 'jump')
  return {
    passes: rows,
    jumpPasses: jumpRows.length,
    counted: jumpRows.filter(r => r.jump !== null).length,
    nojumpCounted: rows.filter(r => r.label === 'nojump' && r.jump !== null).length,
    elsewhere: jumps.map(j => j[0]).filter(n => !used.has(n)).sort((a, b) => a - b),
  }
}

/** Draw each path once: a point within `radiusM` of a point drawn more than a minute earlier is a repeat pass. */
export function singlePass (points, radiusM = 12) {
  const cell = 0.00015, grid = new Map(), lines = []
  let cur = []
  const dist = (a, b) => {
    const c = Math.cos(a[1] * Math.PI / 180)
    return Math.hypot((a[1] - b[1]) * M_PER_DEG, (a[2] - b[2]) * M_PER_DEG * c)
  }
  for (const p of points) {
    const gx = Math.floor(p[1] / cell), gy = Math.floor(p[2] / cell)
    let repeat = false
    for (let dx = -1; dx <= 1 && !repeat; dx++) {
      for (let dy = -1; dy <= 1 && !repeat; dy++) {
        for (const q of grid.get(`${gx + dx},${gy + dy}`) || []) {
          if (p[0] - q[0] > 60 && dist(p, q) < radiusM) { repeat = true; break }
        }
      }
    }
    if (repeat) { if (cur.length > 1) lines.push(cur); cur = []; continue }
    cur.push([p[1], p[2]])
    const key = `${gx},${gy}`
    if (!grid.has(key)) grid.set(key, [])
    grid.get(key).push(p)
  }
  if (cur.length > 1) lines.push(cur)
  return lines
}

/** samples.csv text → [t (s), lat, lon] with a position. */
export function parseTrack (csv) {
  const lines = csv.split(/\r?\n/)
  const head = lines[0].split(',')
  const it = head.indexOf('wall_ms'), ila = head.indexOf('lat'), ilo = head.indexOf('lon')
  const out = []
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i]) continue
    const c = lines[i].split(',')
    const lat = parseFloat(c[ila]), lon = parseFloat(c[ilo])
    if (!isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) continue
    out.push([parseInt(c[it], 10) / 1000, lat, lon])
  }
  return out
}

/** events.jsonl text → the Karoo's jumps {n, t (s), lat, lon, airSec, …}. */
export function parseJumps (jsonl) {
  const out = []
  for (const line of jsonl.split(/\r?\n/)) {
    if (!line.trim()) continue
    let e
    try { e = JSON.parse(line) } catch { continue }
    const j = e.jump
    if (j && typeof j.takeoffWallMs === 'number') out.push({ ...j, t: j.takeoffWallMs / 1000 })
  }
  return out
}
