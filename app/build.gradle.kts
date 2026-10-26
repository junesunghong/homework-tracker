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
        minSdk = 24  // 안드로이드 7 이상 (공기 심판과 같다). 구형 탭에서 "파싱 오류"로 설치가 막히지 않게
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

    // v1(JAR) + v2 서명을 모두 넣는다. minSdk 24 면 기본은 v2 만인데, 구형·제조사 설치기에서
    // "앱이 설치되지 않았습니다"가 나지 않도록 v1 도 붙인다(크기 차이는 거의 없다).
    signingConfigs.configureEach {
        enableV1Signing = true
        enableV2Signing = true
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
}

// 화면(static/)과 server.py 는 server/ 의 것을 빌드할 때 복사해 넣는다 — 저장소에 복사본을 두지 않는다.
// 소스 폴더에 복사 작업 자체를 넘겨야 Gradle 이 "복사 → 사용" 순서를 안다(Gradle 9 는 순서가 없으면 빌드를 막는다).
val syncWeb = tasks.register<Sync>("syncWeb") {
    from(rootProject.file("server/static")) { into("web") }
    into(layout.buildDirectory.dir("generated/hw-assets"))
}
val syncPython = tasks.register<Sync>("syncPython") {
    from(rootProject.file("server/server.py"))
    into(layout.buildDirectory.dir("generated/hw-python"))
}
android.sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/hw-assets"))

chaquopy {
    defaultConfig {
        version = "3.11"  // 3.12 이상은 32비트 ARM(armeabi-v7a) 런타임이 없다 — 저가형 태블릿 지원
        pyc {
            src = false  // 빌드 PC 의 파이썬 버전과 무관하게 빌드되도록 .py 그대로 넣는다
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(syncPython)
        }
    }
}

// 위 연결로 대부분 해결되지만, 소스 폴더를 읽는 다른 작업(lint 등)도 복사 뒤에 돌도록 한 번 더 묶는다.
tasks.configureEach {
    if (name != "syncWeb" && name != "syncPython" && name != "clean") dependsOn(syncWeb, syncPython)
}
