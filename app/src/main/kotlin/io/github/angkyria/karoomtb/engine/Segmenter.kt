package io.github.angkyria.karoomtb.engine

import kotlin.math.abs
import kotlin.math.max

/**
 * Splits a ride into climbs, descents and flat sections with a zig-zag (hysteresis) filter on
 * barometric altitude: a new section starts once the altitude has reversed by at least
 * [minElevationM] from the last high or low point. Without altitude data the ride is cut into
 * fixed 2 km sections instead.
 */
object Segmenter {
    data class Range(val type: String, val start: Int, val end: Int)

    private const val FALLBACK_SECTION_M = 2000.0
    private const val SMOOTH_HALF_WINDOW = 5

    /** A stretch flatter than this (%) and longer than [FLAT_MIN_M] splits a climb or descent. */
    private const val FLAT_GRADE_PCT = 2.5
    private const val FLAT_MIN_M = 400.0
    private const val GRADE_HALF_WINDOW = 15

    fun split(samples: List<SecondSample>, minElevationM: Double): List<Range> {
        if (samples.size < 2) return emptyList()
        val alt = smoothedAltitude(samples) ?: return byDistance(samples)
        val pivots = pivots(alt, minElevationM)
        val ranges = ArrayList<Range>()
        for (i in 0 until pivots.size - 1) {
            val from = pivots[i]
            val to = pivots[i + 1]
            if (to <= from) continue
            ranges += Range(classify(alt[to] - alt[from], minElevationM), from, to)
        }
        return mergeAdjacent(splitFlats(ranges, samples, alt, minElevationM))
    }

    private fun classify(delta: Double, h: Double): String = when {
        delta >= 0.6 * h -> "CLIMB"
        delta <= -0.6 * h -> "DESCENT"
        else -> "FLAT"
    }

    /**
     * The zig-zag only reacts to reversals, so "descent – long flat – descent" would be one
     * descent. Cut long flat stretches out as their own sections.
     */
    private fun splitFlats(ranges: List<Range>, samples: List<SecondSample>, alt: DoubleArray, h: Double): List<Range> {
        val flat = BooleanArray(samples.size) { i ->
            val a = max(0, i - GRADE_HALF_WINDOW)
            val b = minOf(samples.lastIndex, i + GRADE_HALF_WINDOW)
            val d = samples[b].distanceM - samples[a].distanceM
            d > 20.0 && abs(100.0 * (alt[b] - alt[a]) / d) < FLAT_GRADE_PCT
        }
        val out = ArrayList<Range>()
        for (r in ranges) {
            if (r.type == "FLAT") {
                out += r
                continue
            }
            var cursor = r.start
            var i = r.start
            while (i <= r.end) {
                if (!flat[i]) {
                    i++
                    continue
                }
                var j = i
                while (j + 1 <= r.end && flat[j + 1]) j++
                if (samples[j].distanceM - samples[i].distanceM >= FLAT_MIN_M) {
                    if (i > cursor) out += Range(classify(alt[i] - alt[cursor], h), cursor, i)
                    out += Range("FLAT", i, j)
                    cursor = j
                }
                i = j + 1
            }
            if (r.end > cursor) out += Range(classify(alt[r.end] - alt[cursor], h), cursor, r.end)
        }
        return out
    }

    /** Indices where the smoothed altitude turns by at least [h], plus the first and last index. */
    private fun pivots(alt: DoubleArray, h: Double): List<Int> {
        val result = arrayListOf(0)
        var direction = 0 // +1 climbing, -1 descending, 0 not yet known
        var hiIdx = 0
        var loIdx = 0
        for (i in 1 until alt.size) {
            if (alt[i] > alt[hiIdx]) hiIdx = i
            if (alt[i] < alt[loIdx]) loIdx = i
            when (direction) {
                0 -> if (alt[hiIdx] - alt[loIdx] >= h) {
                    // The extreme reached first starts the first real section.
                    if (loIdx < hiIdx) {
                        if (loIdx != 0) result += loIdx
                        direction = 1
                    } else {
                        if (hiIdx != 0) result += hiIdx
                        direction = -1
                    }
                }
                1 -> if (alt[hiIdx] - alt[i] >= h) {
                    result += hiIdx
                    direction = -1
                    loIdx = i
                }
                -1 -> if (alt[i] - alt[loIdx] >= h) {
                    result += loIdx
                    direction = 1
                    hiIdx = i
                }
            }
        }
        if (result.last() != alt.size - 1) result += alt.size - 1
        return result
    }

    /** Joins neighbouring sections of the same type (can happen at the ride start). */
    private fun mergeAdjacent(ranges: List<Range>): List<Range> {
        val out = ArrayList<Range>()
        for (r in ranges) {
            val last = out.lastOrNull()
            if (last != null && last.type == r.type) out[out.size - 1] = last.copy(end = r.end) else out += r
        }
        return out
    }

    private fun byDistance(samples: List<SecondSample>): List<Range> {
        val out = ArrayList<Range>()
        var start = 0
        var startDist = samples[0].distanceM
        for (i in samples.indices) {
            if (samples[i].distanceM - startDist >= FALLBACK_SECTION_M || i == samples.lastIndex) {
                if (i > start) out += Range("FLAT", start, i)
                start = i
                startDist = samples[i].distanceM
            }
        }
        return out
    }

    /** Centered moving average with gaps filled from neighbours; null when there is no altitude. */
    fun smoothedAltitude(samples: List<SecondSample>): DoubleArray? {
        val raw = DoubleArray(samples.size) { samples[it].altitude }
        val firstValid = raw.indexOfFirst { !it.isNaN() }
        if (firstValid < 0) return null
        var last = raw[firstValid]
        for (i in raw.indices) {
            if (raw[i].isNaN()) raw[i] = last else last = raw[i]
        }
        val out = DoubleArray(raw.size)
        for (i in raw.indices) {
            val from = max(0, i - SMOOTH_HALF_WINDOW)
            val to = minOf(raw.lastIndex, i + SMOOTH_HALF_WINDOW)
            var sum = 0.0
            for (j in from..to) sum += raw[j]
            out[i] = sum / (to - from + 1)
        }
        return out
    }
}

/** Statistics for any slice of the ride (segments, laps, descents). */
object RangeStats {
    fun compute(
        index: Int,
        type: String,
        name: String,
        samples: List<SecondSample>,
        from: Int,
        to: Int,
        jumps: List<Jump>,
        corners: List<Corner>,
        rideStartWallMs: Long,
        shifts: List<Shift> = emptyList(),
        weightKg: Double = Double.NaN,
    ): SegmentStats {
        val slice = samples.subList(from, to + 1)
        val startOffset = (slice.first().wallMs - rideStartWallMs) / 1000.0
        val endOffset = (slice.last().wallMs - rideStartWallMs) / 1000.0
        var distance = 0.0
        var movingSec = 0.0
        var maxSpeed = 0.0
        var grit = 0.0
        var flow = 0.0
        var flowDist = 0.0
        var roughSum = 0.0
        var roughN = 0
        var brakingSec = 0.0
        var maxLat = 0.0
        for (s in slice) {
            distance += s.dDist
            if (s.moving) {
                movingSec += s.dt
                maxSpeed = max(maxSpeed, s.speed)
                maxLat = max(maxLat, s.latG)
                if (!s.rough.isNaN()) {
                    roughSum += s.rough
                    roughN++
                }
                if (s.processed) {
                    flow += s.flow
                    flowDist += s.dDist
                }
                if (s.braking) brakingSec += s.dt
            }
            grit += s.grit
        }
        val (gain, loss) = elevationChange(slice)
        val altStart = slice.firstOrNull { !it.altitude.isNaN() }?.altitude
        val altEnd = slice.lastOrNull { !it.altitude.isNaN() }?.altitude
        val avgGrade = if (altStart != null && altEnd != null && distance > 10.0) 100.0 * (altEnd - altStart) / distance else 0.0
        val inRange = { offset: Double -> offset >= startOffset && offset <= endOffset + 1.0 }
        val rangeJumps = jumps.filter { inRange(it.offsetSec) }
        val base = SegmentStats(
            index = index,
            type = type,
            name = name,
            startOffsetSec = startOffset,
            durationSec = endOffset - startOffset + slice.last().dt,
            distanceM = distance,
            elevGainM = gain,
            elevLossM = loss,
            avgGradePct = avgGrade,
            avgSpeedMs = if (movingSec > 0) distance / movingSec else 0.0,
            maxSpeedMs = maxSpeed,
            gritK = grit / 1000.0,
            gritAvg = if (movingSec > 0) grit / movingSec else 0.0,
            flowScore = Scoring.flowScore(flow, flowDist),
            roughAvg = if (roughN > 0) roughSum / roughN else null,
            jumps = rangeJumps.size,
            maxAirSec = rangeJumps.maxOfOrNull { it.airSec } ?: 0.0,
            brakingPct = if (movingSec > 0) 100.0 * brakingSec / movingSec else 0.0,
            maxLateralG = maxLat,
            corners = corners.count { inRange(it.offsetSec) },
        )
        return BikeAnalytics.forRange(base, slice, shifts, weightKg)
    }

    /** Gain and loss with a 1 m dead band against barometric noise. */
    fun elevationChange(slice: List<SecondSample>): Pair<Double, Double> {
        var gain = 0.0
        var loss = 0.0
        var ref = Double.NaN
        for (s in slice) {
            val a = s.altitude
            if (a.isNaN()) continue
            if (ref.isNaN()) {
                ref = a
                continue
            }
            val d = a - ref
            if (abs(d) >= 1.0) {
                if (d > 0) gain += d else loss -= d
                ref = a
            }
        }
        return gain to loss
    }
}
