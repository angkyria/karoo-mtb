package io.github.angkyria.karoomtb.trails

import io.github.angkyria.karoomtb.engine.GeoPoint
import io.github.angkyria.karoomtb.engine.RideSim
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.engine.SegmentTrack
import io.github.angkyria.karoomtb.engine.TrackPoint
import io.github.angkyria.karoomtb.notify.SummaryFormatter
import io.github.angkyria.karoomtb.notify.Units
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import kotlin.math.cos
import kotlin.math.sin

class TrailsTest {
    private val mPerDegLat = 111_195.0
    private val mPerDegLon = 111_195.0 * cos(Math.toRadians(46.0))

    /** A wiggly trail heading south-east; [s] metres along it, [side] metres to the side. */
    private fun trailPoint(s: Double, side: Double = 0.0) = GeoPoint(
        46.0 - (s * 0.7 + side * 0.7) / mPerDegLat,
        8.0 + (s * 0.7 - side * 0.7 + 30.0 * sin(s / 100.0)) / mPerDegLon,
    )

    private fun run(fromM: Double, toM: Double, speed: Double, side: Double = 0.0, t0: Double = 100.0): List<TrackPoint> {
        val out = ArrayList<TrackPoint>()
        var s = fromM
        var t = t0
        while (s <= toM) {
            val p = trailPoint(s, side)
            out += TrackPoint(p.lat, p.lon, t)
            s += 10.0
            t += 10.0 / speed
        }
        return out
    }

    private val reference = run(0.0, 1200.0, 6.0).map { GeoPoint(it.lat, it.lon) }
    private val referenceLength = TrailMatcher.length(reference)

    @Test
    fun `a run starting before and ending after the trail is timed between the trail's endpoints`() {
        val m = TrailMatcher.match(run(-80.0, 1300.0, 6.0, side = 4.0), reference, referenceLength)
        assertNotNull(m)
        assertEquals(200.0, m!!.timeSec, 2.0)
        assertEquals(1200.0 * referenceLength / 1200.0, m.distanceM, 40.0)
        assertTrue(m.meanDeviationM < 8.0)
    }

    @Test
    fun `parallel, partial or reversed tracks do not match`() {
        assertNull("100 m beside", TrailMatcher.match(run(0.0, 1200.0, 6.0, side = 100.0), reference, referenceLength))
        assertNull("only half", TrailMatcher.match(run(0.0, 600.0, 6.0), reference, referenceLength))
        assertNull("uphill", TrailMatcher.match(run(0.0, 1200.0, 6.0).reversed(), reference, referenceLength))
    }

    private fun tempLibrary(): Pair<TrailLibrary, File> {
        val file = File(Files.createTempDirectory("trails").toFile(), TrailLibrary.FILE_NAME)
        return TrailLibrary(file) to file
    }

    /** A ride: flat start, one descent down the trail per lap (climbing back up off-trail), flat run-out. */
    private fun ride(start: Long, speeds: List<Double>): RideSummary {
        val sim = RideSim(seed = start)
        sim.engine.start(start, sim.startElapsedMs)
        for (speed in speeds) {
            var alt = 600.0
            sim.ride(30, speed = { 4.0 }, altitude = { alt }, location = { trailPoint(-100.0 + it * 4.0 - 20.0) })
            val seconds = (1250.0 / speed).toInt()
            sim.ride(seconds, speed = { speed }, grade = { -10.0 }, altitude = { alt - speed * 0.1 * (it + 1) }, location = { trailPoint(-20.0 + it * speed) })
            alt -= speed * 0.1 * seconds
            sim.ride(100, speed = { 4.0 }, altitude = { alt }, location = { trailPoint(1230.0 + it * 4.0, side = it * 3.0) })
            // Back up the hill on a road far from the trail.
            sim.ride(300, speed = { 2.5 }, grade = { 8.0 }, altitude = { a -> alt + 0.4 * (a + 1) }, location = { GeoPoint(46.05, 8.05) })
        }
        return sim.engine.finish(sim.wallMs(), io.github.angkyria.karoomtb.engine.SummaryMeta("test", "Trail", "K2"))
    }

    @Test
    fun `second ride on the same trail is ranked and a faster run is a PB`() {
        val (library, file) = tempLibrary()
        val first = ride(1_790_000_000_000L, listOf(6.0))
        assertEquals(1, first.descentTracks.size)
        val r1 = library.addRide(first)
        assertEquals(1, r1.size)
        assertTrue(r1[0].newTrail)
        assertEquals("Trail 1", r1[0].trailName)

        val second = ride(1_790_100_000_000L, listOf(6.6, 5.5))
        val r2 = library.addRide(second)
        assertEquals(2, r2.size)
        assertTrue("faster run is a PB: $r2", r2[0].pb)
        assertEquals(1, r2[0].rank)
        assertFalse(r2[1].pb)
        assertEquals("third run, slowest", 3, r2[1].rank)
        assertEquals(3, r2[1].runs)
        assertEquals(3, library.state().trails.single().runs.size)

        // Adding the same ride again replaces its runs.
        library.addRide(second)
        assertEquals(3, library.state().trails.single().runs.size)
        assertTrue(file.readText().contains("Trail 1"))

        val lines = SummaryFormatter.trailLines(r2, Units())
        assertTrue(lines[0], lines[0].startsWith("🏆 ") && lines[0].contains("PB "))
        assertTrue(lines[1], lines[1].contains("3rd of 3"))
    }

    @Test
    fun `live comparison does not store anything, rename and delete do`() {
        val (library, _) = tempLibrary()
        library.addRide(ride(1_790_000_000_000L, listOf(6.0)))
        val id = library.state().trails.single().id
        val faster = run(-60.0, 1260.0, 7.0)
        val stats = ride(1_790_200_000_000L, listOf(7.0)).segments.first { it.type == "DESCENT" }
        val live = library.compare(stats, SegmentTrack(0, faster))
        assertNotNull(live)
        assertTrue(live!!.pb)
        assertEquals(1, library.state().trails.single().runs.size)
        assertTrue(SummaryFormatter.descentAlertTitle(stats, Units(), live).startsWith("PB! Trail 1"))
        library.rename(id, "  Dragon's back ")
        assertEquals("Dragon's back", library.state().trails.single().name)
        library.delete(id)
        assertTrue(library.state().trails.isEmpty())
    }

    @Test
    fun `ordinals`() {
        val expected = listOf("1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd")
        assertEquals(expected, listOf(1, 2, 3, 4, 11, 12, 13, 21, 22).map(SummaryFormatter::ordinal))
    }
}
