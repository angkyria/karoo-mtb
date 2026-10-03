package io.github.angkyria.karoomtb.engine

import io.github.angkyria.karoomtb.fit.MtbFitFields
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The engine with RockShox Flight Attendant, SRAM AXS and power meter streams. */
class MtbEngineBikeTest {
    /** 300 s climb at 230 W in the 32T, then a 300 s descent with the fork open after 20 s. */
    private fun bikeRide(sim: RideSim) {
        sim.ride(
            300, speed = { 3.0 }, grade = { 8.0 }, altitude = { 100.0 + it * 0.24 },
            each = {
                sim.engine.updatePower(230.0)
                sim.engine.updateCadence(75.0)
                sim.engine.updateBalance(47.0)
                sim.engine.updateSuspension(front = FaState.LOCK, rear = FaState.LOCK, effortZone = 2, mode = 1, bias = 0)
                sim.engine.updateGears(if (it < 20) 5 else 4, if (it < 20) 28 else 32, sim.elapsedMs, sim.wallMs())
            },
        )
        sim.ride(
            300, speed = { 6.0 }, grade = { -10.0 }, altitude = { 172.0 - it * 0.6 }, vibrationG = 0.4,
            each = {
                sim.engine.updatePower(if (it < 60) 150.0 else 0.0)
                sim.engine.updateCadence(if (it < 60) 80.0 else 0.0)
                val fa = if (it < 20) FaState.PEDAL else FaState.OPEN
                sim.engine.updateSuspension(front = fa, rear = fa, effortZone = 0)
                sim.engine.updateGears(8, 18, sim.elapsedMs, sim.wallMs())
            },
        )
    }

    @Test
    fun `shifts are counted while recording, not on the first gear or across sleep`() {
        val sim = RideSim().apply { start() }
        val e = sim.engine
        e.updateGears(4, 32, sim.elapsedMs, sim.wallMs()) // first value: no shift
        sim.ride(5, speed = { 5.0 })
        e.updateGears(5, 28, sim.elapsedMs, sim.wallMs()) // shift 1 (harder)
        e.pause()
        e.updateGears(6, 24, sim.elapsedMs, sim.wallMs()) // while paused: not counted
        e.resume()
        e.updateGears(7, 21, sim.elapsedMs, sim.wallMs()) // shift 2, from the gear set while paused
        e.updateGears(-1, null, sim.elapsedMs, sim.wallMs()) // derailleur asleep
        e.updateGears(3, 38, sim.elapsedMs, sim.wallMs()) // wakes up in another gear: not a shift
        sim.ride(2, speed = { 5.0 })
        val shifts = e.drainForStorage().shifts
        assertEquals(2, shifts.size)
        assertEquals(4, shifts[0].fromGear)
        assertEquals(32, shifts[0].fromTeeth)
        assertEquals(28, shifts[0].teeth)
        assertEquals(6, shifts[1].fromGear)
        assertTrue(!shifts[0].easier)
        assertEquals(listOf(1, 2), shifts.map { it.n })
        assertEquals(3, e.live().rearGear)
        assertEquals(2, e.live().easierGearsLeft)
        // Drained once only.
        assertTrue(e.drainForStorage().shifts.isEmpty())
    }

    @Test
    fun `locked on rough ground raises one alert, then the cooldown applies`() {
        val sim = RideSim().apply { start() }
        sim.ride(40, speed = { 5.0 }, vibrationG = 2.0, each = { sim.engine.updateSuspension(front = FaState.LOCK) })
        val live = sim.engine.live()
        assertTrue("rough ${live.roughNow}", live.roughNow!! >= BikeAnalytics.LOCKED_ROUGH_G)
        assertEquals(SuspensionMatch.LOCKED_ROUGH, live.suspensionMatch)
        assertEquals(listOf<RideAlert>(RideAlert.LockedOnRough), sim.engine.pollAlerts())
        sim.ride(10, speed = { 5.0 }, vibrationG = 2.0, each = { sim.engine.updateSuspension(front = FaState.OPEN) })
        assertEquals(SuspensionMatch.OK, sim.engine.live().suspensionMatch)
        assertTrue(sim.engine.pollAlerts().isEmpty())
    }

    @Test
    fun `no alert on smooth ground or without flight attendant`() {
        val sim = RideSim().apply { start() }
        sim.ride(30, speed = { 5.0 }, vibrationG = 0.1, each = { sim.engine.updateSuspension(front = FaState.LOCK) })
        assertEquals(SuspensionMatch.OK, sim.engine.live().suspensionMatch)
        val plain = RideSim().apply { start() }
        plain.ride(30, speed = { 5.0 }, vibrationG = 2.0)
        assertEquals(SuspensionMatch.NONE, plain.engine.live().suspensionMatch)
        assertTrue(sim.engine.pollAlerts().isEmpty())
        assertTrue(plain.engine.pollAlerts().isEmpty())
    }

    @Test
    fun `grinding a steep climb with easier gears left suggests a shift`() {
        val sim = RideSim().apply { start() }
        sim.ride(
            12, speed = { 2.0 }, grade = { 12.0 }, altitude = { 100.0 + it * 0.24 },
            each = {
                sim.engine.updateCadence(45.0)
                sim.engine.updateGears(3, 38, sim.elapsedMs, sim.wallMs())
            },
        )
        assertEquals(listOf<RideAlert>(RideAlert.ShiftDown(2)), sim.engine.pollAlerts())
    }

    @Test
    fun `battery alerts once per component, never while idle`() {
        val e = MtbEngine()
        e.setBattery("FA fork", "LOW")
        assertTrue(e.pollAlerts().isEmpty())
        val sim = RideSim(e).apply { start() }
        e.setBattery("FA fork", "LOW")
        e.setBattery("FA fork", "CRITICAL")
        e.setBattery("AXS derailleur", "GOOD", percent = 90)
        assertEquals(listOf<RideAlert>(RideAlert.BatteryLow("FA fork", "LOW")), e.pollAlerts())
        sim.ride(5, speed = { 5.0 })
        val batteries = sim.finish().bike.batteries
        assertEquals(listOf("FA fork" to "CRITICAL", "AXS derailleur" to "GOOD"), batteries.map { it.component to it.status })
        assertEquals(90, batteries[1].percent)
    }

    @Test
    fun `session and FIT carry bike fields only when paired`() {
        val sim = RideSim().apply { start() }
        sim.engine.setRiderWeight(75.0)
        bikeRide(sim)
        val v = sim.engine.sessionValues()
        assertEquals(230.0, v.climbPowerW!!, 5.0)
        assertEquals(230.0 / 75.0, v.climbWattsPerKg!!, 0.1)
        assertTrue("open ${v.faOpenDescentPct}", v.faOpenDescentPct!! in 85.0..96.0)
        assertEquals(2, v.faChanges)
        assertEquals(2, v.shifts)
        assertEquals(32, v.largestCogTeeth)
        assertTrue("pedal ${v.descentPedallingPct}", v.descentPedallingPct!! in 15.0..25.0)
        assertTrue("reaction ${v.faReactionSec}", v.faReactionSec!! in 15.0..25.0)
        val names = MtbFitFields.session(v, native = false).values.mapNotNull { it.developerField?.fieldName }
        assertTrue(names.containsAll(listOf("mtb_fa_open_desc", "mtb_shifts", "mtb_climb_power", "mtb_cog_max", "mtb_fa_reaction")))
        assertTrue(sim.engine.live().faOpenDescentPct!! > 80)

        val plain = RideSim().apply { start() }
        plain.ride(300, speed = { 3.0 }, grade = { 8.0 }, altitude = { 100.0 + it * 0.24 })
        plain.ride(300, speed = { 6.0 }, grade = { -10.0 }, altitude = { 172.0 - it * 0.6 })
        val pv = plain.engine.sessionValues()
        assertNull(pv.faOpenDescentPct)
        assertNull(pv.shifts)
        assertNull(pv.climbPowerW)
        val plainNames = MtbFitFields.session(pv, native = false).values.mapNotNull { it.developerField?.fieldName }
        assertTrue(plainNames.none { it.startsWith("mtb_fa_") || it == "mtb_shifts" || it == "mtb_climb_power" })
    }

    @Test
    fun `summary has bike statistics and a restored ride keeps them`() {
        val sim = RideSim().apply { start() }
        sim.engine.setRiderWeight(75.0)
        bikeRide(sim)
        val batch = sim.engine.drainForStorage()
        val original = sim.finish()
        val su = original.bike.suspension!!
        assertEquals(100.0, su.climbs!!.lock, 1.0)
        assertTrue(su.descents!!.open > 85)
        assertEquals(1, su.descentsReachingOpen)
        assertEquals(1, su.mode)
        val d = original.bike.drivetrain!!
        assertEquals(2, d.shifts)
        assertEquals(32, d.climbMedianCog)
        assertEquals(18, d.descentMedianCog)
        assertEquals(230.0, original.bike.power!!.climbs!!.avgW, 5.0)
        val climb = original.segments.first { it.type == "CLIMB" }
        assertEquals(230.0, climb.avgPowerW!!, 5.0)
        assertEquals(32, climb.medianCogTeeth)

        val replay = MtbEngine()
        replay.restore(
            sim.startWallMs, batch.samples.last().wallMs, 9_000_000, batch.samples, emptyList(), emptyList(),
            restoredShifts = batch.shifts,
        )
        val restored = replay.finish(batch.samples.last().wallMs + 1000, SummaryMeta("t", null, null))
        assertEquals(d.shifts, restored.bike.drivetrain!!.shifts)
        assertEquals(su.descents!!.open, restored.bike.suspension!!.descents!!.open, 2.0)
        assertEquals(original.bike.power!!.climbs!!.avgW, restored.bike.power!!.climbs!!.avgW, 2.0)
    }

    @Test
    fun `a new ride does not inherit the previous bike's state`() {
        val sim = RideSim().apply { start() }
        bikeRide(sim)
        sim.finish()
        assertNotNull(sim.engine.live().power)
        sim.start()
        sim.ride(30, speed = { 5.0 })
        val live = sim.engine.live()
        assertEquals(-1, live.faFront)
        assertEquals(-1, live.rearGear)
        assertNull(live.power)
        assertEquals(0, live.shifts)
        val summary = sim.finish()
        assertNull(summary.bike.suspension)
        assertNull(summary.bike.drivetrain)
        assertNull(summary.bike.power)
        assertTrue(summary.bike.batteries.isEmpty())
    }
}
