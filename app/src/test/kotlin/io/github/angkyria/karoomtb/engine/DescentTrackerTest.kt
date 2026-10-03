package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DescentTrackerTest {
    /** Rides a profile of (seconds, speed m/s, grade %) legs; altitude follows the grade. */
    private fun ride(sim: RideSim, legs: List<Triple<Int, Double, Double>>, baro: Boolean = true) {
        var alt = 500.0
        for ((seconds, speed, grade) in legs) {
            val start = alt
            sim.ride(
                seconds,
                speed = { speed },
                grade = { grade },
                altitude = { i -> if (baro) start + speed * grade / 100.0 * (i + 1) else Double.NaN },
            )
            alt = start + speed * grade / 100.0 * seconds
        }
    }

    private fun descentAlerts(sim: RideSim) = sim.engine.pollAlerts().filterIsInstance<RideAlert.DescentFinished>()

    @Test
    fun `two descents with a climb between are reported with their drop`() {
        val sim = RideSim().apply { start() }
        ride(sim, listOf(Triple(60, 5.0, 0.0), Triple(120, 6.0, -10.0)))
        val live = sim.outputs.last().live.descent
        assertNotNull("descent in progress", live)
        assertEquals(1, live!!.number)
        assertTrue("drop so far ${live.dropM}", live.dropM > 50)
        assertTrue(live.timeSec > 100)

        ride(sim, listOf(Triple(120, 3.0, 8.0), Triple(100, 6.0, -10.0), Triple(120, 5.0, 0.0)))
        val alerts = descentAlerts(sim)
        assertEquals(listOf(1, 2), alerts.map { it.stats.index })
        assertEquals(72.0, alerts[0].stats.elevLossM, 6.0)
        assertEquals(60.0, alerts[1].stats.elevLossM, 6.0)
        assertTrue("about 2 min", alerts[0].stats.durationSec in 110.0..135.0)
        assertNull("flat at the end", sim.outputs.last().live.descent)
        assertEquals("Descent 2", sim.outputs.last().live.lastDescent?.name)
    }

    @Test
    fun `a small dip is not a descent`() {
        val sim = RideSim().apply { start() }
        ride(sim, listOf(Triple(60, 5.0, 0.0), Triple(30, 5.0, -6.0), Triple(60, 4.0, 4.0), Triple(200, 5.0, 0.0)))
        assertTrue(descentAlerts(sim).isEmpty())
        assertNull(sim.outputs.last().live.lastDescent)
    }

    @Test
    fun `without barometer the grade is integrated`() {
        val sim = RideSim().apply { start() }
        ride(sim, listOf(Triple(30, 5.0, 0.0), Triple(90, 6.0, -12.0), Triple(150, 5.0, 0.0)), baro = false)
        val alerts = descentAlerts(sim)
        assertEquals(1, alerts.size)
        assertTrue("distance ${alerts[0].stats.distanceM}", alerts[0].stats.distanceM in 450.0..620.0)
    }

    @Test
    fun `descent track follows the GPS`() {
        val sim = RideSim().apply { start() }
        var alt = 400.0
        sim.ride(30, speed = { 5.0 }, altitude = { alt }, location = { GeoPoint(46.0, 8.0 + it * 5e-5) })
        sim.ride(80, speed = { 6.0 }, grade = { -10.0 }, altitude = { alt - 0.6 * (it + 1) }, location = { GeoPoint(46.0 - it * 5e-5, 8.0015) })
        alt -= 48.0
        sim.ride(150, speed = { 5.0 }, altitude = { alt }, location = { GeoPoint(45.996, 8.0015 + it * 5e-5) })
        val track = descentAlerts(sim).single().track!!
        assertTrue("core points ${track.core.size}", track.core.size in 35..70)
        assertTrue("margins", track.coreStart > 0 && track.coreEnd < track.points.lastIndex)
        assertTrue(track.core.first().lat > track.core.last().lat)
    }

    @Test
    fun `a ride restored mid-descent continues the descent`() {
        val sim = RideSim().apply { start() }
        ride(sim, listOf(Triple(30, 5.0, 0.0), Triple(60, 6.0, -12.0)))
        val stored = sim.engine.drainForStorage()
        val restored = MtbEngine()
        restored.restore(sim.startWallMs, sim.wallMs(), 9_000_000L, stored.samples, stored.jumps, stored.corners)
        val live = restored.live().descent
        assertNotNull(live)
        assertEquals(1, live!!.number)
        assertTrue("drop ${live.dropM}", live.dropM > 25)
    }
}
