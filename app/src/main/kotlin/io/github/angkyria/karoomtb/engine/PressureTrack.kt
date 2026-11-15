package io.github.angkyria.karoomtb.engine

import kotlin.math.pow

/**
 * The last seconds of raw barometer samples (Karoo 2: ~13 Hz, ~0.03 hPa noise), for the height
 * lost over a jump. One sample is about ±25 cm, so a median over a second before take-off and a
 * second after landing is used; small hops stay below what it can see, drops of ~0.5 m do not.
 *
 * Measurement only: [Jump.baroDropM] is stored for analysis and does not change jump heights.
 */
class PressureTrack {
    private val times = ArrayDeque<Double>()
    private val hpa = ArrayDeque<Double>()

    fun reset() {
        times.clear()
        hpa.clear()
    }

    fun add(tSec: Double, pressureHpa: Double) {
        if (pressureHpa.isNaN() || pressureHpa <= 0.0) return
        times.addLast(tSec)
        hpa.addLast(pressureHpa)
        while (times.isNotEmpty() && tSec - times.first() > KEEP_SEC) {
            times.removeFirst()
            hpa.removeFirst()
        }
    }

    /** Height lost (m) from take-off to landing, + = landed lower; null without enough samples. */
    fun dropM(takeoffSec: Double, landSec: Double): Double? {
        val before = medianAltitude(takeoffSec - BEFORE_SEC, takeoffSec - GAP_SEC) ?: return null
        val after = medianAltitude(landSec + SETTLE_SEC, landSec + SETTLE_SEC + AFTER_SEC) ?: return null
        return before - after
    }

    private fun medianAltitude(from: Double, to: Double): Double? {
        val window = times.indices.filter { times[it] in from..to }.map { hpa[it] }.sorted()
        if (window.size < MIN_SAMPLES) return null
        return altitudeM(window[window.size / 2])
    }

    companion object {
        const val BEFORE_SEC = 1.0
        const val GAP_SEC = 0.1
        const val SETTLE_SEC = 0.3
        const val AFTER_SEC = 1.0
        const val MIN_SAMPLES = 3
        private const val KEEP_SEC = 20.0

        /** International barometric formula (as SensorManager.getAltitude with standard pressure). */
        fun altitudeM(pressureHpa: Double): Double = 44330.0 * (1.0 - (pressureHpa / 1013.25).pow(1.0 / 5.255))
    }
}
