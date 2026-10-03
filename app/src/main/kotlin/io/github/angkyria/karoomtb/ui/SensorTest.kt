package io.github.angkyria.karoomtb.ui

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import io.github.angkyria.karoomtb.engine.ImuProcessor
import io.github.angkyria.karoomtb.engine.JumpDetector
import io.github.angkyria.karoomtb.engine.MtbConfig
import io.github.angkyria.karoomtb.engine.RawJump
import java.util.Locale
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Runs the accelerometer / gyroscope for a few seconds through the same processing as a ride:
 * shows the real sample rates, |a| at rest and vibration, and whether a flight (gently toss the
 * Karoo onto a cushion) would be detected as a jump.
 */
class SensorTest(context: Context, private val config: MtbConfig) : SensorEventListener {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val lock = Any()
    private val imu = ImuProcessor()
    private val detector = JumpDetector(config)
    private var accelCount = 0
    private var gyroCount = 0
    private var firstNs = 0L
    private var lastAccelNs = 0L
    private var lastGyroNs = 0L
    private var firstGyroNs = 0L
    private var minG = Double.MAX_VALUE
    private var maxG = 0.0
    private var sumG = 0.0
    private var maxRotation = 0.0
    private val flights = ArrayList<RawJump>()

    fun run(seconds: Int, onDone: (String) -> Unit) {
        val accel = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        if (accel == null) {
            onDone("No accelerometer found: jumps and roughness are not available.")
            return
        }
        val gyro = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        val thread = HandlerThread("mtb-sensor-test").apply { start() }
        val handler = Handler(thread.looper)
        sensorManager.registerListener(this, accel, SAMPLING_US, handler)
        gyro?.let { sensorManager.registerListener(this, it, SAMPLING_US, handler) }
        Handler(Looper.getMainLooper()).postDelayed({
            sensorManager.unregisterListener(this)
            thread.quitSafely()
            onDone(report(gyro != null))
        }, seconds * 1000L)
    }

    override fun onSensorChanged(event: SensorEvent) = synchronized(lock) {
        val v = event.values
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                if (firstNs == 0L) firstNs = event.timestamp
                lastAccelNs = event.timestamp
                accelCount++
                val t = event.timestamp / 1e9
                val air = detector.airborne
                imu.onAccel(t, v[0].toDouble(), v[1].toDouble(), v[2].toDouble(), freezeGravity = air, countRoughness = !air)
                detector.onAccel(t, imu.magLpG, imu.magG)?.let { flights += it }
                if (accelCount > WARMUP) {
                    minG = min(minG, imu.magLpG)
                    maxG = max(maxG, imu.magG)
                    sumG += imu.magG
                }
            }
            Sensor.TYPE_GYROSCOPE -> {
                if (firstGyroNs == 0L) firstGyroNs = event.timestamp
                lastGyroNs = event.timestamp
                gyroCount++
                maxRotation = max(maxRotation, sqrt((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).toDouble()))
                detector.onGyro(event.timestamp / 1e9, v[0].toDouble(), v[1].toDouble(), v[2].toDouble())
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    private fun report(hasGyro: Boolean): String = synchronized(lock) {
        fun rate(count: Int, first: Long, last: Long) = if (last > first) (count - 1) / ((last - first) / 1e9) else 0.0
        val n = (accelCount - WARMUP).coerceAtLeast(1)
        val rough = imu.drainSecond().roughG
        buildString {
            append(String.format(Locale.ROOT, "Accelerometer %.0f Hz", rate(accelCount, firstNs, lastAccelNs)))
            append(if (hasGyro) String.format(Locale.ROOT, " · gyroscope %.0f Hz\n", rate(gyroCount, firstGyroNs, lastGyroNs)) else " · no gyroscope\n")
            append(String.format(Locale.ROOT, "|a| average %.2f g (filtered min %.2f g, peak %.2f g)\n", sumG / n, minG, maxG))
            append(String.format(Locale.ROOT, "Vibration %.3f g RMS · max rotation %.0f°/s\n", rough, Math.toDegrees(maxRotation)))
            if (flights.isEmpty()) {
                append(
                    String.format(
                        Locale.ROOT, "No flight detected (needs < %.2f g for %.2f s and a landing ≥ %.2f g).",
                        config.sensitivity.takeoffG, config.sensitivity.minAirSec, config.sensitivity.minLandingG,
                    ),
                )
            } else {
                append("Detected flights: " + flights.joinToString { String.format(Locale.ROOT, "%.2f s (landing %.1f g)", it.airSec, it.landingG) })
            }
        }
    }

    companion object {
        private const val SAMPLING_US = 10_000
        private const val WARMUP = 20
    }
}
