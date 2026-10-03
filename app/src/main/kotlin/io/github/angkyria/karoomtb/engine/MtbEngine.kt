package io.github.angkyria.karoomtb.engine

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToLong

/** What a finished ride needs besides the sensor data. */
data class SummaryMeta(
    val appVersion: String,
    val profileName: String?,
    val device: String?,
    /** Karoo's own elevation gain / loss, NaN if unavailable. */
    val ascentM: Double = Double.NaN,
    val descentM: Double = Double.NaN,
)

/** Data that became final since the last [MtbEngine.drainForStorage] call. */
data class StorageBatch(
    val samples: List<SecondSample>,
    val jumps: List<Jump>,
    val corners: List<Corner>,
    val shifts: List<Shift> = emptyList(),
)

/**
 * The MTB Dynamics engine. Pure Kotlin (no Android), thread-safe.
 *
 *  - IMU samples arrive at 50-100 Hz from the sensor thread ([onAccel], [onGyro]).
 *  - Karoo data streams update the riding context ([updateSpeed], [updateGrade], ...).
 *  - [tick] is called once per second while recording. It closes the second, computes Grit,
 *    evaluates Flow for the second [MtbConfig.flowLagSec] seconds ago (Flow needs to see what
 *    is coming: braking before a tight corner is fine) and returns the FIT record values.
 *
 * Time base: everything uses the monotonic elapsed-realtime clock (IMU nanos / 1e9 and tick
 * milliseconds share it); wall-clock time is only attached for output.
 */
class MtbEngine(config: MtbConfig = MtbConfig()) {
    private val lock = Any()

    var config: MtbConfig = config
        private set

    @Volatile
    var status: RideStatus = RideStatus.IDLE
        private set

    /** Called (outside the lock) on the sensor thread whenever a jump lands. */
    @Volatile
    var jumpListener: ((Jump) -> Unit)? = null

    private val imu = ImuProcessor()
    private val jumpDetector = JumpDetector(config)
    private var cornerDetector = CornerDetector()

    // Latest context from the Karoo.
    private var speed = 0.0
    private var grade = 0.0
    private var altitude = Double.NaN
    private var distanceTotal = Double.NaN
    private var lat = Double.NaN
    private var lon = Double.NaN
    private var bearing = Double.NaN
    private var lastTickBearing = Double.NaN
    private val speedHistory = ArrayDeque<Pair<Long, Double>>()

    // Bike systems: power meter, RockShox Flight Attendant, SRAM AXS (NaN / -1 = not paired).
    private var power = Double.NaN
    private var cadence = Double.NaN
    private var balanceLeft = Double.NaN
    private var faFront = -1
    private var faRear = -1
    private var effortZone = -1
    private var faMode: Int? = null
    private var faBias: Int? = null
    private var rearGear = -1
    private var rearTeeth = -1
    private var riderWeightKg = Double.NaN
    private val batteries = LinkedHashMap<String, BatteryInfo>()

    @Volatile
    var hasAccelerometer = false
        private set

    @Volatile
    var hasGyroscope = false
        private set

    // Ride data.
    private var rideStartWallMs = 0L
    private var rideStartElapsedMs = 0L
    private var lastTickElapsedMs = 0L
    private var lastTickSec = Double.NaN
    private var lastDistanceTotal = Double.NaN
    private var cumDistance = 0.0
    private var gritBonus = 0.0
    private var airborneThisSecond = false
    private var lastCornerFeedSec = Double.NaN

    private val samples = ArrayList<SecondSample>()
    private var processedUpTo = -1
    private val jumps = ArrayList<Jump>()
    private val jumpsAwaitingAltitude = ArrayList<Int>()
    private val jumpsForNextRecord = ArrayList<Jump>()
    private val corners = ArrayList<Corner>()
    private val lapStarts = arrayListOf(0)
    private var totals = Totals()
    private val lapTotals = arrayListOf(Totals())

    private val storageSamples = ArrayList<SecondSample>()
    private val storageJumps = ArrayList<Jump>()
    private val storageCorners = ArrayList<Corner>()
    private val shifts = ArrayList<Shift>()
    private val storageShifts = ArrayList<Shift>()

    // Live coaching and alerts.
    private val coach = BikeCoach()
    private val pendingAlerts = ArrayList<RideAlert>()

    /** Any power, cadence, Flight Attendant or AXS data this ride (else the bike totals are skipped). */
    private var bikeDataSeen = false

    // Live descents: found by the tracker, reported once Flow has caught up with their last second.
    private val descents = DescentTracker()
    private val descentsAwaitingFlow = ArrayList<DescentTracker.Finished>()
    private var lastDescent: SegmentStats? = null

    // ---- Ride lifecycle ---------------------------------------------------------------------

    fun start(wallMs: Long, elapsedMs: Long, newConfig: MtbConfig = config) = synchronized(lock) {
        config = newConfig
        jumpDetector.reconfigure(newConfig)
        jumpDetector.reset()
        cornerDetector = CornerDetector()
        rideStartWallMs = wallMs
        rideStartElapsedMs = elapsedMs
        lastTickElapsedMs = 0L
        lastTickSec = Double.NaN
        lastDistanceTotal = Double.NaN
        lastTickBearing = Double.NaN
        cumDistance = 0.0
        gritBonus = 0.0
        airborneThisSecond = false
        samples.clear()
        processedUpTo = -1
        jumps.clear()
        jumpsAwaitingAltitude.clear()
        jumpsForNextRecord.clear()
        corners.clear()
        lapStarts.clear()
        lapStarts += 0
        totals = Totals()
        lapTotals.clear()
        lapTotals += Totals()
        storageSamples.clear()
        storageJumps.clear()
        storageCorners.clear()
        shifts.clear()
        storageShifts.clear()
        coach.reset()
        pendingAlerts.clear()
        bikeDataSeen = false
        descents.reset()
        descentsAwaitingFlow.clear()
        lastDescent = null
        // Bike state is per ride (the next ride may be on another bike); the streams refill it.
        power = Double.NaN
        cadence = Double.NaN
        balanceLeft = Double.NaN
        faFront = -1
        faRear = -1
        effortZone = -1
        faMode = null
        faBias = null
        rearGear = -1
        rearTeeth = -1
        batteries.clear()
        status = RideStatus.RECORDING
    }

    fun pause() = synchronized(lock) {
        if (status == RideStatus.RECORDING) status = RideStatus.PAUSED
    }

    fun resume() = synchronized(lock) {
        if (status == RideStatus.PAUSED) {
            status = RideStatus.RECORDING
            // The paused gap is not a riding second.
            lastTickElapsedMs = 0L
            lastDistanceTotal = Double.NaN
            jumpDetector.reset()
        }
    }

    /** Marks the start of a new lap at the next second. */
    fun markLap() = synchronized(lock) {
        if (status == RideStatus.IDLE) return@synchronized
        lapStarts += samples.size
        lapTotals += Totals()
    }

    /**
     * Rebuilds the ride after the extension process restarted mid-ride. [restoredSamples] must
     * be the processed samples written by [drainForStorage] (oldest first).
     */
    fun restore(
        startWallMs: Long,
        nowWallMs: Long,
        nowElapsedMs: Long,
        restoredSamples: List<SecondSample>,
        restoredJumps: List<Jump>,
        restoredCorners: List<Corner>,
        newConfig: MtbConfig = config,
        restoredShifts: List<Shift> = emptyList(),
    ) = synchronized(lock) {
        start(startWallMs, nowElapsedMs - (nowWallMs - startWallMs), newConfig)
        var lap = 0
        for (s in restoredSamples) {
            // Elapsed time restarts after a reboot, so rebuild it from the wall clock.
            val sample = s.restoredAs(samples.size, rideStartElapsedMs + (s.wallMs - startWallMs))
            while (sample.lap > lap) {
                lap++
                lapStarts += samples.size
                lapTotals += Totals()
            }
            samples += sample
            totals.addImmediate(sample)
            totals.addProcessed(sample)
            lapTotals[lapTotals.lastIndex].addImmediate(sample)
            lapTotals[lapTotals.lastIndex].addProcessed(sample)
            cumDistance = sample.distanceM
            coach.onRestored(sample)
            if (sample.hasBikeData) bikeDataSeen = true
        }
        processedUpTo = samples.lastIndex
        jumps += restoredJumps
        corners += restoredCorners
        shifts += restoredShifts
        // Replay the descent tracker silently so numbering and a descent in progress continue.
        for (i in samples.indices) descents.onSample(samples, i, config.segmentMinElevationM)
    }

    // ---- Context from Karoo streams ---------------------------------------------------------

    fun updateSpeed(metersPerSecond: Double, elapsedMs: Long) = synchronized(lock) {
        if (metersPerSecond.isNaN()) return@synchronized
        speed = max(0.0, metersPerSecond)
        speedHistory.addLast(elapsedMs to speed)
        while (speedHistory.size > 1 && elapsedMs - speedHistory.first().first > SPEED_HISTORY_MS) speedHistory.removeFirst()
    }

    fun updateGrade(gradePct: Double) = synchronized(lock) {
        if (!gradePct.isNaN()) grade = gradePct.coerceIn(-60.0, 60.0)
    }

    fun updateAltitude(meters: Double) = synchronized(lock) {
        if (!meters.isNaN()) altitude = meters
    }

    fun updateDistance(meters: Double) = synchronized(lock) {
        if (!meters.isNaN()) distanceTotal = meters
    }

    fun updateLocation(latitude: Double, longitude: Double, bearingDeg: Double?) = synchronized(lock) {
        lat = latitude
        lon = longitude
        if (bearingDeg != null && !bearingDeg.isNaN()) bearing = bearingDeg
    }

    // ---- Bike systems (karoo-ext streams) ------------------------------------------------

    fun updatePower(watts: Double?) = synchronized(lock) { power = watts?.takeIf { it >= 0 } ?: Double.NaN }

    fun updateCadence(rpm: Double?) = synchronized(lock) { cadence = rpm?.takeIf { it >= 0 } ?: Double.NaN }

    fun updateBalance(leftPct: Double?) = synchronized(lock) {
        balanceLeft = leftPct?.takeIf { it > 0 && it < 100 } ?: Double.NaN
    }

    /** Flight Attendant: state 0 Open, 1 Pedal, 2 Lock; null keeps the previous value, -1 = gone. */
    fun updateSuspension(front: Int? = null, rear: Int? = null, effortZone: Int? = null, mode: Int? = null, bias: Int? = null) =
        synchronized(lock) {
            front?.let { faFront = it }
            rear?.let { faRear = it }
            effortZone?.let { this.effortZone = it }
            mode?.let { faMode = it }
            bias?.let { faBias = it }
        }

    /** SRAM AXS rear gear (1 = largest cog) and its teeth; a change of gear while recording is a shift. */
    fun updateGears(gear: Int?, teeth: Int?, elapsedMs: Long, wallMs: Long) = synchronized(lock) {
        if (gear == null || gear <= 0) {
            if (gear != null) {
                rearGear = -1
                rearTeeth = -1
            }
            return@synchronized
        }
        if (rearGear > 0 && gear != rearGear && status == RideStatus.RECORDING) {
            val shift = Shift(
                n = shifts.size + 1,
                wallMs = wallMs,
                offsetSec = (elapsedMs - rideStartElapsedMs) / 1000.0,
                gear = gear,
                teeth = teeth?.takeIf { it > 0 },
                fromGear = rearGear,
                fromTeeth = rearTeeth.takeIf { it > 0 },
                powerW = power.takeUnless { it.isNaN() },
                cadenceRpm = cadence.takeUnless { it.isNaN() },
                gradePct = grade,
                speedMs = speed,
            )
            shifts += shift
            storageShifts += shift
        }
        rearGear = gear
        if (teeth != null && teeth > 0) rearTeeth = teeth
    }

    fun setRiderWeight(kg: Double) = synchronized(lock) { if (kg > 20) riderWeightKg = kg }

    /** Battery status (BatteryStatus name) of a paired component; [percent] when the source reports one. */
    fun setBattery(component: String, status: String, percent: Int? = null) = synchronized(lock) {
        if (this.status == RideStatus.IDLE) return@synchronized
        batteries[component] = BatteryInfo(component, status, percent)
        coach.onBattery(component, status, pendingAlerts)
    }

    /** Coaching alerts raised since the last call. */
    fun pollAlerts(): List<RideAlert> = synchronized(lock) {
        pendingAlerts.toList().also { pendingAlerts.clear() }
    }

    // ---- IMU -------------------------------------------------------------------------------

    fun onAccel(timestampNs: Long, x: Float, y: Float, z: Float) {
        var landed: Jump? = null
        synchronized(lock) {
            hasAccelerometer = true
            val tSec = timestampNs / 1e9
            val recording = status == RideStatus.RECORDING
            val wasAirborne = jumpDetector.airborne
            imu.onAccel(
                tSec, x.toDouble(), y.toDouble(), z.toDouble(),
                freezeGravity = wasAirborne,
                countRoughness = recording && !wasAirborne,
            )
            if (!recording) return
            val raw = jumpDetector.onAccel(tSec, imu.magLpG, imu.magG)
            if (jumpDetector.airborne) airborneThisSecond = true
            if (raw != null) landed = acceptJump(raw)
        }
        landed?.let { jumpListener?.invoke(it) }
    }

    fun onGyro(timestampNs: Long, x: Float, y: Float, z: Float) = synchronized(lock) {
        hasGyroscope = true
        val tSec = timestampNs / 1e9
        imu.onGyro(tSec, x.toDouble(), y.toDouble(), z.toDouble(), speed)
        if (status != RideStatus.RECORDING) return@synchronized
        jumpDetector.onGyro(tSec, x.toDouble(), y.toDouble(), z.toDouble())
        if (lastCornerFeedSec.isNaN() || tSec - lastCornerFeedSec >= CORNER_FEED_SEC) {
            lastCornerFeedSec = tSec
            cornerDetector.update(tSec, imu.yawRateLp, speed)?.let { addCorner(it) }
        }
    }

    // ---- Per second ------------------------------------------------------------------------

    fun tick(elapsedMs: Long, wallMs: Long): TickOutput = synchronized(lock) {
        if (status != RideStatus.RECORDING) {
            imu.drainSecond()
            return TickOutput(null, liveLocked())
        }
        val dt = if (lastTickElapsedMs == 0L) 1.0 else ((elapsedMs - lastTickElapsedMs) / 1000.0).coerceIn(0.2, 5.0)
        lastTickElapsedMs = elapsedMs
        val tSec = elapsedMs / 1000.0
        val imuSecond = imu.drainSecond()
        val v = speed
        val moving = v >= Scoring.MOVING_SPEED

        var dDist = v * dt
        if (!distanceTotal.isNaN()) {
            if (!lastDistanceTotal.isNaN()) {
                val d = distanceTotal - lastDistanceTotal
                if (d >= 0.0 && d <= v * dt + 25.0) dDist = d
            }
            lastDistanceTotal = distanceTotal
        }
        cumDistance += dDist

        val gpsYaw = gpsYawRate(dt)
        val gyroOk = imuSecond.gyroSamples >= 5 && imuSecond.yawTimeSec >= 0.3
        val yawRate = if (gyroOk) imuSecond.yawRad / imuSecond.yawTimeSec else gpsYaw
        if (!hasGyroscope) cornerDetector.update(tSec, gpsYaw, v)?.let { addCorner(it) }
        lastTickSec = tSec

        val curvature = if (v >= 1.5) abs(yawRate) / v else 0.0
        // Mean turn rate over the second: the bar-mounted gyro also sees steering wobble, whose
        // peaks are not cornering load. Real tyres on dirt stay below ~1.2 g.
        val latG = (v * abs(yawRate) / Scoring.G).coerceAtMost(Scoring.MAX_LATERAL_G)
        val rough = if (imuSecond.accelSamples >= 5) imuSecond.roughG else Double.NaN
        val grit = (if (moving) Scoring.gritPerSecond(grade, curvature, rough) * dt else 0.0) + gritBonus
        gritBonus = 0.0

        val sample = SecondSample(
            idx = samples.size,
            elapsedMs = elapsedMs,
            wallMs = wallMs,
            dt = dt,
            distanceM = cumDistance,
            dDist = dDist,
            speed = v,
            grade = grade,
            altitude = altitude,
            lat = lat,
            lon = lon,
            rough = rough,
            yawRate = yawRate,
            curvature = curvature,
            latG = latG,
            grit = grit,
            moving = moving,
            lap = lapTotals.lastIndex,
            airborne = airborneThisSecond,
            power = power,
            cadence = cadence,
            balanceLeft = balanceLeft,
            faFront = faFront,
            faRear = faRear,
            effortZone = effortZone,
            rearGear = rearGear,
            rearTeeth = rearTeeth,
        )
        airborneThisSecond = jumpDetector.airborne
        val recent = (samples.takeLast(4) + sample).map { it.rough }.filter { !it.isNaN() }
        coach.onSecond(sample, if (recent.isEmpty()) Double.NaN else recent.average(), tSec, pendingAlerts)
        if (sample.hasBikeData) bikeDataSeen = true
        samples += sample
        totals.addImmediate(sample)
        lapTotals[sample.lap].addImmediate(sample)
        descents.onSample(samples, samples.lastIndex, config.segmentMinElevationM)?.let { descentsAwaitingFlow += it }

        var flowOut = 0.0
        var brakeOut = 0.0
        while (processedUpTo < samples.size - 1 - config.flowLagSec) {
            val processed = process(processedUpTo + 1)
            flowOut += processed.flow
            brakeOut = max(brakeOut, processed.brake)
        }
        refineJumpHeights(elapsedMs)
        reportFinishedDescents()

        val landed = jumpsForNextRecord.maxByOrNull { it.airSec }
        jumpsForNextRecord.clear()
        val record = RecordValues(
            grit = grit,
            rough = rough.takeUnless { it.isNaN() },
            latG = latG,
            flow = flowOut,
            brake = brakeOut,
            jumpAir = landed?.airSec ?: 0.0,
            jumpDistance = landed?.distanceM ?: 0.0,
            jumpHeight = landed?.heightM ?: 0.0,
        )
        TickOutput(record, liveLocked())
    }

    fun live(): LiveMetrics = synchronized(lock) { liveLocked() }

    /**
     * FIT session values. The bike-system totals re-segment the whole ride, so they are computed
     * on a snapshot outside the lock (the 100 Hz sensor thread needs it), and only when a power
     * meter, Flight Attendant or AXS sent data this ride.
     */
    fun sessionValues(): SessionValues {
        val (base, bikeInput) = synchronized(lock) {
            sessionLocked() to if (bikeDataSeen && samples.isNotEmpty()) BikeInput(samples.toList(), shifts.toList(), faMode, faBias, riderWeightKg) else null
        }
        return if (bikeInput == null) base else base.withBike(bikeInput, config.segmentMinElevationM)
    }

    fun drainForStorage(): StorageBatch = synchronized(lock) {
        StorageBatch(storageSamples.toList(), storageJumps.toList(), storageCorners.toList(), storageShifts.toList()).also {
            storageSamples.clear()
            storageJumps.clear()
            storageCorners.clear()
            storageShifts.clear()
        }
    }

    /** Ends the ride and builds the summary. Safe to call once per ride. */
    fun finish(wallMs: Long, meta: SummaryMeta): RideSummary = synchronized(lock) {
        while (processedUpTo < samples.lastIndex) process(processedUpTo + 1)
        refineJumpHeights(Long.MAX_VALUE)
        if (!lastTickSec.isNaN()) cornerDetector.flush(lastTickSec)?.let { addCorner(it) }
        status = RideStatus.IDLE
        SummaryBuilder.build(
            meta = meta,
            startWallMs = rideStartWallMs,
            endWallMs = wallMs,
            samples = samples,
            lapStarts = lapStarts,
            jumps = jumps,
            corners = corners,
            config = config,
            sensors = SensorInfo(hasAccelerometer, hasGyroscope, imu.accelRateHz),
            shifts = shifts,
            weightKg = riderWeightKg,
            batteries = batteries.values.toList(),
            faMode = faMode,
            faBias = faBias,
        )
    }

    // ---- Internals -------------------------------------------------------------------------

    private fun process(i: Int): SecondSample {
        val s = samples[i]
        val prev = samples[max(0, i - 1)]
        val next = samples[min(samples.lastIndex, i + 1)]
        val span = (next.elapsedMs - prev.elapsedMs) / 1000.0
        val accel = if (span >= 0.5) (next.speed - prev.speed) / span else 0.0
        // Wheel-speed readings around a flight are not braking.
        val nearAir = s.airborne || prev.airborne || next.airborne
        val brake = if (s.moving && !nearAir) Scoring.brakingDecel(accel, s.speed, s.grade) else 0.0
        val weight = if (s.speed >= 2.0) Scoring.brakeWeight(brake) else 0.0
        var necessity = 0.0
        for (j in max(0, i - 1)..min(samples.lastIndex, i + config.flowLagSec)) {
            val q = samples[j]
            necessity = max(necessity, Scoring.brakingNecessity(s.speed, q.curvature, q.grade, q.rough))
        }
        s.brake = brake
        s.brakeWeight = weight
        s.necessity = necessity
        s.flow = s.dDist * weight * (1.0 - necessity)
        s.processed = true
        processedUpTo = i
        totals.addProcessed(s)
        lapTotals[s.lap].addProcessed(s)
        storageSamples += s
        return s
    }

    private fun acceptJump(raw: RawJump): Jump? {
        val takeoffElapsedMs = (raw.takeoffSec * 1000.0).roundToLong()
        val v0 = takeoffSpeed(takeoffElapsedMs)
        if (v0 < config.jumpMinSpeed) return null
        val distance = v0 * raw.airSec
        val jump = Jump(
            n = jumps.size + 1,
            takeoffWallMs = rideStartWallMs + (takeoffElapsedMs - rideStartElapsedMs),
            offsetSec = (takeoffElapsedMs - rideStartElapsedMs) / 1000.0,
            airSec = raw.airSec,
            distanceM = distance,
            heightM = Scoring.jumpHeight(raw.airSec, 0.0),
            speedMs = v0,
            landingG = raw.landingG,
            rotationDeg = raw.rotationDeg,
            rotations = raw.rotations,
            score = Scoring.jumpScore(raw.airSec, distance, raw.rotations),
            lat = lat.takeUnless { it.isNaN() },
            lon = lon.takeUnless { it.isNaN() },
        )
        jumps += jump
        jumpsAwaitingAltitude += jumps.lastIndex
        jumpsForNextRecord += jump
        gritBonus += Scoring.GRIT_PER_AIR_SECOND * raw.airSec
        return jump
    }

    /** Median speed over the 2.5 s before take-off: GPS speed lags and wheel sensors spin freely. */
    private fun takeoffSpeed(takeoffElapsedMs: Long): Double {
        val window = speedHistory.filter { it.first in (takeoffElapsedMs - 2500)..(takeoffElapsedMs + 200) }.map { it.second }
        if (window.isEmpty()) return speed
        val sorted = window.sorted()
        return sorted[sorted.size / 2]
    }

    /**
     * Once a few seconds of altitude after the landing exist, estimate the barometric drop and
     * correct the jump height (a step-down flight is higher above the landing than g·t²/8).
     * The final jump is then queued for storage.
     */
    private fun refineJumpHeights(nowElapsedMs: Long) {
        val iterator = jumpsAwaitingAltitude.iterator()
        while (iterator.hasNext()) {
            val index = iterator.next()
            val jump = jumps[index]
            val takeoffMs = rideStartElapsedMs + (jump.offsetSec * 1000.0).roundToLong()
            val landMs = takeoffMs + (jump.airSec * 1000.0).roundToLong()
            if (nowElapsedMs < landMs + ALTITUDE_SETTLE_MS) continue
            iterator.remove()
            val refined = withBarometricDrop(jump, takeoffMs, landMs)
            jumps[index] = refined
            storageJumps += refined
        }
    }

    private fun withBarometricDrop(jump: Jump, takeoffMs: Long, landMs: Long): Jump {
        if (jump.airSec < 0.45) return jump
        val before = altitudeTrendAt(takeoffMs - 3000, takeoffMs, takeoffMs) ?: return jump
        val after = altitudeTrendAt(landMs, landMs + ALTITUDE_SETTLE_MS, landMs) ?: return jump
        val maxDrop = Scoring.G * jump.airSec * jump.airSec / 2.0 + 0.5
        val drop = (before - after).coerceIn(-maxDrop, maxDrop)
        if (abs(drop) < 1.0) return jump
        return jump.copy(dropM = drop, heightM = Scoring.jumpHeight(jump.airSec, drop))
    }

    /** Least-squares altitude at [atMs] from the samples in [fromMs, toMs]. */
    private fun altitudeTrendAt(fromMs: Long, toMs: Long, atMs: Long): Double? {
        val points = samples.filter { it.elapsedMs in fromMs..toMs && !it.altitude.isNaN() }
        if (points.isEmpty()) return null
        if (points.size == 1) return points[0].altitude
        val mx = points.sumOf { it.elapsedMs.toDouble() } / points.size
        val my = points.sumOf { it.altitude } / points.size
        var sxy = 0.0
        var sxx = 0.0
        for (p in points) {
            val dx = p.elapsedMs - mx
            sxy += dx * (p.altitude - my)
            sxx += dx * dx
        }
        val slope = if (sxx > 0) sxy / sxx else 0.0
        return my + slope * (atMs - mx)
    }

    /** Descents whose last second has been through Flow: stats and an alert. */
    private fun reportFinishedDescents() {
        val iterator = descentsAwaitingFlow.iterator()
        while (iterator.hasNext()) {
            val d = iterator.next()
            if (d.end > processedUpTo) continue
            iterator.remove()
            val stats = RangeStats.compute(
                d.number, "DESCENT", "Descent ${d.number}", samples, d.start, d.end, jumps, corners, rideStartWallMs, shifts, riderWeightKg,
            )
            lastDescent = stats
            pendingAlerts += RideAlert.DescentFinished(stats, Tracks.withMargins(0, samples, d.start, d.end, rideStartWallMs))
        }
    }

    private fun liveDescentLocked(): LiveDescent? {
        val range = descents.currentRange(samples.lastIndex) ?: return null
        var distance = 0.0
        var movingSec = 0.0
        var flow = 0.0
        var flowDist = 0.0
        var processedSec = 0.0
        var brakingSec = 0.0
        var maxLat = 0.0
        for (i in range) {
            val s = samples[i]
            distance += s.dDist
            if (!s.moving) continue
            movingSec += s.dt
            maxLat = max(maxLat, s.latG)
            if (s.processed) {
                flow += s.flow
                flowDist += s.dDist
                processedSec += s.dt
                if (s.braking) brakingSec += s.dt
            }
        }
        val first = samples[range.first]
        val last = samples[range.last]
        val startOffset = (first.elapsedMs - rideStartElapsedMs) / 1000.0
        return LiveDescent(
            number = descents.number,
            timeSec = (last.elapsedMs - first.elapsedMs) / 1000.0 + last.dt,
            distanceM = distance,
            dropM = descents.currentDropM,
            avgSpeedMs = if (movingSec > 0) distance / movingSec else 0.0,
            flowScore = Scoring.flowScore(flow, flowDist),
            brakingPct = if (processedSec > 0) 100.0 * brakingSec / processedSec else 0.0,
            jumps = jumps.count { it.offsetSec >= startOffset - 1.0 },
            maxLateralG = maxLat,
        )
    }

    private fun addCorner(c: CornerDetector.FinishedCorner) {
        val corner = Corner(
            n = corners.size + 1,
            offsetSec = c.startSec - rideStartElapsedMs / 1000.0,
            durationSec = c.durationSec,
            angleDeg = c.angleDeg,
            entrySpeedMs = c.entrySpeed,
            minSpeedMs = c.minSpeed,
            exitSpeedMs = c.exitSpeed,
            maxLateralG = c.maxLateralG,
            radiusM = if (c.radiusM.isNaN()) 0.0 else c.radiusM,
        )
        corners += corner
        storageCorners += corner
    }

    /** Yaw rate from GPS bearing (rad/s, + = left); 0 when too slow for a stable bearing. */
    private fun gpsYawRate(dt: Double): Double {
        val previous = lastTickBearing
        lastTickBearing = bearing
        if (previous.isNaN() || bearing.isNaN() || speed < 2.5) return 0.0
        var delta = bearing - previous
        while (delta > 180.0) delta -= 360.0
        while (delta < -180.0) delta += 360.0
        // Compass bearings grow clockwise; a left turn is positive yaw.
        return -Math.toRadians(delta) / dt
    }

    private fun liveLocked(): LiveMetrics {
        val n = samples.size
        var grit60 = 0.0
        var time60 = 0.0
        var rough60 = 0.0
        var rough60n = 0
        for (k in n - 1 downTo max(0, n - WINDOW_SEC)) {
            val s = samples[k]
            grit60 += s.grit
            time60 += s.dt
            if (s.moving && !s.rough.isNaN()) {
                rough60 += s.rough
                rough60n++
            }
        }
        var flow60 = 0.0
        var flowDist60 = 0.0
        for (k in processedUpTo downTo max(0, processedUpTo - WINDOW_SEC + 1)) {
            val s = samples[k]
            if (s.moving) {
                flow60 += s.flow
                flowDist60 += s.dDist
            }
        }
        val lap = lapTotals.last()
        val score = scoreLocked()
        return LiveMetrics(
            status = status,
            gritTotalK = totals.grit / 1000.0,
            grit60 = if (time60 > 0) grit60 / time60 else 0.0,
            gritLapK = lap.grit / 1000.0,
            gritAvg = totals.avgGrit,
            flowScore = totals.flowScore,
            flow60 = Scoring.flowScore(flow60, flowDist60),
            flowLap = lap.flowScore,
            jumpCount = jumps.size,
            lastJump = jumps.lastOrNull(),
            maxAirSec = jumps.maxOfOrNull { it.airSec } ?: 0.0,
            totalAirSec = jumps.sumOf { it.airSec },
            latG = samples.lastOrNull()?.latG ?: 0.0,
            maxLatG = totals.maxLatG,
            cornerCount = corners.size,
            rough60 = if (rough60n > 0) rough60 / rough60n else null,
            descentBrakingPct = totals.descentBrakingPct,
            mtbScore = score.total,
            hasAccelerometer = hasAccelerometer,
            hasGyroscope = hasGyroscope,
            faFront = faFront,
            effortZone = effortZone,
            suspensionMatch = coach.suspensionMatch,
            roughNow = samples.takeLast(5).map { it.rough }.filter { !it.isNaN() }.takeIf { it.isNotEmpty() }?.average(),
            faOpenDescentPct = coach.faOpenDescentPct,
            rearGear = rearGear,
            rearTeeth = rearTeeth,
            easierGearsLeft = if (rearGear > 0) rearGear - 1 else -1,
            shifts = shifts.size,
            power = power.takeUnless { it.isNaN() },
            descent = liveDescentLocked(),
            lastDescent = lastDescent,
        )
    }

    private fun scoreLocked(): ScoreStats {
        val difficulty = Scoring.difficultyScore(totals.avgGrit)
        val smoothness = Scoring.smoothnessScore(totals.flowScore)
        val air = Scoring.airScore(jumps.sumOf { it.airSec })
        return ScoreStats(Scoring.mtbScore(difficulty, smoothness, air), difficulty, smoothness, air)
    }

    private fun sessionLocked(): SessionValues {
        val score = scoreLocked()
        val speedKept = corners.filter { it.entrySpeedMs > 0.5 }.map { 100.0 * it.minSpeedMs / it.entrySpeedMs }
        return SessionValues(
            totalGritK = totals.grit / 1000.0,
            avgGrit = totals.avgGrit,
            flowScore = totals.flowScore,
            totalFlowM = totals.flow,
            jumps = jumps.size,
            maxAirSec = jumps.maxOfOrNull { it.airSec } ?: 0.0,
            totalAirSec = jumps.sumOf { it.airSec },
            maxJumpDistanceM = jumps.maxOfOrNull { it.distanceM } ?: 0.0,
            maxJumpHeightM = jumps.maxOfOrNull { it.heightM } ?: 0.0,
            score = score.total,
            difficulty = score.difficulty,
            smoothness = score.smoothness,
            airScore = score.air,
            corners = corners.size,
            maxLateralG = totals.maxLatG,
            cornerSpeedKeptPct = if (speedKept.isEmpty()) 0.0 else speedKept.average(),
            descentSec = totals.descentSec,
            descentBrakingPct = totals.descentBrakingPct,
            descentAvgSpeed = if (totals.descentSec > 0) totals.descentDist / totals.descentSec else 0.0,
            descentFlow = Scoring.flowScore(totals.descentFlow, totals.descentFlowDist),
            avgRough = if (totals.roughN > 0) totals.roughSum / totals.roughN else 0.0,
            flowLagSec = config.flowLagSec,
        )
    }

    /** What the bike totals need, copied under the lock. Samples' bike fields never change after the second closes. */
    private class BikeInput(
        val samples: List<SecondSample>,
        val shifts: List<Shift>,
        val faMode: Int?,
        val faBias: Int?,
        val weightKg: Double,
    )

    /** Adds the Flight Attendant / AXS / power totals. */
    private fun SessionValues.withBike(input: BikeInput, segmentMinElevationM: Double): SessionValues {
        val samples = input.samples
        val ranges = Segmenter.split(samples, segmentMinElevationM)
        val terrain = BikeAnalytics.terrain(samples, ranges)
        val su = BikeAnalytics.suspension(samples, terrain, ranges, input.faMode, input.faBias)
        val dr = BikeAnalytics.drivetrain(samples, terrain, ranges, input.shifts)
        val pw = BikeAnalytics.power(samples, terrain, input.weightKg)
        return copy(
            faOpenDescentPct = su?.descents?.open,
            faLockedRoughSec = su?.lockedRoughSec,
            faOpenHardClimbSec = su?.openHardClimbSec,
            faChanges = su?.changes,
            shifts = dr?.shifts,
            shiftsPerKm = dr?.shiftsPerKm,
            climbPowerW = pw?.climbs?.avgW,
            climbWattsPerKg = pw?.climbs?.wattsPerKg,
            descentPedallingPct = pw?.descents?.pedallingPct,
            largestCogTeeth = dr?.largestCogTeeth,
            faReactionSec = su?.reactionSecMedian,
        )
    }

    private fun SecondSample.restoredAs(index: Int, elapsed: Long): SecondSample = SecondSample(
        idx = index, elapsedMs = elapsed, wallMs = wallMs, dt = dt, distanceM = distanceM, dDist = dDist,
        speed = speed, grade = grade, altitude = altitude, lat = lat, lon = lon, rough = rough,
        yawRate = yawRate, curvature = curvature, latG = latG, grit = grit, moving = moving, lap = lap,
        airborne = airborne, power = power, cadence = cadence, balanceLeft = balanceLeft, faFront = faFront,
        faRear = faRear, effortZone = effortZone, rearGear = rearGear, rearTeeth = rearTeeth,
    ).also {
        it.brake = brake
        it.brakeWeight = brakeWeight
        it.necessity = necessity
        it.flow = flow
        it.processed = true
    }

    /** Running sums over a ride or a lap. */
    private class Totals {
        var grit = 0.0
        var movingSec = 0.0
        var movingDist = 0.0
        var maxLatG = 0.0
        var roughSum = 0.0
        var roughN = 0
        var flow = 0.0
        var flowDist = 0.0
        var descentSec = 0.0
        var descentDist = 0.0
        var descentProcessedSec = 0.0
        var descentBrakingSec = 0.0
        var descentFlow = 0.0
        var descentFlowDist = 0.0

        val avgGrit: Double get() = if (movingSec > 0) grit / movingSec else 0.0
        val flowScore: Double get() = Scoring.flowScore(flow, flowDist)
        val descentBrakingPct: Double get() = if (descentProcessedSec > 0) 100.0 * descentBrakingSec / descentProcessedSec else 0.0

        fun addImmediate(s: SecondSample) {
            grit += s.grit
            if (!s.moving) return
            movingSec += s.dt
            movingDist += s.dDist
            maxLatG = max(maxLatG, s.latG)
            if (!s.rough.isNaN()) {
                roughSum += s.rough
                roughN++
            }
            if (s.descending) {
                descentSec += s.dt
                descentDist += s.dDist
            }
        }

        fun addProcessed(s: SecondSample) {
            if (!s.moving) return
            flow += s.flow
            flowDist += s.dDist
            if (s.descending) {
                descentProcessedSec += s.dt
                if (s.braking) descentBrakingSec += s.dt
                descentFlow += s.flow
                descentFlowDist += s.dDist
            }
        }
    }

    companion object {
        const val WINDOW_SEC = 60
        private const val SPEED_HISTORY_MS = 10_000L
        private const val CORNER_FEED_SEC = 0.1
        private const val ALTITUDE_SETTLE_MS = 3_000L
    }
}
