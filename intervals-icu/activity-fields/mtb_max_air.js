// intervals.icu custom activity field: MTB longest airtime
// Settings: Code MtbMaxAir · Units s · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_max_air", Garmin MTB Dynamics fallback.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_max_air ? s.mtb_max_air.value : null
  if (v == null) {
    for (let j of icu.fit.jump || []) if (j.hang_time && (v == null || j.hang_time.value > v)) v = j.hang_time.value
  }
  v
}
