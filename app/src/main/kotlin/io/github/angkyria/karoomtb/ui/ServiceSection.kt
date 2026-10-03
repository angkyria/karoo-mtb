package io.github.angkyria.karoomtb.ui

import android.app.Activity
import android.app.AlertDialog
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.notify.Units
import io.github.angkyria.karoomtb.notify.Units.Companion.fmt
import io.github.angkyria.karoomtb.service.ServiceBasis
import io.github.angkyria.karoomtb.service.ServiceState
import io.github.angkyria.karoomtb.service.ServiceStatus
import io.github.angkyria.karoomtb.service.ServiceTracker
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** "Service tracker" part of the settings screen: usage per item (editable) and a "Serviced" button. */
class ServiceSection(
    private val activity: Activity,
    private val container: LinearLayout,
    private val summary: TextView,
    private val tracker: ServiceTracker,
    private val units: () -> Units,
) {
    /** The texts as rendered: only fields the rider changed are saved (values are shown rounded). */
    private class Row(
        val status: ServiceStatus,
        val used: EditText,
        val interval: EditText,
        val miles: Boolean,
        val usedText: String = used.text.toString(),
        val intervalText: String = interval.text.toString(),
    )

    private val rows = ArrayList<Row>()
    private val date = SimpleDateFormat("d MMM yyyy", Locale.getDefault())

    fun render() {
        container.removeAllViews()
        rows.clear()
        val u = units()
        for (status in tracker.statuses()) addRow(status, u)
        summary.text = summaryText(tracker.state(), u)
    }

    /** Stores edited usage and intervals. */
    fun save() {
        for (row in rows) {
            val id = row.status.item.id
            val factor = if (row.miles) MILE_KM else 1.0
            val intervalText = row.interval.text.toString()
            val interval = intervalText.replace(',', '.').toDoubleOrNull()
            if (intervalText != row.intervalText && interval != null && interval > 0) tracker.setInterval(id, interval * factor)
            val usedText = row.used.text.toString()
            val used = usedText.replace(',', '.').toDoubleOrNull()
            if (usedText != row.usedText && used != null && used >= 0) tracker.setUsed(id, used * factor)
        }
    }

    private fun addRow(status: ServiceStatus, u: Units) {
        val miles = status.item.basis == ServiceBasis.DRIVETRAIN_KM && u.imperialDistance
        val unit = when {
            status.item.basis != ServiceBasis.DRIVETRAIN_KM -> "h"
            miles -> "mi"
            else -> "km"
        }
        val title = TextView(activity, null, 0, R.style.Label).apply {
            text = status.item.name
            setTextColor(activity.getColor(R.color.text_primary))
        }
        container.addView(title, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(10) })

        val state = when {
            status.due -> "DUE · "
            status.soon -> "soon · "
            else -> ""
        }
        val last = status.lastServiceWallMs?.let { " · serviced ${date.format(Date(it))}" } ?: ""
        val progress = TextView(activity, null, 0, R.style.Hint).apply {
            text = state + fmt("%.0f%% used", 100 * status.progress) + last
            if (status.due) setTextColor(activity.getColor(R.color.alert_warn_bg))
        }
        container.addView(progress, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))

        val line = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        fun number(value: Double) = EditText(activity, null, 0, R.style.Input).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText(fmt(if (value >= 100) "%.0f" else "%.1f", value))
            setSingleLine()
        }
        fun label(text: String) = TextView(activity, null, 0, R.style.Hint).apply {
            this.text = text
            setPadding(dp(4), 0, dp(4), 0)
        }
        val used = number(shown(status.used, miles))
        val interval = number(shown(status.interval, miles))
        line.addView(used, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        line.addView(label("$unit of"))
        line.addView(interval, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        line.addView(label(unit))
        val done = Button(activity).apply {
            text = "Serviced"
            setOnClickListener { confirmServiced(status) }
        }
        line.addView(done, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT))
        container.addView(line, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        rows += Row(status, used, interval, miles)
    }

    private fun confirmServiced(status: ServiceStatus) {
        AlertDialog.Builder(activity)
            .setMessage("${status.item.name} done today? Its usage starts again from zero.")
            .setPositiveButton("Yes") { _, _ ->
                save()
                tracker.markServiced(status.item.id)
                render()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun summaryText(state: ServiceState, u: Units): String {
        val t = state.totals
        if (t.rides == 0) {
            return "Counts the rides where the Karoo receives Flight Attendant or AXS data, so rides on other bikes do not add up. " +
                "Set how much each part has been used since its last service, or tap Serviced. " +
                "Default intervals follow the RockShox / SRAM service guides: check the manual of your parts."
        }
        val cogs = t.cogHours.entries.sortedByDescending { it.value }.take(4)
            .joinToString(", ") { fmt("%dT %.1f h", it.key, it.value) }
        val batteries = tracker.latestBatteries().joinToString(" · ") { b ->
            "${b.component} " + (b.percent?.let { "$it%" } ?: b.status.lowercase())
        }
        return buildString {
            appendLine("Since ${date.format(Date(t.sinceWallMs))} · ${t.rides} ride${if (t.rides == 1) "" else "s"} on this bike")
            appendLine(fmt("Fork %.1f h (%.1f h rough) · shock %.1f h · %,d Flight Attendant changes", t.forkHours, t.roughHours, t.shockHours, t.faChanges))
            append("Drivetrain ${u.distance(t.drivetrainKm * 1000)} · " + fmt("%,d shifts", t.shifts))
            if (cogs.isNotEmpty()) append(" · most used cogs $cogs")
            if (batteries.isNotEmpty()) append("\nBatteries (last ride): $batteries")
            append("\nDefault intervals follow the RockShox / SRAM service guides: check the manual of your parts.")
        }
    }

    private fun shown(value: Double, miles: Boolean) = if (miles) value / MILE_KM else value

    private fun dp(v: Int) = (v * activity.resources.displayMetrics.density).toInt()

    companion object {
        private const val MILE_KM = 1.609344
    }
}
