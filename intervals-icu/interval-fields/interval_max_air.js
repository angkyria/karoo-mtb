// intervals.icu custom interval field: Interval longest airtime
// Settings: Code IntMtbMaxAir · Units s · needs the custom stream MtbJumpAir
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const air = stream('MtbJumpAir')
  let best = 0
  if (air) for (let i = interval.start_index; i < interval.end_index; i++) best = Math.max(best, air[i] || 0)
  air ? best : null
}
