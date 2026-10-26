# 작업 스냅샷 — 숙제 체크 v1.2.0: 개인 레포 분리 · 안드로이드 앱(서버/접속 모드) · CI APK 빌드

> 세션 컨텍스트 · 진행 2026-10-26 22:57 · 머신 클라우드 컨테이너 · 조종 미상(사용자는 집 PC 로 이동) · 환경 클라우드 · 용도 개인 · 직전 (첫 세션)

## 1. 요약
- 숙제·학습 체크 프로그램을 `claude-commands` 브랜치에서 시작해 **개인 레포 `junesunghong/homework-tracker`** 로 분리했다(공기 심판 레포 구조를 따름).
- 서버(파이썬 표준 라이브러리) + 웹 화면 + **안드로이드 앱 1개로 서버/접속 두 역할**(Chaquopy 로 `server.py` 내장 실행). 집 서버가 자기 APK 를 배포해 접속 기기가 앱 안에서 업데이트한다.
- GitHub Actions 로 **APK 빌드·점검 통과**(run 40297033315, `c35b426`). 실제 기기 설치·동작은 **아직 미검증**.

## 2. 한 일
| 항목 | 결과 |
|---|---|
| 서버 | `server/server.py` v1.2.0 — 가족 그룹·자녀/부모 권한·상태 전이·반복 학습·기간 요약·외부 가져오기, `/app/version.json`·`/app/homework-tracker.apk` 배포, UDP 47800 자동 찾기, `run_embedded()` |
| 테스트 | `python -m unittest discover -s server/tests` **13 passed** (CI 는 앱과 같은 파이썬 3.11) |
| 앱 | `app/` Java·AndroidX 없음, minSdk 24(안드로이드 7) · target 35, ABI arm64-v8a·armeabi-v7a, APK 31.5MB |
| CI | `.github/workflows/android.yml` — 서버 테스트 → APK 빌드 → **APK 점검**(v2 서명·minSdk·ABI·testOnly·내장 파일) → 산출물(APK·PC 서버 zip·version.json·설치 안내문). `v*` 태그면 Releases 첨부 |
| 설치 실패 대비 | 공기 심판 경험 반영: 안드로이드 7 지원, 받은 크기 검증(끊긴 APK), 실패 원인별 한글 안내, `deploy/설치안내.txt`, README 「설치가 안 될 때」 |
| 문서 | `README.md` v1.2.0, `docs/설계서-v1.2.0.md`(구판 `docs/Old/`) |
| 이어받기 | `.claude/commands/` 에 `/작업시작`·`/작업종료` vendoring, `.gitattributes`(gradlew·*.sh LF 고정) |

## 3. 결정
- **레포 분리** — 개인 프로젝트이므로 `claude-commands` 가 아닌 전용 레포. (`claude-commands` PR #1 은 이관 정리 + targets 등록으로 바꿈)
- **단일 APK, 역할은 설치 후 선택** — 서버 기기 1대(집에 늘 켜 둠) + 접속 기기들. 업데이트는 **서버 기기에만 릴리스 APK 설치** → 나머지는 앱 안 업데이트.
- **파이썬 3.11** — 3.12+ 는 Chaquopy 에 armeabi-v7a 런타임이 없다(1차 CI 실패 원인). 32비트 저가형 탭 지원 우선.
- **v1 서명 미사용** — minSdk 24 는 전부 v2 를 읽는다. 점검은 v2 유효성만 요구.
- **태그 릴리스는 서명 키 필수**(키 없으면 CI 실패) — 디버그 키는 빌드마다 달라 업데이트가 끊긴다(공기 심판의 "삭제 후 재설치" 문제).

## 4. 현재 상태
- `main` 동기, 미머지 브랜치 없음. 태그 없음(아직 릴리스 전).
- 최신 성공 빌드: https://github.com/junesunghong/homework-tracker/actions/runs/40297033315 (산출물 = **디버그 키 시험용**)
- GitHub Secrets `HW_KEYSTORE_B64`·`HW_KS_PASS` **미등록**.

## 5. 주의 / 함정
- **디버그 키 시험 APK 를 가족 기기에 설치했다면** 정식 릴리스 전에 **삭제**해야 한다(서명 불일치 → "앱이 설치되지 않았습니다").
- 경로에 한글(`기타`) → 로컬 Gradle 빌드는 `-Pandroid.overridePathCheck=true` 필요. SDK 없는 PC 는 푸시해서 CI 로 빌드.
- **Gradle 9 는 작업 순서 미선언을 오류로 막는다** — `app/build.gradle.kts` 의 `syncWeb`·`syncPython` 연결을 지우지 말 것(2차 CI 실패 원인).
- Windows 방화벽: PC 서버 첫 실행 시 **개인 네트워크 허용**(TCP 8080, 자동 찾기 UDP 47800).
- 버전은 `server/server.py` 의 `APP_VERSION` **하나만** 올린다(앱 versionCode 가 여기서 계산됨).
- 클라우드 세션에서는 Android SDK(`dl.google.com`)가 네트워크 정책으로 막혀 로컬 빌드 불가 → CI 로 확인.

## 6. 미완
- 실제 기기 설치·기능 테스트(서버 모드·자동 찾기·화면 꺼짐 유지·재부팅 자동 시작·앱 안 업데이트).
- 서명 키 생성·Secrets 등록 → `v1.2.0` 릴리스.

## 7. 다음 단계
1. **집 PC 에 clone** — `git clone https://github.com/junesunghong/homework-tracker.git "E:\기타\homework-tracker"` → 그 폴더에서 Claude Code 세션을 열고 `/작업시작`.
2. **커맨드 배포 갱신** — `E:\claude-commands` 에서 `git pull` 후 `pwsh scripts\propagate.ps1` (targets.txt 에 `E:\기타\homework-tracker` 등록됨 → `[COMMITTED]` 확인).
3. **서버·화면 확인** — `python server\server.py` → 브라우저 `http://localhost:8080`, 휴대폰은 같은 와이파이에서 `http://<PC IP>:8080`. 테스트: `python -m unittest discover -s server\tests`.
4. **서명 키** — `keytool -genkeypair -v -keystore "E:\기타\keys\homework.jks" -alias homework -keyalg RSA -keysize 2048 -validity 10000` (keytool 이 없으면 Android Studio 의 `jbr\bin\keytool.exe`) → README 「서명 키」대로 Secrets 2개 등록 + `%USERPROFILE%\.gradle\gradle.properties`.
5. **릴리스** — `git tag v1.2.0` → `git push origin v1.2.0` → Releases 의 APK 를 서버 기기에 설치 → 접속 기기는 서버 ⚙ 설정 → 「안드로이드 앱」 주소로 설치.
6. **모바일 기능 테스트** — 숙제 흐름·기간 요약·자동 찾기·화면 꺼짐 10분·재부팅·백업. 업데이트 시험은 키 등록 후 1.2.1 빌드로.

## 8. 참고 파일
- `README.md` (처음 설치 · 새 버전 배포 · 서명 키 · 설치가 안 될 때 · PC 에서 작업)
- `docs/설계서-v1.2.0.md` §9 안드로이드 앱
- `.github/workflows/android.yml` (APK 점검 단계)
- `deploy/설치안내.txt`
- 참고 레포: `junesunghong/gonggi-referee` (구조·서명 키 방식·설치 실패 기록)
