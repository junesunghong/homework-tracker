package kr.home.homeworktracker;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 집 서버와의 통신. 모두 백그라운드 스레드에서 부른다. */
final class Net {
    static final int DISCOVERY_PORT = 47800;  // server.py 의 DISCOVERY_PORT 와 같아야 한다

    private Net() {}

    static String get(String url, int timeoutMs) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(timeoutMs);
        c.setReadTimeout(timeoutMs);
        try {
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code);
            return read(c.getInputStream());
        } finally {
            c.disconnect();
        }
    }

    static String read(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        in.close();
        return out.toString(StandardCharsets.UTF_8.name());
    }

    /** "192.168.0.23", "192.168.0.23:8080", "http://…" 어떤 꼴이든 http://호스트:포트 로 바꾼다. */
    static String normalize(String input) {
        String s = input.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (s.isEmpty()) return null;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        String hostPart = s.substring(s.indexOf("://") + 3);
        if (!hostPart.contains(":")) s = s + ":" + Prefs.PORT;
        return s;
    }

    /** 숙제 체크 서버가 맞으면 가족 이름(없으면 빈 문자열)을, 아니면 예외를 던진다. */
    static String checkServer(String base) throws Exception {
        JSONObject st = new JSONObject(get(base + "/api/status", 4000));
        if (!st.has("setup_done")) throw new IOException("숙제 체크 서버가 아닙니다");
        return st.optString("family_name", "");
    }

    static final class Found {
        final String url;
        final String name;
        final String version;

        Found(String url, String name, String version) {
            this.url = url;
            this.name = name;
            this.version = version;
        }
    }

    /** 같은 와이파이에 'HWT_DISCOVER' 를 브로드캐스트하고 답한 서버를 모은다. */
    static List<Found> discover(int waitMs) {
        Map<String, Found> found = new LinkedHashMap<>();
        try (DatagramSocket sock = new DatagramSocket()) {
            sock.setBroadcast(true);
            sock.setSoTimeout(300);
            byte[] msg = "HWT_DISCOVER".getBytes(StandardCharsets.US_ASCII);
            for (InetAddress target : broadcastTargets()) {
                try {
                    sock.send(new DatagramPacket(msg, msg.length, target, DISCOVERY_PORT));
                } catch (IOException ignored) {
                    // 보낼 수 없는 인터페이스는 건너뛴다
                }
            }
            long end = System.currentTimeMillis() + waitMs;
            byte[] buf = new byte[1024];
            while (System.currentTimeMillis() < end) {
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                try {
                    sock.receive(p);
                } catch (SocketTimeoutException e) {
                    continue;
                }
                try {
                    JSONObject j = new JSONObject(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8));
                    if (!"homework-tracker".equals(j.optString("app"))) continue;
                    String url = "http://" + p.getAddress().getHostAddress() + ":" + j.optInt("port", Prefs.PORT);
                    found.put(url, new Found(url, j.optString("name"), j.optString("version")));
                } catch (Exception ignored) {
                    // 다른 프로그램의 응답
                }
            }
        } catch (IOException ignored) {
            // 와이파이가 꺼져 있으면 빈 목록
        }
        return new ArrayList<>(found.values());
    }

    private static List<InetAddress> broadcastTargets() {
        List<InetAddress> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    if (ia.getBroadcast() != null && !out.contains(ia.getBroadcast())) out.add(ia.getBroadcast());
                }
            }
            out.add(InetAddress.getByName("255.255.255.255"));
        } catch (IOException ignored) {
            // 인터페이스 목록을 못 읽으면 전체 브로드캐스트만
        }
        return out;
    }

    /** 이 기기의 와이파이(사설망) IPv4 주소들 — 서버 알림에 접속 주소를 보여 줄 때 쓴다. */
    static List<String> lanAddresses() {
        List<String> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    InetAddress a = ia.getAddress();
                    if (a.getAddress().length == 4 && a.isSiteLocalAddress()) out.add(a.getHostAddress());
                }
            }
        } catch (IOException ignored) {
            // 없으면 빈 목록
        }
        return out;
    }
}
