package io.github.angkyria.karoomtb.karoo

import io.github.angkyria.karoomtb.engine.FaState
import io.github.angkyria.karoomtb.engine.LiveMetrics
import io.github.angkyria.karoomtb.notify.Units

/**
 * The cells a graphical panel field can show. Riders pick 4 (or 6, for tall fields) per panel in
 * the settings; the Descent cells show the descent in progress, else the last one.
 */
enum class PanelCell(val label: String, val title: String) {
    GRIT("GRIT", "Grit (ride, kGrit)"),
    GRIT_60("GRIT 60S", "Grit 60 s"),
    GRIT_LAP("LAP GRIT", "Lap Grit"),
    FLOW("FLOW", "Flow (ride)"),
    FLOW_60("FLOW 60S", "Flow 60 s"),
    FLOW_LAP("LAP FLOW", "Lap Flow"),
    SCORE("SCORE", "MTB score"),
    JUMPS("JUMPS", "Jumps"),
    AIR("AIR", "Last airtime"),
    MAX_AIR("MAX AIR", "Max airtime"),
    JUMP_DIST("JUMP", "Last jump distance"),
    CORNERS("CORNERS", "Corners"),
    CORNER_G("CORNER G", "Lateral g now"),
    MAX_G("MAX G", "Max lateral g"),
    ROUGH("ROUGH", "Roughness (60 s)"),
    ROUGH_NOW("ROUGH", "Roughness now (5 s)"),
    DESCENT_BRAKE("DESC BRAKE", "Braking on descents (ride)"),
    D_TIME("TIME", "Descent: time"),
    D_DROP("DROP", "Descent: drop"),
    D_FLOW("D FLOW", "Descent: Flow"),
    D_BRAKE("BRAKE", "Descent: braking"),
    D_JUMPS("D JUMPS", "Descent: jumps"),
    D_SPEED("SPEED", "Descent: average speed"),
    SUSPENSION("SUSPENSION", "Flight Attendant state"),
    COG("COG", "Rear cog"),
    GEARS_LEFT("GEARS LEFT", "Easier gears left"),
    POWER("POWER", "Power"),
    FA_OPEN("FA OPEN", "Fork open on descents"),
    SHIFTS("SHIFTS", "Shifts"),
    ;

    fun value(live: LiveMetrics, units: Units): String {
        val d = live.descent
        val last = live.lastDescent
        return when (this) {
            GRIT -> fmt("%.1f", live.gritTotalK)
            GRIT_60 -> fmt("%.1f", live.grit60)
            GRIT_LAP -> fmt("%.1f", live.gritLapK)
            FLOW -> fmt("%.1f", live.flowScore)
            FLOW_60 -> fmt("%.1f", live.flow60)
            FLOW_LAP -> fmt("%.1f", live.flowLap)
            SCORE -> fmt("%.0f", live.mtbScore)
            JUMPS -> live.jumpCount.toString()
            AIR -> live.lastJump?.let { fmt("%.2f s", it.airSec) } ?: NONE
            MAX_AIR -> if (live.jumpCount > 0) fmt("%.2f s", live.maxAirSec) else NONE
            JUMP_DIST -> live.lastJump?.let { units.meters(it.distanceM) } ?: NONE
            CORNERS -> live.cornerCount.toString()
            CORNER_G -> fmt("%.2f g", live.latG)
            MAX_G -> fmt("%.2f g", live.maxLatG)
            ROUGH -> live.rough60?.let { fmt("%.2f g", it) } ?: NONE
            ROUGH_NOW -> live.roughNow?.let { fmt("%.2f g", it) } ?: NONE
            DESCENT_BRAKE -> fmt("%.0f%%", live.descentBrakingPct)
            D_TIME -> (d?.timeSec ?: last?.durationSec)?.let { Units.duration(it) } ?: NONE
            D_DROP -> (d?.dropM ?: last?.elevLossM)?.let { units.elevation(it) } ?: NONE
            D_FLOW -> (d?.flowScore ?: last?.flowScore)?.let { fmt("%.1f", it) } ?: NONE
            D_BRAKE -> (d?.brakingPct ?: last?.brakingPct)?.let { fmt("%.0f%%", it) } ?: NONE
            D_JUMPS -> (d?.jumps ?: last?.jumps)?.toString() ?: NONE
            D_SPEED -> (d?.avgSpeedMs ?: last?.avgSpeedMs)?.let { units.speed(it) } ?: NONE
            SUSPENSION -> if (live.faFront >= 0) FaState.name(live.faFront).uppercase() else NONE
            COG -> if (live.rearTeeth > 0) "${live.rearTeeth}T" else NONE
            GEARS_LEFT -> if (live.easierGearsLeft >= 0) live.easierGearsLeft.toString() else NONE
            POWER -> live.power?.let { "${it.toInt()} W" } ?: NONE
            FA_OPEN -> live.faOpenDescentPct?.let { fmt("%.0f%%", it) } ?: NONE
            SHIFTS -> live.shifts.toString()
        }
    }

    companion object {
        const val NONE = "–"
        private fun fmt(pattern: String, value: Double) = MtbDataTypes.fmt(pattern, value)

        /** Parses a stored list ("GRIT,FLOW,..."); unknown names fall back to the defaults. */
        fun parse(stored: String?, defaults: List<PanelCell>): List<PanelCell> {
            val cells = stored?.split(',')?.mapNotNull { name -> entries.firstOrNull { it.name == name.trim() } }.orEmpty()
            return if (cells.size == defaults.size) cells else defaults
        }
    }
}

/** A configurable graphical panel: 4 cells, plus 2 more when the field is tall. */
enum class Panel(val typeId: String, val title: String, val defaults: List<PanelCell>) {
    MTB(
        "panel", "MTB Dynamics",
        listOf(PanelCell.GRIT, PanelCell.FLOW, PanelCell.JUMPS, PanelCell.AIR, PanelCell.SCORE, PanelCell.CORNERS),
    ),
    BIKE(
        "bike-panel", "Bike Systems",
        listOf(PanelCell.SUSPENSION, PanelCell.COG, PanelCell.POWER, PanelCell.ROUGH_NOW, PanelCell.GEARS_LEFT, PanelCell.FA_OPEN),
    ),
    DESCENT(
        "descent-panel", "Descent",
        listOf(PanelCell.D_TIME, PanelCell.D_DROP, PanelCell.D_FLOW, PanelCell.D_BRAKE, PanelCell.D_JUMPS, PanelCell.D_SPEED),
    ),
    ;

    /** Header line, or null for panels without one. */
    fun header(live: LiveMetrics): String? = when (this) {
        DESCENT -> live.descent?.let { "DESCENT ${it.number}" } ?: live.lastDescent?.let { "LAST: ${it.name.uppercase()}" } ?: "DESCENT"
        else -> null
    }

    companion object {
        const val CELLS = 6

        /** Six cells fit when the field is about as tall as it is wide and not tiny. */
        fun useSixCells(widthPx: Int, heightPx: Int): Boolean = heightPx >= 300 && heightPx >= widthPx * 0.75
    }
}
