package io.github.angkyria.karoomtb.engine

import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale
import kotlin.math.sin

/**
 * Synthetic rides of known character, printed as a table (see the test report's stdout) so
 * the scales can be checked against the targets documented in Scoring.kt / README.
 */
class CalibrationTest {
    private data class Row(val name: String, val s: RideSummary)

    private fun ride(name: String, minutes: Int, block: RideSim.() -> Unit): Row {
        val sim = RideSim(seed = name.hashCode().toLong()).apply { start() }
        repeat(minutes) { sim.block() }
        return Row(name, sim.finish())
    }

    @Test
    fun `typical rides land in Garmin-like ranges`() {
        val rows = listOf(
            // Gravel road: smooth, gentle, few turns.
            ride("gravel 60 min", 60) { ride(60, speed = { 7.0 }, grade = { 3.0 * sin(it / 10.0) }, vibrationG = 0.15) },
            // Flowy trail: moderate grade, regular turns, light braking.
            ride("flow trail 90 min", 90) {
                ride(
                    60, speed = { if (it % 15 == 7) 4.5 else 6.0 }, grade = { -6.0 + 8.0 * sin(it / 7.0) },
                    yawRate = { 0.5 * sin(it / 3.0) }, vibrationG = 0.3,
                )
            },
            // Technical: steep, rough, tight switchbacks, lots of braking.
            ride("technical 120 min", 120) {
                jumpIn(20.0, 0.5)
                ride(
                    60, speed = { if (it % 8 < 2) 2.5 else 5.0 }, grade = { if (it % 30 < 15) 14.0 else -16.0 },
                    yawRate = { if (it % 8 < 3) 1.0 else -0.4 }, vibrationG = 0.55,
                )
            },
        )
        println(String.format(Locale.ROOT, "%-20s %8s %8s %7s %6s %6s %6s %6s", "ride", "kGrit", "grit/s", "flow", "jumps", "rough", "score", "diff"))
        for (r in rows) {
            println(
                String.format(
                    Locale.ROOT, "%-20s %8.1f %8.2f %7.2f %6d %6.2f %6.0f %6.0f",
                    r.name, r.s.grit.totalK, r.s.grit.avgPerSec, r.s.flow.score, r.s.jumps.count,
                    r.s.roughnessAvg ?: 0.0, r.s.score.total, r.s.score.difficulty,
                ),
            )
        }
        val (gravel, flow, technical) = rows.map { it.s }
        assertTrue(gravel.grit.totalK < 20.0)
        assertTrue(flow.grit.totalK in 15.0..45.0)
        assertTrue(technical.grit.totalK > 45.0)
        assertTrue(gravel.score.difficulty < flow.score.difficulty && flow.score.difficulty < technical.score.difficulty)
        assertTrue(technical.jumps.count >= 100)
    }
}
