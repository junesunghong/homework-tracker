package kr.home.homeworktracker;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 앱 업데이트 — 집 서버의 /app/version.json 을 보고, 더 새 버전이면 /app/homework-tracker.apk 를 받아 설치한다.
 * 서버 기기의 앱만 새 버전으로 바꾸면 나머지 기기는 여기서 따라 올라간다(같은 서명 키여야 한다).
 */
final class Updater {
    private static final long AUTO_INTERVAL_MS = 6 * 60 * 60 * 1000L;
    private static long lastAutoCheck;

    private Updater() {}

    /** 앱을 열 때 6시간에 한 번 조용히 확인한다. */
    static void autoCheck(Activity a, String base) {
        long now = System.currentTimeMillis();
        if (now - lastAutoCheck < AUTO_INTERVAL_MS) return;
        lastAutoCheck = now;
        check(a, base, false);
    }

    static void check(Activity a, String base, boolean manual) {
        if (base == null) return;
        new Thread(() -> {
            try {
                JSONObject v = new JSONObject(Net.get(base + "/app/version.json", 5000));
                int code = v.getInt("versionCode");
                String name = v.optString("versionName");
                if (code > BuildConfig.VERSION_CODE) {
                    a.runOnUiThread(() -> {
                        if (a.isFinishing()) return;
                        new AlertDialog.Builder(a)
                                .setTitle("새 버전 " + name)
                                .setMessage("지금 버전은 " + BuildConfig.VERSION_NAME + " 입니다. 업데이트할까요?")
                                .setPositiveButton("업데이트", (d, w) -> download(a, base, name))
                                .setNegativeButton("나중에", null)
                                .show();
                    });
                } else if (manual) {
                    toast(a, "최신 버전입니다 (" + BuildConfig.VERSION_NAME + ")");
                }
            } catch (FileNotFoundException e) {
                if (manual) toast(a, "서버에 앱 파일이 없습니다");
            } catch (Exception e) {
                if (manual) toast(a, "업데이트를 확인하지 못했습니다: " + e.getMessage());
            }
        }, "update-check").start();
    }

    private static void download(Activity a, String base, String name) {
        if (!a.getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(a)
                    .setTitle("설치 허용이 필요합니다")
                    .setMessage("다음 화면에서 「이 출처 허용」을 켠 뒤, 돌아와서 다시 업데이트를 누르세요.")
                    .setPositiveButton("설정 열기", (d, w) -> a.startActivity(new Intent(
                            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + a.getPackageName()))))
                    .setNegativeButton("취소", null)
                    .show();
            return;
        }
        AlertDialog progress = new AlertDialog.Builder(a)
                .setTitle("새 버전 " + name)
                .setMessage("내려받는 중…")
                .setCancelable(false)
                .show();
        new Thread(() -> {
            try {
                install(a, base + "/app/homework-tracker.apk");
                a.runOnUiThread(progress::dismiss);
            } catch (Exception e) {
                a.runOnUiThread(progress::dismiss);
                toast(a, "업데이트 실패: " + e.getMessage());
            }
        }, "update-download").start();
    }

    /** PackageInstaller 세션에 APK 를 써 넣고 설치를 요청한다. 확인 화면은 InstallReceiver 가 띄운다. */
    private static void install(Activity a, String apkUrl) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(apkUrl).openConnection();
        c.setConnectTimeout(5000);
        c.setReadTimeout(30000);
        if (c.getResponseCode() != 200) throw new IOException("HTTP " + c.getResponseCode());
        long size = c.getContentLengthLong();
        PackageInstaller pi = a.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params =
                new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(a.getPackageName());
        int id = pi.createSession(params);
        try (PackageInstaller.Session s = pi.openSession(id)) {
            try (InputStream in = c.getInputStream(); OutputStream out = s.openWrite("app.apk", 0, size)) {
                byte[] buf = new byte[64 * 1024];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                s.fsync(out);
            } finally {
                c.disconnect();
            }
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;  // 설치기가 결과를 채워 넣는다
            PendingIntent pending = PendingIntent.getBroadcast(a, id, new Intent(a, InstallReceiver.class), flags);
            s.commit(pending.getIntentSender());
        }
    }

    static void toast(Activity a, String msg) {
        a.runOnUiThread(() -> Toast.makeText(a, msg, Toast.LENGTH_LONG).show());
    }
}
