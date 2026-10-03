package io.github.angkyria.karoomtb.fit

import io.github.angkyria.karoomtb.engine.RecordValues
import io.github.angkyria.karoomtb.engine.SessionValues
import io.hammerhead.karooext.models.DeveloperField
import io.hammerhead.karooext.models.FieldValue
import io.hammerhead.karooext.models.WriteToRecordMesg
import io.hammerhead.karooext.models.WriteToSessionMesg

/**
 * FIT output. Every value is written as a developer field named `mtb_*` (what intervals.icu
 * custom streams / fields read). Optionally the same values also go into Garmin's native MTB
 * fields so Garmin Connect, GoldenCheetah & co. show Grit/Flow/Jumps natively.
 *
 * Developer field numbers must start at 0 and increase by 1 (karoo-ext requirement).
 */
object MtbFitFields {
    private const val FLOAT32: Short = 136
    private const val UINT16: Short = 132
    private const val UINT8: Short = 2

    private var next = 0
    private fun field(name: String, units: String, type: Short = FLOAT32): DeveloperField =
        DeveloperField(fieldDefinitionNumber = (next++).toShort(), fitBaseTypeId = type, fieldName = name, units = units)

    // ---- Record message, 1 Hz ----
    val GRIT = field("mtb_grit", "grit")
    val FLOW = field("mtb_flow", "m")
    val ROUGH = field("mtb_rough", "g")
    val LAT_G = field("mtb_lat_g", "g")
    val BRAKE = field("mtb_brake", "m/s2")
    val JUMP_AIR = field("mtb_jump_air", "s")
    val JUMP_DIST = field("mtb_jump_dist", "m")
    val JUMP_HEIGHT = field("mtb_jump_height", "m")

    // ---- Session message ----
    val TOTAL_GRIT = field("mtb_total_grit", "kGrit")
    val AVG_GRIT = field("mtb_avg_grit", "grit/s")
    val FLOW_SCORE = field("mtb_flow_score", "flow")
    val TOTAL_FLOW = field("mtb_total_flow", "m")
    val JUMPS = field("mtb_jumps", "jumps", UINT16)
    val MAX_AIR = field("mtb_max_air", "s")
    val TOTAL_AIR = field("mtb_total_air", "s")
    val MAX_JUMP_DIST = field("mtb_max_jump_dist", "m")
    val MAX_JUMP_HEIGHT = field("mtb_max_jump_height", "m")
    val SCORE = field("mtb_score", "score")
    val DIFFICULTY = field("mtb_difficulty", "score")
    val SMOOTHNESS = field("mtb_smoothness", "score")
    val AIR_SCORE = field("mtb_air_score", "score")
    val CORNERS = field("mtb_corners", "corners", UINT16)
    val MAX_LAT_G = field("mtb_max_lat_g", "g")
    val CORNER_SPEED_KEPT = field("mtb_corner_speed_kept", "%")
    val DESCENT_TIME = field("mtb_descent_time", "s")
    val DESCENT_BRAKING = field("mtb_descent_braking", "%")
    val DESCENT_SPEED = field("mtb_descent_speed", "m/s")
    val DESCENT_FLOW = field("mtb_descent_flow", "flow")
    val AVG_ROUGH = field("mtb_avg_rough", "g")
    val FLOW_LAG = field("mtb_flow_lag", "s", UINT8)

    // ---- Session: RockShox Flight Attendant / SRAM AXS / power meter (only when paired) ----
    val FA_OPEN_DESCENT = field("mtb_fa_open_desc", "%")
    val FA_LOCK_ROUGH = field("mtb_fa_lock_rough", "s")
    val FA_OPEN_CLIMB = field("mtb_fa_open_climb", "s")
    val FA_CHANGES = field("mtb_fa_changes", "changes", UINT16)
    val SHIFTS = field("mtb_shifts", "shifts", UINT16)
    val SHIFTS_KM = field("mtb_shifts_km", "/km")
    val CLIMB_POWER = field("mtb_climb_power", "W")
    val CLIMB_WKG = field("mtb_climb_wkg", "W/kg")
    val DESCENT_PEDAL = field("mtb_desc_pedal", "%")
    val COG_MAX = field("mtb_cog_max", "T", UINT8)
    val FA_REACTION = field("mtb_fa_reaction", "s")

    // Native FIT profile field numbers (Garmin MTB Dynamics).
    private const val RECORD_GRIT = 114
    private const val RECORD_FLOW = 115
    private const val SESSION_TOTAL_GRIT = 181
    private const val SESSION_TOTAL_FLOW = 182
    private const val SESSION_JUMP_COUNT = 183
    private const val SESSION_AVG_GRIT = 186
    private const val SESSION_AVG_FLOW = 187

    fun record(v: RecordValues, native: Boolean): WriteToRecordMesg {
        val values = mutableListOf(
            FieldValue(GRIT, v.grit),
            FieldValue(FLOW, v.flow),
            FieldValue(ROUGH, v.rough ?: 0.0),
            FieldValue(LAT_G, v.latG),
            FieldValue(BRAKE, v.brake),
            FieldValue(JUMP_AIR, v.jumpAir),
            FieldValue(JUMP_DIST, v.jumpDistance),
            FieldValue(JUMP_HEIGHT, v.jumpHeight),
        )
        if (native) {
            values += FieldValue(RECORD_GRIT, v.grit)
            values += FieldValue(RECORD_FLOW, v.flow)
        }
        return WriteToRecordMesg(values)
    }

    fun session(v: SessionValues, native: Boolean): WriteToSessionMesg {
        val values = mutableListOf(
            FieldValue(TOTAL_GRIT, v.totalGritK),
            FieldValue(AVG_GRIT, v.avgGrit),
            FieldValue(FLOW_SCORE, v.flowScore),
            FieldValue(TOTAL_FLOW, v.totalFlowM),
            FieldValue(JUMPS, v.jumps.toDouble()),
            FieldValue(MAX_AIR, v.maxAirSec),
            FieldValue(TOTAL_AIR, v.totalAirSec),
            FieldValue(MAX_JUMP_DIST, v.maxJumpDistanceM),
            FieldValue(MAX_JUMP_HEIGHT, v.maxJumpHeightM),
            FieldValue(SCORE, v.score),
            FieldValue(DIFFICULTY, v.difficulty),
            FieldValue(SMOOTHNESS, v.smoothness),
            FieldValue(AIR_SCORE, v.airScore),
            FieldValue(CORNERS, v.corners.toDouble()),
            FieldValue(MAX_LAT_G, v.maxLateralG),
            FieldValue(CORNER_SPEED_KEPT, v.cornerSpeedKeptPct),
            FieldValue(DESCENT_TIME, v.descentSec),
            FieldValue(DESCENT_BRAKING, v.descentBrakingPct),
            FieldValue(DESCENT_SPEED, v.descentAvgSpeed),
            FieldValue(DESCENT_FLOW, v.descentFlow),
            FieldValue(AVG_ROUGH, v.avgRough),
            FieldValue(FLOW_LAG, v.flowLagSec.toDouble()),
        )
        fun optional(field: DeveloperField, value: Double?) {
            if (value != null && !value.isNaN()) values += FieldValue(field, value)
        }
        optional(FA_OPEN_DESCENT, v.faOpenDescentPct)
        optional(FA_LOCK_ROUGH, v.faLockedRoughSec)
        optional(FA_OPEN_CLIMB, v.faOpenHardClimbSec)
        optional(FA_CHANGES, v.faChanges?.toDouble())
        optional(SHIFTS, v.shifts?.toDouble())
        optional(SHIFTS_KM, v.shiftsPerKm)
        optional(CLIMB_POWER, v.climbPowerW)
        optional(CLIMB_WKG, v.climbWattsPerKg)
        optional(DESCENT_PEDAL, v.descentPedallingPct)
        optional(COG_MAX, v.largestCogTeeth?.toDouble())
        optional(FA_REACTION, v.faReactionSec)
        if (native) {
            values += FieldValue(SESSION_TOTAL_GRIT, v.totalGritK)
            values += FieldValue(SESSION_TOTAL_FLOW, v.totalFlowM)
            values += FieldValue(SESSION_JUMP_COUNT, v.jumps.toDouble())
            values += FieldValue(SESSION_AVG_GRIT, v.avgGrit)
            values += FieldValue(SESSION_AVG_FLOW, v.flowScore)
        }
        return WriteToSessionMesg(values)
    }
}
