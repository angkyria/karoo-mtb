package io.github.angkyria.karoomtb.notify

import io.github.angkyria.karoomtb.engine.RideSim
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.engine.SummaryMeta
import io.github.angkyria.karoomtb.storage.NtfyStatus
import io.github.angkyria.karoomtb.storage.RideMeta
import io.github.angkyria.karoomtb.storage.RideStore
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files
import java.util.TimeZone

class IcuTest {
    private val rideStart = 1_790_000_000_000L // 2026-09-21T14:13:20Z

    private val summary: RideSummary by lazy {
        val sim = RideSim().apply { engine.start(rideStart, startElapsedMs) }
        sim.ride(300, speed = { 5.0 }, grade = { -6.0 })
        sim.engine.finish(sim.wallMs(), SummaryMeta("test", "Trail", "K2"))
    }

    @Test
    fun `the ride's activity is found by start time and type`() {
        val list = """[
            {"id": "i1", "type": "Run", "start_date": "2026-09-21T14:13:00Z"},
            {"id": "i2", "type": "MountainBikeRide", "start_date": "2026-09-21T14:15:00Z"},
            {"id": "i3", "type": "Ride", "start_date": "2026-09-21T11:00:00Z"}
        ]"""
        assertEquals("i2", IcuRequest.findActivity(list, rideStart))
        val local = """[{"id": "i9", "type": "Ride", "start_date_local": "2026-09-21T17:14:10"}]"""
        assertEquals("i9", IcuRequest.findActivity(local, rideStart, TimeZone.getTimeZone("Europe/Athens")))
        assertNull(IcuRequest.findActivity(local, rideStart, TimeZone.getTimeZone("UTC")))
        assertNull(IcuRequest.findActivity("not json", rideStart))
    }

    @Test
    fun `the description block replaces an earlier one and keeps the rest`() {
        val block = IcuRequest.block(summary, Units())
        assertTrue(block.startsWith("🚵 MTB Dynamics · score"))
        val old = listOf(
            "Great ride with Nikos", "", "🚵 MTB Dynamics · score 12", "Grit 1.0 kGrit · Flow 0.10 · 0 jumps",
            "3 corners · max 0.20 g · descents 1:00, braking 5 %", "PB Trail 1 4:00 (was 4:10)", "See you",
        ).joinToString("\n")
        val merged = IcuRequest.mergedDescription(old, block)
        assertTrue(merged, merged.startsWith("Great ride with Nikos\n"))
        assertTrue(merged.contains("See you"))
        assertEquals(1, Regex("MTB Dynamics").findAll(merged).count())
        assertFalse(merged.contains("PB Trail 1"))
        assertEquals(block, IcuRequest.mergedDescription(null, block))
    }

    @Test
    fun `requests carry the API key and the right dates`() {
        val r = IcuRequest.activities("abc", "", rideStart)
        assertEquals("GET", r.method)
        assertTrue(r.url, r.url.endsWith("/api/v1/athlete/0/activities?oldest=2026-09-20&newest=2026-09-22"))
        assertEquals("Basic QVBJX0tFWTphYmM=", r.headers["Authorization"])
        val body = IcuRequest.updateBody("text", summary, withFields = true).toString()
        assertTrue(body, body.contains("\"description\":\"text\"") && body.contains("\"MtbGrit\""))
        assertFalse(IcuRequest.updateBody("text", summary, withFields = false).toString().contains("MtbGrit"))
    }

    private class FakeIcu(val activityFound: Boolean, val fieldsRefused: Boolean = false) : HttpClient {
        val puts = ArrayList<String>()
        override suspend fun send(request: HttpRequestSpec, waitForConnection: Boolean, timeoutMs: Long?): SendResult = when {
            request.url.contains("/activities?") ->
                SendResult(true, 200, "", if (activityFound) """[{"id":"i42","type":"Ride","start_date":"2026-09-21T14:14:00Z"}]""" else "[]")
            request.method == "GET" -> SendResult(true, 200, "", """{"id":"i42","description":"Rode with friends"}""")
            else -> {
                val body = request.body.decodeToString()
                puts += body
                if (fieldsRefused && body.contains("MtbGrit")) SendResult(false, 422, "unknown field") else SendResult(true, 200, "")
            }
        }
    }

    private fun store(): Pair<RideStore, java.io.File> {
        val store = RideStore(Files.createTempDirectory("rides").toFile())
        val dir = store.begin(RideMeta(rideStart, "test"))
        store.saveSummary(dir, summary)
        return store to dir
    }

    @Test
    fun `uploader updates the description, waits while the activity is missing`() = runBlocking {
        val (store, dir) = store()
        val missing = FakeIcu(activityFound = false)
        val config = IcuConfig(enabled = true, apiKey = "k")
        IcuUploader({ config }, store, missing).publish(dir, summary, Units())
        assertEquals(NtfyStatus.PENDING, store.icuStatus(dir)?.state)
        assertTrue(missing.puts.isEmpty())

        val found = FakeIcu(activityFound = true)
        IcuUploader({ config }, store, found, clock = { rideStart + 3_600_000 }).retryPending(Units())
        assertEquals(NtfyStatus.SENT, store.icuStatus(dir)?.state)
        assertTrue(found.puts.single(), found.puts.single().contains("Rode with friends\\n\\n🚵 MTB Dynamics"))
    }

    @Test
    fun `refused custom fields still update the description`() = runBlocking {
        val (store, dir) = store()
        val fake = FakeIcu(activityFound = true, fieldsRefused = true)
        val r = IcuUploader({ IcuConfig(true, "k", fields = true) }, store, fake).publish(dir, summary, Units())
        assertTrue(r.ok)
        assertEquals(2, fake.puts.size)
        assertTrue(store.icuStatus(dir)!!.detail.contains("custom fields refused"))
        assertFalse(IcuUploader({ IcuConfig(false, "k") }, store, fake).enabled)
    }
}
