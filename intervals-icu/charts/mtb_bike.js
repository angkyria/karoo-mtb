// intervals.icu custom activity chart: Suspension & gears
// Flight Attendant state (Open / Pedal / Lock) as a coloured band with the rear cog in use on top,
// plus minutes per cog split into climbing / flat / descending.
// Needs the custom streams FaFront (record field front_suspension) and RearCog (streams/rear_cog.js).
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const imperial = !!(icu.athlete && icu.athlete.measurement_preference === 'feet')
  const distF = imperial ? 1 / 1609.344 : 1 / 1000
  const dist = stream('distance') || [], fa = stream('FaFront') || [], cog = stream('RearCog') || []
  const grade = stream('grade_smooth') || [], vel = stream('velocity_smooth') || []
  const x = dist.map(d => (d || 0) * distF)
  const names = ['Open', 'Pedal', 'Lock'], colors = ['#2e7d32', '#f9a825', '#c62828']
  const data = []
  // Each band bar reaches to the next sample: Plotly would otherwise size every bar by the smallest
  // gap (stops), leaving thin stripes instead of a band.
  const dx = x.map((v, i) => Math.max((i + 1 < x.length ? x[i + 1] : v) - v, 0))
  for (let code = 0; code < 3; code++) {
    data.push({ x: x, y: fa.map(v => (v === code ? 1 : null)), type: 'bar', name: 'FA ' + names[code],
      width: dx, offset: 0, marker: { color: colors[code], line: { width: 0 } }, hoverinfo: 'name', xaxis: 'x', yaxis: 'y' })
  }
  data.push({ x: x, y: cog.map(v => (v == null ? null : v)), name: 'Rear cog (T)', type: 'scatter',
    line: { shape: 'hv', color: '#37474f', width: 1.5 }, xaxis: 'x', yaxis: 'y2' })
  // Minutes per cog by terrain (grade from intervals.icu's smoothed grade).
  const kinds = [['Climb', '#d84315'], ['Flat', '#90a4ae'], ['Descent', '#1565c0']]
  const teeth = [...new Set(cog.filter(v => v != null))].sort((a, b) => a - b)
  for (const [kind, color] of kinds) {
    data.push({
      x: teeth.map(t => t + 'T'), type: 'bar', name: kind, marker: { color: color }, xaxis: 'x2', yaxis: 'y3',
      y: teeth.map(t => {
        let n = 0
        for (let i = 0; i < cog.length; i++) {
          if (cog[i] !== t || (vel[i] || 0) < 1) continue
          const g = grade[i] || 0
          const k = g >= 2.5 ? 'Climb' : g <= -2.5 ? 'Descent' : 'Flat'
          if (k === kind) n++
        }
        return n / 60
      }),
    })
  }
  // Two panels by explicit domains: a Plotly grid would put the cog axis (y2, overlaying y) in the
  // second row and leave the minutes axis (y3) spanning the whole chart.
  const layout = {
    title: { text: 'Suspension & gears' },
    barmode: 'stack', bargap: 0,
    xaxis: { title: { text: imperial ? 'mi' : 'km' }, anchor: 'y' },
    yaxis: { visible: false, range: [0, 1], domain: [0.58, 1] },
    yaxis2: { overlaying: 'y', side: 'right', autorange: 'reversed', title: { text: 'cog (T)' } },
    xaxis2: { title: { text: 'Rear cog' }, anchor: 'y3', type: 'category' },
    yaxis3: { title: { text: 'minutes' }, domain: [0, 0.4], anchor: 'x2' },
    legend: { orientation: 'h', y: 1.15 },
    margin: { t: 60, l: 50, r: 50, b: 40 },
    height: 600,
  }
  chart = { data, layout }
}
