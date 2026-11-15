package io.github.angkyria.karoomtb.engine

/**
 * Jump detection presets. A bike in the air is in free fall, so the head unit reads far below
 * 1 g until the wheels touch down again.
 *
 * @param takeoffG filtered |a| (g) below which the bike counts as airborne
 * @param minAirSec shortest airtime that counts as a jump
 * @param minLandingG impact peak (g) required after touchdown
 * @param trailTakeoffG, trailMinAirSec the same gates on a trail ([TrailMode]), where jumps are
 *   small and the bike is shaken in the air. Fitted on labelled jump spots (2026-11).
 */
enum class Sensitivity(
    val takeoffG: Double,
    val minAirSec: Double,
    val minLandingG: Double,
    val trailTakeoffG: Double,
    val trailMinAirSec: Double,
) {
    LOW(takeoffG = 0.35, minAirSec = 0.35, minLandingG = 1.3, trailTakeoffG = 0.40, trailMinAirSec = 0.30),
    MEDIUM(takeoffG = 0.45, minAirSec = 0.28, minLandingG = 1.15, trailTakeoffG = 0.50, trailMinAirSec = 0.23),
    HIGH(takeoffG = 0.55, minAirSec = 0.20, minLandingG = 1.05, trailTakeoffG = 0.60, trailMinAirSec = 0.15),
}

data class MtbConfig(
    val sensitivity: Sensitivity = Sensitivity.MEDIUM,
    /** Filtered |a| (g) that ends the airborne phase (hysteresis above takeoffG). */
    val jumpLandG: Double = 0.80,
    /** Longer "flights" are a dropped or thrown device, not a jump. */
    val jumpMaxAirSec: Double = 3.0,
    /** Minimum speed at take-off (m/s), filters out lifting the bike or a falling Karoo. */
    val jumpMinSpeed: Double = 2.2,
    /** Mean filtered |a| during the flight must stay below this (g). */
    val jumpMaxMeanAirG: Double = 0.6,
    /** [jumpMaxMeanAirG] on a trail. */
    val trailMaxMeanAirG: Double = 0.70,
    /** Median vibration RMS (g) over [trailWindowSec] at or above which the bike is on a trail. */
    val trailRoughG: Double = 0.9,
    val trailWindowSec: Int = 30,
    /** Seconds of look-ahead used by Flow (braking before a corner is not penalised). */
    val flowLagSec: Int = 3,
    /** Elevation change (m) that splits the ride into climb / descent segments. */
    val segmentMinElevationM: Double = 15.0,
)
