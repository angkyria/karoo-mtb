// intervals.icu custom activity chart: MTB Dynamics
// Altitude profile with Grit (60 s) and Flow (60 s) on top and every jump marked.
// Needs the custom streams mtb_grit, mtb_flow and mtb_jump_air (see intervals-icu/README.md).
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const imperial = !!(icu.athlete && icu.athlete.measurement_preference === 'feet')
  const distF = imperial ? 1 / 1609.344 : 1 / 1000, altF = imperial ? 3.28084 : 1
  const dist = stream('distance') || [], alt = stream('altitude') || stream('fixed_altitude') || []
  const vel = stream('velocity_smooth') || []
  const grit = stream('mtb_grit') || [], flow = stream('mtb_flow') || [], air = stream('mtb_jump_air') || []
  const n = dist.length
  const W = 60
  const x = [], altY = [], grit60 = [], flow60 = []
  const step = [], moving = []
  let g = 0, f = 0, d = 0
  for (let i = 0; i < n; i++) {
    step[i] = i > 0 ? Math.max(0, (dist[i] || 0) - (dist[i - 1] || 0)) : 0
    moving[i] = (vel[i] || 0) >= 1
    g += grit[i] || 0
    if (moving[i]) { f += flow[i] || 0; d += step[i] }
    if (i >= W) {
      g -= grit[i - W] || 0
      if (moving[i - W]) { f -= flow[i - W] || 0; d -= step[i - W] }
    }
    x.push((dist[i] || 0) * distF)
    altY.push(alt[i] == null ? null : alt[i] * altF)
    grit60.push(grit.length ? g / Math.min(i + 1, W) : null)
    flow60.push(flow.length && d >= 50 ? 100 * f / d : null)
  }
  const jx = [], jy = [], js = [], jt = []
  for (let i = 0; i < n; i++) {
    if ((air[i] || 0) > 0) {
      jx.push(x[i]); jy.push(altY[i]); js.push(8 + air[i] * 14); jt.push(air[i].toFixed(2) + ' s')
    }
  }
  const data = [
    { x: x, y: altY, name: 'Altitude', type: 'scatter', fill: 'tozeroy', line: { color: '#90a4ae', width: 1 }, hoverinfo: 'skip' },
    { x: x, y: grit60, name: 'Grit 60 s', yaxis: 'y2', type: 'scatter', line: { color: '#d84315', width: 2 } },
    { x: x, y: flow60, name: 'Flow 60 s', yaxis: 'y2', type: 'scatter', line: { color: '#1565c0', width: 2 } },
    { x: jx, y: jy, name: 'Jumps', mode: 'markers', type: 'scatter', text: jt, marker: { color: '#ff6d00', size: js } },
  ]
  const layout = {
    title: { text: 'MTB Dynamics' },
    xaxis: { title: { text: imperial ? 'mi' : 'km' } },
    yaxis: { title: { text: imperial ? 'ft' : 'm' } },
    yaxis2: { title: { text: 'Grit /s · Flow' }, overlaying: 'y', side: 'right', rangemode: 'tozero', showgrid: false },
    legend: { orientation: 'h', y: 1.12 },
    margin: { t: 50, l: 50, r: 50, b: 40 },
  }
  chart = { data, layout }
}
