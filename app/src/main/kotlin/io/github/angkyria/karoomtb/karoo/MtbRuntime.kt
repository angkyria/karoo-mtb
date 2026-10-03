package io.github.angkyria.karoomtb.karoo

import android.content.Context
import io.github.angkyria.karoomtb.Settings
import io.github.angkyria.karoomtb.engine.LiveMetrics
import io.github.angkyria.karoomtb.engine.MapFeatures
import io.github.angkyria.karoomtb.engine.MtbEngine
import io.github.angkyria.karoomtb.notify.Units
import io.github.angkyria.karoomtb.service.ServiceTracker
import io.github.angkyria.karoomtb.storage.RideStore
import io.github.angkyria.karoomtb.trails.TrailLibrary
import io.hammerhead.karooext.models.FitEffect
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import java.io.File

/** Process-wide state shared by the extension service, its data fields and the settings screen. */
object MtbRuntime {
    val engine = MtbEngine()

    /** Updated every second while riding; the data fields render from this. */
    val live = MutableStateFlow(LiveMetrics())

    /** What the Karoo map layer shows ([MtbExtension.startMap]). */
    val map = MutableStateFlow(MapFeatures())

    /** Effects for the FIT file, consumed by [MtbExtension.startFit]. */
    val fitEffects = MutableSharedFlow<FitEffect>(extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)

    @Volatile
    var units: Units = Units()

    @Volatile
    private var initialized = false
    lateinit var settings: Settings
        private set
    lateinit var store: RideStore
        private set
    lateinit var service: ServiceTracker
        private set
    lateinit var trails: TrailLibrary
        private set

    @Synchronized
    fun init(context: Context) {
        if (initialized) return
        settings = Settings(context)
        store = RideStore(context)
        val dir = context.getExternalFilesDir(null) ?: context.filesDir
        service = ServiceTracker(File(dir, ServiceTracker.FILE_NAME))
        trails = TrailLibrary(File(dir, TrailLibrary.FILE_NAME))
        initialized = true
    }
}
