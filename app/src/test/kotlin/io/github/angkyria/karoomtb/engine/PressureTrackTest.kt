package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Random

class PressureTrackTest {
    /** ~13 Hz pressure for a 0.6 s flight at 10 s that lands [dropM] lower, with sensor noise. */
    private fun track(dropM: Double, noiseHpa: Double = 0.03): PressureTrack {
        val p = PressureTrack()
        val rnd = Random(3)
        val p0 = 980.0
        var t = 0.0
        while (t < 14.0) {
            val alt = if (t < 10.0) 0.0 else -dropM
            // ~0.118 hPa per metre near 980 hPa
            p.add(t, p0 + alt * -0.1176 + rnd.nextGaussian() * noiseHpa)
            t += 0.075
        }
        return p
    }

    @Test
    fun `a 1 m drop is measured`() {
        assertEquals(1.0, track(1.0).dropM(10.0, 10.6)!!, 0.25)
    }

    @Test
    fun `flat ground reads about zero`() {
        assertEquals(0.0, track(0.0).dropM(10.0, 10.6)!!, 0.25)
    }

    @Test
    fun `no samples, no drop`() {
        assertNull(PressureTrack().dropM(10.0, 10.6))
    }

    @Test
    fun `old samples are dropped`() {
        val p = track(1.0)
        p.add(40.0, 980.0)
        assertNull(p.dropM(10.0, 10.6))
    }

    @Test
    fun `barometric formula`() {
        assertEquals(0.0, PressureTrack.altitudeM(1013.25), 1e-9)
        assertEquals(110.9, PressureTrack.altitudeM(1000.0), 0.2)
    }
}
