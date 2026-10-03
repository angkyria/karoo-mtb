package io.github.angkyria.karoomtb.engine

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sign

/**
 * Finds corners in the yaw-rate signal: a corner starts when the bike turns faster than
 * [ENTER_RATE], ends when it straightens out (or turns the other way, for S-bends) and is kept
 * when it changed heading by at least [MIN_ANGLE_DEG].
 *
 * Fed at ~10 Hz from the gyroscope, or at 1 Hz from GPS bearing when there is no gyroscope.
 */
class CornerDetector {
    private var turning = false
    private var startSec = 0.0
    private var lastSec = Double.NaN
    private var angle = 0.0
    private var direction = 0.0
    private var entrySpeed = 0.0
    private var minSpeed = 0.0
    private var lastSpeed = 0.0
    private var maxLateral = 0.0
    private var lateralLp = 0.0
    private var distance = 0.0
    private var calmSince = Double.NaN

    /** @return a finished corner or null. */
    fun update(tSec: Double, yawRate: Double, speed: Double): FinishedCorner? {
        val dt = if (lastSec.isNaN()) 0.0 else (tSec - lastSec).coerceIn(0.0, 1.5)
        lastSec = tSec
        var finished: FinishedCorner? = null

        if (turning) {
            val reversed = sign(yawRate) != direction && abs(yawRate) >= ENTER_RATE
            when {
                speed < STOP_SPEED -> {
                    finished = finish(tSec)
                }
                reversed -> {
                    finished = finish(tSec)
                }
                else -> {
                    angle += yawRate * dt
                    distance += speed * dt
                    minSpeed = min(minSpeed, speed)
                    // Smoothed over ~1 s: steering wobble of the bar-mounted gyro is not cornering load.
                    val lateral = speed * abs(yawRate) / Scoring.G
                    lateralLp += dt / (LATERAL_TAU + dt) * (lateral - lateralLp)
                    maxLateral = max(maxLateral, lateralLp)
                    lastSpeed = speed
                    if (abs(yawRate) < EXIT_RATE) {
                        if (calmSince.isNaN()) calmSince = tSec
                        if (tSec - calmSince >= EXIT_HOLD_SEC) finished = finish(calmSince)
                    } else {
                        calmSince = Double.NaN
                    }
                }
            }
        }

        if (!turning && abs(yawRate) >= ENTER_RATE && speed >= MIN_SPEED) {
            turning = true
            startSec = tSec
            angle = yawRate * dt
            direction = sign(yawRate)
            entrySpeed = speed
            minSpeed = speed
            lastSpeed = speed
            lateralLp = speed * abs(yawRate) / Scoring.G
            maxLateral = 0.0
            distance = 0.0
            calmSince = Double.NaN
        }
        return finished
    }

    /** Closes a corner that is still open at the end of the ride. */
    fun flush(tSec: Double): FinishedCorner? = if (turning) finish(tSec) else null

    private fun finish(endSec: Double): FinishedCorner? {
        turning = false
        calmSince = Double.NaN
        val duration = endSec - startSec
        val angleDeg = Math.toDegrees(angle)
        if (abs(angleDeg) < MIN_ANGLE_DEG || duration < MIN_DURATION_SEC) return null
        val radius = if (abs(angle) > 1e-3) distance / abs(angle) else Double.NaN
        return FinishedCorner(startSec, duration, angleDeg, entrySpeed, minSpeed, lastSpeed, min(maxLateral, Scoring.MAX_LATERAL_G), radius)
    }

    data class FinishedCorner(
        val startSec: Double,
        val durationSec: Double,
        val angleDeg: Double,
        val entrySpeed: Double,
        val minSpeed: Double,
        val exitSpeed: Double,
        val maxLateralG: Double,
        val radiusM: Double,
    )

    companion object {
        const val ENTER_RATE = 0.20
        const val EXIT_RATE = 0.10
        const val EXIT_HOLD_SEC = 0.5
        const val MIN_ANGLE_DEG = 35.0
        const val MIN_DURATION_SEC = 0.8
        const val MIN_SPEED = 2.0
        const val STOP_SPEED = 1.0
        const val LATERAL_TAU = 1.0
    }
}
