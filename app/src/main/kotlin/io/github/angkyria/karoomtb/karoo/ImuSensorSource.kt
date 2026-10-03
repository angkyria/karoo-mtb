package io.github.angkyria.karoomtb.karoo

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import android.os.Process
import android.os.SystemClock
import android.util.Log
import io.github.angkyria.karoomtb.engine.MtbEngine
import io.github.angkyria.karoomtb.storage.ImuLogger
import kotlin.math.abs

/**
 * Streams the Karoo's accelerometer and gyroscope into the engine on a dedicated thread.
 * Both Karoo 2 and Karoo 3 expose them through the normal Android SensorManager.
 */
class ImuSensorSource(context: Context, private val engine: MtbEngine) : SensorEventListener {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private var thread: HandlerThread? = null

    /** Sensor clocks are usually elapsedRealtimeNanos; if a device uses another base we shift it. */
    @Volatile
    private var timestampOffsetNs: Long? = null

    /** Debug: raw sample log for offline tuning (null = off). */
    @Volatile
    var rawLogger: ImuLogger? = null

    val hasAccelerometer: Boolean get() = accelerometer != null
    val hasGyroscope: Boolean get() = gyroscope != null

    @Synchronized
    fun start(): Boolean {
        if (thread != null) return true
        if (accelerometer == null && gyroscope == null) {
            Log.w(TAG, "No accelerometer or gyroscope: jumps and roughness disabled")
            return false
        }
        val t = HandlerThread("mtb-imu", Process.THREAD_PRIORITY_MORE_FAVORABLE).apply { start() }
        thread = t
        timestampOffsetNs = null
        val handler = Handler(t.looper)
        val ok = listOfNotNull(accelerometer, gyroscope).map { sensor ->
            try {
                sensorManager.registerListener(this, sensor, SAMPLING_PERIOD_US, MAX_REPORT_LATENCY_US, handler)
            } catch (e: SecurityException) {
                Log.e(TAG, "registerListener(${sensor.name}) denied", e)
                false
            }
        }
        Log.i(TAG, "IMU started accel=${accelerometer?.name} gyro=${gyroscope?.name} ok=$ok")
        return ok.any { it }
    }

    @Synchronized
    fun stop() {
        sensorManager.unregisterListener(this)
        thread?.quitSafely()
        thread = null
    }

    override fun onSensorChanged(event: SensorEvent) {
        val offset = timestampOffsetNs ?: run {
            val diff = SystemClock.elapsedRealtimeNanos() - event.timestamp
            (if (abs(diff) > 1_000_000_000L) diff else 0L).also { timestampOffsetNs = it }
        }
        val t = event.timestamp + offset
        val v = event.values
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                engine.onAccel(t, v[0], v[1], v[2])
                rawLogger?.write('a', t, v[0], v[1], v[2])
            }
            Sensor.TYPE_GYROSCOPE -> {
                engine.onGyro(t, v[0], v[1], v[2])
                rawLogger?.write('g', t, v[0], v[1], v[2])
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) = Unit

    companion object {
        private const val TAG = "MtbImu"

        /** 100 Hz requested; the hardware may deliver less (the engine adapts to the real rate). */
        private const val SAMPLING_PERIOD_US = 10_000

        /** Batch in the sensor FIFO for up to 100 ms to save wake-ups. */
        private const val MAX_REPORT_LATENCY_US = 100_000
    }
}
