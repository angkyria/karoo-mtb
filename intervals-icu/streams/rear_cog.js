// intervals.icu custom activity stream: Rear cog (teeth) from SRAM AXS shifts
// Settings: Code RearCog · Units T · tick "Processes fit file messages"
//
// The Karoo writes one FIT event per rear shift (rear_gear = teeth). This turns them into a
// second-by-second "cog in use" stream.
{
  // FIT event 43 = rear_gear_change (name casing differs between FIT SDKs)
  const isRearShift = m => m.event && (m.event.value === 43 || String(m.event.valueName).toLowerCase() === 'rear_gear_change')
  let teeth = null
  for (let m of icu.fit) {
    if (m._name === 'event' && isRearShift(m) && m.rear_gear) {
      teeth = m.rear_gear.value
    } else if (m._name === 'record' && m.timestamp && teeth != null) {
      data.setAt(m.timestamp.value, teeth)
    }
  }
}
