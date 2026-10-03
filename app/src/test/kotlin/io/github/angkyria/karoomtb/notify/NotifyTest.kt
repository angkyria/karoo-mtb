package io.github.angkyria.karoomtb.notify

import io.github.angkyria.karoomtb.engine.FaState
import io.github.angkyria.karoomtb.engine.RideSim
import io.github.angkyria.karoomtb.engine.RideSummary
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NotifyTest {
    private fun bigRide(): RideSummary {
        val sim = RideSim().apply { start() }
        // Many short climbs and descents => many segments.
        repeat(30) { lap ->
            sim.ride(60, speed = { 3.0 }, grade = { 10.0 }, altitude = { 100.0 + it * 0.5 })
            sim.jumpIn(5.0, 0.5)
            sim.ride(40, speed = { 8.0 }, grade = { -10.0 }, altitude = { 130.0 - it * 0.75 })
            if (lap % 5 == 4) sim.engine.markLap()
        }
        return sim.finish()
    }

    @Test
    fun `markdown summary fits in one ntfy message`() {
        val summary = bigRide()
        assertTrue(summary.segments.size > 20)
        val text = SummaryFormatter.markdown(summary, Units())
        assertTrue("bytes ${text.toByteArray().size}", text.toByteArray().size <= SummaryFormatter.MAX_MESSAGE_BYTES)
        assertTrue(text.contains("Grit"))
        assertTrue(text.contains("Flow"))
        assertTrue(text.contains("jumps"))
        assertTrue(text.contains("Trail segments"))
    }

    @Test
    fun `example message for the README`() {
        val sim = RideSim().apply { start() }
        sim.ride(600, speed = { 3.2 }, grade = { 8.0 }, altitude = { 300.0 + it * 0.256 }, vibrationG = 0.15)
        repeat(2) {
            sim.jumpIn(30.0, 0.62)
            sim.jumpIn(120.0, 0.85)
            sim.ride(
                300,
                speed = { if (it % 20 in 8..9) 5.0 else if (it % 20 in 10..13) 3.5 else if (it % 61 in 3..5) 5.5 else 7.5 },
                grade = { -11.0 },
                altitude = { 450.0 - it * 0.8 },
                yawRate = { if (it % 20 in 10..13) (if (it / 20 % 2 == 0) 1.0 else -1.0) else 0.0 },
                vibrationG = 0.45,
            )
            sim.ride(240, speed = { 5.0 }, altitude = { 210.0 }, vibrationG = 0.2)
        }
        val summary = sim.finish()
        val text = SummaryFormatter.markdown(summary, Units())
        println(SummaryFormatter.title(summary))
        println(text)
        assertTrue(text.contains("jumps"))
    }

    @Test
    fun `imperial units`() {
        val units = Units(imperialDistance = true, imperialElevation = true)
        assertEquals("22.4 mph", units.speed(10.0))
        assertEquals("1.0 mi", units.distance(1609.344))
        assertEquals("328 ft", units.elevation(100.0))
        assertEquals("1:01:01", Units.duration(3661.0))
    }

    @Test
    fun `json publish request`() {
        val target = NtfyTarget(server = "ntfy.example.com/", topic = "mtb-abc", token = "tk_123", priority = 4, clickUrl = "https://intervals.icu")
        val req = NtfyRequest.message(target, "Title ⛰️", "**body** 🚵")
        assertEquals("POST", req.method)
        assertEquals("https://ntfy.example.com", req.url)
        assertEquals("Bearer tk_123", req.headers["Authorization"])
        val json = Json.parseToJsonElement(String(req.body)).jsonObject
        assertEquals("mtb-abc", json["topic"]!!.jsonPrimitive.content)
        assertEquals("Title ⛰️", json["title"]!!.jsonPrimitive.content)
        assertTrue(json["markdown"]!!.jsonPrimitive.boolean)
        assertEquals(4, json["priority"]!!.jsonPrimitive.int)
        assertEquals("https://intervals.icu", json["click"]!!.jsonPrimitive.content)
    }

    @Test
    fun `auth header variants`() {
        assertNull(NtfyRequest.authHeader(" "))
        assertTrue(NtfyRequest.authHeader("user:pass")!!.startsWith("Basic "))
        assertEquals(NtfyRequest.DEFAULT_SERVER, NtfyRequest.serverRoot(""))
        assertTrue(NtfyRequest.isValidTopic("mtb-x_9"))
        assertTrue(!NtfyRequest.isValidTopic("bad topic"))
    }

    @Test
    fun `attachment goes to the topic url`() {
        val req = NtfyRequest.attachment(NtfyTarget("https://ntfy.sh", "t1"), "ride.json", "{}".toByteArray(), "Full report")
        assertEquals("PUT", req.method)
        assertEquals("https://ntfy.sh/t1", req.url)
        assertEquals("ride.json", req.headers["Filename"])
    }

    @Test
    fun `bike section only when components were paired`() {
        val sim = RideSim().apply { start() }
        sim.engine.setRiderWeight(75.0)
        sim.ride(
            300, speed = { 3.0 }, grade = { 8.0 }, altitude = { 100.0 + it * 0.24 },
            each = {
                sim.engine.updatePower(230.0)
                sim.engine.updateCadence(75.0)
                sim.engine.updateBalance(47.0)
                sim.engine.updateSuspension(front = FaState.LOCK)
                sim.engine.updateGears(if (it < 20) 5 else 4, if (it < 20) 28 else 32, sim.elapsedMs, sim.wallMs())
            },
        )
        sim.ride(
            300, speed = { 6.0 }, grade = { -10.0 }, altitude = { 172.0 - it * 0.6 },
            each = {
                sim.engine.updatePower(0.0)
                sim.engine.updateCadence(0.0)
                sim.engine.updateSuspension(front = if (it < 20) FaState.PEDAL else FaState.OPEN)
                sim.engine.updateGears(8, 18, sim.elapsedMs, sim.wallMs())
            },
        )
        sim.engine.setBattery("FA fork", "LOW")
        sim.engine.setBattery("AXS derailleur", "GOOD")
        val summary = sim.finish()
        val text = SummaryFormatter.markdown(summary, Units(), notices = listOf("🛠️ Fork lower-leg service due"))
        println(text)
        assertTrue(text, text.contains("🔩 **Flight Attendant** descents 9"))
        assertTrue(text, text.contains("climbs 100% lock"))
        assertTrue(text, text.contains("⚙️ **2 shifts**"))
        assertTrue(text, text.contains("cogs 18–32T"))
        assertTrue(text, text.contains("💪 **Power** climbs 230 W (3.1 W/kg)"))
        assertTrue(text, text.contains("L/R 47/53"))
        assertTrue(text, text.contains("FA fork low ⚠️ · AXS derailleur good"))
        assertTrue(text, text.contains("🛠️ Fork lower-leg service due"))
        assertTrue(text, text.contains(" · 230 W"))
        assertTrue(text, text.contains("% open"))

        val plain = RideSim().apply { start() }
        plain.ride(300, speed = { 3.0 }, grade = { 8.0 }, altitude = { 100.0 + it * 0.24 })
        val plainSummary = plain.finish()
        val plainText = SummaryFormatter.markdown(plainSummary, Units())
        assertTrue(SummaryFormatter.bikeLines(plainSummary).isEmpty())
        for (marker in listOf("Flight Attendant", "shifts", "Power", "🔋")) assertTrue(marker, !plainText.contains(marker))
    }
}
