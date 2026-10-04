// intervals.icu custom activity chart: MTB Jumps
// One bar per jump: airtime, coloured by estimated height; hover shows distance and speed.
// Needs the custom streams MtbJumpAir, MtbJumpDist and MtbJumpHeight.
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const imperial = !!(icu.athlete && icu.athlete.measurement_preference === 'feet')
  const lenF = imperial ? 3.28084 : 1, lenU = imperial ? 'ft' : 'm'
  const air = stream('MtbJumpAir') || [], dist = stream('MtbJumpDist') || [], height = stream('MtbJumpHeight') || []
  const time = stream('time') || []
  const x = [], y = [], color = [], text = []
  for (let i = 0; i < air.length; i++) {
    if ((air[i] || 0) <= 0) continue
    const t = time[i] != null ? time[i] : i
    const clock = Math.floor(t / 3600) + ':' + String(Math.floor(t % 3600 / 60)).padStart(2, '0') + ':' + String(Math.floor(t % 60)).padStart(2, '0')
    const d = (dist[i] || 0), h = (height[i] || 0)
    x.push('#' + (x.length + 1) + ' ' + clock)
    y.push(air[i])
    color.push(h * lenF)
    text.push((d * lenF).toFixed(1) + ' ' + lenU + ' · ~' + (h * lenF).toFixed(1) + ' ' + lenU + ' high · ' +
      (air[i] > 0 ? (imperial ? (d / air[i] * 2.236936).toFixed(0) + ' mph' : (d / air[i] * 3.6).toFixed(0) + ' km/h') : ''))
  }
  const data = [{
    x: x, y: y, type: 'bar', text: text, hovertemplate: '%{x}<br>%{y:.2f} s airtime<br>%{text}<extra></extra>',
    marker: { color: color, colorscale: 'YlOrRd', showscale: true, colorbar: { title: { text: lenU } } },
  }]
  const layout = {
    title: { text: x.length ? 'Jumps: ' + x.length + ', longest ' + Math.max(...y).toFixed(2) + ' s' : 'No jumps' },
    yaxis: { title: { text: 'Airtime (s)' } },
    margin: { t: 50, l: 50, r: 30, b: 80 },
  }
  chart = { data, layout }
}
