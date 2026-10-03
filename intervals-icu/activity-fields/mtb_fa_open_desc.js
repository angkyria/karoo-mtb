// intervals.icu custom activity field: Flight Attendant Open on descents (%)
// Settings: Code MtbFaOpenDesc · Units % · tick "Processes fit file messages"
// Session field mtb_fa_open_desc (MTB Dynamics 0.2+), else computed from the Karoo's
// front_suspension record field (0 Open, 1 Pedal, 2 Lock) on records with grade <= -2.5 %.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_fa_open_desc ? s.mtb_fa_open_desc.value : null
  if (v == null) {
    let open = 0, n = 0
    for (let m of icu.fit.record || []) {
      if (!m.front_suspension || !m.grade || m.grade.value > -2.5) continue
      let speed = m.enhanced_speed || m.speed
      if (speed && speed.value < 1) continue
      n++
      if (m.front_suspension.value === 0) open++
    }
    v = n >= 30 ? 100 * open / n : null
  }
  v
}
