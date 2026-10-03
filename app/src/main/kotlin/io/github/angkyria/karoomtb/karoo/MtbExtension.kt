package io.github.angkyria.karoomtb.karoo

import android.util.Log
import io.github.angkyria.karoomtb.BuildConfig
import io.hammerhead.karooext.KarooSystemService
import io.hammerhead.karooext.extension.DataTypeImpl
import io.hammerhead.karooext.extension.KarooExtension
import io.hammerhead.karooext.internal.Emitter
import io.hammerhead.karooext.models.FitEffect
import io.hammerhead.karooext.models.HidePolyline
import io.hammerhead.karooext.models.HideSymbols
import io.hammerhead.karooext.models.MapEffect
import io.hammerhead.karooext.models.ShowSymbols
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** The Karoo extension service (bound by Karoo OS on Karoo 2 and Karoo 3). */
class MtbExtension : KarooExtension(EXTENSION_ID, BuildConfig.VERSION_NAME) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var karoo: KarooSystemService
    private var controller: RideController? = null

    override val types: List<DataTypeImpl> by lazy { MtbDataTypes.create(extension) }

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "MTB Dynamics ${BuildConfig.VERSION_NAME} starting")
        MtbRuntime.init(applicationContext)
        karoo = KarooSystemService(applicationContext)
        controller = RideController(applicationContext, karoo, scope, BuildConfig.VERSION_NAME).also { it.start() }
        karoo.connect { connected ->
            Log.i(TAG, "Karoo system connected=$connected hardware=${if (connected) karoo.hardwareType else null}")
            if (connected) controller?.onConnected()
        }
    }

    /** Karoo calls this when it opens the ride's FIT file (extension_info: fitFile="true"). */
    override fun startFit(emitter: Emitter<FitEffect>) {
        val job = scope.launch {
            MtbRuntime.fitEffects.collect { emitter.onNext(it) }
        }
        emitter.setCancellable { job.cancel() }
    }

    /** Controller / remote buttons (extension_info BonusAction). */
    override fun onBonusAction(actionId: String) {
        Log.i(TAG, "bonus action $actionId")
        when (actionId) {
            ACTION_MARK -> controller?.markMoment()
        }
    }

    /**
     * Map layer (extension_info mapLayer="true"): jumps and marked moments as symbols, rough
     * ground as orange / red lines. A new ride clears the previous one.
     */
    override fun startMap(emitter: Emitter<MapEffect>) {
        val job = scope.launch {
            var symbols = emptySet<String>()
            var lines = emptySet<String>()
            MtbRuntime.map.collect { features ->
                val enabled = MtbRuntime.settings.mapLayer
                val newSymbols = if (!enabled) emptyList() else MapLayer.symbols(features)
                val newLines = if (!enabled) emptyMap() else MapLayer.polylines(features)
                val staleSymbols = symbols - newSymbols.map { it.id }.toSet()
                if (staleSymbols.isNotEmpty()) emitter.onNext(HideSymbols(staleSymbols.toList()))
                if (newSymbols.isNotEmpty()) emitter.onNext(ShowSymbols(newSymbols))
                (lines - newLines.keys).forEach { emitter.onNext(HidePolyline(it)) }
                newLines.filterKeys { it !in lines }.values.forEach { emitter.onNext(it) }
                symbols = newSymbols.map { it.id }.toSet()
                lines = newLines.keys
            }
        }
        emitter.setCancellable { job.cancel() }
    }

    override fun onDestroy() {
        controller?.stop()
        controller = null
        scope.cancel()
        karoo.disconnect()
        super.onDestroy()
    }

    companion object {
        const val EXTENSION_ID = "karoo-mtb"
        const val ACTION_MARK = "mark"
        private const val TAG = "MtbExtension"
    }
}
