package io.github.angkyria.karoomtb.storage

import io.github.angkyria.karoomtb.engine.MtbEngine
import io.github.angkyria.karoomtb.engine.RideSim
import io.github.angkyria.karoomtb.engine.SummaryMeta
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RideStoreCsvTest {
    @Test
    fun `csv round trip keeps everything a restore needs`() {
        val sim = RideSim().apply { start() }
        sim.ride(60, speed = { if (it % 10 < 5) 7.0 else 3.0 }, grade = { -9.0 }, altitude = { 300.0 - it }, vibrationG = 0.3)
        val batch = sim.engine.drainForStorage()
        assertTrue(batch.samples.isNotEmpty())

        val parsed = batch.samples.map { RideStore.fromCsv(RideStore.toCsv(it)) }
        for ((a, b) in batch.samples.zip(parsed)) {
            assertEquals(a.wallMs, b.wallMs)
            assertEquals(a.speed, b.speed, 0.01)
            assertEquals(a.grit, b.grit, 0.001)
            assertEquals(a.flow, b.flow, 0.001)
            assertEquals(a.rough, b.rough, 0.001)
            assertEquals(a.moving, b.moving)
            assertTrue(b.processed)
        }

        // A ride rebuilt from the CSV produces the same summary numbers.
        val original = sim.finish()
        val replay = MtbEngine()
        replay.restore(sim.startWallMs, parsed.last().wallMs, 9_000_000, parsed, original.jumps.list, emptyList())
        val restored = replay.finish(parsed.last().wallMs + 1000, SummaryMeta("t", null, null))
        assertEquals(original.grit.totalK, restored.grit.totalK, original.grit.totalK * 0.06)
        assertEquals(original.flow.score, restored.flow.score, 0.5)
        assertEquals(original.segments.size, restored.segments.size)
    }

    @Test
    fun `rows of older versions without bike columns still load`() {
        val line = "1790000000000,1.000,10.0,5.00,5.00,0.0,,,,,0.000,0.0000,0.000,1.250,1,0,0,0.00,0.000,0.000,0.000"
        val s = RideStore.fromCsv(line)
        assertTrue(s.altitude.isNaN())
        assertTrue(s.rough.isNaN())
        assertTrue(s.power.isNaN())
        assertEquals(-1, s.faFront)
        assertEquals(-1, s.rearTeeth)
        assertEquals(21, line.split(',').size)
    }

    @Test
    fun `bike columns round trip and stay empty when nothing is paired`() {
        val sim = RideSim().apply { start() }
        sim.ride(20, speed = { 5.0 }, each = {
            sim.engine.updatePower(if (it < 10) 210.0 else null)
            sim.engine.updateCadence(82.0)
            sim.engine.updateBalance(48.0)
            sim.engine.updateSuspension(front = it % 3, rear = 2, effortZone = 1)
            sim.engine.updateGears(4, 32, sim.elapsedMs, sim.wallMs())
        })
        val samples = sim.engine.drainForStorage().samples
        val lines = samples.map { RideStore.toCsv(it) }
        assertEquals(RideStore.CSV_HEADER.split(',').size, lines.first().split(',').size)
        val parsed = lines.map { RideStore.fromCsv(it) }
        for ((a, b) in samples.zip(parsed)) {
            if (a.power.isNaN()) assertTrue(b.power.isNaN()) else assertEquals(a.power, b.power, 0.5)
            assertEquals(a.cadence, b.cadence, 0.5)
            assertEquals(a.balanceLeft, b.balanceLeft, 0.5)
            assertEquals(a.faFront, b.faFront)
            assertEquals(a.faRear, b.faRear)
            assertEquals(a.effortZone, b.effortZone)
            assertEquals(a.rearGear, b.rearGear)
            assertEquals(a.rearTeeth, b.rearTeeth)
        }
        assertEquals(210.0, parsed[3].power, 0.5)
        assertTrue(parsed[15].power.isNaN())

        val plain = RideSim().apply { start() }
        plain.ride(5, speed = { 5.0 })
        val row = RideStore.toCsv(plain.engine.drainForStorage().samples.first())
        assertTrue(row, row.endsWith(",,,,,,,,"))
    }
}
