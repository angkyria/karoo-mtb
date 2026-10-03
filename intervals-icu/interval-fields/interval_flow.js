// intervals.icu custom interval field: Interval Flow (unnecessary braking per 100 m, lower = smoother)
// Settings: Code IntMtbFlow · Units flow · needs the custom stream mtb_flow
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const flow = stream('mtb_flow'), dist = icu.streams.distance, vel = stream('velocity_smooth')
  let f = 0, d = 0
  if (flow && dist) {
    for (let i = Math.max(1, interval.start_index); i < interval.end_index; i++) {
      if (vel && (vel[i] || 0) < 1) continue
      f += flow[i] || 0
      d += Math.max(0, (dist[i] || 0) - (dist[i - 1] || 0))
    }
  }
  flow && d >= 50 ? 100 * f / d : null
}
