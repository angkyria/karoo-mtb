package io.github.angkyria.karoomtb.engine

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.max

/**
 * Scoring.kt and the Python analyser must compute the same numbers. Both test suites read
 * testdata/scoring_vectors.json, which tools/make_scoring_vectors.py writes from the analyser.
 */
class ScoringParityTest {
    private val vectors: JsonObject by lazy {
        val file = listOf("../testdata/scoring_vectors.json", "testdata/scoring_vectors.json").map(::File).first { it.isFile }
        Json.parseToJsonElement(file.readText()).jsonObject
    }

    private fun JsonElement.num(): Double = if (this is JsonNull) Double.NaN else jsonPrimitive.double

    private fun evaluate(fn: String, a: List<Double>): Double = when (fn) {
        "gritPerSecond" -> Scoring.gritPerSecond(a[0], a[1], a[2])
        "brakingDecel" -> Scoring.brakingDecel(a[0], a[1], a[2])
        "brakeWeight" -> Scoring.brakeWeight(a[0])
        "brakingNecessity" -> Scoring.brakingNecessity(a[0], a[1], a[2], a[3])
        "flowScore" -> Scoring.flowScore(a[0], a[1])
        "difficultyScore" -> Scoring.difficultyScore(a[0])
        "smoothnessScore" -> Scoring.smoothnessScore(a[0])
        "airScore" -> Scoring.airScore(a[0])
        "mtbScore" -> Scoring.mtbScore(a[0], a[1], a[2])
        "jumpHeight" -> Scoring.jumpHeight(a[0], a[1])
        else -> error("unknown function $fn in scoring_vectors.json")
    }

    @Test
    fun `formulas match the analyser`() {
        val cases = vectors.getValue("cases") as JsonArray
        assertTrue(cases.size > 500)
        for (case in cases.map { it.jsonObject }) {
            val fn = case.getValue("fn").jsonPrimitive.content
            val args = case.getValue("args").jsonArray.map { it.num() }
            val expected = case.getValue("expected").num()
            val got = evaluate(fn, args)
            val tolerance = max(1e-12, 1e-9 * abs(expected))
            assertTrue("$fn$args = $got, analyser says $expected", abs(got - expected) <= tolerance)
        }
    }

    @Test
    fun `constants match the analyser`() {
        val c = vectors.getValue("constants").jsonObject.mapValues { it.value.num() }
        val config = MtbConfig()
        val mine = mapOf(
            "G" to Scoring.G, "MOVING_SPEED" to Scoring.MOVING_SPEED, "GRIT_SCALE" to Scoring.GRIT_SCALE,
            "GRIT_W_GRADE" to Scoring.GRIT_W_GRADE, "GRIT_W_TURN" to Scoring.GRIT_W_TURN, "GRIT_W_ROUGH" to Scoring.GRIT_W_ROUGH,
            "CRR" to Scoring.CRR, "AIR_K" to Scoring.AIR_K, "BRAKE_MIN" to Scoring.BRAKE_MIN, "BRAKE_FULL" to Scoring.BRAKE_FULL,
            "BRAKING_THRESHOLD" to Scoring.BRAKING_THRESHOLD, "DESCENT_GRADE" to Scoring.DESCENT_GRADE,
            "MAX_LATERAL_G" to Scoring.MAX_LATERAL_G, "FLOW_LAG" to config.flowLagSec.toDouble(),
            "JUMP_LAND_G" to config.jumpLandG, "JUMP_MAX_AIR" to config.jumpMaxAirSec, "JUMP_MAX_MEAN_AIR_G" to config.jumpMaxMeanAirG,
            "JUMP_GLITCH" to JumpDetector.GLITCH_SEC, "JUMP_LANDING_WINDOW" to JumpDetector.LANDING_WINDOW_SEC,
            "JUMP_COOLDOWN" to JumpDetector.COOLDOWN_SEC, "JUMP_MIN_SPEED" to config.jumpMinSpeed,
        )
        assertEquals(c.keys, mine.keys)
        for ((key, value) in mine) assertEquals(key, c.getValue(key), value, 0.0)
    }

    @Test
    fun `jump presets match the analyser`() {
        val presets = vectors.getValue("presets").jsonObject
        assertEquals(Sensitivity.entries.map { it.name }.toSet(), presets.keys)
        for (s in Sensitivity.entries) {
            val p = presets.getValue(s.name).jsonObject
            assertEquals(s.name, p.getValue("takeoffG").num(), s.takeoffG, 0.0)
            assertEquals(s.name, p.getValue("minAirSec").num(), s.minAirSec, 0.0)
            assertEquals(s.name, p.getValue("minLandingG").num(), s.minLandingG, 0.0)
        }
    }
}
