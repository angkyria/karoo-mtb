// intervals.icu custom activity field: pedalling on descents (% of descending time)
// Settings: Code MtbDescPedal · Units % · tick "Processes fit file messages"
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_desc_pedal ? s.mtb_desc_pedal.value : null
  if (v == null) {
    let ped = 0, n = 0
    for (let m of icu.fit.record || []) {
      if (!m.grade || m.grade.value > -2.5) continue
      let speed = m.enhanced_speed || m.speed
      if (speed && speed.value < 1) continue
      n++
      if (m.cadence && m.cadence.value > 0) ped++
    }
    v = n >= 30 ? 100 * ped / n : null
  }
  v
}
