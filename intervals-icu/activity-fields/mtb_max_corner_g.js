// intervals.icu custom activity field: MTB max cornering g
// Settings: Code MtbMaxCornerG · Units g · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_max_lat_g".
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_max_lat_g ? s.mtb_max_lat_g.value : null
  v
}
