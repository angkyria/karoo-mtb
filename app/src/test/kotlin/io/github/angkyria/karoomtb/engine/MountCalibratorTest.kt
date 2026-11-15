package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Random
import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.sin

class MountCalibratorTest {
    // Bike axes in a Karoo frame like the rider's (screen tilted ~13° back, top towards the rider):
    // forward = -y tilted, up = mostly +z. Built from a rotation so the axes stay orthonormal.
    private val tilt = Math.toRadians(13.0)
    private val bikeForward = doubleArrayOf(0.0, -cos(tilt), -sin(tilt))
    private val bikeUp = doubleArrayOf(0.0, -sin(tilt), cos(tilt))
    private val bikeLeft = MountCalibrator.cross(bikeUp, bikeForward)

    private fun sensor(fwd: Double, left: Double, up: Double) =
        DoubleArray(3) { bikeForward[it] * fwd + bikeLeft[it] * left + bikeUp[it] * up }

    private fun angleDeg(a: DoubleArray, b: DoubleArray) = Math.toDegrees(acos(MountCalibrator.dot(a, b).coerceIn(-1.0, 1.0)))

    /** Seconds of riding: corners left and right, braking and vibration noise on every axis. */
    private fun ride(cal: MountCalibrator, seconds: Int, noise: Double = 1.0) {
        val rnd = Random(11)
        repeat(seconds) { i ->
            val v = 6.0
            val yaw = 0.4 * sin(i / 5.0)                 // turning left and right
            val push = v * yaw                           // m/s² towards the inside of the corner
            val brake = if (i % 7 == 0) -2.0 else 0.0
            val a = sensor(brake, push, Scoring.G)
            for (k in 0..2) a[k] += rnd.nextGaussian() * noise
            cal.onSecond(a, yaw, v)
        }
    }

    @Test
    fun `finds the forward axis from corners`() {
        val cal = MountCalibrator()
        ride(cal, 600)
        val f = assertNotNullAndGet(cal.forward)
        assertTrue("off by ${angleDeg(f, bikeForward)}°", angleDeg(f, bikeForward) < 5.0)
        assertTrue("agreement ${cal.agreement}", cal.agreement > 0.3)
    }

    @Test
    fun `needs enough corner seconds`() {
        val cal = MountCalibrator()
        ride(cal, 40)
        assertNull(cal.forward)
    }

    @Test
    fun `straight riding does not calibrate`() {
        val cal = MountCalibrator()
        repeat(600) { cal.onSecond(sensor(0.5, 0.0, Scoring.G), 0.0, 6.0) }
        assertEquals(0, cal.corneringSeconds)
        assertNull(cal.forward)
    }

    @Test
    fun `reset forgets the mount`() {
        val cal = MountCalibrator()
        ride(cal, 600)
        cal.reset()
        assertNull(cal.forward)
        assertEquals(0, cal.corneringSeconds)
    }

    @Test
    fun `flight rotation is split along the bike axes`() {
        val nose = Math.toRadians(12.0)
        val turn = Math.toRadians(-20.0)
        val rotation = DoubleArray(3) { bikeLeft[it] * nose + bikeUp[it] * turn }
        val r = assertNotNullAndGet(FlightRotation.of(rotation, bikeForward, bikeUp))
        assertEquals(12.0, r.pitchDeg, 1e-6)
        assertEquals(-20.0, r.yawDeg, 1e-6)
        assertEquals(0.0, r.rollDeg, 1e-6)
    }

    private fun <T> assertNotNullAndGet(value: T?): T {
        assertNotNull(value)
        return value!!
    }
}
