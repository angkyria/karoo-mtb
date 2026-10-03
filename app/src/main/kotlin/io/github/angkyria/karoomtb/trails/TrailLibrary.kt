package io.github.angkyria.karoomtb.trails

import android.util.Log
import io.github.angkyria.karoomtb.engine.GeoPoint
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.engine.SegmentStats
import io.github.angkyria.karoomtb.engine.SegmentTrack
import io.github.angkyria.karoomtb.engine.TrackPoint
import io.github.angkyria.karoomtb.engine.TrailRunResult
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File

@Serializable
data class TrailRun(
    val rideStartWallMs: Long,
    /** When in the ride the trail started (several runs per ride are fine). */
    val offsetSec: Double = 0.0,
    val timeSec: Double,
    val flowScore: Double,
    val brakingPct: Double,
    val jumps: Int,
    val avgSpeedMs: Double,
)

@Serializable
data class Trail(
    val id: Int,
    val name: String,
    val distanceM: Double,
    val dropM: Double,
    /** Reference track from the first run (thinned). */
    val track: List<GeoPoint>,
    val runs: List<TrailRun> = emptyList(),
) {
    val best: TrailRun? get() = runs.minByOrNull { it.timeSec }
}

@Serializable
data class TrailState(val schema: Int = 1, val nextId: Int = 1, val trails: List<Trail> = emptyList())

/**
 * The descents ridden so far, as trails with their runs (trails.json next to the rides folder).
 * Every descent of a ride either matches a known trail (a new run) or becomes a new trail, so
 * the second ride down the same trail already gets a comparison.
 */
class TrailLibrary(private val file: File) {
    private val lock = Any()

    fun state(): TrailState = synchronized(lock) { load() }

    /**
     * Compares a descent that just ended with the library, without storing it (in-ride alert).
     * Null when it is not a known trail.
     */
    fun compare(stats: SegmentStats, track: SegmentTrack?): TrailRunResult? = synchronized(lock) {
        if (track == null) return null
        val state = load()
        val (trail, match) = bestMatch(state, track.points) ?: return null
        result(stats.name, trail, match.timeSec, stats, trail.runs)
    }

    /**
     * Adds the ride's descents (from [RideSummary.descentTracks]): new runs on known trails, new
     * trails otherwise. Repeats of a trail in the same ride are compared with each other too.
     * A ride added twice (restart) replaces its earlier runs.
     */
    fun addRide(summary: RideSummary): List<TrailRunResult> = synchronized(lock) {
        val loaded = load()
        var state = loaded.copy(
            trails = loaded.trails.map { t -> t.copy(runs = t.runs.filter { it.rideStartWallMs != summary.startWallMs }) }.filter { it.runs.isNotEmpty() },
        )
        val results = ArrayList<TrailRunResult>()
        for (segTrack in summary.descentTracks) {
            val stats = summary.segments.firstOrNull { it.index == segTrack.segment } ?: continue
            if (stats.distanceM < MIN_TRAIL_M || stats.elevLossM < MIN_DROP_M) continue
            val found = bestMatch(state, segTrack.points)
            if (found != null) {
                val (trail, match) = found
                val run = TrailRun(summary.startWallMs, match.startT, match.timeSec, stats.flowScore, stats.brakingPct, stats.jumps, stats.avgSpeedMs)
                results += result(stats.name, trail, match.timeSec, stats, trail.runs)
                val updated = trail.copy(runs = (trail.runs + run).sortedWith(compareBy({ it.rideStartWallMs }, { it.offsetSec })).takeLast(MAX_RUNS))
                state = state.copy(trails = state.trails.map { if (it.id == trail.id) updated else it })
            } else {
                val core = segTrack.core
                val points = TrailMatcher.thin(core.map { GeoPoint(it.lat, it.lon) }, MAX_TRACK_POINTS)
                val time = core.last().t - core.first().t
                val trail = Trail(
                    id = state.nextId, name = "Trail ${state.nextId}", distanceM = TrailMatcher.length(points), dropM = stats.elevLossM,
                    track = points,
                    runs = listOf(
                        TrailRun(summary.startWallMs, core.first().t, time, stats.flowScore, stats.brakingPct, stats.jumps, stats.avgSpeedMs),
                    ),
                )
                results += TrailRunResult(
                    descent = stats.name, trailId = trail.id, trailName = trail.name, timeSec = time, rank = 1, runs = 1,
                    flowScore = stats.flowScore, newTrail = true, distanceM = trail.distanceM, dropM = trail.dropM,
                )
                state = state.copy(nextId = state.nextId + 1, trails = (state.trails + trail).takeLast(MAX_TRAILS))
            }
        }
        if (results.isNotEmpty() || state != loaded) save(state)
        results
    }

    fun rename(id: Int, name: String) = update { s ->
        s.copy(trails = s.trails.map { if (it.id == id && name.isNotBlank()) it.copy(name = name.trim().take(40)) else it })
    }

    fun delete(id: Int) = update { s -> s.copy(trails = s.trails.filterNot { it.id == id }) }

    private fun bestMatch(state: TrailState, track: List<TrackPoint>): Pair<Trail, TrailMatcher.Match>? =
        state.trails.mapNotNull { trail -> TrailMatcher.match(track, trail.track, trail.distanceM)?.let { trail to it } }
            .minByOrNull { it.second.meanDeviationM }

    private fun result(descent: String, trail: Trail, time: Double, stats: SegmentStats, earlier: List<TrailRun>): TrailRunResult {
        val times = earlier.map { it.timeSec }
        return TrailRunResult(
            descent = descent, trailId = trail.id, trailName = trail.name, timeSec = time,
            rank = 1 + times.count { it < time }, runs = earlier.size + 1,
            previousBestSec = times.minOrNull(), flowScore = stats.flowScore,
            previousBestFlow = earlier.minOfOrNull { it.flowScore }, distanceM = trail.distanceM, dropM = trail.dropM,
        )
    }

    private fun update(change: (TrailState) -> TrailState) = synchronized(lock) { save(change(load())) }

    private fun load(): TrailState =
        if (!file.exists()) TrailState() else runCatching { json.decodeFromString<TrailState>(file.readText()) }
            .onFailure { Log.w(TAG, "unreadable ${file.name}, starting over", it) }
            .getOrDefault(TrailState())

    private fun save(state: TrailState) {
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(json.encodeToString(state))
        if (!tmp.renameTo(file)) {
            file.writeText(tmp.readText())
            tmp.delete()
        }
    }

    companion object {
        const val FILE_NAME = "trails.json"
        private const val TAG = "MtbTrails"
        const val MIN_TRAIL_M = 200.0
        const val MIN_DROP_M = 15.0
        const val MAX_TRACK_POINTS = 300
        const val MAX_RUNS = 200
        const val MAX_TRAILS = 500
        private val json = Json { ignoreUnknownKeys = true }
    }
}
