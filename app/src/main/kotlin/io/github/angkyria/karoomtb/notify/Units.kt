package io.github.angkyria.karoomtb.notify

import java.util.Locale

/** Formats SI values in the rider's preferred units (taken from the Karoo user profile). */
data class Units(val imperialDistance: Boolean = false, val imperialElevation: Boolean = false) {

    fun speed(ms: Double): String =
        if (imperialDistance) fmt("%.1f mph", ms * 2.236936) else fmt("%.1f km/h", ms * 3.6)

    fun distance(m: Double): String =
        if (imperialDistance) fmt("%.1f mi", m / 1609.344) else fmt("%.1f km", m / 1000.0)

    /** Short distances (jumps). */
    fun meters(m: Double): String =
        if (imperialDistance) fmt("%.1f ft", m * 3.28084) else fmt("%.1f m", m)

    fun elevation(m: Double): String =
        if (imperialElevation) fmt("%.0f ft", m * 3.28084) else fmt("%.0f m", m)

    fun height(m: Double): String =
        if (imperialElevation) fmt("%.1f ft", m * 3.28084) else fmt("%.1f m", m)

    companion object {
        fun fmt(pattern: String, vararg args: Any?): String = String.format(Locale.ROOT, pattern, *args)

        fun duration(seconds: Double): String {
            val total = seconds.toLong().coerceAtLeast(0)
            val h = total / 3600
            val m = (total % 3600) / 60
            val s = total % 60
            return if (h > 0) fmt("%d:%02d:%02d", h, m, s) else fmt("%d:%02d", m, s)
        }
    }
}
