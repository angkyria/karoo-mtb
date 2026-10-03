// intervals.icu custom interval field: Interval Grit (difficulty of the selection / lap)
// Settings: Code IntMtbGrit · Units kGrit · needs the custom stream mtb_grit
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const grit = stream('mtb_grit')
  let sum = 0
  if (grit) for (let i = interval.start_index; i < interval.end_index; i++) sum += grit[i] || 0
  grit ? sum / 1000 : null
}
