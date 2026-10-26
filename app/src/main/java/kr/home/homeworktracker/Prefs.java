package kr.home.homeworktracker;

import android.content.Context;
import android.content.SharedPreferences;

/** 이 기기의 역할(서버/접속 기기)과 접속할 서버 주소. 설치 후 처음 한 번 SetupActivity 에서 정한다. */
final class Prefs {
    static final String ROLE_SERVER = "server";
    static final String ROLE_CLIENT = "client";
    static final int PORT = 8080;

    private Prefs() {}

    private static SharedPreferences p(Context c) {
        return c.getSharedPreferences("homework", Context.MODE_PRIVATE);
    }

    static String role(Context c) {
        return p(c).getString("role", null);
    }

    static boolean isServer(Context c) {
        return ROLE_SERVER.equals(role(c));
    }

    static String serverUrl(Context c) {
        return p(c).getString("server_url", null);
    }

    static void setServer(Context c) {
        p(c).edit().putString("role", ROLE_SERVER).remove("server_url").apply();
    }

    static void setClient(Context c, String url) {
        p(c).edit().putString("role", ROLE_CLIENT).putString("server_url", url).apply();
    }

    /** 이 기기가 화면을 띄울 주소. 서버 기기는 자기 자신에 붙는다. */
    static String baseUrl(Context c) {
        return isServer(c) ? "http://127.0.0.1:" + PORT : serverUrl(c);
    }
}
