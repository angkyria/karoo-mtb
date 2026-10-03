package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * A hand-built ride with known answers: 100 s flat (500 m, long enough to be its own section),
 * 300 s climb, 300 s descent, 200 s flat. Mirrors test_sram_analytics in tools/tests/test_analyze.py.
 */
class BikeAnalyticsTest {
    private val startWall = 1_790_000_000_000L

    private data class Second(
        val speed: Double, val grade: Double, val rough: Double, val fa: Int,
        val power: Double, val cadence: Double, val gear: Int, val teeth: Int,
    )

    private fun second(i: Int): Second {
        // Gears (1 = largest cog): 21T, shift to 28T at 90 s, 32T at 110 s, 18T at 405 s, 21T at 705 s.
        val (gear, teeth) = when {
            i < 90 -> 7 to 21
            i < 110 -> 5 to 28
            i < 405 -> 4 to 32
            i < 705 -> 8 to 18
            else -> 7 to 21
        }
        return when {
            i < 100 -> Second(5.0, 0.0, 0.3, FaState.LOCK, 150.0, 85.0, gear, teeth)
            i < 400 -> Second(
                3.0, 8.0, 0.3,
                when {
                    i < 250 -> FaState.LOCK
                    i < 270 -> FaState.OPEN // 20 s open while pushing 230 W uphill
                    else -> FaState.PEDAL
                },
                230.0, 75.0, gear, teeth,
            )
            i < 700 -> {
                val pedalling = i < 460
                Second(
                    6.0, -10.0, if (i >= 680) 1.1 else 0.8,
                    when {
                        i < 420 -> FaState.PEDAL // takes 20 s to open
                        i < 680 -> FaState.OPEN
                        else -> FaState.LOCK // 20 s locked on rough ground
                    },
                    if (pedalling) 150.0 else 0.0, if (pedalling) 80.0 else 0.0, gear, teeth,
                )
            }
            else -> Second(5.0, 0.0, 0.3, FaState.LOCK, 150.0, 85.0, gear, teeth)
        }
    }

    private fun ride(withBike: Boolean = true): List<SecondSample> {
        var alt = 100.0
        var dist = 0.0
        return (0 until 900).map { i ->
            val s = second(i)
            alt += s.speed * s.grade / 100.0
            dist += s.speed
            SecondSample(
                idx = i, elapsedMs = i * 1000L, wallMs = startWall + i * 1000L, dt = 1.0, distanceM = dist, dDist = s.speed,
                speed = s.speed, grade = s.grade, altitude = alt, lat = Double.NaN, lon = Double.NaN, rough = s.rough,
                yawRate = 0.0, curvature = 0.0, latG = 0.0, grit = 1.0, moving = true, lap = 0, airborne = false,
                power = if (withBike) s.power else Double.NaN,
                cadence = if (withBike) s.cadence else Double.NaN,
                balanceLeft = if (withBike) 47.0 else Double.NaN,
                faFront = if (withBike) s.fa else -1,
                faRear = if (withBike) s.fa else -1,
                effortZone = if (withBike) (if (s.power >= 200) 2 else 1) else -1,
                rearGear = if (withBike) s.gear else -1,
                rearTeeth = if (withBike) s.teeth else -1,
            ).also { it.processed = true }
        }
    }

    private val shifts = listOf(
        Shift(1, startWall + 90_000, 90.0, gear = 5, teeth = 28, fromGear = 7, fromTeeth = 21, powerW = 150.0),
        Shift(2, startWall + 110_000, 110.0, gear = 4, teeth = 32, fromGear = 5, fromTeeth = 28, powerW = 230.0),
        Shift(3, startWall + 405_000, 405.0, gear = 8, teeth = 18, fromGear = 4, fromTeeth = 32, powerW = 260.0),
        Shift(4, startWall + 705_000, 705.0, gear = 7, teeth = 21, fromGear = 8, fromTeeth = 18, powerW = 150.0),
    )

    private fun analyse(samples: List<SecondSample>): Triple<Array<String>, List<Segmenter.Range>, List<SecondSample>> {
        val ranges = Segmenter.split(samples, 15.0)
        return Triple(BikeAnalytics.terrain(samples, ranges), ranges, samples)
    }

    @Test
    fun `segments are what the test expects`() {
        val (_, ranges) = analyse(ride())
        assertEquals(listOf("FLAT", "CLIMB", "DESCENT", "FLAT"), ranges.map { it.type })
        assertTrue("climb starts at ${ranges[1].start}", ranges[1].start in 92..102)
    }

    @Test
    fun `flight attendant shares, harsh lock and reaction`() {
        val (terrain, ranges, samples) = analyse(ride())
        val su = BikeAnalytics.suspension(samples, terrain, ranges, mode = 1, bias = 2)
        assertNotNull(su)
        su!!
        assertEquals(50.0, su.climbs!!.lock, 4.0)
        assertTrue("descent open ${su.descents!!.open}", su.descents!!.open in 80.0..92.0)
        assertEquals(100.0, su.flats!!.lock, 0.01)
        assertEquals(20.0, su.lockedRoughSec, 0.01)
        assertEquals(20.0, su.openHardClimbSec, 0.01)
        assertEquals(4, su.changes)
        assertEquals(1, su.descentCount)
        assertEquals(1, su.descentsReachingOpen)
        assertTrue("reaction ${su.reactionSecMedian}", su.reactionSecMedian!! in 14.0..26.0)
        assertEquals(0.0, su.forkShockDifferSec, 0.0)
        assertEquals(listOf(1, 2), su.effortZones.map { it.zone })
        assertEquals(2, su.bias)
    }

    @Test
    fun `drivetrain usage and anticipation`() {
        val (terrain, ranges, samples) = analyse(ride())
        val d = BikeAnalytics.drivetrain(samples, terrain, ranges, shifts)!!
        assertEquals(4, d.shifts)
        assertEquals(4 / (samples.sumOf { it.dDist } / 1000.0), d.shiftsPerKm, 1e-9)
        assertEquals(listOf(18, 21, 28, 32), d.cogMinutes.keys.toList())
        assertEquals(20.0 / 60.0, d.cogMinutes[28]!!, 1e-9)
        assertEquals(18, d.smallestCogTeeth)
        assertEquals(32, d.largestCogTeeth)
        assertEquals(3, d.easierGearsUnused)
        assertEquals(32, d.climbMedianCog)
        assertEquals(18, d.descentMedianCog)
        assertEquals(21, d.flatMedianCog)
        assertEquals(1, d.underLoad)
        assertEquals(2, d.climbShiftsBefore + d.climbShiftsAfter)
        assertEquals(75.0, d.steepCadenceRpm!!, 0.01)
        // 230 W at 75 rpm = 29.3 Nm
        assertEquals(29.3, d.steepTorqueNm!!, 0.1)
        assertEquals(0.0, d.steepLowCadenceSec, 0.0)
    }

    @Test
    fun `power by terrain`() {
        val (terrain, _, samples) = analyse(ride())
        val p = BikeAnalytics.power(samples, terrain, weightKg = 75.0)!!
        assertEquals(230.0, p.climbs!!.avgW, 2.0)
        assertEquals(230.0 / 75.0, p.climbs!!.wattsPerKg!!, 0.05)
        assertTrue("descent pedalling ${p.descents!!.pedallingPct}", p.descents!!.pedallingPct in 15.0..25.0)
        assertEquals(47.0, p.climbs!!.balanceLeft!!, 0.01)
        assertEquals(230.0, p.best5minW!!, 0.01)
        assertEquals(75.0, p.weightKg!!, 0.0)
        assertNull(BikeAnalytics.power(samples, terrain, weightKg = Double.NaN)!!.climbs!!.wattsPerKg)
    }

    @Test
    fun `segments carry bike fields`() {
        val samples = ride()
        val ranges = Segmenter.split(samples, 15.0)
        val climb = ranges.first { it.type == "CLIMB" }
        val stats = RangeStats.compute(1, climb.type, "Climb 1", samples, climb.start, climb.end, emptyList(), emptyList(), startWall, shifts, 75.0)
        assertEquals(230.0, stats.avgPowerW!!, 3.0)
        assertEquals(32, stats.medianCogTeeth)
        assertNotNull(stats.vamMh)
        assertTrue(stats.faLockPct!! > 40)
        assertTrue(stats.shifts >= 1)
    }

    @Test
    fun `nothing paired means no bike statistics`() {
        val (terrain, ranges, samples) = analyse(ride(withBike = false))
        assertNull(BikeAnalytics.suspension(samples, terrain, ranges, null, null))
        assertNull(BikeAnalytics.drivetrain(samples, terrain, ranges, emptyList()))
        assertNull(BikeAnalytics.power(samples, terrain, 75.0))
        val climb = ranges.first { it.type == "CLIMB" }
        val stats = RangeStats.compute(1, climb.type, "Climb 1", samples, climb.start, climb.end, emptyList(), emptyList(), startWall)
        assertNull(stats.avgPowerW)
        assertNull(stats.faOpenPct)
        assertNull(stats.medianCogTeeth)
        assertNull(stats.pedallingPct)
    }
}
