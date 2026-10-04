// intervals.icu custom activity field: MTB Jumps
// Settings: Code MtbJumps · Units jumps · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_jumps", Garmin MTB Dynamics fallback.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_jumps ? s.mtb_jumps.value : null
  if (v == null) {
    // Empty rather than 0 for rides without MTB Dynamics: intervals.icu gives every ride a jump list.
    if (s && s.jump_count) v = s.jump_count.value
    else if (icu.fit.jump && icu.fit.jump.length) v = icu.fit.jump.length
  }
  v
}
