package io.github.angkyria.karoomtb.storage

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * A zip for bug reports, sent over ntfy from the settings screen (no adb needed): the last
 * ride's files with the GPS positions removed, plus text files such as the log and the
 * (redacted) settings. The raw IMU log is left out (size). ntfy gets it in parts the Karoo's
 * HTTP bridge accepts; `cat name.zip.* > name.zip` joins them.
 */
object DebugBundle {
    /** The Karoo bridge refuses request bodies above 100 KB. */
    const val PART_BYTES = 90_000
    private const val MAX_SAMPLE_LINES = 7_200

    /** Keys that hold positions or GPS tracks. */
    private val GPS_KEYS = setOf("lat", "lon", "track", "descentTracks", "points")
    private val RIDE_FILES = listOf("meta.json", "summary.json", "events.jsonl", "samples.csv", "ntfy.json", "icu.json")
    private val json = Json { prettyPrint = false }

    fun build(rideDir: File?, extras: Map<String, String>): ByteArray {
        val out = ByteArrayOutputStream()
        ZipOutputStream(out).use { zip ->
            fun add(name: String, text: String) {
                zip.putNextEntry(ZipEntry(name))
                zip.write(text.toByteArray())
                zip.closeEntry()
            }
            if (rideDir != null) {
                for (name in RIDE_FILES) {
                    val file = File(rideDir, name)
                    if (!file.isFile) continue
                    val text = file.readText()
                    val clean = when {
                        name.endsWith(".csv") -> stripCsvGps(tailLines(text, MAX_SAMPLE_LINES))
                        name.endsWith(".jsonl") -> text.lines().filter { it.isNotBlank() }.joinToString("\n") { stripJsonGps(it) }
                        else -> stripJsonGps(text)
                    }
                    add("ride-${rideDir.name}/$name", clean)
                }
            }
            for ((name, text) in extras) add(name, if (name.endsWith(".json")) stripJsonGps(text) else text)
        }
        return out.toByteArray()
    }

    /** Blanks the lat / lon columns (by header name) of a ride CSV. */
    fun stripCsvGps(csv: String): String {
        val lines = csv.lines()
        if (lines.isEmpty()) return csv
        val header = lines.first().split(',')
        val drop = header.indices.filter { header[it].trim() in setOf("lat", "lon") }.toSet()
        if (drop.isEmpty()) return csv
        return lines.joinToString("\n") { line ->
            if (line === lines.first() || line.isBlank()) line else line.split(',').mapIndexed { i, v -> if (i in drop) "" else v }.joinToString(",")
        }
    }

    /** Removes position keys from a JSON document (unparseable text is returned unchanged). */
    fun stripJsonGps(text: String): String = runCatching { json.encodeToString(JsonElement.serializer(), strip(json.parseToJsonElement(text))) }
        .getOrDefault(text)

    private fun strip(e: JsonElement): JsonElement = when (e) {
        is JsonObject -> JsonObject(e.filterKeys { it !in GPS_KEYS }.mapValues { strip(it.value) })
        is JsonArray -> JsonArray(e.map(::strip))
        else -> e
    }

    /** The header plus the last [max] lines. */
    fun tailLines(text: String, max: Int): String {
        val lines = text.lines()
        return if (lines.size <= max + 1) text else (listOf(lines.first()) + lines.takeLast(max)).joinToString("\n")
    }

    fun parts(bytes: ByteArray, max: Int = PART_BYTES): List<ByteArray> =
        if (bytes.isEmpty()) emptyList() else (bytes.indices step max).map { bytes.copyOfRange(it, minOf(bytes.size, it + max)) }
}
