package io.github.angkyria.karoomtb

import android.content.Context
import io.github.angkyria.karoomtb.engine.MtbConfig
import io.github.angkyria.karoomtb.engine.Sensitivity
import io.github.angkyria.karoomtb.karoo.Panel
import io.github.angkyria.karoomtb.karoo.PanelCell
import io.github.angkyria.karoomtb.notify.NtfyRequest
import io.github.angkyria.karoomtb.notify.NtfyTarget
import java.security.SecureRandom

/** User settings (SharedPreferences, shared by the extension service and the settings screen). */
class Settings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("karoo_mtb", Context.MODE_PRIVATE)

    var ntfyEnabled: Boolean
        get() = prefs.getBoolean("ntfy_enabled", true)
        set(v) = prefs.edit().putBoolean("ntfy_enabled", v).apply()

    var ntfyServer: String
        get() = prefs.getString("ntfy_server", null) ?: NtfyRequest.DEFAULT_SERVER
        set(v) = prefs.edit().putString("ntfy_server", v.trim()).apply()

    /** A random topic is generated on first use: ntfy.sh topics are only as private as their name. */
    var ntfyTopic: String
        get() = prefs.getString("ntfy_topic", null) ?: randomTopic().also { ntfyTopic = it }
        set(v) = prefs.edit().putString("ntfy_topic", v.trim()).apply()

    var ntfyToken: String
        get() = prefs.getString("ntfy_token", null) ?: ""
        set(v) = prefs.edit().putString("ntfy_token", v.trim()).apply()

    var ntfyPriority: Int
        get() = prefs.getInt("ntfy_priority", 3)
        set(v) = prefs.edit().putInt("ntfy_priority", v.coerceIn(1, 5)).apply()

    var ntfyClickUrl: String
        get() = prefs.getString("ntfy_click", null) ?: "https://intervals.icu/activities"
        set(v) = prefs.edit().putString("ntfy_click", v.trim()).apply()

    var ntfyAttachJson: Boolean
        get() = prefs.getBoolean("ntfy_attach", false)
        set(v) = prefs.edit().putBoolean("ntfy_attach", v).apply()

    /** OpenStreetMap links on the braking spots: puts GPS positions into the ntfy message. */
    var ntfyMapLinks: Boolean
        get() = prefs.getBoolean("ntfy_map_links", false)
        set(v) = prefs.edit().putBoolean("ntfy_map_links", v).apply()

    /** Rides with less moving time than this are not sent (e.g. a discarded test ride). */
    var minNotifyMinutes: Int
        get() = prefs.getInt("min_notify_min", 3)
        set(v) = prefs.edit().putInt("min_notify_min", v.coerceIn(0, 240)).apply()

    var mtbProfilesOnly: Boolean
        get() = prefs.getBoolean("mtb_only", false)
        set(v) = prefs.edit().putBoolean("mtb_only", v).apply()

    var jumpAlerts: Boolean
        get() = prefs.getBoolean("jump_alerts", true)
        set(v) = prefs.edit().putBoolean("jump_alerts", v).apply()

    var jumpBeep: Boolean
        get() = prefs.getBoolean("jump_beep", false)
        set(v) = prefs.edit().putBoolean("jump_beep", v).apply()

    var sensitivity: Sensitivity
        get() = runCatching { Sensitivity.valueOf(prefs.getString("sensitivity", null) ?: "MEDIUM") }.getOrDefault(Sensitivity.MEDIUM)
        set(v) = prefs.edit().putString("sensitivity", v.name).apply()

    /** Also write Garmin's own grit/flow/jump_count FIT fields (besides the mtb_* developer fields). */
    var writeNativeFit: Boolean
        get() = prefs.getBoolean("fit_native", true)
        set(v) = prefs.edit().putBoolean("fit_native", v).apply()

    /** In-ride alert at the bottom of each descent (time, drop, Flow, braking, jumps). */
    var descentAlerts: Boolean
        get() = prefs.getBoolean("alert_descent", true)
        set(v) = prefs.edit().putBoolean("alert_descent", v).apply()

    /** In-ride alert when Flight Attendant stays in Lock on rough ground. */
    var suspensionAlerts: Boolean
        get() = prefs.getBoolean("alert_suspension", true)
        set(v) = prefs.edit().putBoolean("alert_suspension", v).apply()

    /** In-ride hint to shift down when grinding a steep climb with easier gears left. */
    var shiftAdvice: Boolean
        get() = prefs.getBoolean("alert_shift", false)
        set(v) = prefs.edit().putBoolean("alert_shift", v).apply()

    /** In-ride alert when an AXS / Flight Attendant battery reports low. */
    var batteryAlerts: Boolean
        get() = prefs.getBoolean("alert_battery", true)
        set(v) = prefs.edit().putBoolean("alert_battery", v).apply()

    /** Debug: store raw accelerometer / gyroscope samples with each ride (imu.csv.gz, ~3 MB/h). */
    var debugRawImu: Boolean
        get() = prefs.getBoolean("debug_raw_imu", false)
        set(v) = prefs.edit().putBoolean("debug_raw_imu", v).apply()

    var segmentMinElevationM: Int
        get() = prefs.getInt("segment_min_elev", 15)
        set(v) = prefs.edit().putInt("segment_min_elev", v.coerceIn(5, 100)).apply()

    /** The cells of a graphical panel field (6; small fields show the first 4). */
    fun panelCells(panel: Panel): List<PanelCell> = PanelCell.parse(prefs.getString("panel_${panel.typeId}", null), panel.defaults)

    fun setPanelCells(panel: Panel, cells: List<PanelCell>) {
        prefs.edit().putString("panel_${panel.typeId}", cells.joinToString(",") { it.name }).apply()
    }

    fun mtbConfig(): MtbConfig = MtbConfig(sensitivity = sensitivity, segmentMinElevationM = segmentMinElevationM.toDouble())

    fun ntfyTarget(): NtfyTarget = NtfyTarget(ntfyServer, ntfyTopic, ntfyToken, ntfyPriority, ntfyClickUrl)

    companion object {
        fun randomTopic(): String {
            val alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
            val rnd = SecureRandom()
            return "mtb-" + (1..14).map { alphabet[rnd.nextInt(alphabet.length)] }.joinToString("")
        }
    }
}
