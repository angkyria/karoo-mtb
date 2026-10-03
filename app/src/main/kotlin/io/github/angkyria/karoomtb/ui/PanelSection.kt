package io.github.angkyria.karoomtb.ui

import android.app.Activity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.ArrayAdapter
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.TextView
import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.Settings
import io.github.angkyria.karoomtb.karoo.Panel
import io.github.angkyria.karoomtb.karoo.PanelCell

/** "Data field panels" part of the settings screen: the cells of each graphical panel field. */
class PanelSection(
    private val activity: Activity,
    private val container: LinearLayout,
    private val settings: Settings,
) {
    private val spinners = LinkedHashMap<Panel, List<Spinner>>()

    fun render() {
        container.removeAllViews()
        spinners.clear()
        val names = PanelCell.entries.map { it.title }
        for (panel in Panel.entries) {
            val title = TextView(activity, null, 0, R.style.Label).apply {
                text = "${panel.title}: cells 1-4, and 5-6 when the field is tall"
                setTextColor(activity.getColor(R.color.text_primary))
            }
            container.addView(title, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            val current = settings.panelCells(panel)
            spinners[panel] = (0 until Panel.CELLS).map { i ->
                Spinner(activity).apply {
                    adapter = ArrayAdapter(activity, android.R.layout.simple_spinner_item, names.map { "${i + 1}. $it" }).apply {
                        setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
                    }
                    setSelection(current[i].ordinal)
                    container.addView(this, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
                }
            }
        }
    }

    fun save() {
        for ((panel, list) in spinners) {
            settings.setPanelCells(panel, list.map { PanelCell.entries[it.selectedItemPosition.coerceIn(0, PanelCell.entries.lastIndex)] })
        }
    }
}
