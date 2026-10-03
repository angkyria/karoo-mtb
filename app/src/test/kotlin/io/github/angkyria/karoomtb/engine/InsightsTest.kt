package io.github.angkyria.karoomtb.engine

import io.github.angkyria.karoomtb.notify.SummaryFormatter
import io.github.angkyria.karoomtb.notify.Units
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InsightsTest {
    private fun lap(index: Int, distance: Double, seconds: Double, flow: Double) = SegmentStats(
        index = index, type = "LAP", name = "Lap $index", startOffsetSec = 0.0, durationSec = seconds, distanceM = distance,
        elevGainM = 0.0, elevLossM = 0.0, avgGradePct = 0.0, avgSpeedMs = 0.0, maxSpeedMs = 0.0, gritK = 0.0, gritAvg = 0.0,
        flowScore = flow, roughAvg = null, jumps = 0, maxAirSec = 0.0, brakingPct = 0.0, maxLateralG = 0.0, corners = 0,
    )

    @Test
    fun `comparable laps exclude a short last lap and show the trend`() {
        val laps = listOf(
            lap(1, 3000.0, 200.0, 1.0), lap(2, 3050.0, 195.0, 0.6), lap(3, 2980.0, 190.0, 0.8),
            lap(4, 3010.0, 205.0, 0.9), lap(5, 3020.0, 215.0, 1.1), lap(6, 3000.0, 220.0, 1.2), lap(7, 900.0, 60.0, 0.1),
        )
        val c = Insights.lapComparison(laps)!!
        assertEquals(6, c.comparable)
        assertEquals(7, c.laps)
        assertEquals(3, c.fastestLap)
        assertEquals(2, c.smoothestLap)
        // last two (215, 220) vs first two (200, 195): +10 %
        assertEquals(10.1, c.trendPct!!, 0.2)
        val line = SummaryFormatter.lapComparisonLine(c)
        assertTrue(line, line.contains("fastest Lap 3 3:10") && line.contains("last laps 10% slower") && line.contains("6 comparable"))
        assertNull(Insights.lapComparison(listOf(lap(1, 3000.0, 200.0, 1.0))))
    }

    @Test
    fun `braking on a straight is the top braking spot, with its segment`() {
        val sim = RideSim().apply { start() }
        sim.ride(60, speed = { 6.0 }, location = { GeoPoint(46.0, 8.0 + it * 1e-4) })
        // Hard braking on a straight, twice; the second is longer.
        sim.ride(20, speed = { i -> if (i in 5..8) 6.0 - (i - 4) * 1.2 else if (i > 8) 1.5 + (i - 8) * 0.4 else 6.0 })
        sim.ride(40, speed = { 6.0 })
        sim.ride(25, speed = { i -> if (i in 5..10) 7.0 - (i - 4) * 1.0 else if (i > 10) 1.0 + (i - 10) * 0.4 else 7.0 })
        sim.ride(40, speed = { 6.0 })
        val s = sim.finish()
        assertTrue("spots ${s.brakingSpots}", s.brakingSpots.size == 2)
        val top = s.brakingSpots.first()
        assertTrue(top.flowM >= s.brakingSpots.last().flowM)
        assertTrue("before ${top.speedBeforeMs} after ${top.speedAfterMs}", top.speedBeforeMs > top.speedAfterMs + 3)
        assertTrue(top.offsetSec > 120)
        val lines = SummaryFormatter.brakingSpotLines(s.brakingSpots, Units(), mapLinks = true)
        assertTrue(lines[0], lines[0].startsWith("1. at "))
        assertTrue(SummaryFormatter.brakingSpotLines(s.brakingSpots, Units(), mapLinks = false).none { "openstreetmap" in it })
    }

    @Test
    fun `corner sides need five corners each and name the weaker side`() {
        fun corner(angle: Double, kept: Double) = Corner(0, 0.0, 1.0, angle, 5.0, 5.0 * kept, 5.0, 0.5, 10.0)
        val corners = List(5) { corner(60.0, 0.96) } + List(6) { corner(-60.0, 0.88) }
        val (left, right) = Insights.cornerSides(corners)
        assertEquals(96.0, left!!, 0.01)
        assertEquals(88.0, right!!, 0.01)
        assertEquals("You lose more speed in right-handers (88% vs 96% kept)", SummaryFormatter.cornerSideHint(left, right))
        assertNull(Insights.cornerSides(corners.drop(1)).first)
        assertNotNull(SummaryFormatter.cornerSideHint(90.0, 92.0))
        assertNull(SummaryFormatter.cornerSideHint(null, 92.0))
    }
}
