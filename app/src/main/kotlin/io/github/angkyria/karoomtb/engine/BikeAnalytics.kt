package io.github.angkyria.karoomtb.engine

import kotlin.math.PI

/**
 * Analytics for the bike's systems, joined with MTB Dynamics terrain data:
 * RockShox Flight Attendant (suspension state), SRAM AXS (gears / shifts) and the power meter.
 * Mirrors the SRAM section of tools/mtb_analyze.py.
 */
object BikeAnalytics {
    /** Lock on ground at least this rough (g) is a harsh ride. */
    const val LOCKED_ROUGH_G = 0.9

    /** Open while pushing this hard (W) uphill wastes energy. */
    const val HARD_CLIMB_W = 200.0
    const val CLIMB_GRADE = 2.0

    /** A shift at this power (W) or more counts as "under load". */
    const val UNDER_LOAD_W = 250.0
    const val STEEP_GRADE = 6.0

    /** Ground at least this rough (g) counts as hard suspension work in the service tracker. */
    const val SERVICE_ROUGH_G = 0.6

    const val CLIMB = "CLIMB"
    const val DESCENT = "DESCENT"
    const val FLAT = "FLAT"

    /** Terrain type per sample index from the climb / descent segmentation. */
    fun terrain(samples: List<SecondSample>, ranges: List<Segmenter.Range>): Array<String> {
        val kinds = Array(samples.size) { FLAT }
        for (r in ranges) for (i in r.start..minOf(r.end, samples.lastIndex)) kinds[i] = r.type
        return kinds
    }

    fun shares(states: List<Int>): StateShare? {
        if (states.isEmpty()) return null
        val n = states.size.toDouble()
        return StateShare(
            open = 100.0 * states.count { it == FaState.OPEN } / n,
            pedal = 100.0 * states.count { it == FaState.PEDAL } / n,
            lock = 100.0 * states.count { it == FaState.LOCK } / n,
        )
    }

    fun suspension(
        samples: List<SecondSample>,
        terrain: Array<String>,
        ranges: List<Segmenter.Range>,
        mode: Int?,
        bias: Int?,
    ): SuspensionStats? {
        val idx = samples.indices.filter { samples[it].moving && samples[it].faFront >= 0 }
        if (idx.isEmpty()) return null
        fun sharesOf(kind: String) = shares(idx.filter { terrain[it] == kind }.map { samples[it].faFront })
        var changes = 0
        var previous = -1
        for (s in samples) {
            if (s.faFront < 0) continue
            if (previous >= 0 && s.faFront != previous) changes++
            previous = s.faFront
        }
        val reactions = ArrayList<Double>()
        val descents = ranges.filter { it.type == DESCENT }
        for (r in descents) {
            val start = samples[r.start]
            val open = (r.start..r.end).firstOrNull { samples[it].faFront == FaState.OPEN } ?: continue
            reactions += (samples[open].wallMs - start.wallMs) / 1000.0
        }
        val zones = idx.map { samples[it] }.filter { it.effortZone >= 0 }.groupBy { it.effortZone }.toSortedMap()
        val km = samples.sumOf { it.dDist } / 1000.0
        return SuspensionStats(
            overall = shares(idx.map { samples[it].faFront })!!,
            climbs = sharesOf(CLIMB),
            descents = sharesOf(DESCENT),
            flats = sharesOf(FLAT),
            lockedRoughSec = idx.map { samples[it] }
                .filter { it.faFront == FaState.LOCK && !it.rough.isNaN() && it.rough >= LOCKED_ROUGH_G }.sumOf { it.dt },
            openHardClimbSec = idx.map { samples[it] }
                .filter { it.faFront == FaState.OPEN && !it.power.isNaN() && it.power >= HARD_CLIMB_W && it.grade >= CLIMB_GRADE }
                .sumOf { it.dt },
            forkShockDifferSec = idx.map { samples[it] }.filter { it.faRear >= 0 && it.faRear != it.faFront }.sumOf { it.dt },
            changes = changes,
            changesPerKm = if (km > 0.1) changes / km else 0.0,
            descentsReachingOpen = reactions.size,
            descentCount = descents.size,
            reactionSecMedian = reactions.sorted().getOrNull(reactions.size / 2),
            effortZones = zones.map { (zone, list) ->
                EffortZoneStat(zone, list.sumOf { it.dt } / 60.0, list.map { it.power }.filter { !it.isNaN() }.averageOrNull())
            },
            mode = mode,
            bias = bias,
            trackedSec = idx.sumOf { samples[it].dt },
            rearTrackedSec = samples.filter { it.moving && it.faRear >= 0 }.sumOf { it.dt },
            roughSec = idx.map { samples[it] }.filter { !it.rough.isNaN() && it.rough >= SERVICE_ROUGH_G }.sumOf { it.dt },
        )
    }

    fun drivetrain(
        samples: List<SecondSample>,
        terrain: Array<String>,
        ranges: List<Segmenter.Range>,
        shifts: List<Shift>,
    ): DrivetrainStats? {
        val idx = samples.indices.filter { samples[it].moving && samples[it].rearTeeth > 0 }
        if (idx.isEmpty() && shifts.isEmpty()) return null
        val cogSeconds = HashMap<Int, Double>()
        for (i in idx) cogSeconds[samples[i].rearTeeth] = (cogSeconds[samples[i].rearTeeth] ?: 0.0) + samples[i].dt
        val used = cogSeconds.filterValues { it >= 10.0 }.keys.sorted()
        fun medianCog(kind: String) = idx.filter { terrain[it] == kind }.map { samples[it].rearTeeth }.sorted()
            .let { it.getOrNull(it.size / 2) }
        // Easier shifts in the 15 s before a climb starts vs. its first 30 s (anticipation).
        var before = 0
        var after = 0
        for (r in ranges.filter { it.type == CLIMB }) {
            val startOffset = samples[r.start].wallMs
            for (sh in shifts.filter { it.easier }) {
                when (sh.wallMs - startOffset) {
                    in -15_000L until 0L -> before++
                    in 0L until 30_000L -> after++
                }
            }
        }
        val largestUsedGear = idx.map { samples[it].rearGear }.filter { it > 0 }.minOrNull()
        val steep = idx.map { samples[it] }.filter { it.grade >= STEEP_GRADE && !it.cadence.isNaN() && it.cadence > 0 && !it.power.isNaN() }
        val km = samples.sumOf { it.dDist } / 1000.0
        return DrivetrainStats(
            shifts = shifts.size,
            shiftsPerKm = if (km > 0.1) shifts.size / km else 0.0,
            cogMinutes = cogSeconds.toSortedMap().mapValues { it.value / 60.0 },
            smallestCogTeeth = used.firstOrNull(),
            largestCogTeeth = used.lastOrNull(),
            easierGearsUnused = largestUsedGear?.let { it - 1 },
            climbMedianCog = medianCog(CLIMB),
            descentMedianCog = medianCog(DESCENT),
            flatMedianCog = medianCog(FLAT),
            underLoad = shifts.count { (it.powerW ?: 0.0) >= UNDER_LOAD_W },
            climbShiftsBefore = before,
            climbShiftsAfter = after,
            steepCadenceRpm = steep.map { it.cadence }.sorted().getOrNull(steep.size / 2),
            steepTorqueNm = steep.map { it.power / (it.cadence * 2 * PI / 60.0) }.sorted().getOrNull(steep.size / 2),
            steepLowCadenceSec = steep.filter { it.cadence < 60 }.sumOf { it.dt },
            trackedKm = idx.sumOf { samples[it].dDist } / 1000.0,
        )
    }

    fun power(samples: List<SecondSample>, terrain: Array<String>, weightKg: Double): PowerStats? {
        val idx = samples.indices.filter { samples[it].moving && !samples[it].power.isNaN() }
        if (idx.isEmpty()) return null
        fun terrainStats(kind: String): PowerTerrain? {
            val sel = idx.filter { terrain[it] == kind }.map { samples[it] }
            if (sel.isEmpty()) return null
            val avg = sel.map { it.power }.average()
            return PowerTerrain(
                avgW = avg,
                wattsPerKg = if (weightKg > 20) avg / weightKg else null,
                pedallingPct = 100.0 * sel.count { it.pedalling } / sel.size,
                balanceLeft = sel.map { it.balanceLeft }.filter { !it.isNaN() && it > 0 }.averageOrNull(),
            )
        }
        val watts = samples.map { if (it.power.isNaN()) 0.0 else it.power }
        var best5: Double? = null
        if (watts.size >= 300) {
            var run = watts.take(300).sum()
            var best = run
            for (i in 300 until watts.size) {
                run += watts[i] - watts[i - 300]
                if (run > best) best = run
            }
            best5 = best / 300.0
        }
        return PowerStats(
            avgW = idx.map { samples[it].power }.average(),
            climbs = terrainStats(CLIMB),
            descents = terrainStats(DESCENT),
            flats = terrainStats(FLAT),
            best5minW = best5,
            weightKg = weightKg.takeIf { it > 20 },
        )
    }

    /** Bike fields for one segment or lap. */
    fun forRange(
        base: SegmentStats,
        slice: List<SecondSample>,
        shifts: List<Shift>,
        weightKg: Double,
    ): SegmentStats {
        val moving = slice.filter { it.moving }
        val watts = moving.map { it.power }.filter { !it.isNaN() }.averageOrNull()
        val fa = shares(moving.filter { it.faFront >= 0 }.map { it.faFront })
        val hasCadence = moving.any { !it.cadence.isNaN() }
        val startWall = slice.first().wallMs
        val endWall = slice.last().wallMs
        val cogs = moving.map { it.rearTeeth }.filter { it > 0 }.sorted()
        return base.copy(
            avgPowerW = watts,
            wattsPerKg = if (watts != null && weightKg > 20) watts / weightKg else null,
            vamMh = if (base.type == "CLIMB" && base.durationSec > 0) 3600.0 * base.elevGainM / base.durationSec else null,
            cadenceRpm = moving.map { it.cadence }.filter { !it.isNaN() && it > 0 }.averageOrNull(),
            medianCogTeeth = cogs.getOrNull(cogs.size / 2),
            faOpenPct = fa?.open,
            faPedalPct = fa?.pedal,
            faLockPct = fa?.lock,
            pedallingPct = if (hasCadence && moving.isNotEmpty()) 100.0 * moving.count { it.pedalling } / moving.size else null,
            shifts = shifts.count { it.wallMs in startWall..endWall },
        )
    }

    private fun List<Double>.averageOrNull(): Double? = if (isEmpty()) null else average()
}
