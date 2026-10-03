package io.github.angkyria.karoomtb.notify

import android.util.Log
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.storage.NtfyStatus
import io.github.angkyria.karoomtb.storage.RideStore
import java.io.File

/** intervals.icu settings ([io.github.angkyria.karoomtb.Settings.icuConfig]). */
data class IcuConfig(val enabled: Boolean, val apiKey: String, val athleteId: String = "0", val fields: Boolean = false)

/**
 * Puts the MTB block into the description of the intervals.icu activity the Karoo uploaded for a
 * ride (optionally the custom fields too), so the copy-paste custom field setup is not needed for
 * the basics. The upload reaches intervals.icu some minutes after the ride, so a ride stays
 * "pending" until its activity shows up (retried for [RETRY_WINDOW_MS]).
 */
class IcuUploader(
    private val config: () -> IcuConfig,
    private val store: RideStore,
    private val sender: HttpClient,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    val enabled: Boolean get() = config().let { it.enabled && it.apiKey.isNotBlank() }

    suspend fun publish(ride: File, summary: RideSummary, units: Units, waitForConnection: Boolean = true, timeoutMs: Long? = null): SendResult {
        if (!enabled) return SendResult(false, 0, "intervals.icu off")
        val c = config()
        val key = c.apiKey
        val list = sender.send(IcuRequest.activities(key, c.athleteId, summary.startWallMs), waitForConnection, timeoutMs)
        if (!list.ok) return record(ride, list, "activities")
        val id = IcuRequest.findActivity(list.body, summary.startWallMs)
        if (id == null) {
            store.setIcuStatus(ride, NtfyStatus(NtfyStatus.PENDING, "activity not on intervals.icu yet"))
            return SendResult(false, 0, "activity not on intervals.icu yet")
        }
        val activity = sender.send(IcuRequest.activity(key, id), waitForConnection, timeoutMs)
        if (!activity.ok) return record(ride, activity, "activity $id")
        val description = IcuRequest.mergedDescription(IcuRequest.description(activity.body), IcuRequest.block(summary, units))
        var result = sender.send(IcuRequest.update(key, id, IcuRequest.updateBody(description, summary, c.fields)), waitForConnection, timeoutMs)
        var note = ""
        if (!result.ok && result.permanentFailure && c.fields) {
            // Custom fields that do not exist on intervals.icu: keep at least the description.
            result = sender.send(IcuRequest.update(key, id, IcuRequest.updateBody(description, null, false)), waitForConnection, timeoutMs)
            note = " (custom fields refused: create them on intervals.icu)"
        }
        record(ride, result, "activity $id", note)
        Log.i(TAG, "ride ${ride.name}: intervals.icu activity $id -> ${result.status}$note")
        return result
    }

    /** Rides whose activity was not found yet or whose update did not get through. */
    suspend fun retryPending(units: Units) {
        if (!enabled) return
        val cutoff = clock() - RETRY_WINDOW_MS
        for (ride in store.rides()) {
            val status = store.icuStatus(ride) ?: continue
            if (status.state != NtfyStatus.PENDING) continue
            val summary = store.summary(ride) ?: continue
            if (summary.endWallMs < cutoff) {
                store.setIcuStatus(ride, NtfyStatus(NtfyStatus.FAILED, "activity never showed up on intervals.icu"))
                continue
            }
            publish(ride, summary, units)
        }
    }

    /** Checks the API key: the athlete's name, or the error. */
    suspend fun test(): SendResult {
        val c = config()
        if (c.apiKey.isBlank()) return SendResult(false, 0, "no API key")
        val r = sender.send(IcuRequest.athlete(c.apiKey, c.athleteId), waitForConnection = false, timeoutMs = 30_000)
        val name = Regex("\"name\"\\s*:\\s*\"([^\"]*)\"").find(r.body)?.groupValues?.get(1)
        return if (r.ok) r.copy(detail = name ?: "connected") else r
    }

    fun markPending(ride: File) {
        if (enabled) store.setIcuStatus(ride, NtfyStatus(NtfyStatus.PENDING, "waiting for the upload"))
    }

    private fun record(ride: File, r: SendResult, what: String, note: String = ""): SendResult {
        val state = when {
            r.ok -> NtfyStatus.SENT
            r.permanentFailure -> NtfyStatus.FAILED
            else -> NtfyStatus.PENDING
        }
        val detail = when {
            r.ok -> "description updated ($what)$note"
            r.status == 401 || r.status == 403 -> "HTTP ${r.status}: check the API key / athlete id"
            else -> "HTTP ${r.status} ${r.detail.take(80)} ($what)"
        }
        store.setIcuStatus(ride, NtfyStatus(state, detail))
        return r
    }

    companion object {
        private const val TAG = "MtbIcu"
        const val RETRY_WINDOW_MS = 3L * 24 * 3600 * 1000
    }
}
