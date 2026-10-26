# 숙제 체크 v1.2.0

| 날짜 | 버전 | 변경 내용 | 작성 |
|---|---|---|---|
| 2026-10-26 | v1.2.0 | 개인 저장소로 분리. 안드로이드 앱(서버 모드·접속 모드, 집 서버 통한 자동 업데이트), 서버 자동 찾기, 설치 실패 대처(안드로이드 7 지원·설치 안내문) | js.hong |
| 2026-10-26 | v1.1.0 | 기간 요약(오늘·주말까지·이번 주), 반려 메모 카드 표시, 폰 하단 추가 버튼 | js.hong |
| 2026-10-26 | v1.0.0 | 최초 작성 — 가족 그룹·자녀/부모 화면·반복 학습·외부 가져오기 입구 | js.hong |

자녀가 숙제를 등록하고 진행 상황을 올리면, 부모가 휴대폰으로 확인하고 완료 처리하는 **집 와이파이 전용** 숙제·학습 체크.
초등 → 중 → 고까지 학년이 자동으로 올라가고, 자녀는 여러 명 등록할 수 있다. 설계 상세는 [docs/설계서-v1.2.0.md](docs/설계서-v1.2.0.md).

## 구성

```text
 ┌─ 서버 기기 (집에 늘 켜 두는 안드로이드 1대) ─┐            ┌─ 자녀 탭 ───┐  ┌─ 부모 폰 ───┐
 │  숙제 체크 앱 · 「서버로 사용」               │◀─와이파이─▶│ 「접속 기기」 │  │ 「접속 기기」 │
 │  ├ 내장 파이썬 서버 (server/server.py)        │            └─────────────┘  └─────────────┘
 │  ├ 데이터 homework.db                         │
 │  └ 자기 APK 를 다른 기기에 업데이트로 배포    │
 └───────────────────────────────────────────────┘
```

- **앱 하나로 두 역할.** 설치 후 처음 화면에서 이 기기를 **서버**로 쓸지 **접속 기기**로 쓸지 고른다.
- **서버 기기**는 화면이 꺼져도 계속 돌고(알림에 "서버 실행 중" 표시), 재부팅하면 저절로 다시 켜진다.
- **접속 기기**는 같은 와이파이의 서버를 **자동으로 찾는다**(못 찾으면 주소 직접 입력).
- **업데이트**: 서버 기기의 앱만 새 버전으로 바꾸면, 다른 기기는 앱을 열 때 "새 버전" 대화상자 → 업데이트 한 번으로 따라온다. 화면(웹 코드)은 서버가 내려주므로 서버만 바뀌면 바로 바뀐다.
- PC 를 서버로 써도 된다(아래 「PC 서버」). 아이폰·아이패드는 브라우저로 접속만 가능.

## 폴더
| 경로 | 내용 |
|---|---|
| `server/` | 서버(파이썬 표준 라이브러리만) · 화면(`static/`) · 테스트. 앱에도 그대로 들어간다 |
| `app/` | 안드로이드 앱 (Java, AndroidX 없음). 서버 모드는 Chaquopy 로 `server.py` 를 실행 |
| `.github/workflows/android.yml` | 푸시하면 서버 테스트 + APK 빌드. `v` 태그면 릴리스에 APK·PC 서버 zip 첨부 |
| `deploy/설치안내.txt` | 받는 사람용 설치 안내. 릴리스마다 `숙제체크-설치안내-v<버전>.txt` 로 붙는다 |
| `docs/` | 설계서 (구판은 `docs/Old/`) |

## 처음 설치 (가족 기기)

1. **APK 받기** — GitHub 저장소 → Releases → 최신 `homework-tracker-v<버전>.apk` (저장소가 비공개라 GitHub 에 로그인한 브라우저에서 받는다)
2. **서버 기기**에 설치 → "출처를 알 수 없는 앱 허용" → 앱 실행 → **이 기기를 서버로 사용**
   - 알림 허용 · **배터리 최적화 해제**(안 하면 몇 시간 뒤 서버가 꺼질 수 있다) · 충전기에 꽂아 둔다
   - 화면이 뜨면 **가족 그룹 만들기**(부모·자녀 이름, PIN, 초1 입학년도)
3. **자녀 탭·부모 폰** — 서버 기기 화면 **⚙ 설정 → 안드로이드 앱**의 주소(`http://192.168.x.x:8080/app/homework-tracker.apk`)를 각 기기 브라우저로 열어 설치 → 앱 실행 → **서버 자동으로 찾기** → 연결
4. 공유기에서 서버 기기에 **고정 IP(DHCP 예약)** 를 걸어 두면 주소가 바뀌지 않는다.

- 안드로이드 **7.0 이상**, CPU 는 arm64-v8a·armeabi-v7a(32비트 저가형 탭 포함).
- APK 는 **Gmail 첨부가 막힌다** → GitHub(로그인한 브라우저)·구글 드라이브·USB 로 옮긴다.

## 설치가 안 될 때

| 증상 | 원인 | 할 일 |
|---|---|---|
| "앱이 설치되지 않았습니다" · "기존 패키지와 충돌" | 서명 키가 다른 APK 가 이미 설치됨 (디버그 키로 만든 Actions 시험 빌드 등) | 앱 삭제 후 재설치. 서버 기기는 먼저 ⚙ 설정 → 백업 |
| "패키지를 파싱하는 중 문제가 발생했습니다" | 덜 받아진 파일, 또는 안드로이드 7 미만 | 다시 받기 / 기기 버전 확인 |
| 설치 버튼이 안 눌림 · "차단됨" | Play 프로텍트 경고 | [세부정보 더보기] → [무시하고 설치] |
| 허용 질문 없이 막힘 (안드로이드 7) | 전체 「알 수 없는 출처」가 꺼져 있음 | 설정 → 보안 → 알 수 없는 출처 켜기 |
| 앱 안 업데이트가 실패 | 앱이 원인을 토스트로 보여 준다(서명 불일치·옛 버전·공간 부족·손상) | 안내대로. 원문 `INSTALL_FAILED_…` 도 함께 표시 |

- **정확한 원인 보기 (PC + USB 디버깅):** `adb install -r homework-tracker-v<버전>.apk` → `INSTALL_FAILED_UPDATE_INCOMPATIBLE`(서명 다름), `INSTALL_FAILED_VERSION_DOWNGRADE`(옛 버전), `INSTALL_FAILED_NO_MATCHING_ABIS`(CPU 미지원), `INSTALL_FAILED_OLDER_SDK`(안드로이드 버전 낮음)
- **예방:** 가족 기기에는 **`v` 태그 릴리스(서명 키) APK 만** 설치한다. Actions 의 브랜치 빌드 APK 는 디버그 키라 나중에 정식 버전 위에 덮어 설치되지 않는다.

## 새 버전 배포

1. `server/server.py` 의 `APP_VERSION` 을 올린다 (앱 versionCode 도 여기서 정해진다. 1.2.0 → 10200)
2. 커밋·푸시 → `git tag v1.2.0` → `git push origin v1.2.0`
3. Releases 에 붙은 새 APK 를 **서버 기기에만** 설치(덮어쓰기)
4. 다른 기기는 앱을 열면 "새 버전" 대화상자 → 업데이트 (또는 ⚙ 설정 → 업데이트 확인)

> 업데이트가 이어지려면 **모든 버전을 같은 서명 키**로 만들어야 한다. 아래 「서명 키」를 먼저 등록한다.

## 서명 키
서명 키(`homework.jks`)와 비밀번호는 저장소에 넣지 않는다. 키를 잃어버리면 이후 버전은 기존 앱 위에 덮어 설치할 수 없다(앱을 지우고 새로 설치해야 한다. 데이터는 서버 기기에 있으므로 접속 기기는 재설치해도 되지만, **서버 기기는 백업 후 재설치**).

**키 만들기 (한 번만)** — JDK 의 `keytool`:
```powershell
keytool -genkeypair -v -keystore "E:\기타\keys\homework.jks" -alias homework -keyalg RSA -keysize 2048 -validity 10000
```

**GitHub Actions** — 저장소 Settings → Secrets and variables → Actions → New repository secret
| 이름 | 값 |
|---|---|
| `HW_KEYSTORE_B64` | 키 파일을 base64 로 바꾼 문자열. PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("E:\기타\keys\homework.jks")) \| Set-Clipboard` |
| `HW_KS_PASS` | 키 비밀번호 |

비밀 값이 없으면 브랜치 빌드는 디버그 키로 서명한다(시험 설치용, 업데이트 안 이어짐). **`v` 태그 릴리스는 키가 없으면 실패**하게 해 두었다.

**PC** — `%USERPROFILE%\.gradle\gradle.properties` 에 추가 (저장소 밖이라 커밋되지 않음)
```properties
HW_KS_FILE=E:/기타/keys/homework.jks
HW_KS_PASS=비밀번호
```

## APK 받기
- **자동 빌드:** Actions → 최근 "Android APK" 실행 → Artifacts 의 `homework-tracker` (APK · version.json · PC 서버 zip)
- **릴리스:** `v` 로 시작하는 태그를 올리면 Releases 에 붙는다.

## PC 서버 (선택)
안드로이드 서버 대신 집 PC 를 서버로 쓸 때. 파이썬 3.9+ 만 있으면 된다.
1. 릴리스의 `homework-tracker-server-v<버전>.zip` 을 풀고 `run.bat`(Windows) 또는 `./run.sh` 실행
2. zip 안의 `apk/` 폴더(APK + version.json)를 PC 서버가 그대로 배포하므로, 접속 기기 앱 업데이트도 똑같이 된다
3. 처음 실행 시 Windows 방화벽 창 → **개인 네트워크 허용**. 앱 자동 찾기는 UDP 47800 포트를 쓴다

```sh
python server/server.py --port 8080 --data ./data --apk-dir ./apk
```

## 사용 흐름

| 상태 | 의미 | 누가 바꾸나 |
|---|---|---|
| 가져옴·확인 필요 | 문자·알림앱에서 들어온 숙제 | 부모: 목록에 추가 / 버리기 |
| 할 일 → 하는 중 | 진행률 0~100% | 자녀: 시작하기, 25/50/75%, 슬라이더 |
| 완료 요청 | 자녀가 "다 했어요" | 부모: 확인 완료 / 다시 하기(메모가 자녀 카드에 빨간 글씨로) |
| 완료 | 부모가 확인함 | 부모: 다시 열기 |

- **기간 요약**: 화면 위쪽 카드에 [오늘 / 주말까지 / 이번 주] 기준 완료·확인 대기·남음·마감 지남과 남은 일 제목. 다 끝나면 "🎉 모두 완료".
- **반복 학습**: "매일 영단어 30개" 처럼 요일을 정하면 그날의 할 일이 자동 생성.
- **백업**: 부모 ⚙ 설정 → 백업 → JSON 내려받기 (앱에서는 「다운로드」 폴더에 저장).

## 문자·학교 알림앱 연동 (확장 입구)
외부 수집기가 아래처럼 보내면 "가져옴·확인 필요"에 쌓인다. 키는 부모 ⚙ 설정 → 외부 가져오기.
```sh
curl -X POST http://<서버주소>:8080/api/import -H "X-Import-Key: <키>" -H "Content-Type: application/json" \
  -d '{"child":"민준","source":"sms","text":"[OO초] 내일까지 수학익힘책 34쪽"}'
```
제목·마감일(오늘/내일/모레/10/28/11월 3일/금요일)·과목은 원문에서 추정한다.

## PC 에서 작업 (Windows)
```powershell
git clone https://github.com/junesunghong/homework-tracker.git "E:\기타\homework-tracker"
cd "E:\기타\homework-tracker"
python server\server.py                       # 서버만 PC 에서 띄워 화면 확인
python -m unittest discover -s server\tests   # 서버 테스트
```
- **Android Studio:** File → Open → `E:\기타\homework-tracker`. 처음 열 때 SDK·Gradle 을 내려받는다.
- **명령줄 빌드:** `.\gradlew.bat assembleRelease -Pandroid.overridePathCheck=true` → `app\build\outputs\apk\release\app-release.apk`
  - 경로에 한글(`기타`)이 있으면 AGP 가 빌드를 막아 `-Pandroid.overridePathCheck=true` 가 필요하다.
  - Android SDK 가 없는 PC 에서는 푸시해서 GitHub Actions 로 빌드한다.
- **휴대폰에 바로 설치 (USB 디버깅):** `.\gradlew.bat installRelease -Pandroid.overridePathCheck=true`
- **설치 실패 원인:** `adb install -r app\build\outputs\apk\release\app-release.apk` 가 `INSTALL_FAILED_...` 사유를 보여 준다.

## 보안 메모
- 집 와이파이 안에서만 쓴다. **공유기 포트포워딩으로 외부에 열지 말 것** (HTTPS 미적용).
- PIN 은 PBKDF2 해시 저장, 5회 틀리면 60초 잠금. PIN 을 바꾸면 그 사람의 다른 기기 로그인이 끊긴다.
