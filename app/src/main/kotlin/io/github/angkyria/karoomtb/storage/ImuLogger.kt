package io.github.angkyria.karoomtb.storage

import android.util.Log
import java.io.BufferedWriter
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStreamWriter
import java.util.Locale
import java.util.zip.GZIPOutputStream

/**
 * Debug option: writes every accelerometer / gyroscope sample of a ride to `imu.csv.gz`
 * (≈ 3 MB per hour) so jump detection and roughness can be re-tuned offline with
 * `tools/mtb_analyze.py --karoo-dir <ride> --imu`.
 *
 * Lines: `a|g,elapsed_ms,x,y,z` (m/s² or rad/s, device axes). The header maps elapsed time to
 * wall-clock time. Appending after a restart produces a multi-member gzip, which readers accept.
 */
class ImuLogger(file: File, wallMs: Long, elapsedNanos: Long) {
    private val lock = Any()
    private var writer: BufferedWriter? = try {
        BufferedWriter(OutputStreamWriter(GZIPOutputStream(FileOutputStream(file, true), 64 * 1024)), 64 * 1024).also {
            it.write("# wall_ms=$wallMs elapsed_ms=${elapsedNanos / 1_000_000}\n")
            it.write("sensor,elapsed_ms,x,y,z\n")
        }
    } catch (e: Exception) {
        Log.w(TAG, "cannot open $file", e)
        null
    }

    fun write(sensor: Char, timestampNs: Long, x: Float, y: Float, z: Float) = synchronized(lock) {
        val w = writer ?: return
        try {
            w.write(String.format(Locale.ROOT, "%c,%.2f,%.4f,%.4f,%.4f\n", sensor, timestampNs / 1e6, x, y, z))
        } catch (e: Exception) {
            Log.w(TAG, "write failed, stopping raw log", e)
            close()
        }
    }

    fun close() = synchronized(lock) {
        try {
            writer?.close()
        } catch (e: Exception) {
            Log.w(TAG, "close failed", e)
        }
        writer = null
    }

    companion object {
        private const val TAG = "MtbImuLog"
        const val FILE_NAME = "imu.csv.gz"
    }
}
