package io.github.angkyria.karoomtb.notify

import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.util.Base64

/** A ready-to-send HTTP request (sent through the Karoo, or directly as a fallback). */
data class HttpRequestSpec(
    val method: String,
    val url: String,
    val headers: Map<String, String>,
    val body: ByteArray,
) {
    override fun equals(other: Any?): Boolean =
        other is HttpRequestSpec && method == other.method && url == other.url && headers == other.headers && body.contentEquals(other.body)

    override fun hashCode(): Int = ((method.hashCode() * 31 + url.hashCode()) * 31 + headers.hashCode()) * 31 + body.contentHashCode()
}

data class NtfyTarget(
    val server: String,
    val topic: String,
    /** Access token (tk_...) or "user:password"; blank for open topics. */
    val token: String = "",
    val priority: Int = 3,
    val clickUrl: String = "",
)

/**
 * Builds ntfy publish requests. Messages are published as JSON to the server root, which
 * keeps emoji and non-ASCII text out of HTTP headers. See https://docs.ntfy.sh/publish/
 */
object NtfyRequest {
    const val DEFAULT_SERVER = "https://ntfy.sh"

    /** The Karoo HTTP bridge refuses bodies above 100 KB. */
    const val MAX_BODY_BYTES = 95_000

    fun serverRoot(server: String): String {
        val trimmed = server.trim().trimEnd('/')
        if (trimmed.isEmpty()) return DEFAULT_SERVER
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "https://$trimmed"
    }

    fun authHeader(token: String): String? {
        val t = token.trim()
        if (t.isEmpty()) return null
        return if (t.contains(':')) {
            "Basic " + Base64.getEncoder().encodeToString(t.toByteArray())
        } else {
            "Bearer $t"
        }
    }

    fun isValidTopic(topic: String): Boolean = topic.matches(Regex("[-_A-Za-z0-9]{1,64}"))

    fun message(
        target: NtfyTarget,
        title: String,
        markdown: String,
        tags: List<String> = listOf("mountain_bicyclist"),
    ): HttpRequestSpec {
        val json = buildJsonObject {
            put("topic", target.topic.trim())
            put("title", title)
            put("message", markdown)
            put("markdown", true)
            put("priority", target.priority.coerceIn(1, 5))
            putJsonArray("tags") { tags.forEach { add(it) } }
            if (target.clickUrl.isNotBlank()) put("click", target.clickUrl.trim())
        }.toString()
        return HttpRequestSpec("POST", serverRoot(target.server), headers(target, "application/json"), json.toByteArray())
    }

    /** Publishes [content] as a file attachment (ntfy stores it and links it in the notification). */
    fun attachment(target: NtfyTarget, filename: String, content: ByteArray, text: String): HttpRequestSpec {
        val headers = headers(target, "application/json").toMutableMap()
        headers["Filename"] = filename
        headers["Message"] = text
        headers["Tags"] = "page_facing_up"
        headers["Priority"] = "2"
        return HttpRequestSpec("PUT", "${serverRoot(target.server)}/${target.topic.trim()}", headers, content)
    }

    private fun headers(target: NtfyTarget, contentType: String): Map<String, String> = buildMap {
        put("Content-Type", contentType)
        put("User-Agent", "karoo-mtb")
        authHeader(target.token)?.let { put("Authorization", it) }
    }
}
