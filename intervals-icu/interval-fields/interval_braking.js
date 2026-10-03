// intervals.icu custom interval field: Interval braking (% of moving time slowing down hard)
// Settings: Code IntMtbBraking · Units % · needs the custom stream mtb_brake
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const brake = stream('mtb_brake'), vel = stream('velocity_smooth')
  let moving = 0, braking = 0
  if (brake) {
    for (let i = interval.start_index; i < interval.end_index; i++) {
      if (vel && (vel[i] || 0) < 1) continue
      moving++
      if ((brake[i] || 0) >= 0.6) braking++
    }
  }
  brake && moving ? 100 * braking / moving : null
}
