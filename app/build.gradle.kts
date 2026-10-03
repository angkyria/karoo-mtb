import java.util.Base64

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.serialization)
}

// Release metadata, injected by CI (see .github/workflows/build.yml).
val releaseVersion: String = System.getenv("RELEASE_VERSION")?.removePrefix("v") ?: "0.3.0"
val buildNumber: Int = System.getenv("BUILD_NUMBER")?.toIntOrNull() ?: 3
val releaseBaseUrl: String = System.getenv("BASE_URL")
    ?: "https://github.com/angkyria/karoo-mtb/releases/latest/download"
val hasReleaseKeystore = !System.getenv("KEYSTORE_BASE64").isNullOrBlank()

android {
    namespace = "io.github.angkyria.karoomtb"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.angkyria.karoomtb"
        // Karoo 2 runs Android 8.1 (API 27); Karoo 3 runs a newer Android.
        minSdk = 26
        targetSdk = 34
        versionCode = 100 + buildNumber
        versionName = releaseVersion
        manifestPlaceholders["karooManifestUrl"] = "$releaseBaseUrl/manifest.json"
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                val keystore = File.createTempFile("karoo-mtb", ".jks").apply { deleteOnExit() }
                keystore.writeBytes(Base64.getDecoder().decode(System.getenv("KEYSTORE_BASE64")))
                storeFile = keystore
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            // R8 is left off: karoo-ext and kotlinx.serialization rely on reflection-free but
            // name-sensitive serializers, and APK size is irrelevant on a Karoo.
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
    lint {
        // Errors fail CI; warnings are listed in the report (artifact "lint-report").
        abortOnError = true
        warningsAsErrors = false
        checkReleaseBuilds = false
    }
}

/** Writes the manifest.json the Karoo uses for side-loading and update checks. */
val generateKarooManifest by tasks.registering {
    group = "build"
    description = "Generates build/karoo/manifest.json for the GitHub release"
    val output = layout.buildDirectory.file("karoo/manifest.json")
    outputs.file(output)
    doLast {
        val manifest = mapOf(
            "label" to "MTB Dynamics",
            "packageName" to "io.github.angkyria.karoomtb",
            "iconUrl" to "$releaseBaseUrl/karoo-mtb.png",
            "latestApkUrl" to "$releaseBaseUrl/karoo-mtb.apk",
            "latestVersion" to releaseVersion,
            "latestVersionCode" to 100 + buildNumber,
            "developer" to "github.com/angkyria",
            "description" to "Garmin-style MTB Dynamics for Karoo: Grit, Flow, jumps (airtime, distance, height), " +
                "cornering, descents, MTB score and trail segments, live descents and trail personal bests. " +
                "Writes everything to the FIT file and sends a ride summary over ntfy.",
            "releaseNotes" to (System.getenv("RELEASE_NOTES") ?: "See GitHub release notes."),
            "tags" to listOf("performance"),
        )
        val file = output.get().asFile
        file.parentFile.mkdirs()
        file.writeText(groovy.json.JsonBuilder(manifest).toPrettyString())
    }
}

tasks.named("preBuild") { dependsOn(generateKarooManifest) }

dependencies {
    implementation(libs.karoo.ext)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.zxing.core)

    testImplementation(libs.junit)
}
