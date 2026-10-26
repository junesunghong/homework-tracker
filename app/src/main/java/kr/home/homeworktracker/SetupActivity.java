package kr.home.homeworktracker;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

/**
 * 설치 후 처음 한 번 — 이 기기의 역할을 고른다.
 *   서버: 집에 늘 켜 두는 안드로이드 기기 1대. 데이터가 여기에 저장된다.
 *   접속 기기: 자녀 탭·부모 휴대폰. 같은 와이파이의 서버를 찾아 붙는다.
 * 나중에 화면의 「앱 설정」으로 다시 들어와 바꿀 수 있다.
 */
public class SetupActivity extends Activity {
    private static final int TEXT = Color.rgb(0x1F, 0x23, 0x33);
    private static final int MUTED = Color.rgb(0x6B, 0x71, 0x85);

    private LinearLayout foundList;
    private TextView foundStatus;
    private EditText manual;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        scroll.setFitsSystemWindows(true);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        col.setPadding(pad, pad, pad, dp(40));
        scroll.addView(col);

        col.addView(text("숙제 체크 설정", 24, true, TEXT));
        String role = Prefs.role(this);
        String now = role == null ? "아직 정하지 않았습니다"
                : Prefs.isServer(this) ? "현재: 이 기기가 서버" : "현재: 접속 기기 → " + Prefs.serverUrl(this);
        col.addView(text(now + "   ·   앱 버전 " + BuildConfig.VERSION_NAME, 14, false, MUTED));

        // 1) 접속 기기
        col.addView(section("자녀 탭 · 부모 휴대폰 (접속 기기)"));
        col.addView(text("집 와이파이에 연결한 뒤 서버를 찾으세요.", 15, false, MUTED));
        Button find = button("서버 자동으로 찾기");
        find.setOnClickListener(v -> discover());
        col.addView(find);
        foundStatus = text("", 14, false, MUTED);
        col.addView(foundStatus);
        foundList = new LinearLayout(this);
        foundList.setOrientation(LinearLayout.VERTICAL);
        col.addView(foundList);
        col.addView(text("찾지 못하면 서버 화면의 주소를 직접 입력하세요 (예: 192.168.0.23:8080)", 14, false, MUTED));
        manual = new EditText(this);
        manual.setHint("192.168.0.23:8080");
        manual.setSingleLine(true);
        manual.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        if (!Prefs.isServer(this) && Prefs.serverUrl(this) != null) {
            manual.setText(Prefs.serverUrl(this).replace("http://", ""));
        }
        col.addView(manual);
        Button connect = button("이 주소로 연결");
        connect.setOnClickListener(v -> connect(manual.getText().toString()));
        col.addView(connect);

        // 2) 서버
        col.addView(section("이 기기를 집 서버로 사용"));
        col.addView(text("집에 늘 켜 두는 기기 1대만 서버로 정합니다. 숙제 데이터가 이 기기에 저장되고, "
                + "다른 기기에 앱 업데이트도 나눠 줍니다. 충전기에 꽂아 두세요.", 15, false, MUTED));
        Button server = button(Prefs.isServer(this) ? "서버로 계속 사용" : "이 기기를 서버로 사용");
        server.setOnClickListener(v -> confirmServer());
        col.addView(server);
        if (Prefs.isServer(this)) {
            Button battery = button("배터리 최적화 해제 (서버가 꺼지지 않게)");
            battery.setOnClickListener(v -> askBatteryExemption(true));
            col.addView(battery);
        }

        setContentView(scroll);
        if (role == null) discover();  // 처음 설치면 바로 찾아 본다
    }

    // ---------------------------------------------------------------- 접속 기기

    private void discover() {
        foundStatus.setText("같은 와이파이에서 서버를 찾는 중…");
        foundList.removeAllViews();
        new Thread(() -> {
            List<Net.Found> found = Net.discover(2500);
            runOnUiThread(() -> {
                if (isFinishing()) return;
                foundStatus.setText(found.isEmpty() ? "서버를 찾지 못했습니다. 서버 기기가 켜져 있고 같은 와이파이인지 확인하세요."
                        : "찾은 서버 — 눌러서 연결하세요");
                for (Net.Found f : found) {
                    String label = (f.name.isEmpty() ? "숙제 체크 서버" : f.name) + "\n" + f.url;
                    Button b = button(label);
                    b.setOnClickListener(v -> connect(f.url));
                    foundList.addView(b);
                }
            });
        }, "discover").start();
    }

    private void connect(String input) {
        String url = Net.normalize(input);
        if (url == null) {
            toast("서버 주소를 입력하세요");
            return;
        }
        toast("연결 확인 중…");
        new Thread(() -> {
            try {
                String family = Net.checkServer(url);
                runOnUiThread(() -> {
                    if (Prefs.isServer(this)) ServerService.stop(this);
                    Prefs.setClient(this, url);
                    toast((family.isEmpty() ? "서버" : family) + "에 연결했습니다");
                    openMain();
                });
            } catch (Exception e) {
                runOnUiThread(() -> toast("연결할 수 없습니다: " + url + "\n(" + e.getMessage() + ")"));
            }
        }, "connect").start();
    }

    // ---------------------------------------------------------------- 서버

    private void confirmServer() {
        if (Prefs.isServer(this)) {
            openMain();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("이 기기를 서버로 사용할까요?")
                .setMessage("가족 중 서버는 1대만 있어야 합니다. 서버 기기는 집 와이파이에 연결된 채로 켜 두어야 "
                        + "다른 기기가 숙제를 확인할 수 있습니다.")
                .setPositiveButton("서버로 사용", (d, w) -> {
                    Prefs.setServer(this);
                    if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
                    ServerService.start(this);
                    askBatteryExemption(false);
                    openMain();
                })
                .setNegativeButton("취소", null)
                .show();
    }

    private void askBatteryExemption(boolean always) {
        PowerManager pm = getSystemService(PowerManager.class);
        if (pm.isIgnoringBatteryOptimizations(getPackageName())) {
            if (always) toast("이미 배터리 최적화에서 제외되어 있습니다");
            return;
        }
        try {
            startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:" + getPackageName())));
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        }
    }

    private void openMain() {
        Intent i = new Intent(this, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(i);
        finish();
    }

    // ---------------------------------------------------------------- 화면 조각

    private TextView section(String title) {
        TextView t = text(title, 18, true, TEXT);
        t.setPadding(0, dp(28), 0, dp(4));
        return t;
    }

    private TextView text(String s, int sp, boolean bold, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setPadding(0, dp(4), 0, dp(4));
        return t;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(6);
        b.setLayoutParams(lp);
        return b;
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (Prefs.role(this) == null) {
            finishAffinity();  // 역할을 정하지 않고 나가면 앱 종료
        } else {
            openMain();
        }
    }
}
