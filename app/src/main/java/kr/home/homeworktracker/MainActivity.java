package kr.home.homeworktracker;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * 숙제 체크 화면 — 집 서버의 웹 화면을 WebView 로 띄운다.
 * 화면 코드는 서버가 내려주므로, 서버만 업데이트하면 화면도 바뀐다. 앱 껍데기는 Updater 가 올린다.
 */
public class MainActivity extends Activity {
    private static final int MAX_SERVER_WAIT = 20;  // 서버 기기: 내장 서버가 뜰 때까지 1초 간격 재시도 횟수

    private final Handler ui = new Handler(Looper.getMainLooper());
    private WebView web;
    private View errorView;
    private TextView errorText;
    private String base;
    private int retries;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (Prefs.role(this) == null) {
            startActivity(new Intent(this, SetupActivity.class));
            finish();
            return;
        }
        if (Prefs.isServer(this)) ServerService.start(this);
        base = Prefs.baseUrl(this);
        buildUi();
        load();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        // 설정에서 서버 주소나 역할을 바꾸고 돌아온 경우
        String now = Prefs.baseUrl(this);
        if (now != null && !now.equals(base)) {
            base = now;
            load();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
        if (!Prefs.isServer(this)) Updater.autoCheck(this, base);
    }

    @Override
    protected void onPause() {
        if (web != null) web.onPause();
        super.onPause();
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // 로그인 토큰을 localStorage 에 둔다
        s.setTextZoom(100);
        s.setUserAgentString(s.getUserAgentString() + " HomeworkApp/" + BuildConfig.VERSION_NAME);
        web.addJavascriptInterface(new Bridge(), "HomeworkApp");
        web.setWebChromeClient(new WebChromeClient());  // confirm()·alert() 대화상자
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) onLoadFailed();
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (url != null && url.startsWith("http")) retries = 0;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (base != null && u.toString().startsWith(base)) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, u));  // 서버 밖 링크는 브라우저로
                return true;
            }
        });
        root.addView(web);
        root.addView(errorView = buildErrorView());
        setContentView(root);
    }

    private View buildErrorView() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(Color.rgb(0xF5, 0xF6, 0xFA));
        int pad = dp(24);
        box.setPadding(pad, pad, pad, pad);
        errorText = new TextView(this);
        errorText.setTextSize(17);
        errorText.setGravity(Gravity.CENTER);
        errorText.setTextColor(Color.rgb(0x1F, 0x23, 0x33));
        box.addView(errorText);
        Button retry = new Button(this);
        retry.setText("다시 연결");
        retry.setOnClickListener(v -> load());
        box.addView(retry);
        Button settings = new Button(this);
        settings.setText("서버 다시 찾기 · 앱 설정");
        settings.setOnClickListener(v -> openSettings());
        box.addView(settings);
        box.setVisibility(View.GONE);
        return box;
    }

    private void load() {
        errorView.setVisibility(View.GONE);
        web.loadUrl(base + "/");
    }

    private void onLoadFailed() {
        if (Prefs.isServer(this) && retries < MAX_SERVER_WAIT) {
            retries++;
            showError("서버를 시작하는 중입니다…");
            ui.postDelayed(this::load, 1000);
            return;
        }
        showError(Prefs.isServer(this)
                ? "이 기기의 서버가 응답하지 않습니다.\n알림 창의 「숙제 체크 서버」 상태를 확인하세요."
                : "집 서버(" + base + ")에 연결할 수 없습니다.\n\n· 집 와이파이에 연결되어 있나요?\n· 서버 기기가 켜져 있나요?");
    }

    private void showError(String msg) {
        errorText.setText(msg);
        errorView.setVisibility(View.VISIBLE);
    }

    private void openSettings() {
        startActivity(new Intent(this, SetupActivity.class));
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        // 화면 안의 창(할 일 상세·설정 등)이 열려 있으면 그것부터 닫는다
        web.evaluateJavascript("window.hwBack ? window.hwBack() : false", result -> {
            if (!"true".equals(result)) super.onBackPressed();
        });
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        if (web != null) web.destroy();
        super.onDestroy();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    /** 화면 코드(app.js)가 부르는 앱 기능. window.HomeworkApp 으로 보인다. */
    private final class Bridge {
        @JavascriptInterface
        public String appVersion() {
            return BuildConfig.VERSION_NAME;
        }

        @JavascriptInterface
        public String role() {
            return Prefs.role(MainActivity.this);
        }

        @JavascriptInterface
        public void openAppSettings() {
            runOnUiThread(MainActivity.this::openSettings);
        }

        @JavascriptInterface
        public void checkUpdate() {
            runOnUiThread(() -> Updater.check(MainActivity.this, base, true));
        }

        /** WebView 는 blob 다운로드를 못 하므로 백업 JSON 을 앱이 「다운로드」 폴더에 저장한다. */
        @JavascriptInterface
        public void saveFile(String name, String content) {
            String safe = name.replaceAll("[^0-9A-Za-z._-]", "_");
            try {
                String where = save(safe, content.getBytes(StandardCharsets.UTF_8));
                toast("저장했습니다: " + where);
            } catch (Exception e) {
                toast("저장하지 못했습니다: " + e.getMessage());
            }
        }

        private String save(String name, byte[] data) throws Exception {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                v.put(MediaStore.MediaColumns.MIME_TYPE, "application/json");
                v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) throw new IllegalStateException("저장 위치를 만들 수 없습니다");
                try (OutputStream out = getContentResolver().openOutputStream(uri)) {
                    if (out == null) throw new IllegalStateException("파일을 열 수 없습니다");
                    out.write(data);
                }
                return "다운로드/" + name;
            }
            File dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
            File f = new File(dir, name);
            try (OutputStream out = new FileOutputStream(f)) {
                out.write(data);
            }
            return f.getAbsolutePath();
        }

        private void toast(String msg) {
            runOnUiThread(() -> Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show());
        }
    }
}
