package io.github.angkyria.karoomtb.engine

import java.util.Locale
import kotlin.math.floor
import kotlin.math.sqrt

/** A flight that passed the accelerometer checks (speed is checked by [MtbEngine]). */
data class RawJump(
    val takeoffSec: Double,
    val landSec: Double,
    val airSec: Double,
    val meanAirG: Double,
    val landingG: Double,
    val rotationDeg: Double,
) {
    val rotations: Int get() = floor((rotationDeg + 60.0) / 360.0).toInt()
}

/**
 * Any flight the detector saw, accepted or not, for the "mark" button and offline tuning.
 * [reason] is empty when it passed the accelerometer checks.
 */
data class Flight(val takeoffSec: Double, val airSec: Double, val meanAirG: Double, val landingG: Double, val reason: String) {
    val accepted: Boolean get() = reason.isEmpty()
}

/**
 * Take-off → airborne → landing state machine on the filtered acceleration magnitude.
 *
 * While the bike is in the air the head unit is in free fall and |a| drops well below 1 g.
 * Touchdown is the moment |a| climbs back over [MtbConfig.jumpLandG]; the landing is only
 * accepted if an impact peak follows within [LANDING_WINDOW_SEC].
 */
class JumpDetector(private var config: MtbConfig) {
    enum class State { GROUND, AIR, LANDING }

    var state = State.GROUND
        private set

    val airborne: Boolean get() = state == State.AIR

    /** The last completed flight (from [MIN_FLIGHT_SEC]), accepted or rejected. */
    var lastFlight: Flight? = null
        private set

    private var airStart = 0.0
    private var landTime = 0.0
    private var sumG = 0.0
    private var countG = 0
    private var peakLandingG = 0.0
    private var cooldownUntil = 0.0
    private var lastGyroSec = Double.NaN
    private var rotX = 0.0
    private var rotY = 0.0
    private var rotZ = 0.0

    fun reconfigure(newConfig: MtbConfig) {
        config = newConfig
    }

    fun reset() {
        state = State.GROUND
        cooldownUntil = 0.0
        lastFlight = null
    }

    /** @return a finished, validated flight or null. */
    fun onAccel(tSec: Double, magLpG: Double, magG: Double): RawJump? {
        val takeoffG = config.sensitivity.takeoffG
        when (state) {
            State.GROUND -> if (tSec >= cooldownUntil && magLpG < takeoffG) {
                state = State.AIR
                airStart = tSec
                sumG = 0.0
                countG = 0
                rotX = 0.0
                rotY = 0.0
                rotZ = 0.0
                lastGyroSec = Double.NaN
            }

            State.AIR -> {
                sumG += magLpG
                countG++
                if (magLpG > config.jumpLandG) {
                    state = State.LANDING
                    landTime = tSec
                    peakLandingG = magG
                } else if (tSec - airStart > config.jumpMaxAirSec) {
                    // Far too long for a jump: dropped or thrown device.
                    state = State.GROUND
                    cooldownUntil = tSec + 1.0
                    lastFlight = Flight(airStart, tSec - airStart, if (countG > 0) sumG / countG else 1.0, 0.0, "longer than ${config.jumpMaxAirSec} s")
                }
            }

            State.LANDING -> {
                if (magG > peakLandingG) peakLandingG = magG
                if (magLpG < takeoffG && tSec - landTime < GLITCH_SEC) {
                    // A short push on the bars mid-air, not a touchdown.
                    state = State.AIR
                } else if (tSec - landTime >= LANDING_WINDOW_SEC) {
                    state = State.GROUND
                    cooldownUntil = tSec + COOLDOWN_SEC
                    return validate()
                }
            }
        }
        return null
    }

    fun onGyro(tSec: Double, x: Double, y: Double, z: Double) {
        if (state != State.AIR) {
            lastGyroSec = Double.NaN
            return
        }
        if (!lastGyroSec.isNaN()) {
            val dt = (tSec - lastGyroSec).coerceIn(0.0, 0.2)
            rotX += x * dt
            rotY += y * dt
            rotZ += z * dt
        }
        lastGyroSec = tSec
    }

    private fun validate(): RawJump? {
        val air = landTime - airStart
        val meanG = if (countG > 0) sumG / countG else 1.0
        val s = config.sensitivity
        val reason = when {
            air < s.minAirSec -> String.format(Locale.ROOT, "airtime %.2f s < %.2f", air, s.minAirSec)
            air > config.jumpMaxAirSec -> "longer than ${config.jumpMaxAirSec} s"
            meanG > config.jumpMaxMeanAirG -> String.format(Locale.ROOT, "mean %.2f g in flight", meanG)
            peakLandingG < s.minLandingG -> String.format(Locale.ROOT, "landing %.2f g < %.2f", peakLandingG, s.minLandingG)
            else -> ""
        }
        if (air >= MIN_FLIGHT_SEC) lastFlight = Flight(airStart, air, meanG, peakLandingG, reason)
        if (reason.isNotEmpty()) return null
        val rotationDeg = Math.toDegrees(sqrt(rotX * rotX + rotY * rotY + rotZ * rotZ))
        return RawJump(airStart, landTime, air, meanG, peakLandingG, rotationDeg)
    }

    /** The engine rejected an accepted flight later (take-off speed). */
    fun rejectLast(reason: String) {
        lastFlight = lastFlight?.copy(reason = reason)
    }

    companion object {
        /** Spikes shorter than this inside a flight do not end it (s). */
        const val GLITCH_SEC = 0.05

        /** Time after touchdown in which the impact peak is measured (s). */
        const val LANDING_WINDOW_SEC = 0.35

        const val COOLDOWN_SEC = 0.25

        /** Shorter dips below the take-off threshold are not reported as flights. */
        const val MIN_FLIGHT_SEC = 0.08
    }
}
