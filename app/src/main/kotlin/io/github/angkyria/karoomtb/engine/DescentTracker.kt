package io.github.angkyria.karoomtb.engine

/**
 * Finds descents while riding, one second at a time.
 *
 * The post-ride [Segmenter] looks at the whole ride with a centred filter; live, only the past is
 * known. So: a descent starts once the (trailing-smoothed) altitude is [START_DROP_M] below the
 * last high point, and the descent is dated back to that high point. It ends at its lowest point
 * once the altitude has risen [END_RISE_M] again, or after [FLAT_END_M] without a new low (a long
 * fire road). It counts when it dropped at least the segment threshold (default 15 m).
 *
 * Without barometric altitude, the Karoo's grade is integrated over distance instead.
 * Not thread-safe: [MtbEngine] calls it under its lock.
 */
class DescentTracker {
    /** A descent that just ended: sample indices [start]..[end] (high point to low point). */
    data class Finished(val number: Int, val start: Int, val end: Int, val dropM: Double)

    private val window = ArrayDeque<Double>()
    private var lastAlt = Double.NaN

    var descending = false
        private set
    private var startIdx = -1
    private var hiIdx = -1
    private var hiAlt = Double.NaN
    private var loIdx = -1
    private var loAlt = Double.NaN
    private var currentAlt = Double.NaN
    private var finished = 0

    /** Number the current (or next) descent gets. */
    val number: Int get() = finished + 1

    /** Sample indices of the descent in progress, null when not descending. */
    fun currentRange(lastIndex: Int): IntRange? = if (descending) startIdx..lastIndex else null

    /** Metres dropped so far in the descent in progress. */
    val currentDropM: Double get() = if (descending) hiAlt - currentAlt else 0.0

    fun reset() {
        window.clear()
        lastAlt = Double.NaN
        descending = false
        startIdx = -1
        hiIdx = -1
        hiAlt = Double.NaN
        loIdx = -1
        loAlt = Double.NaN
        currentAlt = Double.NaN
        finished = 0
    }

    /** Feeds sample [i] (the newest); returns a descent that just ended and dropped at least [minDropM]. */
    fun onSample(samples: List<SecondSample>, i: Int, minDropM: Double): Finished? {
        val s = samples[i]
        val a = smoothedAltitude(s)
        currentAlt = a
        if (!descending) {
            // ">=": on a level stretch the descent starts where the level ends, not where it began.
            if (hiIdx < 0 || a >= hiAlt) {
                hiIdx = i
                hiAlt = a
            }
            if (hiAlt - a >= START_DROP_M && s.moving) {
                descending = true
                startIdx = hiIdx
                loIdx = i
                loAlt = a
            }
            return null
        }
        if (a < loAlt) {
            loIdx = i
            loAlt = a
        }
        val risen = a - loAlt >= END_RISE_M
        val flat = s.distanceM - samples[loIdx].distanceM >= FLAT_END_M
        return if (risen || flat) end(i, a, minDropM) else null
    }

    /** Ends a descent still in progress (ride end). */
    fun flush(lastIndex: Int, minDropM: Double): Finished? = if (descending) end(lastIndex, currentAlt, minDropM) else null

    private fun end(i: Int, a: Double, minDropM: Double): Finished? {
        val drop = hiAlt - loAlt
        val result = if (drop >= minDropM && loIdx > startIdx) Finished(++finished, startIdx, loIdx, drop) else null
        descending = false
        hiIdx = i
        hiAlt = a
        return result
    }

    /** Trailing mean of the last [SMOOTH_SEC] altitudes; gaps continue from the grade. */
    private fun smoothedAltitude(s: SecondSample): Double {
        val alt = when {
            !s.altitude.isNaN() -> s.altitude
            lastAlt.isNaN() -> 0.0
            else -> lastAlt + s.grade / 100.0 * s.dDist
        }
        lastAlt = alt
        window.addLast(alt)
        while (window.size > SMOOTH_SEC) window.removeFirst()
        return window.average()
    }

    companion object {
        const val START_DROP_M = 8.0
        const val END_RISE_M = 8.0
        const val FLAT_END_M = 400.0
        private const val SMOOTH_SEC = 5
    }
}
