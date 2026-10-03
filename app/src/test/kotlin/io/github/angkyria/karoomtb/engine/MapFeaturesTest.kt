package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MapFeaturesTest {
    @Test
    fun `polyline encoding matches Google's example`() {
        val points = listOf(GeoPoint(38.5, -120.2), GeoPoint(40.7, -120.95), GeoPoint(43.252, -126.453))
        assertEquals("_p~iF~ps|U_ulLnnqC_mqNvxq`@", Polyline.encode(points))
        assertEquals("", Polyline.encode(emptyList()))
    }

    @Test
    fun `rough ground becomes a map section, short bumps do not`() {
        val sim = RideSim().apply { start() }
        val at = { i: Int -> GeoPoint(46.0, 8.0 + i * 5e-5) }
        sim.ride(20, speed = { 5.0 }, vibrationG = 0.05, location = at)
        sim.ride(15, speed = { 5.0 }, vibrationG = 1.4, location = { at(20 + it) })
        sim.ride(10, speed = { 5.0 }, vibrationG = 0.05, location = { at(35 + it) })
        sim.ride(2, speed = { 5.0 }, vibrationG = 1.4, location = { at(45 + it) })
        sim.ride(10, speed = { 5.0 }, vibrationG = 0.05, location = { at(47 + it) })
        val map = sim.engine.mapFeatures()
        assertEquals(1, map.rough.size)
        val section = map.rough.single()
        assertTrue("points ${section.points.size}", section.points.size in 12..18)
        assertTrue("rough ${section.avgRoughG}", section.avgRoughG >= RoughSections.MIN_ROUGH_G)
        assertTrue(map.version > 0)
    }

    @Test
    fun `jumps and markers with a position are on the map`() {
        val sim = RideSim().apply { start() }
        sim.ride(10, speed = { 6.0 }, location = { GeoPoint(46.0, 8.0 + it * 1e-4) })
        val before = sim.engine.mapFeatures().version
        sim.jumpIn(1.0, 0.6)
        sim.ride(5, speed = { 6.0 }, location = { GeoPoint(46.0, 8.001 + it * 1e-4) })
        sim.engine.markMoment(sim.wallMs(), sim.elapsedMs)
        val map = sim.engine.mapFeatures()
        assertEquals(1, map.jumps.size)
        assertEquals(1, map.markers.size)
        assertTrue(map.version >= before + 2)
        assertEquals(sim.startWallMs, map.ride)
    }
}
