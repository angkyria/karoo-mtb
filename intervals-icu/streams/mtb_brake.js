// intervals.icu custom activity stream: MTB Braking (deceleration, m/s²)
// Settings: Code MtbBrake · Units m/s2 · tick "Processes fit file messages"
//
// Like mtb_flow, the Karoo writes mtb_brake mtb_flow_lag seconds late; realign it here.
{
  let session = icu.fit.session ? icu.fit.session[0] : null
  let lag = session && session.mtb_flow_lag ? session.mtb_flow_lag.value : 3
  for (let m of icu.fit.record || []) {
    if (m.timestamp && m.mtb_brake && m.mtb_brake.value != null) {
      data.setAt(m.timestamp.value - lag, m.mtb_brake.value)
    }
  }
}
