package io.github.angkyria.karoomtb.engine

/**
 * Decides from the ground's roughness whether the bike is on a trail. Jumps on a trail are
 * small and frequent, so the detector loosens its gates there; on a road a kerb or a pothole
 * should not count, so the preset's gates stay as they are.
 *
 * On a trail = the median roughness of the last [MtbConfig.trailWindowSec] seconds that have
 * one is at least [MtbConfig.trailRoughG]. A median ignores a short rough patch on the road and
 * a short smooth section on the trail.
 */
class TrailMode(private var config: MtbConfig) {
    private val window = ArrayDeque<Double>()

    var active = false
        private set

    fun reconfigure(newConfig: MtbConfig) {
        config = newConfig
    }

    fun reset() {
        window.clear()
        active = false
    }

    /** @param roughG this second's vibration RMS (g), NaN when there is none. */
    fun onSecond(roughG: Double) {
        if (roughG.isNaN()) return
        window.addLast(roughG)
        while (window.size > config.trailWindowSec) window.removeFirst()
        active = window.size >= MIN_SECONDS && median() >= config.trailRoughG
    }

    private fun median(): Double {
        val sorted = window.sorted()
        return sorted[sorted.size / 2]
    }

    companion object {
        /** Seconds with roughness needed before trail mode can switch on. */
        const val MIN_SECONDS = 10
    }
}
