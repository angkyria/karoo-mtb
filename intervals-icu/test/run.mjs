// Runs every intervals.icu script against a mocked `icu` object (node intervals-icu/test/run.mjs).
// The mock follows @intervals-icu/js-data-model: icu.fit.<message>[] with {value} fields,
// icu.streams.get(code).data, `data.setAt(fitTimestamp, value)` for streams, `interval`, `chart`.
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import assert from 'node:assert/strict'

const here = path.dirname(new URL(import.meta.url).pathname)
const root = path.join(here, '..')
const read = p => fs.readFileSync(path.join(root, p), 'utf8')

// ---- a synthetic 20 min ride: 10 min climb (+150 m), 6 min descent (-180 m), 4 min flat ----
const N = 1200, START = 1_100_000_000, LAG = 3
const ride = []
let dist = 0, alt = 500
for (let i = 0; i < N; i++) {
  const climb = i < 600, descent = i >= 600 && i < 960
  const v = climb ? 3 : descent ? 7 : 5
  dist += v
  alt += climb ? 0.25 : descent ? -0.5 : 0
  const lockedRough = i >= 900 && i < 910
  ride.push({
    i, v, dist, alt,
    grade: climb ? 8.3 : descent ? -7.1 : 0,
    fa: climb ? 1 : descent ? (lockedRough ? 2 : 0) : 2,      // Flight Attendant 0 Open, 1 Pedal, 2 Lock
    power: climb ? 220 : descent ? 40 : 150,
    cadence: climb ? 75 : descent ? (i % 10 === 0 ? 60 : 0) : 85,
    grit: climb ? 3 : descent ? 8 : 1.5,
    flow: descent && i % 30 === 5 ? 2.5 : 0,        // unnecessary braking every 30 s on the descent
    brake: descent && i % 30 === 5 ? 1.2 : 0,
    air: i === 700 ? 0.62 : i === 850 ? 0.9 : 0,
    rough: lockedRough ? 1.0 : descent ? 0.5 : 0.15,
  })
}
const f = value => ({ value })
const records = ride.map(r => {
  const lagged = ride[r.i - LAG]
  return {
    timestamp: f(START + r.i),
    mtb_grit: f(r.grit),
    mtb_flow: f(lagged ? lagged.flow : 0),            // written LAG s late like on the Karoo
    mtb_brake: f(lagged ? lagged.brake : 0),
    mtb_jump_air: f(r.air),
    mtb_rough: f(r.rough),
    front_suspension: f(r.fa),
    grade: f(r.grade),
    enhanced_speed: f(r.v),
    power: f(r.power),
    cadence: f(r.cadence),
    _name: 'record',
  }
})
// AXS rear shifts (FIT event 43): 21T, 28T for the climb, 18T downhill, 21T on the flat
const shiftAt = { 0: 21, 100: 28, 600: 18, 960: 21 }
const events = Object.entries(shiftAt).map(([i, teeth]) => ({
  _name: 'event', timestamp: f(START + Number(i)), event: { value: 43, valueName: 'rear_gear_change' }, rear_gear: f(teeth),
}))
const allMessages = []
for (const r of records) {
  const ev = events.find(e => e.timestamp.value === r.timestamp.value)
  if (ev) allMessages.push(ev)
  allMessages.push(r)
}
const session = {
  mtb_total_grit: f(ride.reduce((s, r) => s + r.grit, 0) / 1000), mtb_flow_score: f(1.23), mtb_jumps: f(2),
  mtb_max_air: f(0.9), mtb_total_air: f(1.52), mtb_score: f(64), mtb_descent_braking: f(12), mtb_corners: f(33),
  mtb_max_lat_g: f(0.71), mtb_flow_lag: f(LAG), total_distance: f(dist),
}
const garminSession = { total_grit: f(17.5), avg_flow: f(4.2), jump_count: f(1) }
const garminJumps = [{ hang_time: f(0.4) }, { hang_time: f(0.75) }]

function streamData() {
  const arr = new Array(N).fill(null)
  arr.startTimestamp = START
  arr.duration = N
  arr.setAt = (ts, value) => {
    const idx = Math.round(ts - START)
    if (idx >= 0 && idx < N) arr[idx] = value
  }
  return arr
}

function icuWith({ fitSession = session, fitJumps = [], customStreams = {} } = {}) {
  const builtIn = {
    distance: ride.map(r => r.dist), altitude: ride.map(r => r.alt), time: ride.map(r => r.i),
    velocity_smooth: ride.map(r => r.v), grade_smooth: ride.map(r => r.grade),
  }
  const all = { ...builtIn, ...customStreams }
  const streams = { ...builtIn, get: code => (all[code] ? { type: code, data: all[code] } : null) }
  return {
    fit: Object.assign([...allMessages], { record: records, session: [fitSession], jump: fitJumps, event: events }),
    streams,
    athlete: { measurement_preference: 'meters' },
    activity: {},
  }
}

function run(file, sandbox) {
  return vm.runInNewContext(read(file), sandbox, { filename: file })
}

let passed = 0
function test(name, fn) {
  fn()
  passed++
  console.log('ok -', name)
}

// ---- streams ----
let flowStream
test('mtb_flow stream re-aligns the lagged values', () => {
  const data = streamData()
  run('streams/mtb_flow.js', { icu: icuWith(), data })
  for (const r of ride) assert.equal(data[r.i] ?? 0, r.flow, `second ${r.i}`)
  flowStream = Array.from(data, v => v ?? 0)
})
let brakeStream
test('mtb_brake stream re-aligns the lagged values', () => {
  const data = streamData()
  run('streams/mtb_brake.js', { icu: icuWith(), data })
  assert.equal(data[605], 1.2)
  assert.equal(data[608] ?? 0, 0)
  brakeStream = Array.from(data, v => v ?? 0)
})
let gritStream
test('mtb_grit stream reads the developer field', () => {
  const data = streamData()
  run('streams/mtb_grit.js', { icu: icuWith(), data })
  assert.equal(data[10], 3)
  gritStream = Array.from(data, v => v ?? 0)
})
const custom = {
  mtb_grit: gritStream, mtb_flow: flowStream, mtb_brake: brakeStream,
  mtb_jump_air: ride.map(r => r.air), mtb_jump_dist: ride.map(r => r.air * r.v), mtb_jump_height: ride.map(r => r.air * r.air * 9.81 / 8),
  mtb_rough: ride.map(r => r.rough),
}

// ---- activity fields ----
test('activity fields read the Karoo session values', () => {
  const expect = {
    'mtb_grit.js': session.mtb_total_grit.value, 'mtb_flow.js': 1.23, 'mtb_jumps.js': 2, 'mtb_max_air.js': 0.9,
    'mtb_total_air.js': 1.52, 'mtb_score.js': 64, 'mtb_descent_braking.js': 12, 'mtb_corners.js': 33,
    'mtb_max_corner_g.js': 0.71,
  }
  for (const [file, value] of Object.entries(expect)) {
    assert.equal(run(`activity-fields/${file}`, { icu: icuWith() }), value, file)
  }
})
test('activity fields fall back to Garmin native MTB Dynamics', () => {
  const icu = icuWith({ fitSession: garminSession, fitJumps: garminJumps })
  assert.equal(run('activity-fields/mtb_grit.js', { icu }), 17.5)
  assert.equal(run('activity-fields/mtb_flow.js', { icu }), 4.2)
  assert.equal(run('activity-fields/mtb_jumps.js', { icu }), 1)
  assert.equal(run('activity-fields/mtb_max_air.js', { icu }), 0.75)
  assert.equal(run('activity-fields/mtb_total_air.js', { icu }), 1.15)
  assert.equal(run('activity-fields/mtb_score.js', { icu }), null)
})

// ---- interval fields ----
test('interval fields on the descent', () => {
  const icu = icuWith({ customStreams: custom })
  const interval = { start_index: 600, end_index: 960 }
  const grit = run('interval-fields/interval_grit.js', { icu, interval })
  assert.ok(Math.abs(grit - 360 * 8 / 1000) < 1e-9, `grit ${grit}`)
  const flow = run('interval-fields/interval_flow.js', { icu, interval })
  assert.ok(Math.abs(flow - 100 * (12 * 2.5) / (360 * 7)) < 0.05, `flow ${flow}`)
  assert.equal(run('interval-fields/interval_jumps.js', { icu, interval }), 2)
  assert.equal(run('interval-fields/interval_max_air.js', { icu, interval }), 0.9)
  const braking = run('interval-fields/interval_braking.js', { icu, interval })
  assert.ok(Math.abs(braking - 100 * 12 / 360) < 0.01, `braking ${braking}`)
  // 350 s at 0.5 g plus 10 s locked on 1.0 g ground
  assert.ok(Math.abs(run('interval-fields/interval_roughness.js', { icu, interval }) - (350 * 0.5 + 10 * 1.0) / 360) < 1e-9)
})
test('interval fields without MTB streams return null', () => {
  const icu = icuWith()
  const interval = { start_index: 0, end_index: 100 }
  for (const file of fs.readdirSync(path.join(root, 'interval-fields'))) {
    assert.equal(run(`interval-fields/${file}`, { icu, interval }), null, file)
  }
})

// ---- charts ----
test('MTB Dynamics chart', () => {
  const sandbox = { icu: icuWith({ customStreams: custom }) }
  run('charts/mtb_dynamics.js', sandbox)
  const { data, layout } = sandbox.chart
  assert.equal(data.length, 4)
  assert.equal(data[0].x.length, N)
  assert.equal(data[3].x.length, 2, 'two jump markers')
  assert.ok(data[1].y[300] > 2.9 && data[1].y[300] < 3.1, 'grit 60 s on the climb')
  assert.ok(layout.yaxis2)
})
test('MTB Jumps chart', () => {
  const sandbox = { icu: icuWith({ customStreams: custom }) }
  run('charts/mtb_jumps.js', sandbox)
  assert.deepEqual(Array.from(sandbox.chart.data[0].y), [0.62, 0.9])
  assert.match(sandbox.chart.layout.title.text, /Jumps: 2/)
})
test('MTB Trail Segments chart', () => {
  const sandbox = { icu: icuWith({ customStreams: custom }) }
  run('charts/mtb_segments.js', sandbox)
  const names = Array.from(sandbox.chart.data[0].cells.values[0])
  assert.deepEqual(names, ['Climb 1', 'Descent 1', 'Flat 1'])
  const jumps = Array.from(sandbox.chart.data[0].cells.values[8])
  assert.deepEqual(jumps, ['0', '2', '0'])
})

// ---- SRAM / RockShox ----
let cogStream
test('rear_cog stream forward-fills AXS shift events', () => {
  const data = streamData()
  run('streams/rear_cog.js', { icu: icuWith(), data })
  assert.equal(data[50], 21)
  assert.equal(data[300], 28)
  assert.equal(data[700], 18)
  assert.equal(data[1100], 21)
  cogStream = Array.from(data, v => v ?? null)
})
test('SRAM activity fields computed from records and events', () => {
  const icu = icuWith()
  const near = (a, b, eps = 0.01) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`)
  near(run('activity-fields/mtb_fa_open_desc.js', { icu }), 100 * 350 / 360)
  assert.equal(run('activity-fields/mtb_fa_lock_rough.js', { icu }), 10)
  near(run('activity-fields/mtb_shifts_km.js', { icu }), 4 / (dist / 1000), 1e-6)
  assert.equal(run('activity-fields/mtb_climb_power.js', { icu }), 220)
  near(run('activity-fields/mtb_desc_pedal.js', { icu }), 10)
})
test('SRAM activity fields prefer the Karoo session values', () => {
  const icu = icuWith({ fitSession: { ...session, mtb_fa_open_desc: f(55), mtb_fa_lock_rough: f(81), mtb_shifts_km: f(10.9),
    mtb_climb_power: f(215), mtb_desc_pedal: f(63) } })
  assert.equal(run('activity-fields/mtb_fa_open_desc.js', { icu }), 55)
  assert.equal(run('activity-fields/mtb_fa_lock_rough.js', { icu }), 81)
  assert.equal(run('activity-fields/mtb_shifts_km.js', { icu }), 10.9)
  assert.equal(run('activity-fields/mtb_climb_power.js', { icu }), 215)
  assert.equal(run('activity-fields/mtb_desc_pedal.js', { icu }), 63)
})
test('SRAM interval fields', () => {
  const icu = icuWith({ customStreams: { ...custom, fa_front: ride.map(r => r.fa), rear_cog: cogStream } })
  const descent = { start_index: 600, end_index: 960 }
  assert.ok(Math.abs(run('interval-fields/interval_fa_open.js', { icu, interval: descent }) - 100 * 350 / 360) < 1e-9)
  assert.ok(Math.abs(run('interval-fields/interval_fa_lock.js', { icu, interval: descent }) - 100 * 10 / 360) < 1e-9)
  assert.equal(run('interval-fields/interval_shifts.js', { icu, interval: { start_index: 590, end_index: 970 } }), 2)
  assert.equal(run('interval-fields/interval_cog.js', { icu, interval: descent }), 18)
})
test('Suspension & gears chart', () => {
  const sandbox = { icu: icuWith({ customStreams: { ...custom, fa_front: ride.map(r => r.fa), rear_cog: cogStream } }) }
  run('charts/mtb_bike.js', sandbox)
  const { data } = sandbox.chart
  assert.equal(data.length, 7)
  assert.deepEqual(Array.from(data[4].x), ['18T', '21T', '28T'])
  const climbMinutes = Array.from(data[4].y)
  assert.ok(Math.abs(climbMinutes[2] - 500 / 60) < 1e-9, `28T climbing minutes ${climbMinutes[2]}`)
})

console.log(`\n${passed} tests passed`)
