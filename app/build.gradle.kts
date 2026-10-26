plugins {
    id("com.android.application")
    id("com.chaquo.python")  // 서버 모드에서 server/server.py 를 앱 안의 파이썬으로 그대로 돌린다
}

// 버전은 server/server.py 의 APP_VERSION 하나로 관리한다. 1.2.0 → versionCode 10200
val versionMatch = Regex("APP_VERSION = \"(\\d+)\\.(\\d+)\\.(\\d+)\"")
    .find(rootProject.file("server/server.py").readText()) ?: error("server.py 에서 APP_VERSION 을 찾지 못했습니다")
val (vMajor, vMinor, vPatch) = versionMatch.destructured
val appVersion = "$vMajor.$vMinor.$vPatch"
val appVersionCode = vMajor.toInt() * 10000 + vMinor.toInt() * 100 + vPatch.toInt()

android {
    namespace = "kr.home.homeworktracker"
    compileSdk = 35

    defaultConfig {
        applicationId = "kr.home.homeworktracker"
        minSdk = 26
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersion
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")  // 태블릿·휴대폰. 에뮬레이터용이면 x86_64 추가
        }
    }

    // 서명 키는 저장소에 넣지 않는다. 환경 변수(GitHub Secrets) 또는 PC 의 ~/.gradle/gradle.properties 에서 읽는다.
    //   HW_KS_FILE  : 키 파일 경로 (homework.jks)
    //   HW_KS_PASS  : 키 저장소 비밀번호
    //   HW_KEY_PASS : 키 비밀번호 (없으면 HW_KS_PASS)
    // 없으면 디버그 키로 서명한다. 설치는 되지만 빌드마다 키가 달라 앱 업데이트가 이어지지 않는다.
    fun secret(name: String): String? =
        System.getenv(name)?.takeIf { it.isNotBlank() } ?: (project.findProperty(name) as String?)
    val ksFile = secret("HW_KS_FILE")?.let { file(it) }?.takeIf { it.exists() }
    val ksPass = secret("HW_KS_PASS")

    signingConfigs {
        if (ksFile != null && ksPass != null) {
            create("release") {
                storeFile = ksFile
                storePassword = ksPass
                keyAlias = "homework"
                keyPassword = secret("HW_KEY_PASS") ?: ksPass
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    // 화면(static/)은 server/ 의 것을 그대로 앱에 넣는다 — 복사본을 저장소에 두지 않는다.
    sourceSets {
        getByName("main") {
            assets.srcDir(layout.buildDirectory.dir("generated/hw-assets"))
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"  // 3.12 이상은 32비트 ARM(armeabi-v7a) 런타임이 없다 — 저가형 태블릿 지원
        pyc {
            src = false  // 빌드 PC 의 파이썬 버전과 무관하게 빌드되도록 .py 그대로 넣는다
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(layout.buildDirectory.dir("generated/hw-python"))
        }
    }
}

val syncWeb by tasks.registering(Sync::class) {
    from(rootProject.file("server/static"))
    into(layout.buildDirectory.dir("generated/hw-assets/web"))
}
val syncPython by tasks.registering(Sync::class) {
    from(rootProject.file("server/server.py"))
    into(layout.buildDirectory.dir("generated/hw-python"))
}
tasks.named("preBuild") {
    dependsOn(syncWeb, syncPython)
}
