package io.github.angkyria.karoomtb.notify

import io.github.angkyria.karoomtb.engine.BrakingSpot
import io.github.angkyria.karoomtb.engine.Insights
import io.github.angkyria.karoomtb.engine.Jump
import io.github.angkyria.karoomtb.engine.LapComparison
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.engine.SegmentStats
import io.github.angkyria.karoomtb.notify.Units.Companion.duration
import io.github.angkyria.karoomtb.notify.Units.Companion.fmt
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Turns a [RideSummary] into the ntfy notification (Markdown) and short Karoo texts. */
object SummaryFormatter {
    /** ntfy turns longer messages into attachments; stay below its 4096 byte limit. */
    const val MAX_MESSAGE_BYTES = 3800
    private const val MAX_SEGMENT_LINES = 10

    fun title(summary: RideSummary): String {
        val date = SimpleDateFormat("EEE d MMM HH:mm", Locale.ENGLISH).format(Date(summary.startWallMs))
        val profile = summary.profileName?.takeIf { it.isNotBlank() }?.let { " · $it" } ?: ""
        return "MTB Dynamics$profile · $date"
    }

    /**
     * [notices]: extra lines such as service reminders, shown after the bike section.
     * [trails]: trail personal-best lines. [mapLinks]: OpenStreetMap links on the braking spots.
     */
    fun markdown(
        summary: RideSummary,
        units: Units,
        notices: List<String> = emptyList(),
        trails: List<String> = emptyList(),
        mapLinks: Boolean = false,
    ): String {
        val head = headLines(summary, units) + bikeLines(summary) +
            (if (trails.isNotEmpty()) listOf("") + trails else emptyList()) +
            (if (notices.isNotEmpty()) listOf("") + notices else emptyList())
        val tail = listOf("", footer(summary, units))
        val segmentLines = segmentLines(summary.segments, units).toMutableList()
        val lapLines = lapLines(summary.laps, units).toMutableList()
        val spotLines = brakingSpotLines(summary.brakingSpots, units, mapLinks).toMutableList()
        // Drop the least important lines (laps first, then segments, then braking spots) until the message fits.
        while (true) {
            val body = buildList {
                addAll(head)
                if (spotLines.isNotEmpty()) {
                    add("")
                    add("**Where Flow was lost** (most unnecessary braking)")
                    addAll(spotLines)
                }
                if (segmentLines.isNotEmpty()) {
                    add("")
                    add("**Trail segments**")
                    addAll(segmentLines)
                }
                if (lapLines.isNotEmpty()) {
                    add("")
                    add("**Laps**")
                    addAll(lapLines)
                }
                addAll(tail)
            }.joinToString("\n")
            when {
                body.toByteArray().size <= MAX_MESSAGE_BYTES -> return body
                lapLines.isNotEmpty() -> lapLines.removeAt(lapLines.lastIndex)
                segmentLines.isNotEmpty() -> segmentLines.removeAt(segmentLines.lastIndex)
                spotLines.isNotEmpty() -> spotLines.removeAt(spotLines.lastIndex)
                else -> return truncateUtf8(body, MAX_MESSAGE_BYTES)
            }
        }
    }

    private fun truncateUtf8(text: String, maxBytes: Int): String {
        // A char is at least one UTF-8 byte, so start at maxBytes chars and shrink.
        var end = minOf(text.length, maxBytes)
        while (end > 0 && text.substring(0, end).toByteArray().size > maxBytes - 3) end--
        // Never split a surrogate pair (emoji).
        if (end > 0 && Character.isHighSurrogate(text[end - 1])) end--
        return text.substring(0, end) + "…"
    }

    /** One line for the Karoo control-center notification. */
    fun oneLine(summary: RideSummary): String = fmt(
        "Score %.0f · Grit %.1f · Flow %.1f · %d jumps",
        summary.score.total, summary.grit.totalK, summary.flow.score, summary.jumps.count,
    )

    fun jumpAlertTitle(jump: Jump): String = fmt("Jump! %.2f s airtime", jump.airSec)

    fun jumpAlertDetail(jump: Jump, units: Units): String =
        "${units.meters(jump.distanceM)} · ${units.speed(jump.speedMs)} · ${fmt("%.1f g", jump.landingG)} landing"

    /** In-ride alert at the bottom of a descent: "Descent 2 · 4:12 · −182 m". */
    fun descentAlertTitle(d: SegmentStats, units: Units): String =
        "${d.name} · ${Units.duration(d.durationSec)} · −${units.elevation(d.elevLossM)}"

    fun descentAlertDetail(d: SegmentStats): String = buildString {
        append(fmt("Flow %.1f · brake %.0f%%", d.flowScore, d.brakingPct))
        if (d.jumps > 0) append(fmt(" · %d jump%s", d.jumps, if (d.jumps == 1) "" else "s"))
        if (d.maxLateralG > 0.05) append(fmt(" · max %.2f g", d.maxLateralG))
    }

    private fun headLines(s: RideSummary, units: Units): List<String> = buildList {
        add(fmt("**🚵 MTB score %.0f** · difficulty %.0f · smoothness %.0f · air %.0f", s.score.total, s.score.difficulty, s.score.smoothness, s.score.air))
        add("")
        add(fmt("⛰️ **Grit %.1f kGrit** · avg %.1f/s · peak 60 s %.1f", s.grit.totalK, s.grit.avgPerSec, s.grit.peak60))
        add(fmt("🌊 **Flow %.1f** (lower = smoother) · descents %.1f · worst 60 s %.1f", s.flow.score, s.flow.descentScore, s.flow.worst60))
        val j = s.jumps
        if (j.count == 0) {
            add("🪂 No jumps detected")
        } else {
            add(fmt("🪂 **%d jump%s** · %.1f s total airtime", j.count, if (j.count == 1) "" else "s", j.totalAirSec))
            j.longest?.let { add("  • Longest: **${fmt("%.2f s", it.airSec)}** · ${units.meters(it.distanceM)} · ${units.speed(it.speedMs)}") }
            val extras = listOfNotNull(
                j.farthest?.let { "farthest ${units.meters(it.distanceM)}" },
                j.highest?.let { "highest ~${units.height(it.heightM)}" },
                j.hardestLanding?.let { fmt("hardest landing %.1f g", it.landingG) },
            )
            if (extras.isNotEmpty()) add("  • " + extras.joinToString(" · ").replaceFirstChar { it.uppercase() })
        }
        val c = s.cornering
        if (c.count > 0) {
            add(fmt("↪️ **%d corners** (%d L / %d R) · max %.2f g · speed kept %.0f%%", c.count, c.left, c.right, c.maxLateralG, c.speedKeptPct))
            cornerSideHint(c.speedKeptLeftPct, c.speedKeptRightPct)?.let { add("  • $it") }
        }
        val d = s.descending
        if (d.timeSec >= 30) {
            add(
                "⬇️ **Descents ${duration(d.timeSec)}** · ${units.elevation(d.dropM)} ↓ · avg ${units.speed(d.avgSpeedMs)} · " +
                    fmt("braking %.0f%%", d.brakingPct),
            )
        }
        s.roughnessAvg?.let { add(fmt("〰️ Roughness avg %.2f g", it)) }
        s.lapComparison?.let { add(lapComparisonLine(it)) }
    }

    /** "You lose more speed in right-handers (88% vs 96% kept)", or null when both sides are alike. */
    fun cornerSideHint(left: Double?, right: Double?): String? {
        if (left == null || right == null) return null
        if (kotlin.math.abs(left - right) < Insights.SIDE_DIFFERENCE_PCT) {
            return fmt("Left and right corners alike (%.0f%% / %.0f%% speed kept)", left, right)
        }
        val (weak, worse, better) = if (left < right) Triple("left", left, right) else Triple("right", right, left)
        return fmt("You lose more speed in %s-handers (%.0f%% vs %.0f%% kept)", weak, worse, better)
    }

    fun lapComparisonLine(l: LapComparison): String = buildString {
        append(fmt("🏁 **%d laps**", l.laps))
        if (l.comparable < l.laps) append(fmt(" (%d comparable)", l.comparable))
        append(" · fastest Lap ${l.fastestLap} ${duration(l.fastestSec)} · median ${duration(l.medianSec)}")
        append(fmt(" · smoothest Lap %d (Flow %.1f)", l.smoothestLap, l.smoothestFlow))
        l.trendPct?.let {
            append(
                when {
                    it > 2.0 -> fmt(" · last laps %.0f%% slower", it)
                    it < -2.0 -> fmt(" · last laps %.0f%% faster", -it)
                    else -> " · steady pace"
                },
            )
        }
    }

    fun brakingSpotLines(spots: List<BrakingSpot>, units: Units, mapLinks: Boolean): List<String> = spots.mapIndexed { i, b ->
        val where = listOfNotNull(b.segment, "at ${units.distance(b.distanceM)} (${duration(b.offsetSec)})").joinToString(" · ")
        val speeds = "${units.speed(b.speedBeforeMs).substringBefore(' ')}→${units.speed(b.speedAfterMs)}"
        val link = if (mapLinks && b.lat != null && b.lon != null) " · [map](${osmLink(b.lat, b.lon)})" else ""
        "${i + 1}. $where · ${units.meters(b.flowM)} braking · $speeds$link"
    }

    fun osmLink(lat: Double, lon: Double): String =
        fmt("https://www.openstreetmap.org/?mlat=%.5f&mlon=%.5f#map=18/%.5f/%.5f", lat, lon, lat, lon)

    /** RockShox Flight Attendant, SRAM AXS and power meter; nothing when none was paired. */
    fun bikeLines(s: RideSummary): List<String> = buildList {
        val b = s.bike
        b.suspension?.let { su ->
            val parts = buildList {
                su.descents?.let { add(fmt("descents %.0f%% open", it.open)) }
                su.climbs?.let { add(fmt("climbs %.0f%% lock", it.lock)) }
                if (su.lockedRoughSec >= 5) add("locked on rough ${duration(su.lockedRoughSec)}")
                if (su.openHardClimbSec >= 5) add("open on hard climbs ${duration(su.openHardClimbSec)}")
                su.reactionSecMedian?.let { add(fmt("opens %.0f s into descents", it)) }
            }
            add("🔩 **Flight Attendant** " + parts.ifEmpty { listOf(fmt("%.0f%% open", su.overall.open)) }.joinToString(" · "))
        }
        b.drivetrain?.let { d ->
            val parts = buildList {
                add(fmt("**%d shifts** (%.1f/km)", d.shifts, d.shiftsPerKm))
                if (d.smallestCogTeeth != null && d.largestCogTeeth != null) add("cogs ${d.smallestCogTeeth}–${d.largestCogTeeth}T")
                d.climbMedianCog?.let { add("climbs ${it}T") }
                if (d.underLoad > 0) add("${d.underLoad} under load")
            }
            add("⚙️ " + parts.joinToString(" · "))
        }
        b.power?.let { p ->
            val parts = buildList {
                p.climbs?.let { c -> add("climbs " + fmt("%.0f W", c.avgW) + (c.wattsPerKg?.let { fmt(" (%.1f W/kg)", it) } ?: "")) }
                p.descents?.let { add(fmt("pedalling on %.0f%% of descents", it.pedallingPct)) }
                p.best5minW?.let { add(fmt("best 5 min %.0f W", it)) }
                p.climbs?.balanceLeft?.let { add(fmt("L/R %.0f/%.0f", it, 100 - it)) }
            }
            add("💪 **Power** " + parts.ifEmpty { listOf(fmt("avg %.0f W", p.avgW)) }.joinToString(" · "))
        }
        if (b.batteries.isNotEmpty()) {
            add(
                "🔋 " + b.batteries.joinToString(" · ") {
                    val low = it.status == "LOW" || it.status == "CRITICAL"
                    "${it.component} " + (it.percent?.let { pct -> "$pct%" } ?: it.status.lowercase()) + if (low) " ⚠️" else ""
                },
            )
        }
        if (isNotEmpty()) add(0, "")
    }

    private fun segmentLines(segments: List<SegmentStats>, units: Units): List<String> {
        // Prefer climbs and descents; flat sections only when there is room.
        val important = segments.filter { it.type != "FLAT" }
        val chosen = (if (important.size >= 2) important else segments).take(MAX_SEGMENT_LINES)
        return chosen.map { seg ->
            val arrow = when (seg.type) {
                "CLIMB" -> "⬆️"
                "DESCENT" -> "⬇️"
                else -> "➡️"
            }
            val elev = when (seg.type) {
                "CLIMB" -> "+${units.elevation(seg.elevGainM)}"
                "DESCENT" -> "−${units.elevation(seg.elevLossM)}"
                else -> fmt("%.0f%%", seg.avgGradePct)
            }
            val jumps = if (seg.jumps > 0) " · ${seg.jumps} jump${if (seg.jumps == 1) "" else "s"}" else ""
            val focus = if (seg.type == "DESCENT") fmt("Flow %.1f · brake %.0f%%", seg.flowScore, seg.brakingPct) else fmt("Grit %.1f", seg.gritK)
            val bike = when {
                seg.type == "CLIMB" && seg.avgPowerW != null -> fmt(" · %.0f W", seg.avgPowerW)
                seg.type == "DESCENT" && seg.faOpenPct != null -> fmt(" · FA %.0f%% open", seg.faOpenPct)
                else -> ""
            }
            "$arrow ${seg.name}: ${units.distance(seg.distanceM)} · $elev · ${duration(seg.durationSec)} · $focus$bike$jumps"
        }
    }

    private fun lapLines(laps: List<SegmentStats>, units: Units): List<String> = laps.take(8).map { lap ->
        "• ${lap.name}: ${units.distance(lap.distanceM)} · ${duration(lap.durationSec)} · " +
            fmt("Grit %.1f · Flow %.1f", lap.gritK, lap.flowScore) +
            (if (lap.jumps > 0) " · ${lap.jumps} jumps" else "")
    }

    private fun footer(s: RideSummary, units: Units): String =
        "⏱ ${duration(s.elapsedSec)} (moving ${duration(s.movingSec)}) · 📏 ${units.distance(s.distanceM)} · ↗ ${units.elevation(s.ascentM)}" +
            " · ⚡ ${units.speed(s.avgSpeedMs)} avg"
}
