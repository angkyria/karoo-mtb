package io.github.angkyria.karoomtb.ui

import android.app.Activity
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import io.github.angkyria.karoomtb.BuildConfig
import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.Settings
import io.github.angkyria.karoomtb.engine.Sensitivity
import io.github.angkyria.karoomtb.karoo.MtbRuntime
import io.github.angkyria.karoomtb.notify.HttpSender
import io.github.angkyria.karoomtb.notify.NtfyRequest
import io.github.angkyria.karoomtb.notify.RideNotifier
import io.github.angkyria.karoomtb.notify.SummaryFormatter
import io.github.angkyria.karoomtb.notify.Units
import io.github.angkyria.karoomtb.service.ServiceTracker
import io.github.angkyria.karoomtb.storage.RideStore
import io.hammerhead.karooext.KarooSystemService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Settings screen (open "MTB Dynamics" from the Karoo app drawer). */
class MainActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val karoo by lazy { KarooSystemService(applicationContext) }
    private lateinit var settings: Settings
    private lateinit var store: RideStore
    private lateinit var notifier: RideNotifier

    private lateinit var ntfyEnabled: Switch
    private lateinit var ntfyServer: EditText
    private lateinit var ntfyTopic: EditText
    private lateinit var ntfyToken: EditText
    private lateinit var ntfyClick: EditText
    private lateinit var ntfyPriority: Spinner
    private lateinit var minMinutes: EditText
    private lateinit var ntfyAttach: Switch
    private lateinit var sensitivity: Spinner
    private lateinit var jumpAlerts: Switch
    private lateinit var jumpBeep: Switch
    private lateinit var alertDescent: Switch
    private lateinit var mtbOnly: Switch
    private lateinit var segmentElev: EditText
    private lateinit var fitNative: Switch
    private lateinit var debugRawImu: Switch
    private lateinit var alertSuspension: Switch
    private lateinit var alertShift: Switch
    private lateinit var alertBattery: Switch
    private lateinit var qr: ImageView
    private lateinit var qrHint: TextView
    private lateinit var testResult: TextView
    private lateinit var lastRide: TextView
    private lateinit var service: ServiceSection
    private lateinit var panels: PanelSection

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        MtbRuntime.init(applicationContext)
        settings = MtbRuntime.settings
        store = MtbRuntime.store
        notifier = RideNotifier(settings, store, HttpSender(karoo)) { MtbRuntime.service.notices(it) }

        ntfyEnabled = findViewById(R.id.ntfy_enabled)
        ntfyServer = findViewById(R.id.ntfy_server)
        ntfyTopic = findViewById(R.id.ntfy_topic)
        ntfyToken = findViewById(R.id.ntfy_token)
        ntfyClick = findViewById(R.id.ntfy_click)
        ntfyPriority = findViewById(R.id.ntfy_priority)
        minMinutes = findViewById(R.id.min_minutes)
        ntfyAttach = findViewById(R.id.ntfy_attach)
        sensitivity = findViewById(R.id.sensitivity)
        jumpAlerts = findViewById(R.id.jump_alerts)
        jumpBeep = findViewById(R.id.jump_beep)
        alertDescent = findViewById(R.id.alert_descent)
        mtbOnly = findViewById(R.id.mtb_only)
        segmentElev = findViewById(R.id.segment_elev)
        fitNative = findViewById(R.id.fit_native)
        debugRawImu = findViewById(R.id.debug_raw_imu)
        alertSuspension = findViewById(R.id.alert_suspension)
        alertShift = findViewById(R.id.alert_shift)
        alertBattery = findViewById(R.id.alert_battery)
        qr = findViewById(R.id.qr)
        qrHint = findViewById(R.id.qr_hint)
        testResult = findViewById(R.id.test_result)
        lastRide = findViewById(R.id.last_ride)
        service = ServiceSection(this, findViewById(R.id.service_items), findViewById(R.id.service_summary), MtbRuntime.service, ::units)
        panels = PanelSection(this, findViewById(R.id.panel_items), settings).also { it.render() }

        ntfyPriority.adapter = adapter(listOf("1 · min", "2 · low", "3 · default", "4 · high", "5 · urgent"))
        sensitivity.adapter = adapter(listOf("Low · only clear jumps", "Medium", "High · small hops too"))

        findViewById<TextView>(R.id.info).text = sensorInfo()
        findViewById<TextView>(R.id.storage).text =
            "Each ride is also saved as CSV + JSON (for tools/mtb_analyze.py):\n${store.rootPath}\n\n" +
            "FIT developer fields: mtb_grit, mtb_flow, mtb_rough, mtb_lat_g, mtb_brake, mtb_jump_air, " +
            "mtb_jump_dist, mtb_jump_height (records) and mtb_total_grit, mtb_flow_score, mtb_jumps, … (session); " +
            "with Flight Attendant / AXS also mtb_fa_open_desc, mtb_fa_lock_rough, mtb_shifts, mtb_climb_power, … " +
            "Service totals: ${ServiceTracker.FILE_NAME} next to the rides folder."

        load()
        val qrUpdater = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: Editable?) = updateQr()
        }
        ntfyTopic.addTextChangedListener(qrUpdater)
        ntfyServer.addTextChangedListener(qrUpdater)

        val sensorButton = findViewById<Button>(R.id.sensor_test)
        val sensorResult = findViewById<TextView>(R.id.sensor_result)
        sensorButton.setOnClickListener {
            if (!save()) return@setOnClickListener
            sensorButton.isEnabled = false
            sensorResult.text = "Measuring for 5 s… keep the Karoo still, or toss it gently onto a cushion to test jump detection."
            SensorTest(this, settings.mtbConfig()).run(5) { result ->
                sensorResult.text = result
                sensorButton.isEnabled = true
            }
        }
        findViewById<Button>(R.id.new_topic).setOnClickListener { ntfyTopic.setText(Settings.randomTopic()) }
        findViewById<Button>(R.id.save).setOnClickListener {
            if (save()) {
                testResult.text = "Saved."
                service.render()
            }
        }
        findViewById<Button>(R.id.test).setOnClickListener {
            if (!save()) return@setOnClickListener
            testResult.text = "Sending…"
            scope.launch {
                val r = notifier.test(units())
                testResult.text = if (r.ok) "✔ Delivered (HTTP ${r.status}). Check the ntfy app." else "✘ Failed: ${r.status} ${r.detail}"
            }
        }
        findViewById<Button>(R.id.resend).setOnClickListener {
            val dir = store.latestFinished() ?: return@setOnClickListener
            val summary = store.summary(dir) ?: return@setOnClickListener
            testResult.text = "Sending last ride…"
            scope.launch {
                val r = notifier.publish(dir, summary, units(), waitForConnection = false, force = true, timeoutMs = 45_000)
                testResult.text = if (r.ok) "✔ Last ride sent." else "✘ Failed: ${r.status} ${r.detail}"
                showLastRide()
            }
        }
    }

    override fun onStart() {
        super.onStart()
        runCatching { karoo.connect() }
        showLastRide()
        service.render()
    }

    override fun onStop() {
        save()
        runCatching { karoo.disconnect() }
        super.onStop()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun load() {
        ntfyEnabled.isChecked = settings.ntfyEnabled
        ntfyServer.setText(settings.ntfyServer)
        ntfyTopic.setText(settings.ntfyTopic)
        ntfyToken.setText(settings.ntfyToken)
        ntfyClick.setText(settings.ntfyClickUrl)
        ntfyPriority.setSelection(settings.ntfyPriority - 1)
        minMinutes.setText(settings.minNotifyMinutes.toString())
        ntfyAttach.isChecked = settings.ntfyAttachJson
        sensitivity.setSelection(settings.sensitivity.ordinal)
        jumpAlerts.isChecked = settings.jumpAlerts
        jumpBeep.isChecked = settings.jumpBeep
        alertDescent.isChecked = settings.descentAlerts
        mtbOnly.isChecked = settings.mtbProfilesOnly
        segmentElev.setText(settings.segmentMinElevationM.toString())
        fitNative.isChecked = settings.writeNativeFit
        debugRawImu.isChecked = settings.debugRawImu
        alertSuspension.isChecked = settings.suspensionAlerts
        alertShift.isChecked = settings.shiftAdvice
        alertBattery.isChecked = settings.batteryAlerts
        updateQr()
    }

    /** @return false if the input is invalid (nothing is saved then). */
    private fun save(): Boolean {
        val topic = ntfyTopic.text.toString().trim()
        if (!NtfyRequest.isValidTopic(topic)) {
            ntfyTopic.error = "Letters, digits, - and _ only (max 64)"
            return false
        }
        settings.ntfyEnabled = ntfyEnabled.isChecked
        settings.ntfyServer = ntfyServer.text.toString().ifBlank { NtfyRequest.DEFAULT_SERVER }
        settings.ntfyTopic = topic
        settings.ntfyToken = ntfyToken.text.toString()
        settings.ntfyClickUrl = ntfyClick.text.toString()
        settings.ntfyPriority = ntfyPriority.selectedItemPosition + 1
        settings.minNotifyMinutes = minMinutes.text.toString().toIntOrNull() ?: settings.minNotifyMinutes
        settings.ntfyAttachJson = ntfyAttach.isChecked
        settings.sensitivity = Sensitivity.entries[sensitivity.selectedItemPosition.coerceIn(0, Sensitivity.entries.lastIndex)]
        settings.jumpAlerts = jumpAlerts.isChecked
        settings.jumpBeep = jumpBeep.isChecked
        settings.descentAlerts = alertDescent.isChecked
        settings.mtbProfilesOnly = mtbOnly.isChecked
        settings.segmentMinElevationM = segmentElev.text.toString().toIntOrNull() ?: settings.segmentMinElevationM
        settings.writeNativeFit = fitNative.isChecked
        settings.debugRawImu = debugRawImu.isChecked
        settings.suspensionAlerts = alertSuspension.isChecked
        settings.shiftAdvice = alertShift.isChecked
        settings.batteryAlerts = alertBattery.isChecked
        service.save()
        panels.save()
        return true
    }

    private fun updateQr() {
        val topic = ntfyTopic.text.toString().trim()
        val url = "${NtfyRequest.serverRoot(ntfyServer.text.toString())}/$topic"
        qrHint.text = "Scan with your phone and subscribe in the ntfy app:\n$url"
        if (!NtfyRequest.isValidTopic(topic)) {
            qr.setImageBitmap(null)
            return
        }
        val size = (180 * resources.displayMetrics.density).toInt()
        val bitmap = runCatching {
            val matrix = QRCodeWriter().encode(url, BarcodeFormat.QR_CODE, size, size, mapOf(EncodeHintType.MARGIN to 1))
            val pixels = IntArray(size * size) { i -> if (matrix[i % size, i / size]) Color.BLACK else Color.WHITE }
            Bitmap.createBitmap(pixels, size, size, Bitmap.Config.RGB_565)
        }.getOrNull()
        qr.setImageBitmap(bitmap)
    }

    private fun showLastRide() {
        val dir = store.latestFinished()
        val summary = dir?.let { store.summary(it) }
        findViewById<Button>(R.id.resend).visibility = if (summary == null) View.GONE else View.VISIBLE
        if (dir == null || summary == null) {
            lastRide.text = "No ride yet. Start a ride: MTB Dynamics runs automatically."
            return
        }
        val units = units()
        val date = SimpleDateFormat("EEE d MMM yyyy, HH:mm", Locale.getDefault()).format(Date(summary.startWallMs))
        val status = store.ntfyStatus(dir)?.let { "${it.state} ${it.detail}".trim() } ?: "not sent"
        lastRide.text = buildString {
            appendLine(date)
            appendLine(SummaryFormatter.oneLine(summary))
            appendLine("${units.distance(summary.distanceM)} · moving ${Units.duration(summary.movingSec)} · ${summary.cornering.count} corners")
            summary.jumps.longest?.let { appendLine("Longest jump ${String.format(Locale.ROOT, "%.2f s", it.airSec)} · ${units.meters(it.distanceM)}") }
            append("ntfy: $status")
        }
    }

    private fun units(): Units = MtbRuntime.units

    private fun sensorInfo(): String {
        val sm = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        fun describe(type: Int, label: String): String {
            val s = sm.getDefaultSensor(type) ?: return "$label: none"
            val hz = if (s.minDelay > 0) " (max ${1_000_000 / s.minDelay} Hz)" else ""
            return "$label: ${s.name}$hz"
        }
        return "Version ${BuildConfig.VERSION_NAME}\n" +
            describe(Sensor.TYPE_ACCELEROMETER, "Accelerometer") + "\n" +
            describe(Sensor.TYPE_GYROSCOPE, "Gyroscope")
    }

    private fun adapter(items: List<String>) =
        ArrayAdapter(this, android.R.layout.simple_spinner_item, items).apply {
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }
}
