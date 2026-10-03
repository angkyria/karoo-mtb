package io.github.angkyria.karoomtb.karoo

import io.github.angkyria.karoomtb.engine.Jump
import io.github.angkyria.karoomtb.engine.LiveDescent
import io.github.angkyria.karoomtb.engine.LiveMetrics
import io.github.angkyria.karoomtb.notify.Units
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PanelsTest {
    private val units = Units()

    @Test
    fun `stored cell lists are parsed, bad ones fall back to the defaults`() {
        val defaults = Panel.MTB.defaults
        val stored = "FLOW,GRIT,D_TIME,POWER,JUMPS,SCORE"
        val expected = listOf(PanelCell.FLOW, PanelCell.GRIT, PanelCell.D_TIME, PanelCell.POWER, PanelCell.JUMPS, PanelCell.SCORE)
        assertEquals(expected, PanelCell.parse(stored, defaults))
        assertEquals(defaults, PanelCell.parse(null, defaults))
        assertEquals(defaults, PanelCell.parse("GRIT,NOPE", defaults))
        assertTrue(Panel.entries.all { it.defaults.size == Panel.CELLS })
    }

    @Test
    fun `jump cells show a dash before the first jump`() {
        val none = LiveMetrics()
        assertEquals(PanelCell.NONE, PanelCell.AIR.value(none, units))
        assertEquals(PanelCell.NONE, PanelCell.MAX_AIR.value(none, units))
        val jump = Jump(1, 0L, 10.0, 0.62, 5.1, 0.47, null, 8.2, 2.4, 0.0, 0, 80.0)
        val one = LiveMetrics(jumpCount = 1, lastJump = jump, maxAirSec = 0.62)
        assertEquals("0.62 s", PanelCell.AIR.value(one, units))
        assertEquals("5.1 m", PanelCell.JUMP_DIST.value(one, units))
    }

    @Test
    fun `descent cells and header follow the descent in progress`() {
        val live = LiveMetrics(descent = LiveDescent(3, 125.0, 900.0, 88.0, 7.2, 0.7, 21.0, 1, 0.8))
        assertEquals("DESCENT 3", Panel.DESCENT.header(live))
        assertEquals("2:05", PanelCell.D_TIME.value(live, units))
        assertEquals("88 m", PanelCell.D_DROP.value(live, units))
        assertEquals("289 ft", PanelCell.D_DROP.value(live, Units(imperialElevation = true)))
        assertEquals("21%", PanelCell.D_BRAKE.value(live, units))
        assertEquals("DESCENT", Panel.DESCENT.header(LiveMetrics()))
        assertNull(Panel.MTB.header(live))
    }

    @Test
    fun `six cells only on tall fields`() {
        assertTrue(Panel.useSixCells(480, 400))
        assertFalse(Panel.useSixCells(480, 200))
        assertFalse(Panel.useSixCells(240, 200))
    }
}
