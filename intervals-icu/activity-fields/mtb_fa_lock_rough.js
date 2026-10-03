// intervals.icu custom activity field: Flight Attendant locked on rough ground (s)
// Settings: Code MtbFaLockRough · Units s · tick "Processes fit file messages"
// Seconds in Lock while MTB Dynamics measured >= 0.9 g trail vibration.
{
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_fa_lock_rough ? s.mtb_fa_lock_rough.value : null
  if (v == null) {
    let n = 0, seen = false
    for (let m of icu.fit.record || []) {
      if (!m.front_suspension || !m.mtb_rough) continue
      seen = true
      if (m.front_suspension.value === 2 && m.mtb_rough.value >= 0.9) n++
    }
    v = seen ? n : null
  }
  v
}
