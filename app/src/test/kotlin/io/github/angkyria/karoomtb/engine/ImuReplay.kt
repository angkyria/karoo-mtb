package io.github.angkyria.karoomtb.engine

/** Replays a snippet CSV (sensor,t_ms,x,y,z) through ImuProcessor + JumpDetector, as the Karoo runs them. */
object ImuReplay {
    fun flights(
        text: String,
        config: MtbConfig,
    ): List<RawJump> {
        val imu = ImuProcessor()
        val detector = JumpDetector(config)
        val jumps = ArrayList<RawJump>()
        for (line in text.lineSequence()) {
            if (line.isBlank() || line.startsWith("#") || line.startsWith("sensor")) continue
            val c = line.split(',')
            val t = c[1].toDouble() / 1000.0
            val x = c[2].toDouble()
            val y = c[3].toDouble()
            val z = c[4].toDouble()
            when (c[0]) {
                "a" -> {
                    val air = detector.airborne
                    imu.onAccel(t, x, y, z, freezeGravity = air, countRoughness = !air)
                    detector.onAccel(t, imu.magLpG, imu.magG)?.let { jumps += it }
                }
                "g" -> detector.onGyro(t, x, y, z)
            }
        }
        return jumps
    }
}
