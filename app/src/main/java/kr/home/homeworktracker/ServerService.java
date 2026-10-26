package kr.home.homeworktracker;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.content.res.AssetManager;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.List;

/**
 * 서버 모드 — 앱 안에 넣은 server.py 를 파이썬(Chaquopy)으로 돌린다.
 * 포그라운드 서비스라 화면이 꺼져도 계속 돌고, 재부팅·앱 업데이트 뒤에는 BootReceiver 가 다시 켠다.
 */
public class ServerService extends Service {
    private static final String TAG = "HomeworkServer";
    private static final String CHANNEL = "server";
    private static final int NOTIFY_ID = 1;

    static volatile boolean running;

    private Thread thread;
    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private WifiManager.MulticastLock multicastLock;

    static void start(Context c) {
        Intent i = new Intent(c, ServerService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
        else c.startService(i);  // 안드로이드 7
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, ServerService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startInForeground(notification("서버를 시작하는 중…"));
        if (thread == null) {
            acquireLocks();
            thread = new Thread(this::runServer, "homework-server");
            thread.start();
        }
        return START_STICKY;
    }

    private void runServer() {
        try {
            if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
            File web = copyWebAssets();
            File data = new File(getFilesDir(), "data");
            if (!data.isDirectory() && !data.mkdirs()) throw new IOException("데이터 폴더를 만들 수 없습니다");
            PyObject server = Python.getInstance().getModule("server");
            List<String> addrs = Net.lanAddresses();
            String where = addrs.isEmpty() ? "와이파이 연결을 확인하세요" : "http://" + addrs.get(0) + ":" + Prefs.PORT;
            notifyText("서버 실행 중 · " + where);
            running = true;
            // 서버가 멈출 때(stop_embedded)까지 돌아오지 않는다. 앱 자신의 APK 를 다른 기기에 배포한다.
            server.callAttr("run_embedded", data.getAbsolutePath(), web.getAbsolutePath(), Prefs.PORT,
                    getApplicationInfo().sourceDir, BuildConfig.VERSION_CODE, BuildConfig.VERSION_NAME);
        } catch (Throwable t) {
            Log.e(TAG, "server failed", t);
            notifyText("서버 오류: " + t.getMessage());
        } finally {
            running = false;
        }
    }

    /** 화면 파일(assets/web)을 파이썬이 읽을 수 있는 앱 폴더로 꺼낸다. 앱이 업데이트되면 새 화면으로 바뀐다. */
    private File copyWebAssets() throws IOException {
        File dir = new File(getFilesDir(), "web");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("화면 폴더를 만들 수 없습니다");
        AssetManager am = getAssets();
        String[] names = am.list("web");
        if (names == null) return dir;
        for (String name : names) {
            try (InputStream in = am.open("web/" + name); OutputStream out = new FileOutputStream(new File(dir, name))) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        }
        return dir;
    }

    @SuppressWarnings("deprecation")
    private void acquireLocks() {
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "homework:server");
        wakeLock.acquire();
        WifiManager wm = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        wifiLock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "homework:server");
        wifiLock.acquire();
        // 화면이 꺼져 있어도 자동 찾기(브로드캐스트) 요청을 받도록
        multicastLock = wm.createMulticastLock("homework:discovery");
        multicastLock.acquire();
    }

    private void releaseLocks() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
    }

    @Override
    public void onDestroy() {
        try {
            if (Python.isStarted()) Python.getInstance().getModule("server").callAttr("stop_embedded");
        } catch (Throwable t) {
            Log.w(TAG, "stop failed", t);
        }
        releaseLocks();
        thread = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ---------------------------------------------------------------- 알림

    private void startInForeground(Notification n) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFY_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFY_ID, n);
        }
    }

    private void notifyText(String text) {
        getSystemService(NotificationManager.class).notify(NOTIFY_ID, notification(text));
    }

    @SuppressWarnings("deprecation")
    private Notification notification(String text) {
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm.getNotificationChannel(CHANNEL) == null) {
                NotificationChannel ch = new NotificationChannel(CHANNEL, "숙제 체크 서버", NotificationManager.IMPORTANCE_LOW);
                ch.setDescription("이 기기가 집 서버로 동작하는 동안 표시됩니다");
                nm.createNotificationChannel(ch);
            }
            b = new Notification.Builder(this, CHANNEL);
        } else {
            b = new Notification.Builder(this).setPriority(Notification.PRIORITY_LOW);  // 안드로이드 7
        }
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return b
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("숙제 체크 서버")
                .setContentText(text)
                .setContentIntent(open)
                .setOngoing(true)
                .build();
    }
}
