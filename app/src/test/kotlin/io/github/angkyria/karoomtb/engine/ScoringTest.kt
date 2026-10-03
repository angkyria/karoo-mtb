package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScoringTest {
    @Test
    fun `grit grows with grade, turns and roughness`() {
        val flat = Scoring.gritPerSecond(0.0, 0.0, 0.1)
        assertTrue(Scoring.gritPerSecond(12.0, 0.0, 0.1) > flat)
        assertTrue(Scoring.gritPerSecond(-12.0, 0.0, 0.1) > flat)
        assertTrue(Scoring.gritPerSecond(0.0, 1.0 / 6.0, 0.1) > flat)
        assertTrue(Scoring.gritPerSecond(0.0, 0.0, 0.6) > flat)
        // No accelerometer: roughness simply does not contribute.
        assertEquals(Scoring.GRIT_SCALE, Scoring.gritPerSecond(0.0, 0.0, Double.NaN), 1e-9)
    }

    @Test
    fun `coasting on the flat is not braking, slowing hard is`() {
        val coast = Scoring.coastingAccel(8.0, 0.0)
        assertEquals(0.0, Scoring.brakingDecel(coast, 8.0, 0.0), 1e-9)
        assertTrue(Scoring.brakingDecel(-2.5, 8.0, 0.0) > 1.5)
        // Slowing down on a 10 % climb is gravity, not brakes.
        assertEquals(0.0, Scoring.brakingDecel(-1.0, 4.0, 10.0), 1e-9)
        // Holding a steady speed down a 12 % slope is not deceleration (Garmin's Flow definition)...
        assertEquals(0.0, Scoring.brakingDecel(0.0, 7.0, -12.0), 1e-9)
        // ...but scrubbing speed on it is.
        assertEquals(1.5, Scoring.brakingDecel(-1.5, 7.0, -12.0), 1e-9)
    }

    @Test
    fun `necessity is high for tight corners and steep descents`() {
        assertEquals(0.0, Scoring.brakingNecessity(6.0, 0.0, 0.0, 0.1), 1e-9)
        assertEquals(1.0, Scoring.brakingNecessity(6.0, 1.0 / 6.0, 0.0, 0.1), 1e-9)
        assertEquals(1.0, Scoring.brakingNecessity(6.0, 0.0, -20.0, 0.1), 1e-9)
        assertTrue(Scoring.brakingNecessity(6.0, 0.0, -3.0, 0.1) < 0.01)
    }

    @Test
    fun `ballistic jump height`() {
        // Flat landing: g t² / 8
        assertEquals(Scoring.G * 0.64 / 8.0, Scoring.jumpHeight(0.8, 0.0), 1e-9)
        // A drop makes the flight higher above the landing than a flat jump of the same airtime.
        assertTrue(Scoring.jumpHeight(0.8, 1.5) > Scoring.jumpHeight(0.8, 0.0))
    }

    @Test
    fun `scores stay within 0 to 100`() {
        for (v in listOf(0.0, 1.0, 5.0, 50.0, 1000.0)) {
            assertTrue(Scoring.difficultyScore(v) in 0.0..100.0)
            assertTrue(Scoring.smoothnessScore(v) in 0.0..100.0)
            assertTrue(Scoring.airScore(v) in 0.0..100.0)
        }
        assertEquals(100.0, Scoring.smoothnessScore(0.0), 1e-9)
    }
}
