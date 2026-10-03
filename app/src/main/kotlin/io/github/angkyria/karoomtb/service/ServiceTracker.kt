package io.github.angkyria.karoomtb.service

import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.notify.Units
import io.github.angkyria.karoomtb.notify.Units.Companion.fmt
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

/** What a service interval is measured in. */
enum class ServiceBasis { FORK_HOURS, SHOCK_HOURS, DRIVETRAIN_KM }

/** A maintenance job with its default interval. */
data class ServiceItem(val id: String, val name: String, val basis: ServiceBasis, val defaultInterval: Double)

/** Usage totals over all rides that had Flight Attendant or AXS data (i.e. on this bike). */
@Serializable
data class ServiceTotals(
    /** Moving hours with data from the fork / the shock. */
    val forkHours: Double = 0.0,
    val shockHours: Double = 0.0,
    /** Part of [forkHours] on ground rougher than 0.6 g. */
    val roughHours: Double = 0.0,
    val faChanges: Long = 0,
    val shifts: Long = 0,
    /** Distance ridden with AXS gear data. */
    val drivetrainKm: Double = 0.0,
    /** Hours per rear cog (teeth). */
    val cogHours: Map<Int, Double> = emptyMap(),
    val rides: Int = 0,
    val sinceWallMs: Long = 0,
)

/** The basis total when the item was last serviced; wallMs 0 = date unknown. */
@Serializable
data class ServiceMark(val atValue: Double, val wallMs: Long)

@Serializable
data class BatteryRecord(val rideStartWallMs: Long, val component: String, val status: String, val percent: Int? = null)

@Serializable
data class ServiceState(
    val totals: ServiceTotals = ServiceTotals(),
    val marks: Map<String, ServiceMark> = emptyMap(),
    /** Intervals set by the rider, overriding the defaults. */
    val intervals: Map<String, Double> = emptyMap(),
    /** Start times of rides already counted: a ride can be finished twice (restart, resend). */
    val counted: List<Long> = emptyList(),
    val batteries: List<BatteryRecord> = emptyList(),
)

data class ServiceStatus(val item: ServiceItem, val used: Double, val interval: Double, val lastServiceWallMs: Long?) {
    val progress: Double get() = if (interval > 0) used / interval else 0.0
    val due: Boolean get() = interval > 0 && used >= interval
    val soon: Boolean get() = !due && interval > 0 && progress >= SOON
    val remaining: Double get() = interval - used

    companion object {
        const val SOON = 0.9
    }
}

/** Result of counting one ride. */
data class ServiceUpdate(val counted: Boolean, val newlyDue: List<ServiceStatus>)

/**
 * Service and battery tracker across rides, stored as JSON (service.json next to the rides
 * folder, so `adb pull` and tools/mtb_analyze.py can read it).
 *
 * Only rides with RockShox Flight Attendant or SRAM AXS data count, so rides on another bike do
 * not wear this bike's fork. The default intervals follow the RockShox / SRAM service guides for
 * SID / SIDLuxe and an Eagle chain; check the manual of your parts.
 */
class ServiceTracker(private val file: File, private val clock: () -> Long = System::currentTimeMillis) {
    private val lock = Any()

    fun state(): ServiceState = synchronized(lock) { load() }

    /** Adds the usage of a finished ride (once per ride). */
    fun addRide(summary: RideSummary): ServiceUpdate = synchronized(lock) {
        val state = load()
        if (summary.startWallMs in state.counted) return ServiceUpdate(false, emptyList())
        val dueBefore = statuses(state).filter { it.due }.map { it.item.id }.toSet()
        val su = summary.bike.suspension
        val dr = summary.bike.drivetrain
        val onThisBike = su != null || dr != null
        val t = state.totals
        val cogs = HashMap(t.cogHours)
        dr?.cogMinutes?.forEach { (teeth, minutes) -> cogs[teeth] = (cogs[teeth] ?: 0.0) + minutes / 60.0 }
        val totals = t.copy(
            forkHours = t.forkHours + (su?.trackedSec ?: 0.0) / 3600.0,
            shockHours = t.shockHours + (su?.rearTrackedSec ?: 0.0) / 3600.0,
            roughHours = t.roughHours + (su?.roughSec ?: 0.0) / 3600.0,
            faChanges = t.faChanges + (su?.changes ?: 0),
            shifts = t.shifts + (dr?.shifts ?: 0),
            drivetrainKm = t.drivetrainKm + (dr?.trackedKm ?: 0.0),
            cogHours = cogs,
            rides = t.rides + if (onThisBike) 1 else 0,
            sinceWallMs = if (t.sinceWallMs == 0L && onThisBike) summary.startWallMs else t.sinceWallMs,
        )
        val batteries = state.batteries + summary.bike.batteries.map {
            BatteryRecord(summary.startWallMs, it.component, it.status, it.percent)
        }
        val next = state.copy(
            totals = totals,
            counted = (state.counted + summary.startWallMs).takeLast(MAX_COUNTED),
            batteries = batteries.takeLast(MAX_BATTERY_RECORDS),
        )
        save(next)
        ServiceUpdate(true, statuses(next).filter { it.due && it.item.id !in dueBefore })
    }

    fun statuses(): List<ServiceStatus> = synchronized(lock) { statuses(load()) }

    /** The item was serviced now: its usage starts again from zero. */
    fun markServiced(id: String) = update { s ->
        s.copy(marks = s.marks + (id to ServiceMark(total(s.totals, item(id).basis), clock())))
    }

    /** Sets the usage since the last service, e.g. the hours a fork had done before tracking began. */
    fun setUsed(id: String, used: Double) = update { s ->
        s.copy(marks = s.marks + (id to ServiceMark(total(s.totals, item(id).basis) - used, s.marks[id]?.wallMs ?: 0L)))
    }

    fun setInterval(id: String, interval: Double) = update { s -> s.copy(intervals = s.intervals + (id to interval)) }

    /** Lines for the ntfy summary: items due or nearly due. */
    fun notices(units: Units = Units()): List<String> = notices(statuses(), units)

    /** Latest status per battery. */
    fun latestBatteries(): List<BatteryRecord> = synchronized(lock) {
        load().batteries.groupBy { it.component }.map { (_, records) -> records.last() }
    }

    private fun update(change: (ServiceState) -> ServiceState) = synchronized(lock) { save(change(load())) }

    private fun statuses(state: ServiceState): List<ServiceStatus> = ITEMS.map { item ->
        val mark = state.marks[item.id]
        ServiceStatus(
            item = item,
            used = (total(state.totals, item.basis) - (mark?.atValue ?: 0.0)).coerceAtLeast(0.0),
            interval = state.intervals[item.id] ?: item.defaultInterval,
            lastServiceWallMs = mark?.wallMs?.takeIf { it > 0 },
        )
    }

    private fun load(): ServiceState =
        if (!file.exists()) ServiceState() else runCatching { json.decodeFromString<ServiceState>(file.readText()) }.getOrElse { ServiceState() }

    private fun save(state: ServiceState) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.encodeToString(state))
        if (!tmp.renameTo(file)) {
            file.writeText(tmp.readText())
            tmp.delete()
        }
    }

    companion object {
        const val FILE_NAME = "service.json"
        private const val MAX_COUNTED = 500
        private const val MAX_BATTERY_RECORDS = 400

        val ITEMS = listOf(
            ServiceItem("fork_lowers", "Fork lower-leg service", ServiceBasis.FORK_HOURS, 50.0),
            ServiceItem("fork_damper", "Fork damper & spring service", ServiceBasis.FORK_HOURS, 200.0),
            ServiceItem("shock_aircan", "Shock air-can service", ServiceBasis.SHOCK_HOURS, 50.0),
            ServiceItem("shock_damper", "Shock damper service", ServiceBasis.SHOCK_HOURS, 200.0),
            ServiceItem("chain", "Chain wear check", ServiceBasis.DRIVETRAIN_KM, 1500.0),
        )

        fun item(id: String): ServiceItem = ITEMS.first { it.id == id }

        fun total(t: ServiceTotals, basis: ServiceBasis): Double = when (basis) {
            ServiceBasis.FORK_HOURS -> t.forkHours
            ServiceBasis.SHOCK_HOURS -> t.shockHours
            ServiceBasis.DRIVETRAIN_KM -> t.drivetrainKm
        }

        fun amount(value: Double, basis: ServiceBasis, units: Units): String = when (basis) {
            ServiceBasis.DRIVETRAIN_KM -> units.distance(value * 1000.0)
            else -> fmt("%.1f h", value)
        }

        fun notices(statuses: List<ServiceStatus>, units: Units): List<String> = statuses.filter { it.due || it.soon }.map { s ->
            val basis = s.item.basis
            if (s.due) {
                "🛠️ **${s.item.name} due** · ${amount(s.used, basis, units)} since the last one (every ${amount(s.interval, basis, units)})"
            } else {
                "🛠️ ${s.item.name} soon · ${amount(s.remaining, basis, units)} left"
            }
        }

        private val json = Json {
            ignoreUnknownKeys = true
            encodeDefaults = true
            prettyPrint = true
        }
    }
}
