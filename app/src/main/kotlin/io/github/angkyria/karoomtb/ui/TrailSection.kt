package io.github.angkyria.karoomtb.ui

import android.app.Activity
import android.app.AlertDialog
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.notify.Units
import io.github.angkyria.karoomtb.notify.Units.Companion.duration
import io.github.angkyria.karoomtb.notify.Units.Companion.fmt
import io.github.angkyria.karoomtb.trails.Trail
import io.github.angkyria.karoomtb.trails.TrailLibrary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** "Trails" part of the settings screen: recognised descents with their best run; rename or delete. */
class TrailSection(
    private val activity: Activity,
    private val container: LinearLayout,
    private val summary: TextView,
    private val library: TrailLibrary,
    private val units: () -> Units,
) {
    private val names = LinkedHashMap<Int, Pair<String, EditText>>()
    private val date = SimpleDateFormat("d MMM yyyy", Locale.getDefault())

    fun render() {
        container.removeAllViews()
        names.clear()
        val trails = library.state().trails.sortedByDescending { it.runs.size }
        summary.text = if (trails.isEmpty()) {
            "Every descent you ride is saved as a trail. Ride one again and the Karoo shows your time between the trail's " +
                "start and end, your rank and personal bests (alert at the bottom, ntfy summary)."
        } else {
            "${trails.size} trail${if (trails.size == 1) "" else "s"}, most ridden first. Rename them to find them in the summary."
        }
        trails.take(MAX_SHOWN).forEach(::addRow)
    }

    fun save() {
        for ((id, entry) in names) {
            val (original, edit) = entry
            val name = edit.text.toString().trim()
            if (name.isNotEmpty() && name != original) library.rename(id, name)
        }
    }

    private fun addRow(trail: Trail) {
        val u = units()
        val line = LinearLayout(activity).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val name = EditText(activity, null, 0, R.style.Input).apply {
            setText(trail.name)
            setSingleLine()
        }
        line.addView(name, LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f))
        val delete = Button(activity).apply {
            text = "Delete"
            setOnClickListener { confirmDelete(trail) }
        }
        line.addView(delete, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT))
        container.addView(line, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = dp(8) })
        val best = trail.best
        val info = TextView(activity, null, 0, R.style.Hint).apply {
            text = buildString {
                append("${u.distance(trail.distanceM)} · −${u.elevation(trail.dropM)} · ${trail.runs.size} run${if (trail.runs.size == 1) "" else "s"}")
                if (best != null) {
                    append(" · best ${duration(best.timeSec)} (${date.format(Date(best.rideStartWallMs))})")
                    append(fmt(" · smoothest Flow %.1f", trail.runs.minOf { it.flowScore }))
                }
            }
        }
        container.addView(info, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        names[trail.id] = trail.name to name
    }

    private fun confirmDelete(trail: Trail) {
        AlertDialog.Builder(activity)
            .setMessage("Delete ${trail.name} and its ${trail.runs.size} runs? The next ride down it starts a new trail.")
            .setPositiveButton("Delete") { _, _ ->
                save()
                library.delete(trail.id)
                render()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun dp(v: Int) = (v * activity.resources.displayMetrics.density).toInt()

    companion object {
        private const val MAX_SHOWN = 40
    }
}
