package io.github.angkyria.karoomtb.engine

import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Finds the bike's forward axis in the Karoo's sensor frame while riding, so in-flight rotation
 * can be split into pitch, yaw and roll. No button: in a corner the head unit feels a sideways
 * push of speed × turn rate towards the inside, so averaging the horizontal acceleration
 * weighted by that expected push gives the "left" axis; forward = left × up.
 *
 * Speed changes were tried as well and are too weak against trail vibration (their direction
 * flips from ride to ride); corners agree within about 15° across rides. "Up" is the long-run
 * mean of the specific force, not the engine's 1 s estimate, which leans into every corner.
 */
class MountCalibrator {
    // Sums over riding seconds; solved for the axes on demand, so the order of seconds does not matter.
    private val accelSum = DoubleArray(3)
    private var ridingSeconds = 0
    private val pushAccelSum = DoubleArray(3)
    private var pushSum = 0.0
    private var pushSqSum = 0.0
    private var cornerAccelSqSum = 0.0
    private val cornerAccelSum = DoubleArray(3)

    var corneringSeconds = 0
        private set

    fun reset() {
        accelSum.fill(0.0)
        ridingSeconds = 0
        pushAccelSum.fill(0.0)
        pushSum = 0.0
        pushSqSum = 0.0
        cornerAccelSqSum = 0.0
        cornerAccelSum.fill(0.0)
        corneringSeconds = 0
    }

    /**
     * One riding second.
     * @param meanAccel mean specific force over the second (m/s², sensor frame)
     * @param yawRate turn rate about the vertical (rad/s, + = left)
     * @param speed m/s
     */
    fun onSecond(meanAccel: DoubleArray, yawRate: Double, speed: Double) {
        if (speed < MIN_SPEED) return
        for (i in 0..2) accelSum[i] += meanAccel[i]
        ridingSeconds++
        if (yawRate.isNaN()) return
        val push = speed * yawRate
        if (abs(push) !in MIN_PUSH..MAX_PUSH) return
        for (i in 0..2) {
            pushAccelSum[i] += push * meanAccel[i]
            cornerAccelSum[i] += meanAccel[i]
        }
        pushSum += push
        pushSqSum += push * push
        cornerAccelSqSum += dot(meanAccel, meanAccel)
        corneringSeconds++
    }

    /** The long-run "up" of the mount: mean specific force over riding seconds (unit). */
    val up: DoubleArray? get() = if (ridingSeconds > 0) unit(accelSum) else null

    /** Unit forward axis in the sensor frame, null until [MIN_SECONDS] corner seconds were seen. */
    val forward: DoubleArray?
        get() {
            if (corneringSeconds < MIN_SECONDS) return null
            val l = left() ?: return null
            return cross(l, up ?: return null)
        }

    /** How well the pushes line up with the acceleration (0..1); a rattling mount reads low. */
    val agreement: Double
        get() {
            val u = up ?: return 0.0
            val l = left() ?: return 0.0
            // Σ |a - g·u|² over corner seconds, from the running sums.
            val dynSq = cornerAccelSqSum - 2.0 * Scoring.G * dot(u, cornerAccelSum) + corneringSeconds * Scoring.G * Scoring.G
            if (pushSqSum <= 0 || dynSq <= 0) return 0.0
            return (dot(horizontalPush(u), l) / sqrt(pushSqSum * dynSq)).coerceIn(0.0, 1.0)
        }

    /** Σ push · (a - g·u), horizontal part. */
    private fun horizontalPush(u: DoubleArray): DoubleArray {
        val d = DoubleArray(3) { pushAccelSum[it] - Scoring.G * u[it] * pushSum }
        val along = dot(d, u)
        return DoubleArray(3) { d[it] - along * u[it] }
    }

    private fun left(): DoubleArray? = up?.let { unit(horizontalPush(it)) }

    companion object {
        const val MIN_SECONDS = 60
        const val MIN_SPEED = 3.0

        /** Expected sideways push (m/s²) that counts as a corner second. */
        const val MIN_PUSH = 0.8
        const val MAX_PUSH = 8.0

        fun dot(a: DoubleArray, b: DoubleArray) = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

        fun cross(a: DoubleArray, b: DoubleArray) =
            doubleArrayOf(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

        fun unit(v: DoubleArray): DoubleArray? {
            val n = sqrt(dot(v, v))
            return if (n > 1e-9) DoubleArray(3) { v[it] / n } else null
        }
    }
}

/** In-flight rotation split along the bike's axes (degrees). */
data class FlightRotation(
    /** About the lateral axis, + = nose down. */
    val pitchDeg: Double,
    /** About up, + = turning left. */
    val yawDeg: Double,
    /** About forward, + = leaning right. */
    val rollDeg: Double,
) {
    companion object {
        /** [rotation] = integrated gyro (rad, sensor frame); [forward] and [up] in the same frame. */
        fun of(rotation: DoubleArray, forward: DoubleArray, up: DoubleArray): FlightRotation? {
            val u = MountCalibrator.unit(up) ?: return null
            val f = MountCalibrator.unit(DoubleArray(3) { forward[it] - MountCalibrator.dot(forward, u) * u[it] }) ?: return null
            val left = MountCalibrator.cross(u, f)
            return FlightRotation(
                pitchDeg = Math.toDegrees(MountCalibrator.dot(rotation, left)),
                yawDeg = Math.toDegrees(MountCalibrator.dot(rotation, u)),
                rollDeg = Math.toDegrees(MountCalibrator.dot(rotation, f)),
            )
        }
    }
}
