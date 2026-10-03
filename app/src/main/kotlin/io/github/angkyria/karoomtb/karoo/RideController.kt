package io.github.angkyria.karoomtb.karoo

import android.content.Context
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.engine.BikeAlert
import io.github.angkyria.karoomtb.engine.Jump
import io.github.angkyria.karoomtb.engine.MtbEngine
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.engine.SummaryMeta
import io.github.angkyria.karoomtb.fit.MtbFitFields
import io.github.angkyria.karoomtb.notify.HttpSender
import io.github.angkyria.karoomtb.notify.RideNotifier
import io.github.angkyria.karoomtb.notify.SendResult
import io.github.angkyria.karoomtb.notify.SummaryFormatter
import io.github.angkyria.karoomtb.notify.Units
import io.github.angkyria.karoomtb.storage.ImuLogger
import io.github.angkyria.karoomtb.storage.RideMeta
import io.hammerhead.karooext.KarooSystemService
import io.hammerhead.karooext.models.ActiveRideProfile
import io.hammerhead.karooext.models.BatteryStatus
import io.hammerhead.karooext.models.DataPoint
import io.hammerhead.karooext.models.DataType
import io.hammerhead.karooext.models.HardwareType
import io.hammerhead.karooext.models.InRideAlert
import io.hammerhead.karooext.models.Lap
import io.hammerhead.karooext.models.OnStreamState
import io.hammerhead.karooext.models.PlayBeepPattern
import io.hammerhead.karooext.models.RideProfile
import io.hammerhead.karooext.models.RideState
import io.hammerhead.karooext.models.StreamState
import io.hammerhead.karooext.models.SystemNotification
import io.hammerhead.karooext.models.UserProfile
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.mapNotNull
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File

/**
 * Turns Karoo ride-state changes into an MTB Dynamics ride:
 * Recording → start (or resume a ride interrupted by a restart), Paused → pause and commit the
 * FIT session values, Idle → summary, ntfy notification and Karoo notification.
 */
class RideController(
    private val context: Context,
    private val karoo: KarooSystemService,
    private val scope: CoroutineScope,
    private val appVersion: String,
) {
    private val engine = MtbRuntime.engine
    private val settings = MtbRuntime.settings
    private val store = MtbRuntime.store
    private val sensors = ImuSensorSource(context, engine)
    private val notifier = RideNotifier(settings, store, HttpSender(karoo)) { MtbRuntime.service.notices(it) }

    private val rideStates = Channel<RideState>(Channel.UNLIMITED)
    private val consumers = ArrayList<String>()
    private val streamConsumers = ArrayList<String>()
    private var tickJob: Job? = null
    private var rideDir: File? = null
    private var ignoringRide = false
    private var wakeLock: PowerManager.WakeLock? = null

    @Volatile
    private var profile: RideProfile? = null

    /** Components whose battery field turned out to be a percentage, not a BatteryStatus ordinal. */
    private val percentBatteries: MutableSet<String> = java.util.concurrent.ConcurrentHashMap.newKeySet()

    @Volatile
    private var ascentM = Double.NaN

    @Volatile
    private var descentM = Double.NaN

    fun start() {
        consumers += karoo.addConsumer<RideState> { rideStates.trySend(it) }
        consumers += karoo.addConsumer<Lap> { engine.markLap() }
        consumers += karoo.addConsumer<UserProfile> { p ->
            engine.setRiderWeight(p.weight.toDouble())
            MtbRuntime.units = Units(
                imperialDistance = p.preferredUnit.distance == UserProfile.PreferredUnit.UnitType.IMPERIAL,
                imperialElevation = p.preferredUnit.elevation == UserProfile.PreferredUnit.UnitType.IMPERIAL,
            )
        }
        consumers += karoo.addConsumer<ActiveRideProfile> { profile = it.profile }
        engine.jumpListener = ::onJump
        scope.launch {
            for (state in rideStates) {
                try {
                    handle(state)
                } catch (e: Exception) {
                    Log.e(TAG, "ride state $state failed", e)
                }
            }
        }
    }

    fun onConnected() {
        scope.launch {
            delay(5_000)
            notifier.retryPending(MtbRuntime.units)
        }
    }

    fun stop() {
        consumers.forEach { karoo.removeConsumer(it) }
        consumers.clear()
        tickJob?.cancel()
        releaseRideResources()
        // Keep what we have; the next start resumes or finishes the ride from storage.
        rideDir?.let { store.append(it, engine.drainForStorage()) }
        engine.jumpListener = null
        rideStates.close()
    }

    private suspend fun handle(state: RideState) {
        Log.i(TAG, "ride state $state (active=${rideDir != null}, ignoring=$ignoringRide)")
        when (state) {
            is RideState.Recording -> when {
                ignoringRide -> Unit
                rideDir == null -> begin()
                else -> engine.resume()
            }
            is RideState.Paused -> {
                if (rideDir == null && !ignoringRide) begin()
                if (rideDir != null) {
                    engine.pause()
                    // Values written while paused are committed to the session message (karoo-ext advice).
                    emitSession()
                    flushStorage()
                }
            }
            is RideState.Idle -> {
                if (rideDir != null) end() else finishOrphanedRide()
                ignoringRide = false
            }
        }
    }

    private suspend fun begin() {
        val p = profile
        if (settings.mtbProfilesOnly && p != null && p.defaultActivityType !in MTB_ACTIVITY_TYPES) {
            Log.i(TAG, "profile '${p.name}' is ${p.defaultActivityType}: MTB Dynamics off for this ride")
            ignoringRide = true
            return
        }
        val unfinished = store.unfinished()
        val meta = unfinished?.let { store.meta(it) }
        // Same ride as the stored one? Compare with the Karoo's own ride clock (includes pauses), so a
        // long café stop does not split the ride; fall back to the age of the stored data.
        val karooRideStart = if (unfinished != null) karooRideStartWallMs() else null
        val nowWall = System.currentTimeMillis()
        val nowElapsed = SystemClock.elapsedRealtime()
        val sameRide = unfinished != null && meta != null && if (karooRideStart != null) {
            kotlin.math.abs(meta.startWallMs - karooRideStart) < SAME_RIDE_TOLERANCE_MS
        } else {
            nowWall - store.lastWriteMs(unfinished) < RESUME_WINDOW_MS
        }
        if (sameRide && unfinished != null && meta != null) {
            Log.i(TAG, "resuming ride ${unfinished.name} after restart")
            engine.restore(
                meta.startWallMs, nowWall, nowElapsed,
                store.loadSamples(unfinished), store.loadJumps(unfinished), store.loadCorners(unfinished),
                settings.mtbConfig(), store.loadShifts(unfinished),
            )
            rideDir = unfinished
        } else {
            if (unfinished != null) finishFromStorage(unfinished)
            engine.start(nowWall, nowElapsed, settings.mtbConfig())
            rideDir = store.begin(RideMeta(nowWall, appVersion, p?.name, deviceName(), settings.sensitivity.name))
        }
        ascentM = Double.NaN
        descentM = Double.NaN
        subscribeStreams()
        val dir = rideDir
        if (settings.debugRawImu && dir != null) {
            sensors.rawLogger = ImuLogger(File(dir, ImuLogger.FILE_NAME), nowWall, SystemClock.elapsedRealtimeNanos())
        }
        val imuOk = sensors.start()
        if (!imuOk) Log.w(TAG, "no IMU: Grit/Flow from GPS and barometer only, no jumps")
        acquireWakeLock()
        tickJob = scope.launch { tickLoop() }
    }

    /** Wall-clock start of the Karoo's current ride, from its "Total Time" (paused time included). */
    private suspend fun karooRideStartWallMs(): Long? = withTimeoutOrNull(RIDE_TIME_WAIT_MS) {
        karoo.streamDataFlow(DataType.Type.RIDE_TIME)
            .mapNotNull { (it as? StreamState.Streaming)?.dataPoint?.singleValue }
            .first()
    }?.let { System.currentTimeMillis() - it.toLong() }

    private suspend fun tickLoop() {
        var next = SystemClock.elapsedRealtime() + 1000
        var count = 0
        while (currentCoroutineContext().isActive) {
            val wait = next - SystemClock.elapsedRealtime()
            if (wait > 0) delay(wait)
            val now = SystemClock.elapsedRealtime()
            // After a long stall (device asleep) re-align instead of ticking many times.
            next = if (now - next > 3_000) now + 1000 else next + 1000
            val out = engine.tick(now, System.currentTimeMillis())
            MtbRuntime.live.value = out.live
            out.record?.let { MtbRuntime.fitEffects.tryEmit(MtbFitFields.record(it, settings.writeNativeFit)) }
            engine.pollAlerts().forEach(::showBikeAlert)
            count++
            if (count % SESSION_EVERY_SEC == 0) emitSession()
            if (count % STORE_EVERY_SEC == 0) flushStorage()
        }
    }

    private suspend fun end() {
        val dir = rideDir ?: return
        tickJob?.cancelAndJoin()
        tickJob = null
        releaseRideResources()
        val summary = engine.finish(System.currentTimeMillis(), SummaryMeta(appVersion, profile?.name, deviceName(), ascentM, descentM))
        // After finish(): the last seconds, jumps and corners are only final now.
        flushStorage()
        rideDir = null
        store.saveSummary(dir, summary)
        MtbRuntime.live.value = engine.live()
        announce(summary)
        countService(summary)
        scope.launch { reportFailure(notifier.publish(dir, summary, MtbRuntime.units)) }
    }

    /** The Karoo is idle but a stored ride never got its summary (the extension was killed). */
    private suspend fun finishOrphanedRide() {
        val dir = store.unfinished() ?: return
        if (System.currentTimeMillis() - store.lastWriteMs(dir) > ORPHAN_MAX_AGE_MS) return
        finishFromStorage(dir)
    }

    private suspend fun finishFromStorage(dir: File) {
        val meta = store.meta(dir) ?: return
        val samples = store.loadSamples(dir)
        if (samples.isEmpty()) {
            dir.deleteRecursively()
            return
        }
        val lastWall = samples.last().wallMs
        val replay = MtbEngine(settings.mtbConfig())
        replay.restore(
            meta.startWallMs, lastWall, SystemClock.elapsedRealtime(), samples, store.loadJumps(dir), store.loadCorners(dir),
            restoredShifts = store.loadShifts(dir),
        )
        val summary = replay.finish(lastWall + 1000, SummaryMeta(appVersion, meta.profileName, meta.device))
        store.saveSummary(dir, summary)
        countService(summary)
        Log.i(TAG, "finished ride ${dir.name} from storage")
        reportFailure(notifier.publish(dir, summary, MtbRuntime.units))
    }

    private fun subscribeStreams() {
        fun stream(type: String, onIdle: (() -> Unit)? = null, onPoint: (DataPoint) -> Unit) {
            streamConsumers += karoo.addConsumer(OnStreamState.StartStreaming(type)) { event: OnStreamState ->
                when (val state = event.state) {
                    is StreamState.Streaming -> onPoint(state.dataPoint)
                    else -> onIdle?.invoke()
                }
            }
        }
        fun DataPoint.value(field: String): Double? = values[field] ?: singleValue

        stream(DataType.Type.SPEED, onIdle = { engine.updateSpeed(0.0, SystemClock.elapsedRealtime()) }) { p ->
            p.value(DataType.Field.SPEED)?.let { engine.updateSpeed(it, SystemClock.elapsedRealtime()) }
        }
        stream(DataType.Type.ELEVATION_GRADE) { p -> p.value(DataType.Field.ELEVATION_GRADE)?.let(engine::updateGrade) }
        stream(DataType.Type.PRESSURE_ELEVATION_CORRECTION) { p -> p.value(DataType.Field.PRESSURE_ELEVATION)?.let(engine::updateAltitude) }
        stream(DataType.Type.DISTANCE) { p -> p.value(DataType.Field.DISTANCE)?.let(engine::updateDistance) }
        stream(DataType.Type.ELEVATION_GAIN) { p -> p.value(DataType.Field.ELEVATION_GAIN)?.let { ascentM = it } }
        stream(DataType.Type.ELEVATION_LOSS) { p -> p.value(DataType.Field.ELEVATION_LOSS)?.let { descentM = it } }
        stream(DataType.Type.LOCATION) { p ->
            val lat = p.values[DataType.Field.LOC_LATITUDE]
            val lon = p.values[DataType.Field.LOC_LONGITUDE]
            if (lat != null && lon != null) engine.updateLocation(lat, lon, p.values[DataType.Field.LOC_BEARING])
        }

        // Bike systems: power meter, RockShox Flight Attendant, SRAM AXS. Streams of components that
        // are not paired simply never deliver data; a component going to sleep reports "not available".
        fun DataPoint.int(field: String): Int? = values[field]?.toInt()
        stream(DataType.Type.POWER, onIdle = { engine.updatePower(null) }) { p -> engine.updatePower(p.value(DataType.Field.POWER)) }
        stream(DataType.Type.CADENCE, onIdle = { engine.updateCadence(null) }) { p -> engine.updateCadence(p.value(DataType.Field.CADENCE)) }
        stream(DataType.Type.PEDAL_POWER_BALANCE) { p -> engine.updateBalance(p.values[DataType.Field.PEDAL_POWER_BALANCE_LEFT]) }
        stream(DataType.Type.SUSPENSION_STATE_FRONT, onIdle = { engine.updateSuspension(front = -1) }) { p ->
            p.int(DataType.Field.SUSPENSION_STATE_FRONT)?.let { engine.updateSuspension(front = it) }
        }
        stream(DataType.Type.SUSPENSION_STATE_REAR, onIdle = { engine.updateSuspension(rear = -1) }) { p ->
            p.int(DataType.Field.SUSPENSION_STATE_REAR)?.let { engine.updateSuspension(rear = it) }
        }
        stream(DataType.Type.SUSPENSION_MODE) { p ->
            engine.updateSuspension(
                effortZone = p.int(DataType.Field.SUSPENSION_EFFORT_ZONE),
                mode = p.int(DataType.Field.SUSPENSION_MODE),
                bias = p.int(DataType.Field.SUSPENSION_BIAS),
            )
        }
        stream(DataType.Type.SHIFTING_GEARS, onIdle = {
            engine.updateGears(-1, null, SystemClock.elapsedRealtime(), System.currentTimeMillis())
        }) { p ->
            engine.updateGears(
                p.int(DataType.Field.SHIFTING_REAR_GEAR), p.int(DataType.Field.SHIFTING_REAR_GEAR_TEETH),
                SystemClock.elapsedRealtime(), System.currentTimeMillis(),
            )
        }
        // Per component when reported (fork / shock, front / rear derailleur), else the system total.
        stream(DataType.Type.SUSPENSION_BATTERY) { p ->
            val front = p.values[DataType.Field.SUSPENSION_BATTERY_STATUS_FRONT]
            val rear = p.values[DataType.Field.SUSPENSION_BATTERY_STATUS_REAR]
            if (front == null && rear == null) battery("Flight Attendant", p.values[DataType.Field.SUSPENSION_BATTERY_STATUS])
            battery("FA fork", front)
            battery("FA shock", rear)
        }
        stream(DataType.Type.SHIFTING_BATTERY) { p ->
            val fd = p.values[DataType.Field.SHIFTING_BATTERY_STATUS_FRONT_DERAILLEUR]
            val rd = p.values[DataType.Field.SHIFTING_BATTERY_STATUS_REAR_DERAILLEUR]
            if (fd == null && rd == null) battery("AXS shifting", p.values[DataType.Field.SHIFTING_BATTERY_STATUS])
            battery("AXS front derailleur", fd)
            battery("AXS derailleur", rd)
        }
    }

    /**
     * Battery fields carry a BatteryStatus ordinal (NEW … CRITICAL, as in the karoo-ext sample);
     * a value above the ordinals is a percentage, and that component is then read as percent.
     */
    private fun battery(component: String, value: Double?) {
        if (value == null || value < 0) return
        val v = value.toInt()
        if (v >= BatteryStatus.entries.size) percentBatteries += component
        val percent = component in percentBatteries
        val status = if (percent) BatteryStatus.fromPercentage(v) else BatteryStatus.entries[v]
        if (status != BatteryStatus.INVALID) engine.setBattery(component, status.name, if (percent) v else null)
    }

    private fun showBikeAlert(alert: BikeAlert) {
        when (alert) {
            is BikeAlert.LockedOnRough -> if (settings.suspensionAlerts) {
                karoo.dispatch(
                    InRideAlert(
                        id = "mtb-suspension", icon = R.drawable.ic_suspension, title = "Suspension locked on rough ground",
                        detail = "Open it, or lower the Flight Attendant bias", autoDismissMs = 5_000,
                        backgroundColor = R.color.alert_warn_bg, textColor = R.color.alert_text,
                    ),
                )
            }
            is BikeAlert.ShiftDown -> if (settings.shiftAdvice) {
                karoo.dispatch(
                    InRideAlert(
                        id = "mtb-shift", icon = R.drawable.ic_gear, title = "Easier gear available",
                        detail = "${alert.easierGears} easier gear${if (alert.easierGears == 1) "" else "s"} left", autoDismissMs = 3_000,
                        backgroundColor = R.color.alert_info_bg, textColor = R.color.alert_text,
                    ),
                )
            }
            is BikeAlert.BatteryLow -> if (settings.batteryAlerts) {
                karoo.dispatch(
                    InRideAlert(
                        id = "mtb-battery-${alert.component}", icon = R.drawable.ic_battery,
                        title = "${alert.component} battery ${alert.status.lowercase()}",
                        detail = "Charge it after the ride", autoDismissMs = 6_000,
                        backgroundColor = R.color.alert_warn_bg, textColor = R.color.alert_text,
                    ),
                )
            }
        }
    }

    private fun releaseRideResources() {
        sensors.stop()
        sensors.rawLogger?.close()
        sensors.rawLogger = null
        streamConsumers.forEach { karoo.removeConsumer(it) }
        streamConsumers.clear()
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
    }

    private fun emitSession() {
        MtbRuntime.fitEffects.tryEmit(MtbFitFields.session(engine.sessionValues(), settings.writeNativeFit))
    }

    private fun flushStorage() {
        rideDir?.let { store.append(it, engine.drainForStorage()) }
    }

    private fun onJump(jump: Jump) {
        MtbRuntime.live.value = engine.live()
        if (settings.jumpAlerts) {
            karoo.dispatch(
                InRideAlert(
                    id = "mtb-jump",
                    icon = R.drawable.ic_jump,
                    title = SummaryFormatter.jumpAlertTitle(jump),
                    detail = SummaryFormatter.jumpAlertDetail(jump, MtbRuntime.units),
                    autoDismissMs = 4_000,
                    backgroundColor = R.color.alert_jump_bg,
                    textColor = R.color.alert_text,
                ),
            )
        }
        if (settings.jumpBeep) {
            karoo.dispatch(
                PlayBeepPattern(
                    listOf(PlayBeepPattern.Tone(3200, 70), PlayBeepPattern.Tone(null, 40), PlayBeepPattern.Tone(3800, 140)),
                ),
            )
        }
    }

    /** Adds the ride to the service tracker; tells the rider when something just became due. */
    private fun countService(summary: RideSummary) {
        val due = runCatching { MtbRuntime.service.addRide(summary).newlyDue }
            .onFailure { Log.w(TAG, "service tracker failed", it) }
            .getOrDefault(emptyList())
        if (due.isEmpty()) return
        karoo.dispatch(
            SystemNotification(
                id = "mtb-service",
                header = "MTB Dynamics",
                message = "Service due: " + due.joinToString(", ") { it.item.name },
                subText = "Mark it as done in the MTB Dynamics settings",
                style = SystemNotification.Style.EVENT,
                action = "Open",
                actionIntent = SETTINGS_ACTION,
            ),
        )
    }

    private fun announce(summary: RideSummary) {
        karoo.dispatch(
            SystemNotification(
                id = "mtb-summary",
                header = "MTB Dynamics",
                message = SummaryFormatter.oneLine(summary),
                subText = if (settings.ntfyEnabled) "Summary sent via ntfy when online" else null,
                style = SystemNotification.Style.EVENT,
                action = "Details",
                actionIntent = SETTINGS_ACTION,
            ),
        )
    }

    private fun reportFailure(result: SendResult) {
        if (result.ok || result.status == 0) return
        karoo.dispatch(
            SystemNotification(
                id = "mtb-ntfy",
                header = "MTB Dynamics",
                message = "ntfy delivery failed (${if (result.status > 0) "HTTP ${result.status}" else result.detail})",
                subText = if (result.permanentFailure) "Check topic / token in the MTB Dynamics app" else "Will retry automatically",
                style = SystemNotification.Style.ERROR,
                actionIntent = SETTINGS_ACTION,
            ),
        )
    }

    private fun acquireWakeLock() {
        val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "karoo-mtb:ride").apply {
            setReferenceCounted(false)
            acquire(WAKE_LOCK_MAX_MS)
        }
    }

    private fun deviceName(): String? = when (runCatching { karoo.hardwareType }.getOrNull()) {
        HardwareType.K2 -> "Karoo 2"
        HardwareType.KAROO -> "Karoo 3"
        else -> null
    }

    companion object {
        private const val TAG = "MtbRide"
        const val SETTINGS_ACTION = "io.github.angkyria.karoomtb.SETTINGS"
        private val MTB_ACTIVITY_TYPES = setOf("MOUNTAIN_BIKE", "EMOUNTAIN_BIKE")
        private const val SESSION_EVERY_SEC = 15
        private const val STORE_EVERY_SEC = 10
        private const val RESUME_WINDOW_MS = 30L * 60 * 1000
        private const val SAME_RIDE_TOLERANCE_MS = 3L * 60 * 1000
        private const val RIDE_TIME_WAIT_MS = 3_000L
        private const val ORPHAN_MAX_AGE_MS = 48L * 3600 * 1000
        private const val WAKE_LOCK_MAX_MS = 12L * 3600 * 1000
    }
}
