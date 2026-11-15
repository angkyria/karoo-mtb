// Browser analyser pin report against testdata/pins_fixture.json (node tools/tests/pins.test.mjs).
// tools/tests/test_pins.py checks tools/mtbdyn/pins.py against the same file.
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import { passes, rideReport, singlePass, parseTrack, parseJumps } from '../../docs/analyser/pins.mjs'

const here = path.dirname(new URL(import.meta.url).pathname)
const fx = JSON.parse(fs.readFileSync(path.join(here, '..', '..', 'testdata', 'pins_fixture.json'), 'utf8'))
const round = (x, n = 6) => Math.round(x * 10 ** n) / 10 ** n
let n = 0
const test = (name, fn) => { fn(); n++; console.log('ok', name) }

test('fixture report matches the Python analyser', () => {
  const r = rideReport(fx.track, fx.jumps, fx.pins)
  const want = fx.expected
  assert.equal(r.jumpPasses, want.jump_passes)
  assert.equal(r.counted, want.counted)
  assert.equal(r.nojumpCounted, want.nojump_counted)
  assert.deepEqual(r.elsewhere, want.elsewhere)
  assert.deepEqual(r.passes.map(p => ({ pin: p.pin, t: round(p.t - fx.t0), d: round(p.d), jump: p.jump })), want.passes)
})

test('a far pin has no passes', () => {
  assert.deepEqual(passes(fx.track, fx.pins[3]), [])
})

test('a jump counts one pass only', () => {
  const r = rideReport(fx.track, [[1, fx.t0 + 10.5], [2, fx.t0 + 10.6]], fx.pins.slice(0, 1))
  assert.equal(r.counted, 1)
  assert.deepEqual(r.elsewhere, [2])
})

test('single pass drops the way back once it is more than a minute later', () => {
  const lines = singlePass(fx.track)
  const drawn = lines.flat()
  // out 0..60 s, back 61..120 s at 10 m/s: a point is a repeat once a point within 12 m is > 60 s older,
  // first at 90 s (300 m, 10 m from the 29 s point)
  assert.equal(drawn.length, 90)
  assert.deepEqual(drawn[drawn.length - 1], [fx.track[89][1], fx.track[89][2]])
})

test('parses samples.csv and events.jsonl', () => {
  const csv = 'wall_ms,dt,lat,lon\n1790000000000,1,35.1,33.2\n1790000001000,1,0,0\n1790000002000,1,,\n'
  assert.deepEqual(parseTrack(csv), [[1790000000, 35.1, 33.2]])
  const jsonl = '{"jump":null,"marker":null}\n{"jump":{"n":1,"takeoffWallMs":1790000000500,"airSec":0.2,"lat":35,"lon":33}}\nnot json\n'
  const j = parseJumps(jsonl)
  assert.equal(j.length, 1)
  assert.equal(j[0].t, 1790000000.5)
})

console.log(`${n} pin tests passed`)
