package io.github.angkyria.karoomtb.engine

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Replays the IMU snippets in src/test/resources/imu through ImuProcessor + JumpDetector, the
 * way the Karoo runs them. Real snippets come from `mtb_analyze.py --karoo-dir RIDE --imu
 * --export-snippets app/src/test/resources/imu` (labelled with the "Mark moment" button or a
 * labels file); a snippet the detector gets wrong fails the build until the thresholds are tuned
 * (or it is marked "knownFailure": true in manifest.json while working on it).
 */
class JumpFixtureTest {
    internal data class Fixture(val file: String, val expect: Map<Sensitivity, Boolean>, val knownFailure: Boolean)

    /** 'expect' per preset, or the older 'expectJump' at 'preset' (default MEDIUM). */
    internal fun parseFixture(o: JsonObject): Fixture {
        val expect =
            o["expect"]?.jsonObject?.entries?.associate { (k, v) -> Sensitivity.valueOf(k) to v.jsonPrimitive.boolean }
                ?: mapOf(
                    (o["preset"]?.jsonPrimitive?.content?.let { Sensitivity.valueOf(it) } ?: Sensitivity.MEDIUM) to
                        o.getValue("expectJump").jsonPrimitive.boolean,
                )
        return Fixture(o.getValue("file").jsonPrimitive.content, expect, o["knownFailure"]?.jsonPrimitive?.booleanOrNull ?: false)
    }

    internal fun parseFixture(json: String): Fixture = parseFixture(Json.parseToJsonElement(json).jsonObject)

    private fun fixtures(): List<Fixture> {
        val manifest = javaClass.getResource("/imu/manifest.json") ?: return emptyList()
        val root = Json.parseToJsonElement(manifest.readText()).jsonObject
        return root.getValue("fixtures").jsonArray.map { parseFixture(it.jsonObject) }
    }

    @Test
    fun `every IMU snippet is detected as labelled`() {
        val all = fixtures()
        assertTrue("no fixtures in src/test/resources/imu", all.isNotEmpty())
        val wrong = ArrayList<String>()
        var tp = 0
        var fp = 0
        var fn = 0
        for (f in all) {
            val text = javaClass.getResource("/imu/${f.file}")?.readText() ?: error("missing fixture ${f.file}")
            for ((preset, expectJump) in f.expect) {
                val detected = ImuReplay.flights(text, MtbConfig(sensitivity = preset)).isNotEmpty()
                when {
                    detected && expectJump -> tp++
                    detected && !expectJump -> fp++
                    !detected && expectJump -> fn++
                }
                if (detected != expectJump && !f.knownFailure) {
                    wrong += "${f.file}: expected ${if (expectJump) "a jump" else "no jump"} at $preset"
                }
            }
        }
        println("JumpFixtureTest: ${all.size} snippets, $tp jumps found, $fn missed, $fp false")
        assertTrue(wrong.joinToString("\n"), wrong.isEmpty())
    }

    @Test
    fun `manifest expect map overrides expectJump per preset`() {
        val f = parseFixture("""{"file":"x.csv","expect":{"LOW":false,"MEDIUM":false,"HIGH":true}}""")
        assertEquals(mapOf(Sensitivity.LOW to false, Sensitivity.MEDIUM to false, Sensitivity.HIGH to true), f.expect)
        val old = parseFixture("""{"file":"y.csv","expectJump":true}""")
        assertEquals(mapOf(Sensitivity.MEDIUM to true), old.expect)
        val atHigh = parseFixture("""{"file":"z.csv","expectJump":false,"preset":"HIGH"}""")
        assertEquals(mapOf(Sensitivity.HIGH to false), atHigh.expect)
    }
}
