// intervals.icu custom interval field: most used rear cog in the selection (teeth)
// Settings: Code IntCog · Units T · needs the custom stream RearCog
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const cog = stream('RearCog')
  const seconds = {}
  if (cog) for (let i = interval.start_index; i < interval.end_index; i++) if (cog[i] != null) seconds[cog[i]] = (seconds[cog[i]] || 0) + 1
  let best = null
  for (const t in seconds) if (best == null || seconds[t] > seconds[best]) best = t
  best == null ? null : Number(best)
}
