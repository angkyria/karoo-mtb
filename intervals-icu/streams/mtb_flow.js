// intervals.icu custom activity stream: MTB Flow (unnecessary braking, metres per second)
// Settings: Code MtbFlow · Units m · tick "Processes fit file messages"
//
// The Karoo writes mtb_flow a few seconds late (Flow looks ahead: braking before a tight corner
// is fine). This script moves every value back to the second it belongs to.
// Garmin Edge files: falls back to the native "flow" record field.
{
  let session = icu.fit.session ? icu.fit.session[0] : null
  let lag = session && session.mtb_flow_lag ? session.mtb_flow_lag.value : 3
  for (let m of icu.fit.record || []) {
    let ts = m.timestamp
    if (!ts) continue
    if (m.mtb_flow && m.mtb_flow.value != null) {
      data.setAt(ts.value - lag, m.mtb_flow.value)
    } else if (m.flow && m.flow.value != null) {
      data.setAt(ts.value, m.flow.value)
    }
  }
}
