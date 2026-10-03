pluginManagement {
    repositories {
        gradlePluginPortal()
        google()
        mavenCentral()
    }
}

/**
 * karoo-ext is published on GitHub Packages, which always requires authentication
 * (any GitHub token with the `read:packages` scope works, the package itself is public).
 *
 * Credentials are looked up in this order:
 *  1. Gradle properties `gpr.user` / `gpr.key` (~/.gradle/gradle.properties or -P)
 *  2. Environment variables `GPR_USER` / `GPR_KEY`
 *  3. `local.properties` entries `gpr.user` / `gpr.key`
 *  4. GitHub Actions defaults `GITHUB_ACTOR` / `GITHUB_TOKEN`
 */
fun localProperty(key: String): String? {
    val file = File(rootDir, "local.properties")
    if (!file.isFile) return null
    val properties = java.util.Properties()
    file.inputStream().use { properties.load(it) }
    return properties.getProperty(key)
}

val gprUser: String? = providers.gradleProperty("gpr.user").orNull
    ?: System.getenv("GPR_USER")
    ?: localProperty("gpr.user")
    ?: System.getenv("GITHUB_ACTOR")
val gprKey: String? = providers.gradleProperty("gpr.key").orNull
    ?: System.getenv("GPR_KEY")
    ?: localProperty("gpr.key")
    ?: System.getenv("GITHUB_TOKEN")

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven {
            url = uri("https://maven.pkg.github.com/hammerheadnav/karoo-ext")
            credentials {
                username = gprUser
                password = gprKey
            }
            content { includeGroup("io.hammerhead") }
        }
    }
}

rootProject.name = "karoo-mtb"
include(":app")
