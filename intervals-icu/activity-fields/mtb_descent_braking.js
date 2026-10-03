// intervals.icu custom activity field: MTB descent braking
// Settings: Code MtbDescentBraking · Units % · tick "Processes fit file messages"
// Karoo MTB Dynamics session field "mtb_descent_braking".
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_descent_braking ? s.mtb_descent_braking.value : null
  v
}
