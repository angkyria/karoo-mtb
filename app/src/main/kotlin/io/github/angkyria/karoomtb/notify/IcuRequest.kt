package io.github.angkyria.karoomtb.notify

import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.notify.Units.Companion.duration
import io.github.angkyria.karoomtb.notify.Units.Companion.fmt
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.text.SimpleDateFormat
import java.util.Base64
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.math.abs

/**
 * intervals.icu API requests (mirrors tools/mtbdyn/icu.py): find the activity the Karoo uploaded
 * for a ride and put the MTB block into its description (and, optionally, custom fields).
 * API key: intervals.icu → Settings → Developer Settings.
 */
object IcuRequest {
    const val BASE = "https://intervals.icu"
    const val DESCRIPTION_MARKER = "🚵 MTB Dynamics"
    val RIDE_TYPES = setOf("Ride", "MountainBikeRide", "GravelRide", "EBikeRide", "EMountainBikeRide")

    /** An activity starting this close to the ride is the same ride. */
    const val START_TOLERANCE_MS = 10L * 60 * 1000

    /** Custom activity field codes from intervals-icu/README.md and the summary value each gets. */
    val FIELDS: List<Pair<String, (RideSummary) -> Double>> = listOf(
        "MtbGrit" to { s -> s.grit.totalK },
        "MtbFlow" to { s -> s.flow.score },
        "MtbJumps" to { s -> s.jumps.count.toDouble() },
        "MtbMaxAir" to { s -> s.jumps.longest?.airSec ?: 0.0 },
        "MtbTotalAir" to { s -> s.jumps.totalAirSec },
        "MtbScore" to { s -> s.score.total },
        "MtbDescentBraking" to { s -> s.descending.brakingPct },
        "MtbCorners" to { s -> s.cornering.count.toDouble() },
        "MtbMaxCornerG" to { s -> s.cornering.maxLateralG },
    )

    private val json = Json { ignoreUnknownKeys = true }

    fun headers(apiKey: String, json: Boolean = false): Map<String, String> = buildMap {
        put("Authorization", "Basic " + Base64.getEncoder().encodeToString("API_KEY:${apiKey.trim()}".toByteArray()))
        put("User-Agent", "karoo-mtb")
        if (json) put("Content-Type", "application/json")
    }

    fun athlete(apiKey: String, athleteId: String): HttpRequestSpec =
        HttpRequestSpec("GET", "$BASE/api/v1/athlete/${id(athleteId)}", headers(apiKey), ByteArray(0))

    /** Activities from the day before to the day after the ride. */
    fun activities(apiKey: String, athleteId: String, rideStartWallMs: Long): HttpRequestSpec {
        val day = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT)
        val oldest = day.format(Date(rideStartWallMs - DAY_MS))
        val newest = day.format(Date(rideStartWallMs + DAY_MS))
        return HttpRequestSpec("GET", "$BASE/api/v1/athlete/${id(athleteId)}/activities?oldest=$oldest&newest=$newest", headers(apiKey), ByteArray(0))
    }

    fun activity(apiKey: String, activityId: String): HttpRequestSpec =
        HttpRequestSpec("GET", "$BASE/api/v1/activity/$activityId", headers(apiKey), ByteArray(0))

    fun update(apiKey: String, activityId: String, body: JsonObject): HttpRequestSpec =
        HttpRequestSpec("PUT", "$BASE/api/v1/activity/$activityId", headers(apiKey, json = true), body.toString().toByteArray())

    /** The ride among the listed activities: a ride type starting within 10 minutes, the closest. */
    fun findActivity(activitiesJson: String, rideStartWallMs: Long, zone: TimeZone = TimeZone.getDefault()): String? {
        val list = runCatching { json.parseToJsonElement(activitiesJson) as JsonArray }.getOrNull() ?: return null
        return list.mapNotNull { e ->
            val o = e.jsonObject
            val type = o["type"]?.jsonPrimitive?.contentOrNull
            if (type != null && type !in RIDE_TYPES) return@mapNotNull null
            val start = o["start_date"]?.jsonPrimitive?.contentOrNull?.let { parse(it, TimeZone.getTimeZone("UTC")) }
                ?: o["start_date_local"]?.jsonPrimitive?.contentOrNull?.let { parse(it, zone) }
                ?: return@mapNotNull null
            val id = o["id"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
            (id to abs(start - rideStartWallMs)).takeIf { it.second <= START_TOLERANCE_MS }
        }.minByOrNull { it.second }?.first
    }

    fun description(activityJson: String): String? =
        runCatching { json.parseToJsonElement(activityJson).jsonObject["description"]?.jsonPrimitive?.contentOrNull }.getOrNull()

    /** The MTB block for the description (same as the analyser's --icu-update, plus trail PBs). */
    fun block(s: RideSummary, units: Units): String = buildList {
        add(fmt("%s · score %.0f", DESCRIPTION_MARKER, s.score.total))
        val longest = s.jumps.longest?.let { fmt(" (longest %.2f s / %s)", it.airSec, units.meters(it.distanceM)) } ?: ""
        add(fmt("Grit %.1f kGrit · Flow %.2f · %d jumps", s.grit.totalK, s.flow.score, s.jumps.count) + longest)
        val c = s.cornering
        add(fmt("%d corners · max %.2f g · descents %s, braking %.0f %%", c.count, c.maxLateralG, duration(s.descending.timeSec), s.descending.brakingPct))
        s.trailRuns.filter { it.pb }.forEach { add("PB ${it.trailName} ${duration(it.timeSec)} (was ${duration(it.previousBestSec!!)})") }
    }.joinToString("\n")

    /** Replaces an earlier MTB block (re-sends) and keeps the rest of the description. */
    fun mergedDescription(old: String?, block: String): String {
        val kept = ArrayList<String>()
        var skipping = false
        for (line in (old ?: "").lines()) {
            if (line.startsWith(DESCRIPTION_MARKER)) {
                skipping = true
                continue
            }
            if (skipping && (line.startsWith("Grit ") || " corners · " in line || line.startsWith("PB "))) continue
            skipping = false
            kept += line
        }
        val text = kept.joinToString("\n").trimEnd()
        return (if (text.isEmpty()) "" else "$text\n\n") + block
    }

    fun updateBody(description: String, summary: RideSummary?, withFields: Boolean): JsonObject = buildJsonObject {
        put("description", description)
        if (withFields && summary != null) FIELDS.forEach { (code, value) -> put(code, value(summary)) }
    }

    private fun id(athleteId: String) = athleteId.trim().ifEmpty { "0" }

    private fun parse(text: String, zone: TimeZone): Long? {
        val clean = text.removeSuffix("Z").substringBefore('+').take(19)
        return runCatching {
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.ROOT).apply { timeZone = zone }.parse(clean)?.time
        }.getOrNull()
    }

    private const val DAY_MS = 24L * 3600 * 1000
}
