// intervals.icu custom activity field: AXS shifts per km
// Settings: Code MtbShiftsKm · Units /km · tick "Processes fit file messages"
{
  // FIT event 43 = rear_gear_change (name casing differs between FIT SDKs)
  const isRearShift = m => m.event && (m.event.value === 43 || String(m.event.valueName).toLowerCase() === 'rear_gear_change')
  let s = icu.fit.session ? icu.fit.session[0] : null
  let v = s && s.mtb_shifts_km ? s.mtb_shifts_km.value : null
  if (v == null) {
    let shifts = 0
    for (let e of icu.fit.event || []) if (isRearShift(e)) shifts++
    let km = s && s.total_distance ? s.total_distance.value / 1000 : 0
    v = km > 0.5 && shifts > 0 ? shifts / km : null
  }
  v
}
