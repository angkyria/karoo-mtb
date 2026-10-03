package io.github.angkyria.karoomtb.engine

/** GPS tracks of ride sections, for trail recognition. */
object Tracks {
    const val SPACING_M = 10.0
    const val MARGIN_M = 150.0

    /** Altitude within this of the top / bottom still counts as the level start / end of a descent. */
    private const val LEVEL_M = 2.0

    /** Points of samples [from]..[to] with a position, one every [SPACING_M] metres (and the last). */
    fun of(samples: List<SecondSample>, from: Int, to: Int, rideStartWallMs: Long): List<TrackPoint> {
        val out = ArrayList<TrackPoint>()
        var lastDist = Double.NEGATIVE_INFINITY
        var lastAdded = -1
        var lastLocated = -1
        for (i in from..to) {
            val s = samples[i]
            if (s.lat.isNaN() || s.lon.isNaN()) continue
            lastLocated = i
            if (s.distanceM - lastDist >= SPACING_M) {
                out += s.point(rideStartWallMs)
                lastDist = s.distanceM
                lastAdded = i
            }
        }
        if (lastLocated > lastAdded) out += samples[lastLocated].point(rideStartWallMs)
        return out
    }

    /**
     * The track of [from]..[to] (the core) with up to [MARGIN_M] before and after it; null with
     * fewer than two located points in the core.
     */
    fun withMargins(segment: Int, samples: List<SecondSample>, from: Int, to: Int, rideStartWallMs: Long): SegmentTrack? {
        var before = from
        while (before > 0 && samples[from].distanceM - samples[before - 1].distanceM <= MARGIN_M) before--
        var after = to
        while (after < samples.lastIndex && samples[after + 1].distanceM - samples[to].distanceM <= MARGIN_M) after++
        val lead = if (before < from) of(samples, before, from - 1, rideStartWallMs) else emptyList()
        val core = of(samples, from, to, rideStartWallMs)
        if (core.size < 2) return null
        val tail = if (after > to) of(samples, to + 1, after, rideStartWallMs) else emptyList()
        return SegmentTrack(segment, lead + core + tail, lead.size, lead.size + core.lastIndex)
    }

    /**
     * A descent segment without the level ground around it: from the last second near its top to
     * the first second near its bottom (smoothed altitude). The whole range without altitude.
     */
    fun descendingCore(samples: List<SecondSample>, from: Int, to: Int): Pair<Int, Int> {
        val alt = Segmenter.smoothedAltitude(samples) ?: return from to to
        val top = (from..to).maxOf { alt[it] }
        val bottom = (from..to).minOf { alt[it] }
        val start = (from..to).last { alt[it] >= top - LEVEL_M }
        val end = (start..to).firstOrNull { alt[it] <= bottom + LEVEL_M } ?: to
        return if (end > start) start to end else from to to
    }

    private fun SecondSample.point(rideStartWallMs: Long) = TrackPoint(lat, lon, (wallMs - rideStartWallMs) / 1000.0)
}
