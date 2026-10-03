package io.github.angkyria.karoomtb.engine

import kotlin.math.max
import kotlin.math.sqrt

/** IMU quantities accumulated over one second. */
data class ImuSecond(
    /** Vibration RMS in g over ground contact samples, NaN without data. */
    val roughG: Double,
    /** Integrated yaw (rad, + = left) and the gyro time it covers. */
    val yawRad: Double,
    val yawTimeSec: Double,
    val peakG: Double,
    val accelSamples: Int,
    val gyroSamples: Int,
)

/**
 * Turns raw accelerometer / gyroscope samples into orientation-independent quantities. The
 * Karoo can be mounted at any angle, so everything is expressed relative to a running estimate
 * of the "up" direction (low-passed specific force).
 *
 * Not thread-safe; [MtbEngine] serialises access.
 */
class ImuProcessor {
    private var upX = 0.0
    private var upY = 0.0
    private var upZ = 0.0
    var hasGravity = false
        private set

    private var lastAccelSec = Double.NaN
    private var lastGyroSec = Double.NaN

    /** |a| low-passed (~30 ms) in g; ~0 in free fall, ~1 at rest. */
    var magLpG = 1.0
        private set

    /** Unfiltered |a| in g of the latest sample. */
    var magG = 1.0
        private set

    /** Dynamic acceleration |a - gravity| low-passed at ~20 Hz (m/s²). */
    private var dynLp = 0.0

    /** Lean-corrected yaw rate about the vertical (rad/s, + = left), low-passed ~0.3 s. */
    var yawRateLp = 0.0
        private set

    var accelRateHz = 0.0
        private set

    // Per-second accumulators.
    private var dynSqSum = 0.0
    private var dynCount = 0
    private var yawIntegral = 0.0
    private var yawTime = 0.0
    private var peakG = 0.0
    private var accelSamples = 0
    private var gyroSamples = 0

    /**
     * @param freezeGravity true while airborne: free fall would otherwise drag the "up"
     *   estimate towards zero.
     * @param countRoughness false for samples that should not count as trail vibration.
     */
    fun onAccel(tSec: Double, x: Double, y: Double, z: Double, freezeGravity: Boolean, countRoughness: Boolean) {
        val dt = if (lastAccelSec.isNaN()) 0.0 else (tSec - lastAccelSec).coerceIn(0.0, 0.2)
        lastAccelSec = tSec
        if (dt > 0.0) {
            val instRate = 1.0 / dt
            accelRateHz = if (accelRateHz == 0.0) instRate else accelRateHz + 0.02 * (instRate - accelRateHz)
        }

        if (!hasGravity) {
            upX = x; upY = y; upZ = z
            hasGravity = true
        } else if (!freezeGravity && dt > 0.0) {
            val a = dt / (GRAVITY_TAU + dt)
            upX += a * (x - upX)
            upY += a * (y - upY)
            upZ += a * (z - upZ)
        }

        val mag = sqrt(x * x + y * y + z * z)
        magG = mag / Scoring.G
        magLpG = if (dt <= 0.0) magG else magLpG + dt / (MAG_TAU + dt) * (magG - magLpG)

        val dx = x - upX
        val dy = y - upY
        val dz = z - upZ
        val dyn = sqrt(dx * dx + dy * dy + dz * dz)
        dynLp = if (dt <= 0.0) dyn else dynLp + dt / (DYN_TAU + dt) * (dyn - dynLp)

        if (countRoughness) {
            dynSqSum += dynLp * dynLp
            dynCount++
        }
        peakG = max(peakG, magG)
        accelSamples++
    }

    /** @param speed current speed (m/s), needed for the lean-angle correction. */
    fun onGyro(tSec: Double, x: Double, y: Double, z: Double, speed: Double) {
        val dt = if (lastGyroSec.isNaN()) 0.0 else (tSec - lastGyroSec).coerceIn(0.0, 0.2)
        lastGyroSec = tSec
        gyroSamples++
        if (!hasGravity) return
        val norm = sqrt(upX * upX + upY * upY + upZ * upZ)
        if (norm < 1.0) return
        // Rotation about the apparent vertical. In a coordinated turn the bike (and the head unit)
        // leans, so the apparent vertical is tilted by the lean angle: divide by cos(lean).
        val projected = (x * upX + y * upY + z * upZ) / norm
        val tanLean = speed * projected / Scoring.G
        val yaw = projected * sqrt(1.0 + tanLean * tanLean).coerceAtMost(MAX_LEAN_CORRECTION)
        yawRateLp = if (dt <= 0.0) yaw else yawRateLp + dt / (YAW_TAU + dt) * (yaw - yawRateLp)
        yawIntegral += yaw * dt
        yawTime += dt
    }

    /** Returns the accumulated second and resets the accumulators. */
    fun drainSecond(): ImuSecond {
        val second = ImuSecond(
            roughG = if (dynCount > 0) sqrt(dynSqSum / dynCount) / Scoring.G else Double.NaN,
            yawRad = yawIntegral,
            yawTimeSec = yawTime,
            peakG = peakG,
            accelSamples = accelSamples,
            gyroSamples = gyroSamples,
        )
        dynSqSum = 0.0
        dynCount = 0
        yawIntegral = 0.0
        yawTime = 0.0
        peakG = 0.0
        accelSamples = 0
        gyroSamples = 0
        return second
    }

    companion object {
        /** Time constant of the "up" estimate (s). */
        const val GRAVITY_TAU = 1.0

        /** Time constant of the |a| filter used for free-fall detection (s). */
        const val MAG_TAU = 0.03

        /** ~20 Hz low-pass on vibration so 50 Hz and 100 Hz sensors give similar RMS. */
        const val DYN_TAU = 0.008

        const val YAW_TAU = 0.3
        const val MAX_LEAN_CORRECTION = 1.6
    }
}
