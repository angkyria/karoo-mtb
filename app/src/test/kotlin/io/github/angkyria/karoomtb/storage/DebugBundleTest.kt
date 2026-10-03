package io.github.angkyria.karoomtb.storage

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.nio.file.Files
import java.util.zip.ZipInputStream

class DebugBundleTest {
    @Test
    fun `GPS is removed from CSV and JSON`() {
        val csv = "wall_ms,speed_ms,lat,lon,grit\n1,5.0,46.1,8.2,1.3\n2,5.1,46.2,8.3,1.4"
        assertEquals("wall_ms,speed_ms,lat,lon,grit\n1,5.0,,,1.3\n2,5.1,,,1.4", DebugBundle.stripCsvGps(csv))
        val json = """{"jump":{"n":1,"airSec":0.6,"lat":46.1,"lon":8.2},"descentTracks":[{"points":[]}],"trails":[{"name":"T","track":[1]}]}"""
        val clean = DebugBundle.stripJsonGps(json)
        assertFalse(clean, clean.contains("lat") || clean.contains("46.1") || clean.contains("descentTracks") || clean.contains("track"))
        assertTrue(clean.contains("\"airSec\":0.6") && clean.contains("\"name\":\"T\""))
        assertEquals("not json", DebugBundle.stripJsonGps("not json"))
    }

    @Test
    fun `bundle holds the ride files and extras, parts fit the bridge`() {
        val store = RideStore(Files.createTempDirectory("rides").toFile())
        val dir = store.begin(RideMeta(1_790_000_000_000L, "test"))
        java.io.File(dir, "summary.json").writeText("""{"brakingSpots":[{"lat":46.0,"lon":8.0,"flowM":5.0}]}""")
        java.io.File(dir, "imu.csv.gz").writeBytes(ByteArray(10))
        val zip = DebugBundle.build(dir, mapOf("settings.txt" to "ntfy_token = ***", "logcat.txt" to "log"))
        val entries = LinkedHashMap<String, String>()
        ZipInputStream(ByteArrayInputStream(zip)).use { z ->
            while (true) {
                val e = z.nextEntry ?: break
                entries[e.name] = z.readBytes().decodeToString()
            }
        }
        val expected = listOf("ride-1790000000000/meta.json", "ride-1790000000000/summary.json", "settings.txt", "logcat.txt")
        assertTrue(entries.keys.toString(), entries.keys.containsAll(expected))
        assertFalse(entries.keys.any { it.endsWith("imu.csv.gz") })
        assertFalse(entries.getValue("ride-1790000000000/summary.json").contains("46.0"))
        val big = ByteArray(200_000) { it.toByte() }
        val parts = DebugBundle.parts(big)
        assertEquals(3, parts.size)
        assertTrue(parts.all { it.size <= DebugBundle.PART_BYTES })
        assertTrue(big.contentEquals(parts.reduce { a, b -> a + b }))
        assertEquals(2, DebugBundle.tailLines("h\n1\n2\n3\n4", 2).lines().size - 1)
    }
}
