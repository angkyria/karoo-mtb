// intervals.icu custom interval field: rear shifts in the selection
// Settings: Code IntShifts · Units shifts · needs the custom stream rear_cog
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const cog = stream('rear_cog')
  let shifts = 0, prev = null
  if (cog) for (let i = interval.start_index; i < interval.end_index; i++) {
    if (cog[i] == null) continue
    if (prev != null && cog[i] !== prev) shifts++
    prev = cog[i]
  }
  cog ? shifts : null
}
