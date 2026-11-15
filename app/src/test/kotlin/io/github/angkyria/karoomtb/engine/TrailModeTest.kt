package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrailModeTest {
    private val config = MtbConfig()

    @Test
    fun `smooth road is not a trail`() {
        val trail = TrailMode(config)
        repeat(60) { trail.onSecond(0.3) }
        assertFalse(trail.active)
    }

    @Test
    fun `sustained rough ground is a trail`() {
        val trail = TrailMode(config)
        repeat(30) { trail.onSecond(1.3) }
        assertTrue(trail.active)
    }

    @Test
    fun `a single rough patch on the road does not switch it on`() {
        val trail = TrailMode(config)
        repeat(25) { trail.onSecond(0.3) }
        repeat(5) { trail.onSecond(1.8) }
        assertFalse(trail.active)
    }

    @Test
    fun `a short smooth section on the trail keeps it on`() {
        val trail = TrailMode(config)
        repeat(30) { trail.onSecond(1.3) }
        repeat(8) { trail.onSecond(0.3) }
        assertTrue(trail.active)
    }

    @Test
    fun `seconds without roughness are ignored`() {
        val trail = TrailMode(config)
        repeat(30) { trail.onSecond(1.3) }
        repeat(30) { trail.onSecond(Double.NaN) }
        assertTrue(trail.active)
    }

    @Test
    fun `needs enough seconds before deciding`() {
        val trail = TrailMode(config)
        repeat(5) { trail.onSecond(1.5) }
        assertFalse(trail.active)
    }

    @Test
    fun `reset forgets the trail`() {
        val trail = TrailMode(config)
        repeat(30) { trail.onSecond(1.3) }
        trail.reset()
        assertFalse(trail.active)
    }
}
