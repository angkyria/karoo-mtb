// intervals.icu custom activity field: MTB Flow (lower = smoother)
// Settings: Code MtbFlow · Units flow · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_flow_score", Garmin MTB Dynamics fallback.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_flow_score ? s.mtb_flow_score.value : null
  if (v == null) {
    v = s && s.avg_flow ? s.avg_flow.value : null
  }
  v
}
