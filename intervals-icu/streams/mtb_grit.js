// intervals.icu custom activity stream: MTB Grit (grit points per second)
// Settings: Code MtbGrit · Units grit · tick "Processes fit file messages"
//
// Only needed if you also ride with a Garmin: it reads the Karoo developer field mtb_grit and
// falls back to Garmin's native "grit" field. Karoo-only riders can instead create the stream
// with Record field = mtb_grit (no script).
{
  for (let m of icu.fit.record || []) {
    if (!m.timestamp) continue
    let f = m.mtb_grit || m.grit
    if (f && f.value != null) data.setAt(m.timestamp.value, f.value)
  }
}
