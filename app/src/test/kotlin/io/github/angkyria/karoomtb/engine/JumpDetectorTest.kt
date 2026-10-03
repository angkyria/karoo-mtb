package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Random

class JumpDetectorTest {
    private val g = Scoring.G

    /** Feeds |a| (in g) at 100 Hz through the same filter the engine uses. */
    private fun run(profile: (Double) -> Double, seconds: Double, seed: Long = 1): List<RawJump> {
        val imu = ImuProcessor()
        val detector = JumpDetector(MtbConfig())
        val rnd = Random(seed)
        val found = ArrayList<RawJump>()
        var t = 0.0
        while (t < seconds) {
            val z = profile(t) * g
            imu.onAccel(t, rnd.nextGaussian() * 0.01 * g, rnd.nextGaussian() * 0.01 * g, z, detector.airborne, !detector.airborne)
            detector.onAccel(t, imu.magLpG, imu.magG)?.let { found += it }
            t += 0.01
        }
        return found
    }

    @Test
    fun `detects a 0_6 s flight`() {
        val jumps = run({ t ->
            when {
                t in 2.0..2.6 -> 0.05
                t in 2.6..2.66 -> 3.0
                else -> 1.0
            }
        }, 4.0)
        assertEquals(1, jumps.size)
        assertEquals(0.6, jumps[0].airSec, 0.05)
        assertEquals(0, jumps[0].rotations)
    }

    @Test
    fun `ignores short weightless moments`() {
        val jumps = run({ t ->
            when {
                t in 2.0..2.12 -> 0.1
                t in 2.12..2.17 -> 2.0
                else -> 1.0
            }
        }, 4.0)
        assertEquals(0, jumps.size)
    }

    @Test
    fun `rough trail vibration is not a jump`() {
        val rnd = Random(7)
        val jumps = run({ 1.0 + rnd.nextGaussian() * 0.6 }, 60.0)
        assertEquals(0, jumps.size)
    }

    @Test
    fun `a push on the bars mid-air does not split the flight`() {
        val jumps = run({ t ->
            when {
                t in 2.0..2.38 -> 0.05
                t in 2.38..2.40 -> 1.2
                t in 2.40..2.8 -> 0.05
                t in 2.8..2.86 -> 3.0
                else -> 1.0
            }
        }, 4.0)
        assertEquals(1, jumps.size)
        assertEquals(0.8, jumps[0].airSec, 0.06)
    }

    @Test
    fun `soft touchdown without impact is rejected`() {
        val result = run({ t -> if (t in 2.0..2.5) 0.1 else 1.0 }, 4.0)
        assertNull(result.firstOrNull())
    }

    @Test
    fun `free fall longer than 3 s is a dropped device`() {
        val result = run({ t ->
            when {
                t in 1.0..5.0 -> 0.0
                t in 5.0..5.06 -> 6.0
                else -> 1.0
            }
        }, 7.0)
        assertEquals(0, result.size)
        assertNotNull(result)
    }
}
