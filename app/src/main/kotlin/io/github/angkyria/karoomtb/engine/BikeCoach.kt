package io.github.angkyria.karoomtb.engine

/**
 * Live suspension / gear / battery coaching (RockShox Flight Attendant, SRAM AXS).
 *
 * Fed once per closed second by [MtbEngine] (under its lock, so not thread-safe on its own).
 * Raises [RideAlert]s into the list passed in; the engine hands them out via [MtbEngine.pollAlerts].
 */
class BikeCoach {
    var suspensionMatch = SuspensionMatch.NONE
        private set

    private var lockedRoughSec = 0.0
    private var lowCadenceSec = 0.0
    private var lastLockedAlertSec = Double.NEGATIVE_INFINITY
    private var lastShiftAlertSec = Double.NEGATIVE_INFINITY
    private val batteryAlerted = HashSet<String>()
    private var faDescentSec = 0.0
    private var faDescentOpenSec = 0.0

    /** Share of descending time with the fork open, once there are 10 s of descent with Flight Attendant data. */
    val faOpenDescentPct: Double? get() = if (faDescentSec >= 10) 100.0 * faDescentOpenSec / faDescentSec else null

    fun reset() {
        suspensionMatch = SuspensionMatch.NONE
        lockedRoughSec = 0.0
        lowCadenceSec = 0.0
        lastLockedAlertSec = Double.NEGATIVE_INFINITY
        lastShiftAlertSec = Double.NEGATIVE_INFINITY
        batteryAlerted.clear()
        faDescentSec = 0.0
        faDescentOpenSec = 0.0
    }

    /** A sample rebuilt after a restart: only the running shares, no alerts. */
    fun onRestored(sample: SecondSample) = countDescent(sample)

    /**
     * Coaching for the second that just closed.
     * @param roughRecent average vibration of the last few seconds (NaN without accelerometer)
     */
    fun onSecond(sample: SecondSample, roughRecent: Double, tSec: Double, alerts: MutableList<RideAlert>) {
        countDescent(sample)
        suspensionMatch = when {
            sample.faFront < 0 -> SuspensionMatch.NONE
            !sample.moving -> SuspensionMatch.OK
            sample.faFront == FaState.LOCK && !roughRecent.isNaN() && roughRecent >= BikeAnalytics.LOCKED_ROUGH_G -> SuspensionMatch.LOCKED_ROUGH
            sample.faFront == FaState.OPEN && !sample.power.isNaN() && sample.power >= BikeAnalytics.HARD_CLIMB_W &&
                sample.grade >= BikeAnalytics.CLIMB_GRADE -> SuspensionMatch.OPEN_HARD_CLIMB
            else -> SuspensionMatch.OK
        }
        lockedRoughSec = if (suspensionMatch == SuspensionMatch.LOCKED_ROUGH) lockedRoughSec + sample.dt else 0.0
        if (lockedRoughSec >= LOCKED_ALERT_AFTER_SEC && tSec - lastLockedAlertSec >= ALERT_COOLDOWN_SEC) {
            alerts += RideAlert.LockedOnRough
            lastLockedAlertSec = tSec
        }
        // Grinding a steep pitch at low cadence while easier gears are left.
        val grinding = sample.moving && sample.grade >= BikeAnalytics.STEEP_GRADE && !sample.cadence.isNaN() &&
            sample.cadence in 1.0..55.0 && sample.rearGear > 1
        lowCadenceSec = if (grinding) lowCadenceSec + sample.dt else 0.0
        if (lowCadenceSec >= SHIFT_ALERT_AFTER_SEC && tSec - lastShiftAlertSec >= SHIFT_ALERT_COOLDOWN_SEC) {
            alerts += RideAlert.ShiftDown(sample.rearGear - 1)
            lastShiftAlertSec = tSec
        }
    }

    /** One alert per component and ride when a battery reports low or critical. */
    fun onBattery(component: String, status: String, alerts: MutableList<RideAlert>) {
        if ((status == "LOW" || status == "CRITICAL") && batteryAlerted.add(component)) {
            alerts += RideAlert.BatteryLow(component, status)
        }
    }

    private fun countDescent(sample: SecondSample) {
        if (sample.descending && sample.faFront >= 0) {
            faDescentSec += sample.dt
            if (sample.faFront == FaState.OPEN) faDescentOpenSec += sample.dt
        }
    }

    companion object {
        private const val LOCKED_ALERT_AFTER_SEC = 5.0
        private const val ALERT_COOLDOWN_SEC = 120.0
        private const val SHIFT_ALERT_AFTER_SEC = 8.0
        private const val SHIFT_ALERT_COOLDOWN_SEC = 90.0
    }
}
