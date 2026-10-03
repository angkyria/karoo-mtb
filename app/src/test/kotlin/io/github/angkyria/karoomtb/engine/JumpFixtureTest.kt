package io.github.angkyria.karoomtb.engine

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
    private data class Fixture(val file: String, val expectJump: Boolean, val preset: Sensitivity, val knownFailure: Boolean)

    private fun fixtures(): List<Fixture> {
        val manifest = javaClass.getResource("/imu/manifest.json") ?: return emptyList()
        val root = Json.parseToJsonElement(manifest.readText()).jsonObject
        return root.getValue("fixtures").jsonArray.map { e ->
            val o = e.jsonObject
            Fixture(
                file = o.getValue("file").jsonPrimitive.content,
                expectJump = o.getValue("expectJump").jsonPrimitive.boolean,
                preset = o["preset"]?.jsonPrimitive?.content?.let { Sensitivity.valueOf(it) } ?: Sensitivity.MEDIUM,
                knownFailure = o["knownFailure"]?.jsonPrimitive?.booleanOrNull ?: false,
            )
        }
    }

    /** Flights the detector accepts in one snippet. */
    private fun replay(f: Fixture): List<RawJump> {
        val text = javaClass.getResource("/imu/${f.file}")?.readText() ?: error("missing fixture ${f.file}")
        val imu = ImuProcessor()
        val detector = JumpDetector(MtbConfig(sensitivity = f.preset))
        val jumps = ArrayList<RawJump>()
        for (line in text.lineSequence()) {
            if (line.isBlank() || line.startsWith("#") || line.startsWith("sensor")) continue
            val c = line.split(',')
            val t = c[1].toDouble() / 1000.0
            val x = c[2].toDouble()
            val y = c[3].toDouble()
            val z = c[4].toDouble()
            when (c[0]) {
                "a" -> {
                    val air = detector.airborne
                    imu.onAccel(t, x, y, z, freezeGravity = air, countRoughness = !air)
                    detector.onAccel(t, imu.magLpG, imu.magG)?.let { jumps += it }
                }
                "g" -> detector.onGyro(t, x, y, z)
            }
        }
        return jumps
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
            val detected = replay(f).isNotEmpty()
            when {
                detected && f.expectJump -> tp++
                detected && !f.expectJump -> fp++
                !detected && f.expectJump -> fn++
            }
            if (detected != f.expectJump && !f.knownFailure) {
                wrong += "${f.file}: expected ${if (f.expectJump) "a jump" else "no jump"} at ${f.preset}"
            }
        }
        println("JumpFixtureTest: ${all.size} snippets, $tp jumps found, $fn missed, $fp false")
        assertTrue(wrong.joinToString("\n"), wrong.isEmpty())
    }
}
