package io.github.angkyria.karoomtb.karoo

import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.engine.MapFeatures
import io.github.angkyria.karoomtb.engine.Polyline
import io.github.angkyria.karoomtb.engine.RoughSections
import io.hammerhead.karooext.models.ShowPolyline
import io.hammerhead.karooext.models.Symbol

/** Turns the ride's [MapFeatures] into karoo-ext map effects. Ids include the ride, so a new ride replaces the old layer. */
object MapLayer {
    private const val MAX_JUMPS = 100
    private const val LINE_WIDTH = 6
    private const val ORANGE = 0xFFFF8F00.toInt()
    private const val RED = 0xFFC62828.toInt()

    fun symbols(f: MapFeatures): List<Symbol> =
        f.jumps.takeLast(MAX_JUMPS).map { j ->
            Symbol.Icon(id = "jump-${f.ride}-${j.n}", lat = j.lat!!, lng = j.lon!!, iconRes = R.drawable.ic_jump, orientation = 0f)
        } + f.markers.map { m ->
            Symbol.POI(id = "mark-${f.ride}-${m.n}", lat = m.lat!!, lng = m.lon!!, type = Symbol.POI.Types.GENERIC, name = "Mark ${m.n}")
        }

    fun polylines(f: MapFeatures): Map<String, ShowPolyline> = f.rough.associate { r ->
        val id = "rough-${f.ride}-${r.id}"
        id to ShowPolyline(id, Polyline.encode(r.points), if (r.avgRoughG >= RoughSections.VERY_ROUGH_G) RED else ORANGE, LINE_WIDTH)
    }
}
