package io.github.angkyria.karoomtb.engine

/**
 * Jump detection presets. A bike in the air is in free fall, so the head unit reads far below
 * 1 g until the wheels touch down again.
 *
 * @param takeoffG filtered |a| (g) below which the bike counts as airborne
 * @param minAirSec shortest airtime that counts as a jump
 * @param minLandingG impact peak (g) required after touchdown
 */
enum class Sensitivity(val takeoffG: Double, val minAirSec: Double, val minLandingG: Double) {
    LOW(takeoffG = 0.35, minAirSec = 0.35, minLandingG = 1.3),
    MEDIUM(takeoffG = 0.45, minAirSec = 0.28, minLandingG = 1.15),
    HIGH(takeoffG = 0.55, minAirSec = 0.20, minLandingG = 1.05),
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
    /** Seconds of look-ahead used by Flow (braking before a corner is not penalised). */
    val flowLagSec: Int = 3,
    /** Elevation change (m) that splits the ride into climb / descent segments. */
    val segmentMinElevationM: Double = 15.0,
)
