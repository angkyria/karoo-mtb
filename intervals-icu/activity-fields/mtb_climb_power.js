// intervals.icu custom activity field: average power on climbs (W)
// Settings: Code MtbClimbPower · Units W · tick "Processes fit file messages"
// Session field mtb_climb_power, else records with grade >= 2.5 % and speed >= 1 m/s.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_climb_power ? s.mtb_climb_power.value : null
  if (v == null) {
    let sum = 0, n = 0
    for (let m of icu.fit.record || []) {
      if (!m.power || !m.grade || m.grade.value < 2.5) continue
      let speed = m.enhanced_speed || m.speed
      if (speed && speed.value < 1) continue
      sum += m.power.value
      n++
    }
    v = n >= 30 ? sum / n : null
  }
  v
}
