// intervals.icu custom interval field: Interval trail roughness (average vibration, g)
// Settings: Code IntMtbRough · Units g · needs the custom stream MtbRough
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const rough = stream('MtbRough')
  let sum = 0, n = 0
  if (rough) for (let i = interval.start_index; i < interval.end_index; i++) if (rough[i] != null && rough[i] > 0) { sum += rough[i]; n++ }
  n ? sum / n : null
}
