// intervals.icu custom activity field: MTB Jumps
// Settings: Code MtbJumps · Units jumps · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_jumps", Garmin MTB Dynamics fallback.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_jumps ? s.mtb_jumps.value : null
  if (v == null) {
    v = s && s.jump_count ? s.jump_count.value : (icu.fit.jump ? icu.fit.jump.length : null)
  }
  v
}
