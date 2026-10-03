package io.github.angkyria.karoomtb.storage

import android.content.Context
import android.util.Log
import io.github.angkyria.karoomtb.engine.Corner
import io.github.angkyria.karoomtb.engine.Jump
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.engine.SecondSample
import io.github.angkyria.karoomtb.engine.Shift
import io.github.angkyria.karoomtb.engine.StorageBatch
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.util.Locale

@Serializable
data class RideMeta(
    val startWallMs: Long,
    val appVersion: String,
    val profileName: String? = null,
    val device: String? = null,
    val sensitivity: String = "MEDIUM",
)

@Serializable
data class NtfyStatus(val state: String, val detail: String = "", val atWallMs: Long = System.currentTimeMillis()) {
    companion object {
        const val PENDING = "pending"
        const val SENT = "sent"
        const val FAILED = "failed"
        const val SKIPPED = "skipped"
    }
}

@Serializable
private data class StoredEvent(val jump: Jump? = null, val corner: Corner? = null, val shift: Shift? = null)

/**
 * One directory per ride (named after the start time) under the app's external files dir, so
 * `adb pull /sdcard/Android/data/io.github.angkyria.karoomtb/files/rides` gets everything:
 *
 *  - meta.json      ride metadata
 *  - samples.csv    one row per second (the same data that goes into the FIT file and more)
 *  - events.jsonl   jumps and corners
 *  - summary.json   end-of-ride summary (also what is sent over ntfy)
 *  - ntfy.json      delivery status of the ntfy notification
 *
 * Also lets the extension resume a ride after its process was restarted.
 */
class RideStore(context: Context) {
    private val root: File = File(context.getExternalFilesDir(null) ?: context.filesDir, "rides").apply { mkdirs() }

    val rootPath: String get() = root.absolutePath

    fun begin(meta: RideMeta): File {
        val dir = File(root, meta.startWallMs.toString()).apply { mkdirs() }
        File(dir, META).writeText(json.encodeToString(meta))
        File(dir, SAMPLES).writeText(CSV_HEADER + "\n")
        File(dir, EVENTS).writeText("")
        prune()
        return dir
    }

    fun append(dir: File, batch: StorageBatch) {
        try {
            if (batch.samples.isNotEmpty()) {
                File(dir, SAMPLES).appendText(batch.samples.joinToString("") { toCsv(it) + "\n" })
            }
            val events = batch.jumps.map { StoredEvent(jump = it) } + batch.corners.map { StoredEvent(corner = it) } +
                batch.shifts.map { StoredEvent(shift = it) }
            if (events.isNotEmpty()) {
                File(dir, EVENTS).appendText(events.joinToString("") { json.encodeToString(it) + "\n" })
            }
        } catch (e: Exception) {
            Log.w(TAG, "append failed", e)
        }
    }

    fun saveSummary(dir: File, summary: RideSummary) {
        File(dir, SUMMARY).writeText(json.encodeToString(summary))
    }

    fun summary(dir: File): RideSummary? = readJson(File(dir, SUMMARY))

    fun meta(dir: File): RideMeta? = readJson(File(dir, META))

    fun setNtfyStatus(dir: File, status: NtfyStatus) {
        File(dir, NTFY).writeText(json.encodeToString(status))
    }

    fun ntfyStatus(dir: File): NtfyStatus? = readJson(File(dir, NTFY))

    /** Newest first. */
    fun rides(): List<File> = root.listFiles { f -> f.isDirectory && f.name.toLongOrNull() != null }
        ?.sortedByDescending { it.name.toLong() } ?: emptyList()

    fun latestFinished(): File? = rides().firstOrNull { File(it, SUMMARY).exists() }

    /** The newest ride that has data but no summary (the extension died mid-ride). */
    fun unfinished(): File? = rides().firstOrNull { File(it, META).exists() && !File(it, SUMMARY).exists() }

    fun lastWriteMs(dir: File): Long = maxOf(File(dir, SAMPLES).lastModified(), File(dir, META).lastModified())

    fun loadSamples(dir: File): List<SecondSample> {
        val file = File(dir, SAMPLES)
        if (!file.exists()) return emptyList()
        return file.readLines().drop(1).mapNotNull { line -> runCatching { fromCsv(line) }.getOrNull() }
    }

    fun loadJumps(dir: File): List<Jump> = loadEvents(dir).mapNotNull { it.jump }

    fun loadCorners(dir: File): List<Corner> = loadEvents(dir).mapNotNull { it.corner }

    fun loadShifts(dir: File): List<Shift> = loadEvents(dir).mapNotNull { it.shift }

    private fun loadEvents(dir: File): List<StoredEvent> {
        val file = File(dir, EVENTS)
        if (!file.exists()) return emptyList()
        return file.readLines().filter { it.isNotBlank() }.mapNotNull { runCatching { json.decodeFromString<StoredEvent>(it) }.getOrNull() }
    }

    private fun prune() {
        rides().drop(KEEP_RIDES).forEach { it.deleteRecursively() }
    }

    private inline fun <reified T> readJson(file: File): T? =
        if (!file.exists()) null else runCatching { json.decodeFromString<T>(file.readText()) }.getOrNull()

    companion object {
        private const val TAG = "RideStore"
        private const val KEEP_RIDES = 60
        const val META = "meta.json"
        const val SAMPLES = "samples.csv"
        const val EVENTS = "events.jsonl"
        const val SUMMARY = "summary.json"
        const val NTFY = "ntfy.json"

        val json = Json {
            ignoreUnknownKeys = true
            encodeDefaults = true
            allowSpecialFloatingPointValues = true
        }

        const val CSV_HEADER = "wall_ms,dt,distance_m,d_dist_m,speed_ms,grade_pct,altitude_m,lat,lon,rough_g," +
            "yaw_rate,curvature,lat_g,grit,moving,lap,airborne,brake_ms2,brake_weight,necessity,flow_m," +
            "power_w,cadence_rpm,balance_left,fa_front,fa_rear,effort_zone,rear_gear,rear_teeth"

        private fun d(v: Double, decimals: Int): String = if (v.isNaN()) "" else String.format(Locale.ROOT, "%.${decimals}f", v)

        fun toCsv(s: SecondSample): String = listOf(
            s.wallMs.toString(), d(s.dt, 3), d(s.distanceM, 1), d(s.dDist, 2), d(s.speed, 2), d(s.grade, 1),
            d(s.altitude, 1), d(s.lat, 6), d(s.lon, 6), d(s.rough, 3), d(s.yawRate, 3), d(s.curvature, 4),
            d(s.latG, 3), d(s.grit, 3), if (s.moving) "1" else "0", s.lap.toString(), if (s.airborne) "1" else "0",
            d(s.brake, 2), d(s.brakeWeight, 3), d(s.necessity, 3), d(s.flow, 3),
            d(s.power, 0), d(s.cadence, 0), d(s.balanceLeft, 0), i(s.faFront), i(s.faRear), i(s.effortZone),
            i(s.rearGear), i(s.rearTeeth),
        ).joinToString(",")

        private fun i(v: Int): String = if (v < 0) "" else v.toString()

        fun fromCsv(line: String): SecondSample {
            val c = line.split(',')
            fun num(i: Int): Double = c.getOrNull(i)?.takeIf { it.isNotEmpty() }?.toDouble() ?: Double.NaN
            fun int(i: Int): Int = c.getOrNull(i)?.takeIf { it.isNotEmpty() }?.toInt() ?: -1
            val wall = c[0].toLong()
            return SecondSample(
                idx = 0, elapsedMs = 0L, wallMs = wall, dt = num(1), distanceM = num(2), dDist = num(3), speed = num(4),
                grade = num(5), altitude = num(6), lat = num(7), lon = num(8), rough = num(9), yawRate = num(10),
                curvature = num(11), latG = num(12), grit = num(13), moving = c[14] == "1", lap = c[15].toInt(),
                airborne = c[16] == "1",
                // Columns 21+ exist since 0.2 (bike systems); older files simply lack them.
                power = num(21), cadence = num(22), balanceLeft = num(23), faFront = int(24), faRear = int(25),
                effortZone = int(26), rearGear = int(27), rearTeeth = int(28),
            ).also {
                it.brake = num(17)
                it.brakeWeight = num(18)
                it.necessity = num(19)
                it.flow = num(20)
                it.processed = true
            }
        }
    }
}
