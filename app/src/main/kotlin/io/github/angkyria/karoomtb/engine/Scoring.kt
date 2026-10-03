package io.github.angkyria.karoomtb.engine

import kotlin.math.abs
import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/**
 * Every MTB Dynamics formula lives here so the Karoo extension, the docs and the Python
 * analyser (tools/mtbdyn/scoring.py mirrors these constants) stay in sync. ScoringParityTest
 * checks both against testdata/scoring_vectors.json (tools/make_scoring_vectors.py).
 *
 * Garmin does not publish its algorithms. The definitions below follow the FIT SDK profile
 * descriptions and are calibrated to land in similar ranges:
 *
 *  - Grit: "how challenging a route could be for a cyclist in terms of time spent going over
 *    sharp turns or large grade slopes", plus trail roughness from the accelerometer.
 *    Accumulates every moving second, so longer and steeper rides score higher.
 *  - Flow: "how long distance-wise a cyclist decelerates over intervals where deceleration is
 *    unnecessary such as smooth turns or small grade angle intervals". Lower is smoother.
 */
object Scoring {
    const val G = 9.80665

    /** Speed above which a second counts as moving (m/s). */
    const val MOVING_SPEED = 1.0

    // ---- Grit ---------------------------------------------------------------------------

    /** Overall scale: a moderate 1.5-2 h trail ride lands around 20-35 kGrit. */
    const val GRIT_SCALE = 1.25
    const val GRIT_W_GRADE = 1.2
    const val GRIT_W_TURN = 1.0
    const val GRIT_W_ROUGH = 1.0

    /** Steepness term: 4 % -> 0.33, 8 % -> 1, 16 % -> 3, capped at 8 (about 30 %). Up or down. */
    fun gradeTerm(gradePct: Double): Double = min(8.0, (abs(gradePct.orZero()) / 8.0).pow(1.6))

    /** Turn term from path curvature (1/m): radius 15 m -> 1, 8 m -> 2.3, 5 m -> 4.2, capped at 6. */
    fun turnTerm(curvature: Double): Double = min(6.0, (max(0.0, curvature.orZero()) * 15.0).pow(1.3))

    /**
     * Roughness term from handlebar vibration RMS (g). Calibrated on real Karoo 2 rides, where
     * smooth gravel reads ~0.35 g, rooty singletrack ~0.9 g and rough descents 1.2-2 g:
     * 0.35 g -> 0.5, 0.6 g -> 1, 1.2 g -> 2.5, 2 g -> 4.8, capped at 6.
     */
    fun roughTerm(roughG: Double): Double =
        if (roughG.isNaN()) 0.0 else min(6.0, (max(0.0, roughG) / 0.6).pow(1.3))

    /** Grit points for one moving second. [roughG] is NaN when no accelerometer is available. */
    fun gritPerSecond(gradePct: Double, curvature: Double, roughG: Double): Double =
        GRIT_SCALE * (
            1.0 +
                GRIT_W_GRADE * gradeTerm(gradePct) +
                GRIT_W_TURN * turnTerm(curvature) +
                GRIT_W_ROUGH * roughTerm(roughG)
            )

    /** Extra grit for a landed jump (grit points per second of airtime). */
    const val GRIT_PER_AIR_SECOND = 4.0

    // ---- Flow / braking ------------------------------------------------------------------

    /** Rolling resistance on dirt. */
    const val CRR = 0.02

    /** 0.5 * rho * CdA / mass for a rider in MTB position (1/m). */
    const val AIR_K = 0.0035

    /**
     * Braking deceleration (m/s²) that starts to count. The Karoo's 1 Hz (mostly GPS) speed
     * smooths short brake taps, so real braking shows up as 0.5-1.5 m/s².
     */
    const val BRAKE_MIN = 0.3

    /** Braking deceleration (m/s²) that counts fully. */
    const val BRAKE_FULL = 1.5

    /** Deceleration (m/s²) above which a second counts as "braking" for braking-% stats. */
    const val BRAKING_THRESHOLD = 0.5

    /** Grade (%) below which a moving second counts as descending (trail descents are often gentle). */
    const val DESCENT_GRADE = -2.5

    /** Physical limit for lateral acceleration on dirt; higher values are steering wobble. */
    const val MAX_LATERAL_G = 1.5

    /** Acceleration expected while coasting (no pedalling, no brakes), m/s². */
    fun coastingAccel(speed: Double, gradePct: Double): Double {
        val theta = atan(gradePct.orZero() / 100.0)
        return -G * sin(theta) - CRR * G * cos(theta) - AIR_K * speed * speed
    }

    /**
     * Braking deceleration (m/s², never negative), following Garmin's definition of Flow which
     * looks at actual deceleration:
     *  - downhill (coasting would speed you up): only real slowing down counts, holding a steady
     *    speed with the brakes does not;
     *  - flat / uphill: slowing down faster than gravity, rolling and air resistance explain.
     */
    fun brakingDecel(observedAccel: Double, speed: Double, gradePct: Double): Double =
        max(0.0, min(0.0, coastingAccel(speed, gradePct)) - observedAccel)

    /** 0 below [BRAKE_MIN], 1 from [BRAKE_FULL]. */
    fun brakeWeight(decel: Double): Double = ((decel - BRAKE_MIN) / (BRAKE_FULL - BRAKE_MIN)).coerceIn(0.0, 1.0)

    /**
     * How much the terrain justifies slowing down: 0 = not at all, 1 = fully.
     * Uses the speed at the moment of braking and the trail a few seconds ahead.
     */
    fun brakingNecessity(speed: Double, curvature: Double, gradePct: Double, roughG: Double): Double {
        val k = max(0.0, curvature.orZero())
        // Lateral acceleration needed to hold the upcoming line at the current speed.
        val lateral = speed * speed * k
        val nLateral = ((lateral - 1.5) / 3.0).coerceIn(0.0, 1.0)
        // Tight radius: from 20 m (none) to 6 m (fully necessary) regardless of speed.
        val nRadius = ((k - 1.0 / 20.0) / (1.0 / 6.0 - 1.0 / 20.0)).coerceIn(0.0, 1.0)
        // Steep descents: from -6 % (none) to -18 % (fully necessary).
        val nGrade = ((-gradePct.orZero() - 6.0) / 12.0).coerceIn(0.0, 1.0)
        // Rough ground: from 1.0 g (none) to 2.0 g (fully necessary); typical singletrack is ~0.9 g.
        val nRough = if (roughG.isNaN()) 0.0 else ((roughG - 1.0) / 1.0).coerceIn(0.0, 1.0)
        return maxOf(nLateral, nRadius, nGrade, nRough)
    }

    /** Flow score: intensity-weighted unnecessary-braking metres per 100 m ridden. */
    fun flowScore(flowMeters: Double, distanceM: Double): Double =
        if (distanceM < 1.0) 0.0 else 100.0 * flowMeters / distanceM

    // ---- MTB score --------------------------------------------------------------------------

    /** 0-100 from average grit per moving second (a flat, smooth ride scores 0). */
    fun difficultyScore(avgGritPerSecond: Double): Double =
        100.0 * (1.0 - exp(-max(0.0, avgGritPerSecond - GRIT_SCALE) / 3.5))

    /** 0-100 from the flow score (0 flow = 100). */
    fun smoothnessScore(flowScore: Double): Double = 100.0 * exp(-max(0.0, flowScore) / 6.0)

    /** 0-100 from total airtime in seconds. */
    fun airScore(totalAirSec: Double): Double = 100.0 * (1.0 - exp(-max(0.0, totalAirSec) / 6.0))

    fun mtbScore(difficulty: Double, smoothness: Double, air: Double): Double =
        0.45 * difficulty + 0.40 * smoothness + 0.15 * air

    // ---- Jumps --------------------------------------------------------------------------

    /**
     * Peak height (m) above the lower of take-off and landing for a ballistic flight of
     * [airSec] seconds that ends [dropM] metres below the take-off (negative = step-up).
     * With no drop this is g·t²/8.
     */
    fun jumpHeight(airSec: Double, dropM: Double): Double {
        if (airSec <= 0.0) return 0.0
        val drop = dropM.orZero()
        val vz0 = (G * airSec * airSec / 2.0 - drop) / airSec
        val apex = if (vz0 > 0.0) vz0 * vz0 / (2.0 * G) else 0.0
        return apex + max(0.0, drop)
    }

    /** Our jump score (Garmin's is unpublished): rewards airtime, distance and rotations. */
    fun jumpScore(airSec: Double, distanceM: Double, rotations: Int): Double =
        100.0 * airSec + 2.0 * distanceM + 50.0 * rotations

    private fun Double.orZero(): Double = if (isNaN()) 0.0 else this
}
