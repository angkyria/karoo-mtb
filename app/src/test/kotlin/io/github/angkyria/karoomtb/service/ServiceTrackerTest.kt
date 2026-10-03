package io.github.angkyria.karoomtb.service

import io.github.angkyria.karoomtb.engine.FaState
import io.github.angkyria.karoomtb.engine.RideSim
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.notify.Units
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class ServiceTrackerTest {
    @get:Rule
    val tmp = TemporaryFolder()

    /** 10 minutes on the Flight Attendant / AXS bike: 5 min climb, 5 min rough descent. */
    private fun bikeRide(seed: Long = 1, battery: String = "GOOD"): RideSummary {
        val sim = RideSim(seed = seed).apply { start() }
        sim.ride(
            300, speed = { 3.0 }, grade = { 8.0 }, altitude = { 100.0 + it * 0.24 },
            each = {
                sim.engine.updatePower(230.0)
                sim.engine.updateSuspension(front = FaState.LOCK, rear = FaState.LOCK)
                sim.engine.updateGears(4, 32, sim.elapsedMs, sim.wallMs())
            },
        )
        sim.ride(
            300, speed = { 6.0 }, grade = { -10.0 }, altitude = { 172.0 - it * 0.6 }, vibrationG = 1.2,
            each = {
                sim.engine.updatePower(0.0)
                sim.engine.updateSuspension(front = FaState.OPEN, rear = FaState.OPEN)
                sim.engine.updateGears(if (it < 150) 8 else 9, if (it < 150) 18 else 16, sim.elapsedMs, sim.wallMs())
            },
        )
        sim.engine.setBattery("FA fork", battery)
        sim.engine.setBattery("AXS derailleur", "OK", percent = 60)
        return sim.finish()
    }

    private fun plainRide(): RideSummary {
        val sim = RideSim().apply { start() }
        sim.ride(600, speed = { 5.0 })
        return sim.finish()
    }

    private fun tracker(file: File = File(tmp.root, ServiceTracker.FILE_NAME), now: Long = 1_800_000_000_000L) =
        ServiceTracker(file) { now }

    @Test
    fun `a ride counts once and only rides on this bike count`() {
        val t = tracker()
        val ride = bikeRide()
        assertTrue(t.addRide(ride).counted)
        assertFalse(t.addRide(ride).counted)
        val totals = t.state().totals
        assertEquals(1, totals.rides)
        assertEquals(ride.movingSec / 3600.0, totals.forkHours, 0.01)
        assertEquals(totals.forkHours, totals.shockHours, 0.01)
        assertTrue("rough ${totals.roughHours}", totals.roughHours > 0.05 && totals.roughHours < totals.forkHours)
        assertEquals(2L, totals.shifts) // 32 -> 18 -> 16
        assertEquals(1L, totals.faChanges)
        assertEquals(ride.distanceM / 1000.0, totals.drivetrainKm, 0.05)
        assertEquals(setOf(16, 18, 32), totals.cogHours.keys)
        assertEquals(ride.startWallMs, totals.sinceWallMs)

        // Another ride without Flight Attendant / AXS data (other bike): counted, adds nothing.
        assertTrue(t.addRide(plainRide().copy(startWallMs = 1_790_000_500_000L)).counted)
        assertEquals(1, t.state().totals.rides)
        assertEquals(totals.forkHours, t.state().totals.forkHours, 1e-9)
    }

    @Test
    fun `items become due once, notices show due and soon, serviced resets`() {
        val t = tracker()
        t.setInterval("fork_lowers", 0.1) // 6 minutes
        t.setUsed("chain", 1400.0) // of 1500 km: soon
        val update = t.addRide(bikeRide())
        assertEquals(listOf("fork_lowers"), update.newlyDue.map { it.item.id })
        val notices = t.notices(Units())
        assertTrue(notices.toString(), notices.any { it.startsWith("🛠️ **Fork lower-leg service due**") && it.contains("every 0.1 h") })
        assertTrue(notices.toString(), notices.any { it.startsWith("🛠️ Chain wear check soon") && it.contains("km left") })
        assertEquals(2, notices.size)

        // Still due after the next ride, but not "newly" due.
        assertTrue(t.addRide(bikeRide(seed = 2).copy(startWallMs = 1_790_000_900_000L)).newlyDue.isEmpty())

        t.markServiced("fork_lowers")
        val fork = t.statuses().first { it.item.id == "fork_lowers" }
        assertEquals(0.0, fork.used, 1e-9)
        assertFalse(fork.due)
        assertEquals(1_800_000_000_000L, fork.lastServiceWallMs)
        assertTrue(t.notices(Units()).none { it.contains("Fork lower-leg") })
        // Imperial riders get miles.
        assertTrue(t.notices(Units(imperialDistance = true)).any { it.contains(" mi left") })
    }

    @Test
    fun `usage set before tracking began counts toward the interval`() {
        val t = tracker()
        t.setUsed("fork_damper", 150.0)
        t.addRide(bikeRide())
        val damper = t.statuses().first { it.item.id == "fork_damper" }
        assertEquals(150.0 + 600.0 / 3600.0, damper.used, 0.01)
        assertNull(damper.lastServiceWallMs)
        assertEquals(200.0, damper.interval, 0.0)
    }

    @Test
    fun `state persists, and a broken file starts over instead of crashing`() {
        val file = File(tmp.root, ServiceTracker.FILE_NAME)
        tracker(file).apply {
            setInterval("chain", 2000.0)
            addRide(bikeRide())
        }
        val again = tracker(file)
        assertEquals(2000.0, again.statuses().first { it.item.id == "chain" }.interval, 0.0)
        assertEquals(1, again.state().totals.rides)
        assertFalse(File(tmp.root, ServiceTracker.FILE_NAME + ".tmp").exists())

        file.writeText("{ not json")
        val broken = tracker(file)
        assertEquals(0, broken.state().totals.rides)
        broken.addRide(bikeRide())
        assertEquals(1, tracker(file).state().totals.rides)
    }

    @Test
    fun `battery history keeps the latest status per component`() {
        val t = tracker()
        t.addRide(bikeRide(battery = "GOOD"))
        t.addRide(bikeRide(seed = 3, battery = "LOW").copy(startWallMs = 1_790_000_900_000L))
        assertEquals(4, t.state().batteries.size)
        val latest = t.latestBatteries().associateBy { it.component }
        assertEquals("LOW", latest["FA fork"]!!.status)
        assertEquals(60, latest["AXS derailleur"]!!.percent)
        assertEquals(1_790_000_900_000L, latest["FA fork"]!!.rideStartWallMs)
    }
}
