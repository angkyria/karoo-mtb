package io.github.angkyria.karoomtb.trails

import io.github.angkyria.karoomtb.engine.GeoPoint
import io.github.angkyria.karoomtb.engine.TrackPoint
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sqrt

/**
 * Recognises a trail ridden before in a descent's GPS track and times it between the trail's own
 * start and end points (like a Strava segment), so runs are comparable however the descent was cut.
 *
 * A run matches when it passes within [ENDPOINT_TOLERANCE_M] of the trail's start and then of its
 * end, the stretch between is about as long as the trail, and the trail's points lie close to it.
 */
object TrailMatcher {
    const val ENDPOINT_TOLERANCE_M = 30.0
    const val MEAN_DEVIATION_M = 20.0
    const val MAX_DEVIATION_M = 45.0
    const val LENGTH_TOLERANCE = 0.2

    /** Where a run passed a trail: interpolated times at the trail's start and end, and the deviation. */
    data class Match(val startT: Double, val endT: Double, val distanceM: Double, val meanDeviationM: Double) {
        val timeSec: Double get() = endT - startT
    }

    fun match(run: List<TrackPoint>, trail: List<GeoPoint>, trailDistanceM: Double): Match? {
        if (run.size < 2 || trail.size < 2) return null
        val origin = trail.first()
        val proj = Projection(origin.lat)
        val r = run.map { proj.xy(it.lat, it.lon, origin) }
        val tr = trail.map { proj.xy(it.lat, it.lon, origin) }
        val start = closest(r, tr.first(), 0) ?: return null
        if (start.distance > ENDPOINT_TOLERANCE_M) return null
        val end = closest(r, tr.last(), start.segment) ?: return null
        if (end.distance > ENDPOINT_TOLERANCE_M) return null
        val startPos = start.segment + start.fraction
        val endPos = end.segment + end.fraction
        if (endPos <= startPos) return null
        val distance = lengthBetween(r, start, end)
        if (trailDistanceM > 0 && kotlin.math.abs(distance - trailDistanceM) > LENGTH_TOLERANCE * trailDistanceM) return null
        // Every trail point must lie near the run's stretch between the two endpoints.
        val firstSeg = start.segment
        val lastSeg = end.segment
        var sum = 0.0
        for (p in tr) {
            val d = (firstSeg..lastSeg).minOf { segmentDistance(p, r[it], r[minOf(it + 1, r.lastIndex)]).first }
            if (d > MAX_DEVIATION_M) return null
            sum += d
        }
        val mean = sum / tr.size
        if (mean > MEAN_DEVIATION_M) return null
        return Match(timeAt(run, start), timeAt(run, end), distance, mean)
    }

    /** Length of a track in metres. */
    fun length(points: List<GeoPoint>): Double {
        if (points.size < 2) return 0.0
        val proj = Projection(points.first().lat)
        val xy = points.map { proj.xy(it.lat, it.lon, points.first()) }
        return (1 until xy.size).sumOf { dist(xy[it - 1], xy[it]) }
    }

    /** Keeps at most [max] points, evenly spread, always with the first and last. */
    fun <T> thin(points: List<T>, max: Int): List<T> {
        if (points.size <= max) return points
        val step = (points.size - 1).toDouble() / (max - 1)
        return (0 until max).map { points[(it * step).toInt().coerceAtMost(points.lastIndex)] }
    }

    private class Closest(val segment: Int, val fraction: Double, val distance: Double)

    /** Closest approach of the run (from segment [fromSegment]) to [p]. */
    private fun closest(r: List<DoubleArray>, p: DoubleArray, fromSegment: Int): Closest? {
        var best: Closest? = null
        for (i in fromSegment until r.lastIndex) {
            val (d, f) = segmentDistance(p, r[i], r[i + 1])
            if (best == null || d < best.distance) best = Closest(i, f, d)
        }
        return best
    }

    private fun lengthBetween(r: List<DoubleArray>, a: Closest, b: Closest): Double {
        if (a.segment == b.segment) return dist(r[a.segment], r[a.segment + 1]) * (b.fraction - a.fraction)
        var total = dist(r[a.segment], r[a.segment + 1]) * (1 - a.fraction)
        for (i in a.segment + 1 until b.segment) total += dist(r[i], r[i + 1])
        return total + dist(r[b.segment], r[b.segment + 1]) * b.fraction
    }

    private fun timeAt(run: List<TrackPoint>, c: Closest): Double {
        val a = run[c.segment]
        val b = run[minOf(c.segment + 1, run.lastIndex)]
        return a.t + (b.t - a.t) * c.fraction
    }

    /** Distance from [p] to segment [a]-[b] and the position along it (0..1). */
    private fun segmentDistance(p: DoubleArray, a: DoubleArray, b: DoubleArray): Pair<Double, Double> {
        val dx = b[0] - a[0]
        val dy = b[1] - a[1]
        val len2 = dx * dx + dy * dy
        val f = if (len2 <= 0.0) 0.0 else (((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2).coerceIn(0.0, 1.0)
        val x = a[0] + f * dx - p[0]
        val y = a[1] + f * dy - p[1]
        return sqrt(x * x + y * y) to f
    }

    private fun dist(a: DoubleArray, b: DoubleArray): Double {
        val x = a[0] - b[0]
        val y = a[1] - b[1]
        return sqrt(x * x + y * y)
    }

    /** Local equirectangular metres around a reference latitude (fine for a few km). */
    private class Projection(lat0: Double) {
        private val kx = EARTH_M * PI / 180.0 * cos(lat0 * PI / 180.0)
        private val ky = EARTH_M * PI / 180.0
        fun xy(lat: Double, lon: Double, origin: GeoPoint) = doubleArrayOf((lon - origin.lon) * kx, (lat - origin.lat) * ky)
    }

    private const val EARTH_M = 6_371_000.0
}
