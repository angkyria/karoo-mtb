// intervals.icu custom activity field: MTB Grit (ride difficulty)
// Settings: Code MtbGrit · Units kGrit · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_total_grit", Garmin MTB Dynamics fallback.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_total_grit ? s.mtb_total_grit.value : null
  if (v == null) {
    v = s && s.total_grit ? s.total_grit.value : null
  }
  v
}
