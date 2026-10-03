// intervals.icu custom activity field: MTB score (0-100)
// Settings: Code MtbScore · Units score · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_score".
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_score ? s.mtb_score.value : null
  v
}
