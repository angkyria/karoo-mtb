package io.github.angkyria.karoomtb.engine

import kotlin.math.abs

/**
 * Post-ride insights that turn the numbers into something to work on (mirrored in
 * tools/mtbdyn/insights.py):
 *  - comparable laps: fastest, smoothest, and whether the last laps were slower than the first;
 *  - the spots with the most unnecessary braking (where Flow was lost);
 *  - speed kept in left vs right corners.
 */
object Insights {
    /** Laps within this share of the median lap distance are compared (a short last lap is not). */
    const val LAP_DISTANCE_TOLERANCE = 0.15
    const val MIN_SPOT_FLOW_M = 3.0
    const val MAX_SPOTS = 3
    private const val SPOT_GAP_SEC = 2
    const val MIN_CORNERS_PER_SIDE = 5
    const val SIDE_DIFFERENCE_PCT = 5.0

    fun lapComparison(laps: List<SegmentStats>): LapComparison? {
        if (laps.size < 2) return null
        val sortedDistances = laps.map { it.distanceM }.sorted()
        val median = sortedDistances[sortedDistances.size / 2]
        if (median < 100.0) return null
        val comparable = laps.filter { abs(it.distanceM - median) <= LAP_DISTANCE_TOLERANCE * median }
        if (comparable.size < 2) return null
        val fastest = comparable.minBy { it.durationSec }
        val smoothest = comparable.minBy { it.flowScore }
        // First third vs last third of the comparable laps (from 4 laps on).
        val trend = if (comparable.size >= 4) {
            val third = comparable.size / 3
            val first = comparable.take(third).map { it.durationSec }.average()
            val last = comparable.takeLast(third).map { it.durationSec }.average()
            100.0 * (last - first) / first
        } else {
            null
        }
        return LapComparison(
            comparable = comparable.size,
            laps = laps.size,
            fastestLap = fastest.index,
            fastestSec = fastest.durationSec,
            medianSec = comparable.map { it.durationSec }.sorted()[comparable.size / 2],
            smoothestLap = smoothest.index,
            smoothestFlow = smoothest.flowScore,
            trendPct = trend,
        )
    }

    /**
     * Runs of seconds with unnecessary braking (gaps up to 2 s joined), ranked by braking metres.
     * [segments] name the climb / descent a spot is in.
     */
    fun brakingSpots(samples: List<SecondSample>, segments: List<SegmentStats>, startWallMs: Long): List<BrakingSpot> {
        val spots = ArrayList<BrakingSpot>()
        var i = 0
        while (i < samples.size) {
            if (!samples[i].counts()) {
                i++
                continue
            }
            // Extend the run while the gap since its last braking second is at most SPOT_GAP_SEC.
            var end = i
            var j = i + 1
            while (j < samples.size && j - end <= SPOT_GAP_SEC + 1) {
                if (samples[j].counts()) end = j
                j++
            }
            val run = samples.subList(i, end + 1)
            val flow = run.sumOf { if (it.processed) it.flow else 0.0 }
            if (flow >= MIN_SPOT_FLOW_M) {
                val first = run.first()
                val before = samples[maxOf(0, i - 1)].speed
                val offset = (first.wallMs - startWallMs) / 1000.0
                val located = run.firstOrNull { !it.lat.isNaN() && !it.lon.isNaN() }
                spots += BrakingSpot(
                    offsetSec = offset,
                    distanceM = first.distanceM - first.dDist,
                    flowM = flow,
                    durationSec = run.sumOf { it.dt },
                    speedBeforeMs = maxOf(before, first.speed),
                    speedAfterMs = run.minOf { it.speed },
                    lat = located?.lat,
                    lon = located?.lon,
                    segment = segments.firstOrNull { it.type != "FLAT" && offset >= it.startOffsetSec && offset < it.startOffsetSec + it.durationSec }?.name,
                )
            }
            i = end + 1
        }
        return spots.sortedByDescending { it.flowM }.take(MAX_SPOTS)
    }

    private fun SecondSample.counts(): Boolean = processed && moving && flow > 0.05

    /** Average apex speed as a share of entry speed, for left and right corners. */
    fun cornerSides(corners: List<Corner>): Pair<Double?, Double?> {
        fun kept(list: List<Corner>): Double? {
            val valid = list.filter { it.entrySpeedMs > 0.5 }
            return if (valid.size < MIN_CORNERS_PER_SIDE) null else valid.map { 100.0 * it.minSpeedMs / it.entrySpeedMs }.average()
        }
        return kept(corners.filter { it.angleDeg > 0 }) to kept(corners.filter { it.angleDeg < 0 })
    }
}
