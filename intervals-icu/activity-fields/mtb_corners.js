// intervals.icu custom activity field: MTB corners
// Settings: Code MtbCorners · Units corners · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_corners".
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_corners ? s.mtb_corners.value : null
  v
}
