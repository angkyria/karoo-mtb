package io.github.angkyria.karoomtb.engine

import kotlin.math.roundToLong

/** A stretch of rough ground for the map layer. */
data class RoughSection(val id: Int, val points: List<GeoPoint>, val avgRoughG: Double)

/**
 * What the Karoo map layer shows for the ride so far. [version] changes whenever something is
 * added; [ride] changes with every new ride (so the layer clears the old one).
 */
data class MapFeatures(
    val ride: Long = 0,
    val version: Int = 0,
    val jumps: List<Jump> = emptyList(),
    val markers: List<Marker> = emptyList(),
    val rough: List<RoughSection> = emptyList(),
)

/**
 * Collects rough sections while riding: seconds at or above [MIN_ROUGH_G] (rooty singletrack
 * and rougher), joined across gaps up to [GAP_SEC], kept when they last [MIN_SEC].
 * Not thread-safe: [MtbEngine] calls it under its lock.
 */
class RoughSections {
    private val finished = ArrayList<RoughSection>()
    private val current = ArrayList<GeoPoint>()
    private var currentSum = 0.0
    private var currentN = 0
    private var gap = 0
    private var nextId = 1

    val sections: List<RoughSection> get() = finished

    fun reset() {
        finished.clear()
        clearCurrent()
        nextId = 1
    }

    /** @return true when a section was closed (the map has something new). */
    fun onSecond(s: SecondSample): Boolean {
        val located = !s.lat.isNaN() && !s.lon.isNaN()
        val rough = s.moving && !s.rough.isNaN() && s.rough >= MIN_ROUGH_G
        if (rough && located) {
            current += GeoPoint(s.lat, s.lon)
            currentSum += s.rough
            currentN++
            gap = 0
            return false
        }
        if (current.isEmpty()) return false
        if (located) current += GeoPoint(s.lat, s.lon)
        gap++
        return if (gap > GAP_SEC) close() else false
    }

    /** Closes the section in progress (ride end). */
    fun flush(): Boolean = current.isNotEmpty() && close()

    private fun close(): Boolean {
        // Drop the trailing gap seconds, keep the section if it was long enough.
        val points = current.dropLast(minOf(gap, current.size))
        val keep = currentN >= MIN_SEC && points.size >= 2
        if (keep) {
            finished += RoughSection(nextId++, points, currentSum / currentN)
            if (finished.size > MAX_SECTIONS) finished.removeAt(0)
        }
        clearCurrent()
        return keep
    }

    private fun clearCurrent() {
        current.clear()
        currentSum = 0.0
        currentN = 0
        gap = 0
    }

    companion object {
        const val MIN_ROUGH_G = 0.9
        const val VERY_ROUGH_G = 1.3
        const val GAP_SEC = 3
        const val MIN_SEC = 5
        const val MAX_SECTIONS = 60
    }
}

/** Google's encoded polyline format (precision 5), which karoo-ext's ShowPolyline expects. */
object Polyline {
    fun encode(points: List<GeoPoint>): String {
        val out = StringBuilder()
        var lastLat = 0L
        var lastLon = 0L
        for (p in points) {
            val lat = (p.lat * 1e5).roundToLong()
            val lon = (p.lon * 1e5).roundToLong()
            encodeValue(lat - lastLat, out)
            encodeValue(lon - lastLon, out)
            lastLat = lat
            lastLon = lon
        }
        return out.toString()
    }

    private fun encodeValue(value: Long, out: StringBuilder) {
        var v = if (value < 0) (value shl 1).inv() else value shl 1
        while (v >= 0x20) {
            out.append(((0x20 or (v and 0x1f).toInt()) + 63).toChar())
            v = v shr 5
        }
        out.append((v.toInt() + 63).toChar())
    }
}
