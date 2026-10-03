// intervals.icu custom interval field: Interval Jumps
// Settings: Code IntMtbJumps · Units jumps · needs the custom stream mtb_jump_air
{
  const stream = code => { try { const s = icu.streams.get(code); if (s && s.data) return s.data } catch (e) {} return null }
  const air = stream('mtb_jump_air')
  let n = 0
  if (air) for (let i = interval.start_index; i < interval.end_index; i++) if ((air[i] || 0) > 0) n++
  air ? n : null
}
