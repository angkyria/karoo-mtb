package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class MtbEngineTest {

    @Test
    fun `smooth flat riding has low grit and no flow`() {
        val sim = RideSim().apply { start() }
        sim.ride(120, speed = { 5.0 }, vibrationG = 0.03)
        val s = sim.finish()
        assertTrue("avg grit ${s.grit.avgPerSec}", s.grit.avgPerSec < 2.0)
        assertEquals(0.0, s.flow.score, 0.05)
        assertEquals(0, s.jumps.count)
        assertEquals(600.0, s.distanceM, 1.0)
    }

    @Test
    fun `rough steep twisty trail has much more grit`() {
        val easy = RideSim().apply { start() }
        easy.ride(300, speed = { 5.0 }, vibrationG = 0.03)
        val hard = RideSim().apply { start() }
        hard.ride(300, speed = { 4.0 }, grade = { -15.0 }, yawRate = { if (it % 6 < 3) 0.8 else -0.8 }, vibrationG = 0.5)
        val e = easy.finish()
        val h = hard.finish()
        assertTrue("easy ${e.grit.totalK} hard ${h.grit.totalK}", h.grit.totalK > 3 * e.grit.totalK)
        assertTrue(h.score.difficulty > e.score.difficulty)
        assertNotNull(h.roughnessAvg)
        assertTrue(h.roughnessAvg!! > 0.3)
    }

    @Test
    fun `braking on a straight costs flow, braking before a tight corner does not`() {
        val brakeProfile = { i: Int ->
            when (i % 20) {
                in 0..9 -> 8.0
                10 -> 6.0
                11 -> 4.0
                12 -> 3.0
                else -> 3.0 + (i % 20 - 12) * 0.7
            }
        }
        val straight = RideSim().apply { start() }
        straight.ride(200, speed = brakeProfile)
        val cornering = RideSim().apply { start() }
        // Tight corner (3 m radius at 3 m/s) right after the braking zone.
        cornering.ride(200, speed = brakeProfile, yawRate = { if (it % 20 in 13..15) 1.0 else 0.0 })

        val s = straight.finish()
        val c = cornering.finish()
        assertTrue("straight flow ${s.flow.score}", s.flow.score > 5.0)
        assertTrue("corner flow ${c.flow.score} vs ${s.flow.score}", c.flow.score < s.flow.score / 3)
        assertTrue(c.cornering.count >= 5)
    }

    @Test
    fun `jump is detected, written to the record and reported with distance`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 })
        sim.jumpIn(0.5, 0.7)
        sim.ride(10, speed = { 6.0 })
        val summary = sim.finish()

        assertEquals(1, summary.jumps.count)
        val jump = summary.jumps.longest!!
        assertEquals(0.7, jump.airSec, 0.06)
        assertEquals(6.0 * jump.airSec, jump.distanceM, 0.01)
        assertEquals(Scoring.jumpHeight(jump.airSec, 0.0), jump.heightM, 1e-6)
        assertEquals(1, sim.landed.size)
        val records = sim.outputs.mapNotNull { it.record }.filter { it.jumpAir > 0 }
        assertEquals(1, records.size)
        assertEquals(jump.airSec, records[0].jumpAir, 1e-9)
    }

    @Test
    fun `jumps are written to storage once final`() {
        // Regression: jumps used to reach the summary but never events.jsonl (lost on restore).
        val sim = RideSim().apply { start() }
        sim.ride(5, speed = { 6.0 })
        sim.jumpIn(0.5, 0.6)
        sim.ride(2, speed = { 6.0 })
        assertEquals(0, sim.engine.drainForStorage().jumps.size) // still waiting for the barometer
        sim.ride(5, speed = { 6.0 })
        assertEquals(1, sim.engine.drainForStorage().jumps.size)

        // A jump right before the ride ends is stored by finish().
        sim.jumpIn(0.5, 0.5)
        sim.ride(2, speed = { 6.0 })
        sim.finish()
        assertEquals(1, sim.engine.drainForStorage().jumps.size)
    }

    @Test
    fun `steering wobble does not create huge lateral g`() {
        val sim = RideSim().apply { start() }
        // Bar oscillating ±1.5 rad/s at 8 m/s: heading barely changes on average.
        var tick = 0
        sim.ride(60, speed = { 8.0 }, yawRate = { tick++; if (it % 2 == 0) 1.5 else -1.5 })
        val s = sim.finish()
        assertTrue("max lateral ${s.cornering.maxLateralG}", s.cornering.maxLateralG <= Scoring.MAX_LATERAL_G)
    }

    @Test
    fun `slow free fall is not a jump`() {
        val sim = RideSim().apply { start() }
        sim.ride(5, speed = { 0.5 })
        sim.jumpIn(0.5, 0.7)
        sim.ride(5, speed = { 0.5 })
        assertEquals(0, sim.finish().jumps.count)
    }

    @Test
    fun `step-down flight is higher above the landing`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 }, altitude = { 200.0 })
        sim.jumpIn(0.2, 0.8)
        // Landing 2 m lower than the take-off.
        sim.ride(10, speed = { 6.0 }, altitude = { if (it == 0) 200.0 else 198.0 })
        val jump = sim.finish().jumps.longest!!
        assertNotNull(jump.dropM)
        assertTrue("height ${jump.heightM}", jump.heightM > Scoring.jumpHeight(0.8, 0.0) + 1.0)
    }

    @Test
    fun `climb then descent gives two segments`() {
        val sim = RideSim().apply { start() }
        sim.ride(200, speed = { 3.0 }, grade = { 10.0 }, altitude = { 100.0 + it * 0.5 })
        sim.ride(150, speed = { 8.0 }, grade = { -10.0 }, altitude = { 200.0 - it * 0.8 })
        val s = sim.finish()
        assertEquals(listOf("CLIMB", "DESCENT"), s.segments.map { it.type })
        assertEquals(100.0, s.segments[0].elevGainM, 3.0)
        assertEquals(120.0, s.segments[1].elevLossM, 3.0)
        assertTrue(s.descending.timeSec > 100)
        assertEquals(listOf("Climb 1", "Descent 1"), s.segments.map { it.name })
    }

    @Test
    fun `laps are reported separately`() {
        val sim = RideSim().apply { start() }
        sim.ride(60, speed = { 5.0 })
        sim.engine.markLap()
        sim.ride(30, speed = { 5.0 }, vibrationG = 0.4)
        val s = sim.finish()
        assertEquals(2, s.laps.size)
        assertEquals(300.0, s.laps[0].distanceM, 1.0)
        assertTrue(s.laps[1].gritAvg > s.laps[0].gritAvg)
    }

    @Test
    fun `pause stops accumulation`() {
        val sim = RideSim().apply { start() }
        sim.ride(30, speed = { 5.0 })
        val before = sim.engine.live().gritTotalK
        sim.engine.pause()
        sim.ride(30, speed = { 5.0 })
        assertEquals(before, sim.engine.live().gritTotalK, 1e-9)
        sim.engine.resume()
        sim.ride(30, speed = { 5.0 })
        assertTrue(sim.engine.live().gritTotalK > before)
    }

    @Test
    fun `restore rebuilds the same totals`() {
        val sim = RideSim().apply { start() }
        sim.ride(100, speed = { if (it % 10 < 5) 8.0 else 4.0 }, grade = { -8.0 }, vibrationG = 0.3)
        sim.jumpIn(0.3, 0.6)
        sim.ride(20, speed = { 6.0 })
        val original = sim.engine.sessionValues()
        val batch = sim.engine.drainForStorage()

        val restored = MtbEngine()
        restored.restore(
            startWallMs = sim.startWallMs,
            nowWallMs = sim.startWallMs + 200_000,
            nowElapsedMs = 42_000_000,
            restoredSamples = batch.samples,
            restoredJumps = sim.engine.finish(sim.startWallMs + 120_000, SummaryMeta("t", null, null)).jumps.list,
            restoredCorners = batch.corners,
        )
        val r = restored.sessionValues()
        // Restored data stops at the last processed sample (flow look-ahead), so allow a few seconds.
        assertEquals(original.totalGritK, r.totalGritK, original.totalGritK * 0.05)
        assertEquals(original.jumps, r.jumps)
        assertTrue(abs(original.flowScore - r.flowScore) < 1.0)
    }

    @Test
    fun `live metrics follow the ride`() {
        val sim = RideSim().apply { start() }
        sim.ride(90, speed = { 6.0 }, vibrationG = 0.3)
        val live = sim.engine.live()
        assertEquals(RideStatus.RECORDING, live.status)
        assertTrue(live.grit60 > 0)
        assertTrue(live.hasAccelerometer && live.hasGyroscope)
        assertNotNull(live.rough60)
        assertTrue(live.mtbScore in 0.0..100.0)
    }
}
