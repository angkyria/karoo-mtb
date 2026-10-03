package io.github.angkyria.karoomtb.karoo

import io.github.angkyria.karoomtb.engine.GeoPoint
import io.github.angkyria.karoomtb.engine.Jump
import io.github.angkyria.karoomtb.engine.MapFeatures
import io.github.angkyria.karoomtb.engine.Marker
import io.github.angkyria.karoomtb.engine.RoughSection
import io.hammerhead.karooext.models.Symbol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MapLayerTest {
    private val features = MapFeatures(
        ride = 42L,
        version = 3,
        jumps = listOf(Jump(1, 0L, 10.0, 0.6, 5.0, 0.4, null, 8.0, 2.5, 0.0, 0, 80.0, 46.0, 8.0)),
        markers = listOf(Marker(1, 0L, 12.0, 46.001, 8.001)),
        rough = listOf(
            RoughSection(1, listOf(GeoPoint(46.0, 8.0), GeoPoint(46.001, 8.001)), 1.0),
            RoughSection(2, listOf(GeoPoint(46.0, 8.0), GeoPoint(46.001, 8.001)), 1.6),
        ),
    )

    @Test
    fun `symbols and lines carry the ride in their ids`() {
        val symbols = MapLayer.symbols(features)
        assertEquals(listOf("jump-42-1", "mark-42-1"), symbols.map { it.id })
        assertTrue(symbols[0] is Symbol.Icon)
        assertEquals("Mark 1", (symbols[1] as Symbol.POI).name)
        val lines = MapLayer.polylines(features)
        assertEquals(setOf("rough-42-1", "rough-42-2"), lines.keys)
        assertTrue("very rough is red", lines.getValue("rough-42-2").color != lines.getValue("rough-42-1").color)
        assertTrue(lines.getValue("rough-42-1").encodedPolyline.isNotEmpty())
    }
}
