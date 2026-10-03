package io.github.angkyria.karoomtb.notify

import android.util.Log
import io.hammerhead.karooext.KarooSystemService
import io.hammerhead.karooext.models.HttpResponseState
import io.hammerhead.karooext.models.OnHttpResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.resume

/** [detail]: the first 200 characters of the response or the error; [body]: the whole response. */
data class SendResult(val ok: Boolean, val status: Int, val detail: String, val body: String = "") {
    /** 4xx other than 408/429 will not get better by retrying (bad topic, token, ...). */
    val permanentFailure: Boolean get() = !ok && status in 400..499 && status != 408 && status != 429
}

/** Something that sends an [HttpRequestSpec] (the Karoo bridge in the app, a fake in tests). */
interface HttpClient {
    suspend fun send(request: HttpRequestSpec, waitForConnection: Boolean, timeoutMs: Long? = null): SendResult
}

/**
 * Sends HTTP requests through the Karoo's network bridge, which uses Wi-Fi, LTE (Karoo 2) or
 * the phone via the Hammerhead companion app over Bluetooth (Karoo 3). Falls back to a direct
 * connection when the Karoo system service is not available.
 */
class HttpSender(private val karoo: KarooSystemService?) : HttpClient {

    /**
     * @param waitForConnection queue on the Karoo until a connection exists (ride end); false for
     *   interactive tests.
     */
    override suspend fun send(request: HttpRequestSpec, waitForConnection: Boolean, timeoutMs: Long?): SendResult {
        // The settings screen binds to the Karoo system asynchronously; give it a moment.
        if (karoo != null && !karoo.connected) withTimeoutOrNull(BIND_WAIT_MS) { while (!karoo.connected) delay(100) }
        val viaKaroo = karoo?.takeIf { it.connected }
        val call: suspend () -> SendResult = {
            if (viaKaroo != null) sendViaKaroo(viaKaroo, request, waitForConnection) else sendDirect(request)
        }
        return if (timeoutMs == null) call() else withTimeoutOrNull(timeoutMs) { call() }
            ?: SendResult(false, -1, "timeout (no network?)")
    }

    private suspend fun sendViaKaroo(karoo: KarooSystemService, request: HttpRequestSpec, wait: Boolean): SendResult =
        suspendCancellableCoroutine { cont ->
            val consumerId = AtomicReference<String?>(null)
            fun finish(result: SendResult) {
                consumerId.getAndSet(null)?.let { karoo.removeConsumer(it) }
                if (cont.isActive) cont.resume(result)
            }
            val params = OnHttpResponse.MakeHttpRequest(
                method = request.method,
                url = request.url,
                headers = request.headers,
                body = request.body,
                waitForConnection = wait,
            )
            val id = karoo.addConsumer(
                params,
                onError = { error -> finish(SendResult(false, -1, error)) },
                onComplete = { if (cont.isActive) finish(SendResult(false, -1, "no response")) },
            ) { event: OnHttpResponse ->
                when (val state = event.state) {
                    is HttpResponseState.Complete -> {
                        val body = state.body?.decodeToString() ?: ""
                        val text = state.error ?: body.take(200)
                        Log.i(TAG, "${request.method} ${request.url.substringBefore('?')} -> ${state.statusCode} ${text.take(80)}")
                        finish(SendResult(state.statusCode in 200..299, state.statusCode, text, body))
                    }
                    else -> Log.d(TAG, "${request.url}: $state")
                }
            }
            consumerId.set(id)
            cont.invokeOnCancellation { consumerId.getAndSet(null)?.let { karoo.removeConsumer(it) } }
        }

    private suspend fun sendDirect(request: HttpRequestSpec): SendResult = withContext(Dispatchers.IO) {
        try {
            val conn = URL(request.url).openConnection() as HttpURLConnection
            conn.requestMethod = request.method
            conn.connectTimeout = 15_000
            conn.readTimeout = 20_000
            request.headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            // A GET must not get an output stream (HttpURLConnection would turn it into a POST).
            if (request.method != "GET") {
                conn.doOutput = true
                conn.outputStream.use { it.write(request.body) }
            }
            val code = conn.responseCode
            val text = (if (code < 400) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            SendResult(code in 200..299, code, text.take(200), text)
        } catch (e: Exception) {
            Log.w(TAG, "direct send failed", e)
            SendResult(false, -1, e.message ?: e.javaClass.simpleName)
        }
    }

    companion object {
        private const val TAG = "MtbHttp"
        private const val BIND_WAIT_MS = 3_000L
    }
}
