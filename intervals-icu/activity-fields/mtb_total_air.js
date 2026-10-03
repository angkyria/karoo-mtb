// intervals.icu custom activity field: MTB total airtime
// Settings: Code MtbTotalAir · Units s · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_total_air", Garmin MTB Dynamics fallback.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_total_air ? s.mtb_total_air.value : null
  if (v == null) {
    for (let j of icu.fit.jump || []) if (j.hang_time) v = (v || 0) + j.hang_time.value
  }
  v
}
