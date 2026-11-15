package io.github.angkyria.karoomtb.engine

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.util.Locale

/**
 * The private label corpus (`./gradlew testDebugUnitTest -Pcorpus=~/karoo-mtb-corpus`) through the real
 * detector: the presets in MtbConfig must be the ones `mtb_analyze.py --fit` proposed, every clip must get
 * the verdict the Python fit computed, and each preset must meet its precision target. Skipped without -Pcorpus.
 */
class CorpusPrecisionTest {
    @Test
    fun `presets meet their precision targets on the corpus and match the Python fit`() {
        val dir = System.getProperty("mtb.corpus").orEmpty().replaceFirst("~", System.getProperty("user.home"))
        assumeTrue("no -Pcorpus", dir.isNotBlank() && File(dir, "fit-result.json").exists())
        val result = Json.parseToJsonElement(File(dir, "fit-result.json").readText()).jsonObject
        val problems = ArrayList<String>()
        val proposed = result.getValue("proposed").jsonObject
        for (s in Sensitivity.entries) {
            val p = proposed.getValue(s.name).jsonObject
            val want = Triple(p.d("takeoffG"), p.d("minAirSec"), p.d("minLandingG"))
            val have = Triple(s.takeoffG, s.minAirSec, s.minLandingG)
            if (want != have) problems += "$s in MtbConfig is $have, the fit proposed $want"
        }
        val mean = result.getValue("jumpMaxMeanAirG").jsonPrimitive.double
        if (mean != MtbConfig().jumpMaxMeanAirG) problems += "jumpMaxMeanAirG is ${MtbConfig().jumpMaxMeanAirG}, the fit proposed $mean"
        assertTrue(problems.joinToString("\n"), problems.isEmpty())

        val targets = result.getValue("targets").jsonObject
        val clips = result.getValue("clips").jsonArray.map { it.jsonObject }
        for (s in Sensitivity.entries) {
            val config = MtbConfig(sensitivity = s)
            var tp = 0.0
            var fp = 0.0
            for (c in clips) {
                val file = c.getValue("file").jsonPrimitive.content
                val speed = c["speed"]?.jsonPrimitive?.doubleOrNull
                val hit = ImuReplay.flights(File(dir, file).readText(), config).isNotEmpty() && (speed == null || speed >= config.jumpMinSpeed)
                val python = c.getValue("verdicts").jsonObject.getValue(s.name).jsonPrimitive.boolean
                if (hit != python) problems += "$file at $s: Kotlin ${if (hit) "jump" else "no jump"}, Python ${if (python) "jump" else "no jump"}"
                val w = c.getValue("weight").jsonPrimitive.double
                if (hit && c.getValue("label").jsonPrimitive.content == "jump") tp += w else if (hit) fp += w
            }
            val precision = if (tp + fp > 0) tp / (tp + fp) else 1.0
            val target = targets.getValue(s.name).jsonPrimitive.double
            if (precision + 1e-9 < target) problems += "$s precision ${String.format(Locale.ROOT, "%.3f", precision)} < $target"
        }
        println("CorpusPrecisionTest: ${clips.size} clips")
        assertTrue(problems.joinToString("\n"), problems.isEmpty())
    }

    private fun kotlinx.serialization.json.JsonObject.d(key: String) = getValue(key).jsonPrimitive.double
}
