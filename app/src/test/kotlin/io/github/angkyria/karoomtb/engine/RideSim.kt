package io.github.angkyria.karoomtb.engine

import java.util.Random

/**
 * Drives an [MtbEngine] like the Karoo would: 100 Hz accelerometer + gyroscope (device mounted
 * upright, so gravity is +z and yaw is the z rate), 1 Hz context updates and a tick per second.
 */
class RideSim(val engine: MtbEngine = MtbEngine(), seed: Long = 42, private val rateHz: Int = 100) {
    private val rnd = Random(seed)
    private val g = Scoring.G

    val startElapsedMs = 5_000_000L
    val startWallMs = 1_790_000_000_000L
    var elapsedMs = startElapsedMs
        private set
    var distance = 0.0
        private set

    /** Absolute flight windows in ride seconds. */
    private val flights = ArrayList<ClosedFloatingPointRange<Double>>()
    private val landingG = 3.0

    val outputs = ArrayList<TickOutput>()
    val landed = ArrayList<Jump>()

    init {
        engine.jumpListener = { landed += it }
    }

    fun start(config: MtbConfig = MtbConfig()) {
        engine.start(startWallMs, startElapsedMs, config)
    }

    fun rideSeconds(): Double = (elapsedMs - startElapsedMs) / 1000.0

    /** Schedule a flight starting [inSeconds] from now lasting [airSec]. */
    fun jumpIn(inSeconds: Double, airSec: Double) {
        val t0 = rideSeconds() + inSeconds
        flights += t0..(t0 + airSec)
    }

    fun ride(
        seconds: Int,
        speed: (Int) -> Double,
        grade: (Int) -> Double = { 0.0 },
        altitude: (Int) -> Double = { 100.0 },
        yawRate: (Int) -> Double = { 0.0 },
        vibrationG: Double = 0.05,
        /** Called at the start of each second, e.g. to feed bike streams (power, Flight Attendant, gears). */
        each: (Int) -> Unit = {},
    ) {
        for (i in 0 until seconds) {
            each(i)
            val v = speed(i)
            engine.updateSpeed(v, elapsedMs)
            engine.updateGrade(grade(i))
            engine.updateAltitude(altitude(i))
            distance += v
            engine.updateDistance(distance)
            val stepMs = 1000.0 / rateHz
            for (k in 0 until rateHz) {
                val tMs = elapsedMs + k * stepMs
                val rideSec = (tMs - startElapsedMs) / 1000.0
                val inAir = flights.any { rideSec in it }
                val justLanded = flights.any { rideSec > it.endInclusive && rideSec <= it.endInclusive + 0.06 }
                val az = when {
                    inAir -> 0.05 * g + rnd.nextGaussian() * 0.02 * g
                    justLanded -> landingG * g
                    else -> g + rnd.nextGaussian() * vibrationG * g
                }
                val ax = rnd.nextGaussian() * vibrationG * 0.5 * g
                val ay = rnd.nextGaussian() * vibrationG * 0.5 * g
                val ns = (tMs * 1_000_000).toLong()
                engine.onAccel(ns, ax.toFloat(), ay.toFloat(), az.toFloat())
                engine.onGyro(ns, (rnd.nextGaussian() * 0.01).toFloat(), (rnd.nextGaussian() * 0.01).toFloat(), yawRate(i).toFloat())
            }
            elapsedMs += 1000
            outputs += engine.tick(elapsedMs, startWallMs + (elapsedMs - startElapsedMs))
        }
    }

    /** Wall-clock time of the current simulated moment. */
    fun wallMs(): Long = startWallMs + (elapsedMs - startElapsedMs)

    fun finish(): RideSummary = engine.finish(startWallMs + (elapsedMs - startElapsedMs), SummaryMeta("test", "Trail", "K2"))
}
