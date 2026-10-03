package io.github.angkyria.karoomtb.karoo

import android.content.Context
import android.content.res.Configuration
import android.graphics.Color
import android.util.TypedValue
import android.view.View
import android.widget.RemoteViews
import io.github.angkyria.karoomtb.R
import io.github.angkyria.karoomtb.engine.FaState
import io.github.angkyria.karoomtb.engine.LiveDescent
import io.github.angkyria.karoomtb.engine.LiveMetrics
import io.github.angkyria.karoomtb.engine.RideStatus
import io.github.angkyria.karoomtb.engine.SuspensionMatch
import io.hammerhead.karooext.extension.DataTypeImpl
import io.hammerhead.karooext.internal.Emitter
import io.hammerhead.karooext.internal.ViewEmitter
import io.hammerhead.karooext.models.DataPoint
import io.hammerhead.karooext.models.DataType
import io.hammerhead.karooext.models.StreamState
import io.hammerhead.karooext.models.UpdateGraphicConfig
import io.hammerhead.karooext.models.UpdateNumericConfig
import io.hammerhead.karooext.models.ViewConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.sample
import kotlinx.coroutines.launch
import java.util.Locale
import kotlin.math.min

/** All data fields of the extension; typeIds must match res/xml/extension_info.xml. */
object MtbDataTypes {
    /**
     * Karoo renders numeric extension fields as integers unless told to borrow the formatting
     * (precision + unit conversion) of a built-in type.
     */
    private const val TWO_DECIMALS = DataType.Type.INTENSITY_FACTOR
    private const val METERS = DataType.Type.PRESSURE_ELEVATION_CORRECTION

    fun create(extension: String): List<DataTypeImpl> = listOf(
        MtbPanelDataType(extension, Panel.MTB, MTB_PREVIEW),
        MtbPanelDataType(extension, Panel.BIKE, BIKE_PREVIEW),
        MtbPanelDataType(extension, Panel.DESCENT, DESCENT_PREVIEW),
        SuspensionCoachDataType(extension),
        numeric(extension, "grit", TWO_DECIMALS) { it.gritTotalK },
        numeric(extension, "grit-60s", TWO_DECIMALS) { it.grit60 },
        numeric(extension, "grit-lap", TWO_DECIMALS) { it.gritLapK },
        numeric(extension, "flow", TWO_DECIMALS) { it.flowScore },
        numeric(extension, "flow-60s", TWO_DECIMALS) { it.flow60 },
        numeric(extension, "flow-lap", TWO_DECIMALS) { it.flowLap },
        numeric(extension, "jumps", null) { it.jumpCount.toDouble() },
        // "Not available" until the first jump (like the panel's "–"), not a misleading 0.
        numeric(extension, "jump-air", TWO_DECIMALS, needsImu = true) { it.lastJump?.airSec },
        numeric(extension, "jump-dist", METERS, needsImu = true) { it.lastJump?.distanceM },
        numeric(extension, "jump-max-air", TWO_DECIMALS, needsImu = true) { it.maxAirSec },
        numeric(extension, "corner-g", TWO_DECIMALS) { it.latG },
        numeric(extension, "corners", null) { it.cornerCount.toDouble() },
        numeric(extension, "roughness", TWO_DECIMALS, needsImu = true) { it.rough60 ?: 0.0 },
        numeric(extension, "descent-braking", null) { it.descentBrakingPct },
        numeric(extension, "mtb-score", null) { it.mtbScore },
        optional(extension, "easier-gears") { live -> live.easierGearsLeft.takeIf { it >= 0 }?.toDouble() },
        optional(extension, "fa-open-desc") { it.faOpenDescentPct },
        optional(extension, "descent-flow") { live -> live.descent?.flowScore ?: live.lastDescent?.flowScore },
    )

    private fun numeric(
        extension: String,
        typeId: String,
        format: String?,
        needsImu: Boolean = false,
        value: (LiveMetrics) -> Double?,
    ): DataTypeImpl = MtbNumericDataType(extension, typeId, format) { live ->
        // A few seconds into a ride without any accelerometer sample: IMU-only fields are unavailable.
        val noImu = needsImu && live.status == RideStatus.RECORDING && !live.hasAccelerometer && live.gritTotalK > 0.05
        if (noImu) null else value(live)
    }

    /** Fields from paired components (Flight Attendant, AXS): "not available" until data arrives. */
    private fun optional(extension: String, typeId: String, value: (LiveMetrics) -> Double?): DataTypeImpl =
        MtbNumericDataType(extension, typeId, null, value)

    fun fmt(pattern: String, value: Double) = String.format(Locale.ROOT, pattern, value)

    private val MTB_PREVIEW = LiveMetrics(gritTotalK = 23.4, flowScore = 3.1, jumpCount = 7, mtbScore = 68.0, cornerCount = 41)
    private val BIKE_PREVIEW =
        LiveMetrics(faFront = FaState.PEDAL, rearTeeth = 28, power = 245.0, roughNow = 0.62, easierGearsLeft = 3, faOpenDescentPct = 91.0)
    private val DESCENT_PREVIEW = LiveMetrics(
        descent = LiveDescent(
            number = 2, timeSec = 192.0, distanceM = 1350.0, dropM = 141.0, avgSpeedMs = 7.0,
            flowScore = 0.8, brakingPct = 19.0, jumps = 2, maxLateralG = 0.8,
        ),
    )
}

class MtbNumericDataType(
    extension: String,
    typeId: String,
    private val format: String?,
    private val value: (LiveMetrics) -> Double?,
) : DataTypeImpl(extension, typeId) {

    override fun startStream(emitter: Emitter<StreamState>) {
        val job = CoroutineScope(Dispatchers.Default).launch {
            MtbRuntime.live
                .map { value(it) }
                .distinctUntilChanged()
                .collect { v ->
                    emitter.onNext(
                        if (v == null || v.isNaN()) StreamState.NotAvailable
                        else StreamState.Streaming(DataPoint(dataTypeId, mapOf(DataType.Field.SINGLE to v))),
                    )
                }
        }
        emitter.setCancellable { job.cancel() }
    }

    override fun startView(context: Context, config: ViewConfig, emitter: ViewEmitter) {
        format?.let { emitter.onNext(UpdateNumericConfig(formatDataTypeId = it)) }
    }
}

private fun isNight(context: Context): Boolean =
    (context.resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

/**
 * A grid of label / value cells (like Garmin's MTB Dynamics page): 2 × 2, or 3 × 2 when the field
 * is tall. The rider picks the cells per panel in the settings ([Settings.panelCells]).
 */
class MtbPanelDataType(
    extension: String,
    private val panel: Panel,
    private val preview: LiveMetrics,
) : DataTypeImpl(extension, panel.typeId) {

    @OptIn(FlowPreview::class)
    override fun startView(context: Context, config: ViewConfig, emitter: ViewEmitter) {
        emitter.onNext(UpdateGraphicConfig(showHeader = false))
        val night = isNight(context)
        val job = CoroutineScope(Dispatchers.Default).launch {
            if (config.preview) {
                emitter.updateView(render(context, config, night, preview))
                return@launch
            }
            // ViewEmitter accepts at most one update per second.
            MtbRuntime.live.sample(1_000).collect { live -> emitter.updateView(render(context, config, night, live)) }
        }
        emitter.setCancellable { job.cancel() }
    }

    private fun render(context: Context, config: ViewConfig, night: Boolean, live: LiveMetrics): RemoteViews {
        val (width, height) = config.viewSize
        val six = Panel.useSixCells(width, height)
        val views = RemoteViews(context.packageName, if (six) R.layout.view_panel_6 else R.layout.view_panel_4)
        val cells = MtbRuntime.settings.panelCells(panel).take(if (six) 6 else 4)
        val header = panel.header(live)
        val rows = cells.size / 2
        val usableHeight = height * (if (header != null) 0.85f else 1f)
        val valuePx = min(usableHeight / rows * 0.5f, width / 2f / 4.2f).coerceAtLeast(14f)
        val labelPx = (valuePx * 0.38f).coerceAtLeast(10f)
        val valueColor = if (night) Color.WHITE else Color.BLACK
        val labelColor = if (night) Color.LTGRAY else Color.DKGRAY
        if (header != null) {
            views.setViewVisibility(R.id.panel_header, View.VISIBLE)
            views.setTextViewText(R.id.panel_header, header)
            views.setTextColor(R.id.panel_header, if (live.descent != null) ACTIVE else labelColor)
            views.setTextViewTextSize(R.id.panel_header, TypedValue.COMPLEX_UNIT_PX, labelPx * 1.15f)
        }
        val units = MtbRuntime.units
        for ((i, cell) in cells.withIndex()) {
            val labelId = LABELS[i]
            val valueId = VALUES[i]
            views.setTextViewText(labelId, cell.label)
            views.setTextViewText(valueId, cell.value(live, units))
            views.setTextColor(labelId, labelColor)
            views.setTextColor(valueId, valueColor)
            views.setTextViewTextSize(labelId, TypedValue.COMPLEX_UNIT_PX, labelPx)
            views.setTextViewTextSize(valueId, TypedValue.COMPLEX_UNIT_PX, valuePx)
        }
        return views
    }

    companion object {
        private val LABELS = listOf(R.id.label_1, R.id.label_2, R.id.label_3, R.id.label_4, R.id.label_5, R.id.label_6)
        private val VALUES = listOf(R.id.value_1, R.id.value_2, R.id.value_3, R.id.value_4, R.id.value_5, R.id.value_6)
        private const val ACTIVE = 0xFFFF6D00.toInt()
    }
}

/**
 * Flight Attendant state on a colour that says whether it suits the terrain:
 * green = fine, red = locked on rough ground, amber = open while climbing hard.
 */
class SuspensionCoachDataType(extension: String) : DataTypeImpl(extension, "suspension") {

    @OptIn(FlowPreview::class)
    override fun startView(context: Context, config: ViewConfig, emitter: ViewEmitter) {
        emitter.onNext(UpdateGraphicConfig(showHeader = false))
        val night = isNight(context)
        val job = CoroutineScope(Dispatchers.Default).launch {
            if (config.preview) {
                emitter.updateView(render(context, config, night, PREVIEW))
                return@launch
            }
            MtbRuntime.live.sample(1_000).collect { live -> emitter.updateView(render(context, config, night, live)) }
        }
        emitter.setCancellable { job.cancel() }
    }

    private fun render(context: Context, config: ViewConfig, night: Boolean, live: LiveMetrics): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.view_suspension)
        val (background, text, hint) = when (live.suspensionMatch) {
            SuspensionMatch.LOCKED_ROUGH -> Triple(RED, Color.WHITE, "rough ground: open it")
            SuspensionMatch.OPEN_HARD_CLIMB -> Triple(AMBER, Color.BLACK, "climbing hard: firm it up")
            SuspensionMatch.OK -> Triple(GREEN, Color.WHITE, live.roughNow?.let { MtbDataTypes.fmt("%.2f g", it) } ?: "")
            SuspensionMatch.NONE -> Triple(Color.TRANSPARENT, if (night) Color.WHITE else Color.BLACK, "no Flight Attendant")
        }
        val state = if (live.faFront >= 0) FaState.name(live.faFront).uppercase() else "–"
        val zone = if (live.effortZone >= 0 && live.suspensionMatch != SuspensionMatch.NONE) " · zone ${live.effortZone}" else ""
        val (width, height) = config.viewSize
        val statePx = min(height * 0.42f, width / 5.5f).coerceAtLeast(16f)
        views.setInt(R.id.suspension_root, "setBackgroundColor", background)
        views.setTextViewText(R.id.suspension_state, state)
        views.setTextViewText(R.id.suspension_hint, hint + zone)
        views.setTextColor(R.id.suspension_state, text)
        views.setTextColor(R.id.suspension_hint, text)
        views.setTextViewTextSize(R.id.suspension_state, TypedValue.COMPLEX_UNIT_PX, statePx)
        views.setTextViewTextSize(R.id.suspension_hint, TypedValue.COMPLEX_UNIT_PX, (statePx * 0.34f).coerceAtLeast(10f))
        return views
    }

    companion object {
        private const val GREEN = 0xFF2E7D32.toInt()
        private const val RED = 0xFFC62828.toInt()
        private const val AMBER = 0xFFF9A825.toInt()
        private val PREVIEW = LiveMetrics(faFront = FaState.OPEN, suspensionMatch = SuspensionMatch.OK, roughNow = 1.2, effortZone = 0)
    }
}
