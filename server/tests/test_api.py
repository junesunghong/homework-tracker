"""API 통합 테스트 — 실제 HTTP 서버를 임시 DB 로 띄워 검증한다.

    python3 -m unittest discover -s tests
"""

import datetime as dt
import json
import os
import sys
import tempfile
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["HW_QUIET"] = "1"
import server  # noqa: E402


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.httpd, self.store = server.make_server(os.path.join(self.tmp.name, "hw.db"), "127.0.0.1", 0)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.db.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token=None, headers=None, expect=200):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                status, payload = r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            status, payload = e.code, json.loads(e.read())
        self.assertEqual(status, expect, payload)
        return payload

    def setup_family(self):
        self.call("POST", "/api/setup", {
            "family_name": "우리집",
            "parent": {"name": "아빠", "pin": "1234"},
            "children": [{"name": "첫째", "pin": "1111", "entry_year": 2021},
                         {"name": "둘째", "pin": "2222", "entry_year": 2024}],
        })
        members = {m["name"]: m for m in self.call("GET", "/api/status")["members"]}
        login = lambda name, pin: self.call("POST", "/api/login", {"user_id": members[name]["id"], "pin": pin})["token"]
        return members, login("아빠", "1234"), login("첫째", "1111"), login("둘째", "2222")

    # ------------------------------------------------------------------
    def test_setup_once_and_static(self):
        self.assertFalse(self.call("GET", "/api/status")["setup_done"])
        self.setup_family()
        self.assertTrue(self.call("GET", "/api/status")["setup_done"])
        self.call("POST", "/api/setup", {"family_name": "x", "parent": {"name": "a", "pin": "1234"},
                                         "children": [{"name": "b", "pin": "1234"}]}, expect=409)
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn("숙제 체크", r.read().decode())
        with urllib.request.urlopen(self.base + "/../server.py") as r:  # 경로 탈출 차단 → index 폴백
            self.assertIn("<!doctype html>", r.read().decode())

    def test_login_and_lockout(self):
        members, *_ = self.setup_family()
        uid = members["첫째"]["id"]
        for _ in range(5):
            self.call("POST", "/api/login", {"user_id": uid, "pin": "0000"}, expect=401)
        self.call("POST", "/api/login", {"user_id": uid, "pin": "1111"}, expect=429)
        self.call("GET", "/api/tasks", expect=401)

    def test_homework_flow(self):
        members, parent, kid1, kid2 = self.setup_family()
        rev0 = self.call("GET", "/api/rev", token=kid1)["rev"]
        t = self.call("POST", "/api/tasks", {"title": "수학익힘책 34쪽", "subject": "수학", "due_date": "2026-10-27"},
                      token=kid1)["task"]
        self.assertEqual(t["child_id"], members["첫째"]["id"])
        self.assertGreater(self.call("GET", "/api/rev", token=kid1)["rev"], rev0)

        # 다른 자녀는 볼 수도 건드릴 수도 없다
        self.assertEqual(self.call("GET", "/api/tasks", token=kid2)["tasks"], [])
        self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "start"}, token=kid2, expect=404)

        self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "progress", "progress": 50}, token=kid1)
        got = self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "submit"}, token=kid1)["task"]
        self.assertEqual((got["status"], got["progress"]), ("submitted", 100))

        # 자녀는 스스로 완료 확인할 수 없다
        self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "approve"}, token=kid1, expect=403)
        # 부모 반려 → 다시 하는 중
        got = self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "reject", "note": "풀이 써"},
                        token=parent)["task"]
        self.assertEqual((got["status"], got["progress"]), ("doing", 50))
        listed = self.call("GET", "/api/tasks", token=kid1)["tasks"][0]
        self.assertEqual((listed["last_decision"], listed["last_note"]), ("reject", "풀이 써"))
        self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "submit"}, token=kid1)
        got = self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "approve"}, token=parent)["task"]
        self.assertEqual(got["status"], "done")
        self.assertIsNotNone(got["completed_at"])

        logs = self.call("GET", f"/api/tasks/{t['id']}/logs", token=kid1)["logs"]
        self.assertEqual([l["action"] for l in logs], ["create", "progress", "submit", "reject", "submit", "approve"])
        self.assertEqual(logs[3]["note"], "풀이 써")

    def test_parent_task_permissions(self):
        members, parent, kid1, _ = self.setup_family()
        self.call("POST", "/api/tasks", {"title": "x"}, token=parent, expect=400)  # 자녀 미지정
        t = self.call("POST", "/api/tasks", {"title": "독서록", "child_id": members["첫째"]["id"]}, token=parent)["task"]
        self.call("PATCH", f"/api/tasks/{t['id']}", {"title": "바꿈"}, token=kid1, expect=403)
        self.call("DELETE", f"/api/tasks/{t['id']}", token=kid1, expect=403)
        self.call("POST", "/api/members", {"role": "child", "name": "셋째", "pin": "3333"}, token=kid1, expect=403)
        self.call("DELETE", f"/api/tasks/{t['id']}", token=parent)

    def test_routine_generates_today(self):
        members, parent, kid1, _ = self.setup_family()
        self.call("POST", "/api/routines", {"child_id": members["첫째"]["id"], "title": "영단어 30개",
                                            "weekdays": [1, 2, 3, 4, 5, 6, 7]}, token=parent)
        tasks = self.call("GET", "/api/tasks", token=kid1)["tasks"]
        self.call("GET", "/api/tasks", token=kid1)  # 두 번 불러도 중복 생성 안 됨
        tasks = self.call("GET", "/api/tasks", token=kid1)["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["due_date"], dt.date.today().isoformat())
        self.assertEqual(tasks[0]["source"], "routine")

    def test_import_inbox(self):
        members, parent, kid1, _ = self.setup_family()
        key = self.call("GET", "/api/settings", token=parent)["import_key"]
        self.call("POST", "/api/import", {"text": "x"}, headers={"X-Import-Key": "wrong"}, expect=401)
        t = self.call("POST", "/api/import", {"child": "첫째", "source": "sms",
                                              "text": "[OO초] 내일까지 수학익힘책 34쪽 풀어오기"},
                      headers={"X-Import-Key": key})["task"]
        self.assertEqual(t["status"], "inbox")
        self.assertEqual(t["subject"], "수학")
        self.assertEqual(t["due_date"], (dt.date.today() + dt.timedelta(days=1)).isoformat())
        self.assertEqual(t["title"], "내일까지 수학익힘책 34쪽 풀어오기")
        # 자녀는 inbox 를 스스로 수락할 수 없다
        self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "accept"}, token=kid1, expect=403)
        got = self.call("POST", f"/api/tasks/{t['id']}/action", {"action": "accept"}, token=parent)["task"]
        self.assertEqual(got["status"], "todo")

    def test_pin_change_revokes_other_sessions(self):
        members, parent, kid1, _ = self.setup_family()
        self.call("PATCH", f"/api/members/{members['첫째']['id']}", {"pin": "9999"}, token=parent)
        self.call("GET", "/api/me", token=kid1, expect=401)


class AppDistributionTest(unittest.TestCase):
    """앱 업데이트 배포 · 자동 찾기 · 내장 실행."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def serve(self, apk=None):
        httpd, store = server.make_server(os.path.join(self.tmp.name, "hw.db"), "127.0.0.1", 0, apk=apk)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close(), store.db.close()))
        return "http://127.0.0.1:%d" % httpd.server_address[1], store

    def test_no_apk_returns_404(self):
        base, _ = self.serve()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(base + "/app/version.json")
        self.assertEqual(cm.exception.code, 404)

    def test_apk_dir_served(self):
        d = os.path.join(self.tmp.name, "apk")
        os.makedirs(d)
        with open(os.path.join(d, "homework-tracker.apk"), "wb") as f:
            f.write(b"PK\x03\x04fake-apk")
        with open(os.path.join(d, "version.json"), "w") as f:
            json.dump({"versionCode": 10200, "versionName": "1.2.0"}, f)
        base, _ = self.serve(server.load_apk_dir(d))
        with urllib.request.urlopen(base + "/app/version.json") as r:
            info = json.loads(r.read())
        self.assertEqual((info["versionCode"], info["versionName"], info["size"]), (10200, "1.2.0", 12))
        with urllib.request.urlopen(base + info["url"]) as r:
            self.assertEqual(r.headers["Content-Type"], "application/vnd.android.package-archive")
            self.assertEqual(r.read(), b"PK\x03\x04fake-apk")
        self.assertIsNone(server.load_apk_dir(os.path.join(self.tmp.name, "none")))

    def test_discovery_reply(self):
        _, store = self.serve()
        port = 47999
        sock = server.start_discovery(store, 8080, port)
        self.assertIsNotNone(sock)
        self.addCleanup(sock.close)
        c = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        c.settimeout(3)
        c.sendto(b"hello", ("127.0.0.1", port))          # 다른 요청은 무시
        c.sendto(server.DISCOVERY_REQUEST, ("127.0.0.1", port))
        reply = json.loads(c.recvfrom(1024)[0])
        c.close()
        self.assertEqual((reply["app"], reply["port"]), ("homework-tracker", 8080))

    def test_run_and_stop_embedded(self):
        static = os.path.join(self.tmp.name, "web")
        os.makedirs(static)
        with open(os.path.join(static, "index.html"), "w", encoding="utf-8") as f:
            f.write("embedded-ui")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        t = threading.Thread(target=server.run_embedded,
                             args=(self.tmp.name, static, port, None, 0, ""), daemon=True)
        t.start()
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
                    self.assertEqual(r.read().decode(), "embedded-ui")
                break
            except OSError:
                time.sleep(0.1)
        else:
            self.fail("내장 서버가 뜨지 않았습니다")
        server.stop_embedded()
        t.join(5)
        self.assertFalse(t.is_alive())


class UnitTest(unittest.TestCase):
    def test_school_grade(self):
        g = server.school_grade
        self.assertEqual(g(2021, dt.date(2026, 10, 26))["label"], "초6")
        self.assertEqual(g(2021, dt.date(2027, 2, 28))["label"], "초6")
        self.assertEqual(g(2021, dt.date(2027, 3, 1))["label"], "중1")
        self.assertEqual(g(2021, dt.date(2030, 3, 1))["label"], "고1")

    def test_guess_due(self):
        base = dt.date(2026, 10, 26)  # 월요일
        self.assertEqual(server.guess_due("10/28까지", base), "2026-10-28")
        self.assertEqual(server.guess_due("11월 3일 제출", base), "2026-11-03")
        self.assertEqual(server.guess_due("1월 5일", dt.date(2026, 12, 20)), "2027-01-05")
        self.assertEqual(server.guess_due("금요일까지", base), "2026-10-30")
        self.assertEqual(server.guess_due("모레까지", base), "2026-10-28")
        self.assertIsNone(server.guess_due("그냥 메모", base))


if __name__ == "__main__":
    unittest.main()
