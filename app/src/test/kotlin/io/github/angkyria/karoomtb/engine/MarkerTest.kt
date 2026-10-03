package io.github.angkyria.karoomtb.engine

import io.github.angkyria.karoomtb.notify.SummaryFormatter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MarkerTest {
    private fun RideSim.mark() = engine.markMoment(wallMs(), elapsedMs)!!

    @Test
    fun `a marker after a jump says it was counted`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 })
        sim.jumpIn(1.0, 0.6)
        sim.ride(5, speed = { 6.0 })
        val m = sim.mark()
        assertEquals(1, m.n)
        assertEquals(0.6, m.flightAirSec!!, 0.05)
        assertEquals("", m.flightVerdict)
        assertTrue(SummaryFormatter.markerDetail(m), SummaryFormatter.markerDetail(m).endsWith("counted"))
    }

    @Test
    fun `a marker after a small hop explains why it was not a jump`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 })
        sim.jumpIn(1.0, 0.15)
        sim.ride(4, speed = { 6.0 })
        val m = sim.mark()
        assertTrue("verdict ${m.flightVerdict}", m.flightVerdict!!.startsWith("airtime 0.1"))
        assertTrue(SummaryFormatter.markerDetail(m).contains("not counted"))
    }

    @Test
    fun `slow take-off is reported, old flights and pauses give no flight`() {
        val slow = RideSim().apply { start() }
        slow.ride(10, speed = { 1.0 })
        slow.jumpIn(1.0, 0.6)
        slow.ride(4, speed = { 1.0 })
        assertTrue(slow.mark().flightVerdict!!.startsWith("take-off speed"))

        val sim = RideSim().apply { start() }
        sim.jumpIn(2.0, 0.6)
        sim.ride(40, speed = { 6.0 })
        val m = sim.mark()
        assertNull("jump was 37 s ago", m.flightAirSec)
        assertEquals("No flight in the last 15 s", SummaryFormatter.markerDetail(m))
        assertEquals(listOf(1, 2), listOf(m, sim.mark()).map { it.n })
        assertEquals(2, sim.finish().markers.size)
        sim.engine.pause()
        assertNull(sim.engine.markMoment(sim.wallMs(), sim.elapsedMs))
    }
}
