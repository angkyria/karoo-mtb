package io.github.angkyria.karoomtb.notify

import android.util.Log
import io.github.angkyria.karoomtb.Settings
import io.github.angkyria.karoomtb.engine.RideSummary
import io.github.angkyria.karoomtb.storage.NtfyStatus
import io.github.angkyria.karoomtb.storage.RideStore
import kotlinx.serialization.encodeToString
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

/** Publishes ride summaries to ntfy and keeps track of what still has to be delivered. */
class RideNotifier(
    private val settings: Settings,
    private val store: RideStore,
    private val sender: HttpSender,
    /** Extra lines for every summary, e.g. service reminders. */
    private val notices: (Units) -> List<String> = { emptyList() },
) {
    /**
     * Sends the summary of [ride]. At the end of a ride [waitForConnection] is true: the Karoo
     * queues the request until Wi-Fi or the companion app is available.
     */
    suspend fun publish(
        ride: File,
        summary: RideSummary,
        units: Units,
        waitForConnection: Boolean = true,
        force: Boolean = false,
        timeoutMs: Long? = null,
    ): SendResult {
        // A request may sit in the Karoo queue for hours; never send the same ride twice at once.
        if (!inFlight.add(ride.name)) return SendResult(false, 0, "already being sent")
        try {
            return publishOnce(ride, summary, units, waitForConnection, force, timeoutMs)
        } finally {
            inFlight.remove(ride.name)
        }
    }

    private suspend fun publishOnce(
        ride: File,
        summary: RideSummary,
        units: Units,
        waitForConnection: Boolean,
        force: Boolean,
        timeoutMs: Long?,
    ): SendResult {
        if (!settings.ntfyEnabled && !force) {
            store.setNtfyStatus(ride, NtfyStatus(NtfyStatus.SKIPPED, "ntfy disabled"))
            return SendResult(false, 0, "ntfy disabled")
        }
        if (!force && summary.movingSec < settings.minNotifyMinutes * 60) {
            store.setNtfyStatus(ride, NtfyStatus(NtfyStatus.SKIPPED, "ride shorter than ${settings.minNotifyMinutes} min"))
            return SendResult(false, 0, "ride too short")
        }
        val target = settings.ntfyTarget()
        if (!NtfyRequest.isValidTopic(target.topic)) {
            store.setNtfyStatus(ride, NtfyStatus(NtfyStatus.FAILED, "invalid topic"))
            return SendResult(false, 0, "invalid ntfy topic")
        }
        store.setNtfyStatus(ride, NtfyStatus(NtfyStatus.PENDING))
        val text = SummaryFormatter.markdown(
            summary, units, runCatching { notices(units) }.getOrDefault(emptyList()), mapLinks = settings.ntfyMapLinks,
        )
        val request = NtfyRequest.message(target, SummaryFormatter.title(summary), text)
        val result = sender.send(request, waitForConnection, timeoutMs)
        val state = when {
            result.ok -> NtfyStatus.SENT
            result.permanentFailure -> NtfyStatus.FAILED
            else -> NtfyStatus.PENDING
        }
        store.setNtfyStatus(ride, NtfyStatus(state, "HTTP ${result.status} ${result.detail}".trim()))
        Log.i(TAG, "ride ${ride.name}: ntfy $state (${result.status})")

        if (result.ok && settings.ntfyAttachJson) {
            val content = RideStore.json.encodeToString(trimmed(summary)).toByteArray()
            if (content.size <= NtfyRequest.MAX_BODY_BYTES) {
                val name = "mtb-" + SimpleDateFormat("yyyyMMdd-HHmm", Locale.ROOT).format(Date(summary.startWallMs)) + ".json"
                sender.send(NtfyRequest.attachment(target, name, content, "Full MTB Dynamics report (JSON)"), waitForConnection)
            }
        }
        return result
    }

    /** Re-sends summaries whose delivery did not complete (e.g. the extension restarted). */
    suspend fun retryPending(units: Units) {
        val cutoff = System.currentTimeMillis() - RETRY_WINDOW_MS
        for (ride in store.rides()) {
            val status = store.ntfyStatus(ride) ?: continue
            if (status.state != NtfyStatus.PENDING) continue
            val summary = store.summary(ride) ?: continue
            if (summary.endWallMs < cutoff) continue
            publish(ride, summary, units)
        }
    }

    /** Sends a short test message; does not wait for a connection. */
    suspend fun test(units: Units): SendResult {
        val target = settings.ntfyTarget()
        if (!NtfyRequest.isValidTopic(target.topic)) return SendResult(false, 0, "invalid topic")
        val text = "✅ MTB Dynamics is connected. Ride summaries will arrive here when a ride ends.\n\n" +
            "Units: ${units.speed(10.0)} · ${units.elevation(100.0)}"
        return sender.send(NtfyRequest.message(target, "MTB Dynamics test", text), waitForConnection = false, timeoutMs = 45_000)
    }

    /** The full jump list can be long; keep the attachment below the Karoo's 100 KB limit. */
    private fun trimmed(summary: RideSummary): RideSummary {
        var s = summary
        while (RideStore.json.encodeToString(s).length > NtfyRequest.MAX_BODY_BYTES && s.jumps.list.isNotEmpty()) {
            s = s.copy(jumps = s.jumps.copy(list = s.jumps.list.take(s.jumps.list.size / 2)))
        }
        return s
    }

    companion object {
        private const val TAG = "MtbNotifier"
        private const val RETRY_WINDOW_MS = 7L * 24 * 3600 * 1000

        /** Process-wide: the extension service and the settings screen share it. */
        private val inFlight: MutableSet<String> = ConcurrentHashMap.newKeySet()
    }
}
