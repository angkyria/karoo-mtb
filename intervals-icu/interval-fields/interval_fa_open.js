// intervals.icu custom interval field: Flight Attendant Open (% of the selection)
// Settings: Code IntFaOpen · Units % · needs the custom stream FaFront (record field front_suspension)
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const fa = stream('FaFront')
  let open = 0, n = 0
  if (fa) for (let i = interval.start_index; i < interval.end_index; i++) if (fa[i] != null) { n++; if (fa[i] === 0) open++ }
  n ? 100 * open / n : null
}
