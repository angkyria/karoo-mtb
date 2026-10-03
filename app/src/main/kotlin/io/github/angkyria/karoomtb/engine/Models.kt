package io.github.angkyria.karoomtb.engine

import kotlinx.serialization.Serializable

/** One detected jump. Distances in metres, speeds in m/s, times in seconds. */
@Serializable
data class Jump(
    val n: Int,
    /** Wall clock (epoch ms) of take-off. */
    val takeoffWallMs: Long,
    /** Seconds since ride start (wall clock, includes pauses). */
    val offsetSec: Double,
    val airSec: Double,
    val distanceM: Double,
    /** Peak height above the lower of take-off and landing (estimate). */
    val heightM: Double,
    /** Barometric height loss from take-off to landing, null when too small to trust. */
    val dropM: Double? = null,
    val speedMs: Double,
    /** Peak |a| right after touchdown (g). */
    val landingG: Double,
    val rotationDeg: Double,
    val rotations: Int,
    val score: Double,
    val lat: Double? = null,
    val lon: Double? = null,
)

/** One detected corner (heading change of at least 35°). Positive angle = left turn. */
@Serializable
data class Corner(
    val n: Int,
    val offsetSec: Double,
    val durationSec: Double,
    val angleDeg: Double,
    val entrySpeedMs: Double,
    val minSpeedMs: Double,
    val exitSpeedMs: Double,
    val maxLateralG: Double,
    val radiusM: Double,
)

/** Raw per-second data, kept for the whole ride (and mirrored to the ride CSV). */
class SecondSample(
    val idx: Int,
    val elapsedMs: Long,
    val wallMs: Long,
    val dt: Double,
    val distanceM: Double,
    val dDist: Double,
    val speed: Double,
    val grade: Double,
    val altitude: Double,
    val lat: Double,
    val lon: Double,
    /** Vibration RMS (g), NaN without accelerometer. */
    val rough: Double,
    /** Signed yaw rate (rad/s, + = left). */
    val yawRate: Double,
    val curvature: Double,
    val latG: Double,
    val grit: Double,
    val moving: Boolean,
    val lap: Int,
    val airborne: Boolean,
    // Bike systems (NaN / -1 = not present): power meter, RockShox Flight Attendant, SRAM AXS
    val power: Double = Double.NaN,
    val cadence: Double = Double.NaN,
    val balanceLeft: Double = Double.NaN,
    /** Flight Attendant fork / shock: 0 Open, 1 Pedal, 2 Lock. */
    val faFront: Int = -1,
    val faRear: Int = -1,
    val effortZone: Int = -1,
    /** Rear gear index (1 = largest, easiest cog) and its teeth. */
    val rearGear: Int = -1,
    val rearTeeth: Int = -1,
) {
    // Filled in [MtbEngine] once the look-ahead window is available.
    var brake: Double = 0.0
    var brakeWeight: Double = 0.0
    var necessity: Double = 0.0
    var flow: Double = 0.0
    var processed: Boolean = false

    val descending: Boolean get() = moving && grade <= Scoring.DESCENT_GRADE
    val braking: Boolean get() = processed && moving && brake >= Scoring.BRAKING_THRESHOLD
    val pedalling: Boolean get() = (!cadence.isNaN() && cadence > 0.0) || (!power.isNaN() && power > 0.0)
    val hasBikeData: Boolean get() = faFront >= 0 || faRear >= 0 || rearGear > 0 || !power.isNaN() || !cadence.isNaN()
}

/** One rear shift of the SRAM AXS drivetrain. */
@Serializable
data class Shift(
    val n: Int,
    val wallMs: Long,
    val offsetSec: Double,
    val gear: Int,
    val teeth: Int? = null,
    val fromGear: Int? = null,
    val fromTeeth: Int? = null,
    val powerW: Double? = null,
    val cadenceRpm: Double? = null,
    val gradePct: Double = 0.0,
    val speedMs: Double = 0.0,
) {
    /** A shift to a larger cog (easier gear). */
    val easier: Boolean get() = fromGear != null && gear < fromGear
}

/** Flight Attendant suspension state names (Karoo values 0/1/2). */
object FaState {
    const val OPEN = 0
    const val PEDAL = 1
    const val LOCK = 2
    fun name(state: Int): String = when (state) {
        OPEN -> "Open"
        PEDAL -> "Pedal"
        LOCK -> "Lock"
        else -> "–"
    }
}

/** How well the suspension setting fits the terrain right now. */
enum class SuspensionMatch { NONE, OK, LOCKED_ROUGH, OPEN_HARD_CLIMB }

/** A GPS position (degrees). */
@Serializable
data class GeoPoint(val lat: Double, val lon: Double)

/** In-ride events raised by [MtbEngine.pollAlerts]. */
sealed class RideAlert {
    data object LockedOnRough : RideAlert()
    data class ShiftDown(val easierGears: Int) : RideAlert()
    data class BatteryLow(val component: String, val status: String) : RideAlert()

    /** The bottom of a descent was reached: its stats and GPS track (every ~20 m, empty without GPS). */
    data class DescentFinished(val stats: SegmentStats, val track: List<GeoPoint>) : RideAlert()
}

/** The descent in progress (live, see [DescentTracker]). */
data class LiveDescent(
    val number: Int,
    val timeSec: Double,
    val distanceM: Double,
    val dropM: Double,
    val avgSpeedMs: Double,
    /** Unnecessary braking per 100 m; covers the descent up to [MtbConfig.flowLagSec] seconds ago. */
    val flowScore: Double,
    val brakingPct: Double,
    val jumps: Int,
    val maxLateralG: Double,
)

/** Values written into each FIT record message. */
data class RecordValues(
    val grit: Double,
    val rough: Double?,
    val latG: Double,
    /** Flow and brake are written [MtbConfig.flowLagSec] seconds late (they need look-ahead). */
    val flow: Double,
    val brake: Double,
    val jumpAir: Double,
    val jumpDistance: Double,
    val jumpHeight: Double,
)

/** Values written into the FIT session message. */
data class SessionValues(
    val totalGritK: Double,
    val avgGrit: Double,
    val flowScore: Double,
    val totalFlowM: Double,
    val jumps: Int,
    val maxAirSec: Double,
    val totalAirSec: Double,
    val maxJumpDistanceM: Double,
    val maxJumpHeightM: Double,
    val score: Double,
    val difficulty: Double,
    val smoothness: Double,
    val airScore: Double,
    val corners: Int,
    val maxLateralG: Double,
    val cornerSpeedKeptPct: Double,
    val descentSec: Double,
    val descentBrakingPct: Double,
    val descentAvgSpeed: Double,
    val descentFlow: Double,
    val avgRough: Double,
    val flowLagSec: Int,
    // Bike systems, null when the component is not paired
    val faOpenDescentPct: Double? = null,
    val faLockedRoughSec: Double? = null,
    val faOpenHardClimbSec: Double? = null,
    val faChanges: Int? = null,
    val shifts: Int? = null,
    val shiftsPerKm: Double? = null,
    val climbPowerW: Double? = null,
    val climbWattsPerKg: Double? = null,
    val descentPedallingPct: Double? = null,
    val largestCogTeeth: Int? = null,
    val faReactionSec: Double? = null,
)

enum class RideStatus { IDLE, RECORDING, PAUSED }

/** Snapshot for the live data fields. */
data class LiveMetrics(
    val status: RideStatus = RideStatus.IDLE,
    val gritTotalK: Double = 0.0,
    val grit60: Double = 0.0,
    val gritLapK: Double = 0.0,
    val gritAvg: Double = 0.0,
    val flowScore: Double = 0.0,
    val flow60: Double = 0.0,
    val flowLap: Double = 0.0,
    val jumpCount: Int = 0,
    val lastJump: Jump? = null,
    val maxAirSec: Double = 0.0,
    val totalAirSec: Double = 0.0,
    val latG: Double = 0.0,
    val maxLatG: Double = 0.0,
    val cornerCount: Int = 0,
    val rough60: Double? = null,
    val descentBrakingPct: Double = 0.0,
    val mtbScore: Double = 0.0,
    val hasAccelerometer: Boolean = false,
    val hasGyroscope: Boolean = false,
    // Bike systems
    val faFront: Int = -1,
    val effortZone: Int = -1,
    val suspensionMatch: SuspensionMatch = SuspensionMatch.NONE,
    val roughNow: Double? = null,
    val faOpenDescentPct: Double? = null,
    val rearGear: Int = -1,
    val rearTeeth: Int = -1,
    val easierGearsLeft: Int = -1,
    val shifts: Int = 0,
    val power: Double? = null,
    // Descents
    val descent: LiveDescent? = null,
    val lastDescent: SegmentStats? = null,
)

data class TickOutput(
    val record: RecordValues?,
    val live: LiveMetrics,
)

// ---- Ride summary (stored as JSON, sent over ntfy) -------------------------------------------

@Serializable
data class GritStats(val totalK: Double, val avgPerSec: Double, val peak60: Double)

@Serializable
data class FlowStats(val score: Double, val totalM: Double, val worst60: Double, val descentScore: Double)

@Serializable
data class JumpStats(
    val count: Int,
    val totalAirSec: Double,
    val longest: Jump? = null,
    val farthest: Jump? = null,
    val highest: Jump? = null,
    val hardestLanding: Jump? = null,
    val list: List<Jump> = emptyList(),
)

@Serializable
data class CornerStats(
    val count: Int,
    val left: Int,
    val right: Int,
    val avgEntrySpeedMs: Double,
    val avgMinSpeedMs: Double,
    /** Average apex speed as a share of entry speed (100 = no speed lost). */
    val speedKeptPct: Double,
    val maxLateralG: Double,
    val avgPeakLateralG: Double,
    val sharpestRadiusM: Double?,
    /** Speed kept in left / right corners (null with fewer than 5 corners on that side). */
    val speedKeptLeftPct: Double? = null,
    val speedKeptRightPct: Double? = null,
)

/** Laps of about the same distance compared with each other. */
@Serializable
data class LapComparison(
    val comparable: Int,
    val laps: Int,
    val fastestLap: Int,
    val fastestSec: Double,
    val medianSec: Double,
    val smoothestLap: Int,
    val smoothestFlow: Double,
    /** Last third of the comparable laps vs the first third, % time (+ = slower); null below 4 laps. */
    val trendPct: Double? = null,
)

/** A stretch with unnecessary braking (where Flow was lost). */
@Serializable
data class BrakingSpot(
    val offsetSec: Double,
    /** Ride distance where the braking started. */
    val distanceM: Double,
    /** Unnecessary-braking metres. */
    val flowM: Double,
    val durationSec: Double,
    val speedBeforeMs: Double,
    val speedAfterMs: Double,
    val lat: Double? = null,
    val lon: Double? = null,
    /** Climb / descent it is in, e.g. "Descent 2". */
    val segment: String? = null,
)

@Serializable
data class DescentStats(
    val timeSec: Double,
    val distanceM: Double,
    val dropM: Double,
    val avgSpeedMs: Double,
    val maxSpeedMs: Double,
    val brakingPct: Double,
    val flowScore: Double,
    val gritK: Double,
    val jumps: Int,
)

@Serializable
data class ScoreStats(val total: Double, val difficulty: Double, val smoothness: Double, val air: Double)

@Serializable
data class SegmentStats(
    val index: Int,
    /** CLIMB, DESCENT, FLAT or LAP. */
    val type: String,
    val name: String,
    val startOffsetSec: Double,
    val durationSec: Double,
    val distanceM: Double,
    val elevGainM: Double,
    val elevLossM: Double,
    val avgGradePct: Double,
    val avgSpeedMs: Double,
    val maxSpeedMs: Double,
    val gritK: Double,
    val gritAvg: Double,
    val flowScore: Double,
    val roughAvg: Double?,
    val jumps: Int,
    val maxAirSec: Double,
    val brakingPct: Double,
    val maxLateralG: Double,
    val corners: Int,
    // Bike systems (null when not recorded)
    val avgPowerW: Double? = null,
    val wattsPerKg: Double? = null,
    val vamMh: Double? = null,
    val cadenceRpm: Double? = null,
    val medianCogTeeth: Int? = null,
    val faOpenPct: Double? = null,
    val faPedalPct: Double? = null,
    val faLockPct: Double? = null,
    val pedallingPct: Double? = null,
    val shifts: Int = 0,
)

@Serializable
data class StateShare(val open: Double, val pedal: Double, val lock: Double)

@Serializable
data class EffortZoneStat(val zone: Int, val minutes: Double, val avgPowerW: Double?)

@Serializable
data class SuspensionStats(
    val overall: StateShare,
    val climbs: StateShare? = null,
    val descents: StateShare? = null,
    val flats: StateShare? = null,
    /** Lock while the trail vibrated at >= 0.9 g. */
    val lockedRoughSec: Double,
    /** Open while pushing >= 200 W uphill. */
    val openHardClimbSec: Double,
    val forkShockDifferSec: Double,
    val changes: Int,
    val changesPerKm: Double,
    val descentsReachingOpen: Int,
    val descentCount: Int,
    val reactionSecMedian: Double? = null,
    val effortZones: List<EffortZoneStat> = emptyList(),
    val mode: Int? = null,
    val bias: Int? = null,
    /** Usage for the service tracker: moving time with fork / shock data, and of it on rough ground. */
    val trackedSec: Double = 0.0,
    val rearTrackedSec: Double = 0.0,
    val roughSec: Double = 0.0,
)

@Serializable
data class DrivetrainStats(
    val shifts: Int,
    val shiftsPerKm: Double,
    /** Minutes per rear cog (teeth). */
    val cogMinutes: Map<Int, Double>,
    val smallestCogTeeth: Int? = null,
    val largestCogTeeth: Int? = null,
    /** Easier gears (larger cogs) never used, from the gear index of the largest cog used. */
    val easierGearsUnused: Int? = null,
    val climbMedianCog: Int? = null,
    val descentMedianCog: Int? = null,
    val flatMedianCog: Int? = null,
    val underLoad: Int,
    val climbShiftsBefore: Int,
    val climbShiftsAfter: Int,
    val steepCadenceRpm: Double? = null,
    val steepTorqueNm: Double? = null,
    val steepLowCadenceSec: Double = 0.0,
    /** Distance ridden with AXS gear data (chain wear). */
    val trackedKm: Double = 0.0,
)

@Serializable
data class PowerTerrain(val avgW: Double, val wattsPerKg: Double? = null, val pedallingPct: Double, val balanceLeft: Double? = null)

@Serializable
data class PowerStats(
    val avgW: Double,
    val climbs: PowerTerrain? = null,
    val descents: PowerTerrain? = null,
    val flats: PowerTerrain? = null,
    val best5minW: Double? = null,
    val weightKg: Double? = null,
)

@Serializable
data class BatteryInfo(val component: String, val status: String, val percent: Int? = null)

@Serializable
data class BikeStats(
    val suspension: SuspensionStats? = null,
    val drivetrain: DrivetrainStats? = null,
    val power: PowerStats? = null,
    val batteries: List<BatteryInfo> = emptyList(),
    val faMode: Int? = null,
    val faBias: Int? = null,
)

@Serializable
data class SensorInfo(
    val accelerometer: Boolean,
    val gyroscope: Boolean,
    val accelRateHz: Double,
)

@Serializable
data class RideSummary(
    val schema: Int = 1,
    val appVersion: String = "",
    val startWallMs: Long,
    val endWallMs: Long,
    val profileName: String? = null,
    val device: String? = null,
    val elapsedSec: Double,
    val movingSec: Double,
    val distanceM: Double,
    val ascentM: Double,
    val descentM: Double,
    val avgSpeedMs: Double,
    val maxSpeedMs: Double,
    val grit: GritStats,
    val flow: FlowStats,
    val jumps: JumpStats,
    val cornering: CornerStats,
    val descending: DescentStats,
    val roughnessAvg: Double?,
    val score: ScoreStats,
    val segments: List<SegmentStats>,
    val laps: List<SegmentStats>,
    val sensors: SensorInfo,
    val flowLagSec: Int,
    val bike: BikeStats = BikeStats(),
    val lapComparison: LapComparison? = null,
    val brakingSpots: List<BrakingSpot> = emptyList(),
)
