package io.github.angkyria.karoomtb.engine

import kotlin.math.max

/** Builds the end-of-ride [RideSummary] from the per-second samples and detected events. */
object SummaryBuilder {
    /** Rolling-window flow is only meaningful over some distance. */
    private const val MIN_WINDOW_DISTANCE_M = 200.0

    fun build(
        meta: SummaryMeta,
        startWallMs: Long,
        endWallMs: Long,
        samples: List<SecondSample>,
        lapStarts: List<Int>,
        jumps: List<Jump>,
        corners: List<Corner>,
        config: MtbConfig,
        sensors: SensorInfo,
        shifts: List<Shift> = emptyList(),
        weightKg: Double = Double.NaN,
        batteries: List<BatteryInfo> = emptyList(),
        faMode: Int? = null,
        faBias: Int? = null,
    ): RideSummary {
        var movingSec = 0.0
        var movingDist = 0.0
        var distance = 0.0
        var maxSpeed = 0.0
        var grit = 0.0
        var flow = 0.0
        var flowDist = 0.0
        var roughSum = 0.0
        var roughN = 0
        var maxLat = 0.0
        for (s in samples) {
            distance += s.dDist
            grit += s.grit
            if (!s.moving) continue
            movingSec += s.dt
            movingDist += s.dDist
            maxSpeed = max(maxSpeed, s.speed)
            maxLat = max(maxLat, s.latG)
            if (!s.rough.isNaN()) {
                roughSum += s.rough
                roughN++
            }
            if (s.processed) {
                flow += s.flow
                flowDist += s.dDist
            }
        }
        val (gain, loss) = RangeStats.elevationChange(samples)
        val avgGrit = if (movingSec > 0) grit / movingSec else 0.0
        val flowScore = Scoring.flowScore(flow, flowDist)
        val totalAir = jumps.sumOf { it.airSec }
        val difficulty = Scoring.difficultyScore(avgGrit)
        val smoothness = Scoring.smoothnessScore(flowScore)
        val air = Scoring.airScore(totalAir)

        val segments = Segmenter.split(samples, config.segmentMinElevationM)
        val counters = HashMap<String, Int>()
        val segmentStats = segments.mapIndexed { i, r ->
            val number = (counters[r.type] ?: 0) + 1
            counters[r.type] = number
            RangeStats.compute(i + 1, r.type, "${label(r.type)} $number", samples, r.start, r.end, jumps, corners, startWallMs, shifts, weightKg)
        }
        val lapStats = if (lapStarts.size > 1) {
            lapStarts.mapIndexedNotNull { i, from ->
                val to = (if (i + 1 < lapStarts.size) lapStarts[i + 1] - 1 else samples.lastIndex)
                if (from > to || from > samples.lastIndex) null
                else RangeStats.compute(i + 1, "LAP", "Lap ${i + 1}", samples, from, to, jumps, corners, startWallMs, shifts, weightKg)
            }
        } else {
            emptyList()
        }
        val terrain = BikeAnalytics.terrain(samples, segments)
        val bike = BikeStats(
            suspension = BikeAnalytics.suspension(samples, terrain, segments, faMode, faBias),
            drivetrain = BikeAnalytics.drivetrain(samples, terrain, segments, shifts),
            power = BikeAnalytics.power(samples, terrain, weightKg),
            batteries = batteries,
            faMode = faMode,
            faBias = faBias,
        )

        return RideSummary(
            appVersion = meta.appVersion,
            startWallMs = startWallMs,
            endWallMs = endWallMs,
            profileName = meta.profileName,
            device = meta.device,
            elapsedSec = (endWallMs - startWallMs) / 1000.0,
            movingSec = movingSec,
            distanceM = distance,
            ascentM = if (meta.ascentM.isNaN()) gain else meta.ascentM,
            descentM = if (meta.descentM.isNaN()) loss else meta.descentM,
            avgSpeedMs = if (movingSec > 0) movingDist / movingSec else 0.0,
            maxSpeedMs = maxSpeed,
            grit = GritStats(totalK = grit / 1000.0, avgPerSec = avgGrit, peak60 = peakGrit60(samples)),
            flow = FlowStats(
                score = flowScore,
                totalM = flow,
                worst60 = worstFlow60(samples),
                descentScore = descentFlow(samples),
            ),
            jumps = JumpStats(
                count = jumps.size,
                totalAirSec = totalAir,
                longest = jumps.maxByOrNull { it.airSec },
                farthest = jumps.maxByOrNull { it.distanceM },
                highest = jumps.maxByOrNull { it.heightM },
                hardestLanding = jumps.maxByOrNull { it.landingG },
                list = jumps.take(MAX_LISTED_JUMPS),
            ),
            cornering = cornerStats(corners, maxLat),
            descending = descentStats(samples, jumps, startWallMs),
            roughnessAvg = if (roughN > 0) roughSum / roughN else null,
            score = ScoreStats(Scoring.mtbScore(difficulty, smoothness, air), difficulty, smoothness, air),
            segments = segmentStats,
            laps = lapStats,
            sensors = sensors,
            flowLagSec = config.flowLagSec,
            bike = bike,
            lapComparison = Insights.lapComparison(lapStats),
            brakingSpots = Insights.brakingSpots(samples, segmentStats, startWallMs),
            descentTracks = segments.mapIndexedNotNull { i, r ->
                if (r.type != "DESCENT") return@mapIndexedNotNull null
                val (from, to) = Tracks.descendingCore(samples, r.start, r.end)
                Tracks.withMargins(i + 1, samples, from, to, startWallMs)
            },
        )
    }

    const val MAX_LISTED_JUMPS = 300

    fun label(type: String): String = when (type) {
        "CLIMB" -> "Climb"
        "DESCENT" -> "Descent"
        "LAP" -> "Lap"
        else -> "Flat"
    }

    private fun peakGrit60(samples: List<SecondSample>): Double {
        var best = 0.0
        var sum = 0.0
        var time = 0.0
        for (i in samples.indices) {
            sum += samples[i].grit
            time += samples[i].dt
            if (i >= MtbEngine.WINDOW_SEC) {
                sum -= samples[i - MtbEngine.WINDOW_SEC].grit
                time -= samples[i - MtbEngine.WINDOW_SEC].dt
            }
            if (i >= MtbEngine.WINDOW_SEC - 1 && time > 0) best = max(best, sum / time)
        }
        return best
    }

    private fun worstFlow60(samples: List<SecondSample>): Double {
        var worst = 0.0
        var flow = 0.0
        var dist = 0.0
        for (i in samples.indices) {
            val s = samples[i]
            if (s.moving && s.processed) {
                flow += s.flow
                dist += s.dDist
            }
            if (i >= MtbEngine.WINDOW_SEC) {
                val old = samples[i - MtbEngine.WINDOW_SEC]
                if (old.moving && old.processed) {
                    flow -= old.flow
                    dist -= old.dDist
                }
            }
            if (dist >= MIN_WINDOW_DISTANCE_M) worst = max(worst, Scoring.flowScore(flow, dist))
        }
        return worst
    }

    private fun descentFlow(samples: List<SecondSample>): Double {
        var flow = 0.0
        var dist = 0.0
        for (s in samples) {
            if (s.descending && s.processed) {
                flow += s.flow
                dist += s.dDist
            }
        }
        return Scoring.flowScore(flow, dist)
    }

    private fun cornerStats(corners: List<Corner>, maxLat: Double): CornerStats {
        val withSpeed = corners.filter { it.entrySpeedMs > 0.5 }
        val (left, right) = Insights.cornerSides(corners)
        return CornerStats(
            count = corners.size,
            left = corners.count { it.angleDeg > 0 },
            right = corners.count { it.angleDeg < 0 },
            avgEntrySpeedMs = corners.map { it.entrySpeedMs }.averageOrZero(),
            avgMinSpeedMs = corners.map { it.minSpeedMs }.averageOrZero(),
            speedKeptPct = withSpeed.map { 100.0 * it.minSpeedMs / it.entrySpeedMs }.averageOrZero(),
            maxLateralG = max(maxLat, corners.maxOfOrNull { it.maxLateralG } ?: 0.0),
            avgPeakLateralG = corners.map { it.maxLateralG }.averageOrZero(),
            sharpestRadiusM = corners.filter { it.radiusM > 0 }.minOfOrNull { it.radiusM },
            speedKeptLeftPct = left,
            speedKeptRightPct = right,
        )
    }

    private fun descentStats(samples: List<SecondSample>, jumps: List<Jump>, startWallMs: Long): DescentStats {
        var time = 0.0
        var dist = 0.0
        var drop = 0.0
        var maxSpeed = 0.0
        var grit = 0.0
        var processedTime = 0.0
        var brakingTime = 0.0
        var flow = 0.0
        var flowDist = 0.0
        var previousAlt = Double.NaN
        val descentSeconds = HashSet<Long>()
        for (s in samples) {
            val alt = s.altitude
            if (s.descending) {
                time += s.dt
                dist += s.dDist
                maxSpeed = max(maxSpeed, s.speed)
                grit += s.grit
                if (!alt.isNaN() && !previousAlt.isNaN() && alt < previousAlt) drop += previousAlt - alt
                if (s.processed) {
                    processedTime += s.dt
                    if (s.braking) brakingTime += s.dt
                    flow += s.flow
                    flowDist += s.dDist
                }
                descentSeconds += (s.wallMs - startWallMs) / 1000
            }
            if (!alt.isNaN()) previousAlt = alt
        }
        return DescentStats(
            timeSec = time,
            distanceM = dist,
            dropM = drop,
            avgSpeedMs = if (time > 0) dist / time else 0.0,
            maxSpeedMs = maxSpeed,
            brakingPct = if (processedTime > 0) 100.0 * brakingTime / processedTime else 0.0,
            flowScore = Scoring.flowScore(flow, flowDist),
            gritK = grit / 1000.0,
            jumps = jumps.count { it.offsetSec.toLong() in descentSeconds || (it.offsetSec.toLong() + 1) in descentSeconds },
        )
    }

    private fun List<Double>.averageOrZero(): Double = if (isEmpty()) 0.0 else average()
}
