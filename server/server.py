#!/usr/bin/env python3
"""숙제·학습 체크 서버 (가족 그룹 1개 = 서버 1대).

집 와이파이 안의 PC·노트북·라즈베리파이·안드로이드(Termux) 중 한 대에서 실행하면
자녀 태블릿·부모 휴대폰이 브라우저로 접속해 같은 데이터를 공유한다.
파이썬 표준 라이브러리만 사용한다 (추가 설치 불필요).

    python3 server.py                 # 0.0.0.0:8080, 데이터는 ./data/homework.db
    python3 server.py --port 9000 --data D:/homework-data
"""

import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP_VERSION = "1.2.0"
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
APK_NAME = "homework-tracker.apk"
DISCOVERY_PORT = 47800          # 안드로이드 앱이 서버를 자동으로 찾을 때 쓰는 UDP 포트
DISCOVERY_REQUEST = b"HWT_DISCOVER"

STATUSES = ("inbox", "todo", "doing", "submitted", "done")
KINDS = ("homework", "study", "prepare", "exam", "etc")
DEFAULT_SUBJECTS = ["국어", "수학", "영어", "사회", "과학", "역사", "한자", "독서", "예체능", "학원", "기타"]
CHILD_COLORS = ["#4f7cff", "#ff7a59", "#2bb673", "#b05cff", "#f5b400", "#00a3c4"]
MAX_BODY = 1024 * 1024
SESSION_DAYS = 180


# ---------------------------------------------------------------- 유틸

def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def today():
    return dt.date.today()


def hash_pin(pin, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def check_pin(pin, stored):
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_pin(pin, salt), stored)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def valid_pin(pin):
    return isinstance(pin, str) and re.fullmatch(r"\d{4,8}", pin) is not None


def valid_date(value):
    if value in (None, ""):
        return True
    try:
        dt.date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def school_grade(entry_year, on=None):
    """초등 입학년도로 현재 학년을 계산한다. 학년도는 3월 1일에 바뀐다."""
    if not entry_year:
        return None
    on = on or today()
    academic_year = on.year if on.month >= 3 else on.year - 1
    n = academic_year - int(entry_year) + 1
    if n < 1:
        return {"level": "미취학", "grade": 0, "label": "미취학"}
    if n <= 6:
        return {"level": "초", "grade": n, "label": f"초{n}"}
    if n <= 9:
        return {"level": "중", "grade": n - 6, "label": f"중{n - 6}"}
    if n <= 12:
        return {"level": "고", "grade": n - 9, "label": f"고{n - 9}"}
    return {"level": "졸업", "grade": n, "label": "졸업"}


def lan_addresses():
    addrs = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------- 저장소

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('parent', 'child')),
    name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    entry_year INTEGER,
    color TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    device TEXT,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY,
    child_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    subject TEXT,
    kind TEXT NOT NULL DEFAULT 'study',
    weekdays TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    child_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    subject TEXT,
    kind TEXT NOT NULL DEFAULT 'homework',
    memo TEXT,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    progress INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    source_text TEXT,
    routine_id INTEGER REFERENCES routines(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_at TEXT,
    completed_at TEXT,
    verified_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_routine_day ON tasks(routine_id, due_date) WHERE routine_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_tasks_child_status ON tasks(child_id, status);
CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    note TEXT,
    progress INTEGER,
    at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', '1')")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('rev', '0')")

    # -- 기본 조회
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def meta(self, key, default=None):
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, str(value)))

    def bump(self):
        """변경 번호를 올린다. 클라이언트는 이 값만 폴링해 변경을 감지한다."""
        self.db.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'rev'")

    def rev(self):
        return int(self.meta("rev", "0"))

    def is_setup(self):
        return self.meta("family_name") is not None

    # -- 루틴 → 오늘 할 일 생성
    def ensure_routine_tasks(self, day=None):
        day = day or today()
        wd = str(day.isoweekday())  # 1=월 … 7=일
        with self.lock, self.db:
            routines = self.db.execute("SELECT * FROM routines WHERE active = 1").fetchall()
            created = 0
            for r in routines:
                if wd not in r["weekdays"].split(","):
                    continue
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO tasks (child_id, title, subject, kind, due_date, status, source, routine_id,"
                    " created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'todo', 'routine', ?, ?, ?, ?)",
                    (r["child_id"], r["title"], r["subject"], r["kind"], day.isoformat(), r["id"],
                     r["created_by"], now_iso(), now_iso()))
                created += cur.rowcount
            if created:
                self.bump()


# ---------------------------------------------------------------- 표현

def public_user(u):
    out = {"id": u["id"], "role": u["role"], "name": u["name"], "color": u["color"], "active": bool(u["active"])}
    if u["role"] == "child":
        out["entry_year"] = u["entry_year"]
        out["grade"] = school_grade(u["entry_year"])
    return out


# ---------------------------------------------------------------- 앱 (라우팅·권한)

class App:
    def __init__(self, store, port=8080, apk=None):
        self.store = store
        self.port = port
        self.apk = apk  # {"path", "versionCode", "versionName"} — 앱 업데이트 배포용
        self.fail = {}  # user_id -> (count, locked_until)
        self.fail_lock = threading.Lock()
        self.routes = []
        r = self.route
        r("GET", r"/api/status", self.status)
        r("POST", r"/api/setup", self.setup)
        r("POST", r"/api/login", self.login)
        r("POST", r"/api/logout", self.logout, auth=True)
        r("GET", r"/api/me", self.me, auth=True)
        r("GET", r"/api/rev", self.get_rev, auth=True)
        r("GET", r"/api/tasks", self.list_tasks, auth=True)
        r("POST", r"/api/tasks", self.create_task, auth=True)
        r("PATCH", r"/api/tasks/(\d+)", self.update_task, auth=True)
        r("DELETE", r"/api/tasks/(\d+)", self.delete_task, auth=True)
        r("POST", r"/api/tasks/(\d+)/action", self.task_action, auth=True)
        r("GET", r"/api/tasks/(\d+)/logs", self.task_logs, auth=True)
        r("GET", r"/api/members", self.list_members, auth=True)
        r("POST", r"/api/members", self.create_member, parent=True)
        r("PATCH", r"/api/members/(\d+)", self.update_member, parent=True)
        r("GET", r"/api/subjects", self.list_subjects, auth=True)
        r("POST", r"/api/subjects", self.create_subject, parent=True)
        r("DELETE", r"/api/subjects/(\d+)", self.delete_subject, parent=True)
        r("GET", r"/api/routines", self.list_routines, auth=True)
        r("POST", r"/api/routines", self.create_routine, parent=True)
        r("PATCH", r"/api/routines/(\d+)", self.update_routine, parent=True)
        r("DELETE", r"/api/routines/(\d+)", self.delete_routine, parent=True)
        r("GET", r"/api/stats", self.stats, auth=True)
        r("GET", r"/api/settings", self.settings, parent=True)
        r("POST", r"/api/settings/import-key", self.rotate_import_key, parent=True)
        r("GET", r"/api/export", self.export, parent=True)
        r("POST", r"/api/import", self.import_message)

    def route(self, method, pattern, handler, auth=False, parent=False):
        self.routes.append((method, re.compile(pattern + r"$"), handler, auth or parent, parent))

    def dispatch(self, method, path, query, body, headers):
        for m, rx, handler, need_auth, need_parent in self.routes:
            match = rx.match(path)
            if not match or m != method:
                continue
            user = None
            if need_auth:
                user = self.authenticate(headers)
                if need_parent and user["role"] != "parent":
                    raise ApiError(403, "부모만 할 수 있습니다.")
            ctx = {"user": user, "query": query, "body": body, "headers": headers}
            return handler(ctx, *[int(g) for g in match.groups()])
        raise ApiError(404, "없는 API 입니다.")

    def authenticate(self, headers):
        auth = headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise ApiError(401, "로그인이 필요합니다.")
        th = token_hash(auth[7:].strip())
        s = self.store
        row = s.one("SELECT u.*, s.last_seen FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
                    (th,))
        if not row or not row["active"]:
            raise ApiError(401, "로그인이 만료되었습니다.")
        if dt.datetime.fromisoformat(row["last_seen"]) < dt.datetime.now() - dt.timedelta(days=SESSION_DAYS):
            with s.lock, s.db:
                s.db.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
            raise ApiError(401, "로그인이 만료되었습니다.")
        with s.lock, s.db:
            s.db.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now_iso(), th))
        row["token_hash"] = th
        return row

    # -- 공통 검사
    def child_or_404(self, child_id):
        c = self.store.one("SELECT * FROM users WHERE id = ? AND role = 'child'", (child_id,))
        if not c:
            raise ApiError(404, "자녀를 찾을 수 없습니다.")
        return c

    def task_for(self, user, task_id):
        t = self.store.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not t or (user["role"] == "child" and t["child_id"] != user["id"]):
            raise ApiError(404, "할 일을 찾을 수 없습니다.")
        return t

    @staticmethod
    def text(body, key, required=False, maxlen=200):
        v = body.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            if required:
                raise ApiError(400, f"{key} 값이 필요합니다.")
            return None
        if not isinstance(v, str):
            raise ApiError(400, f"{key} 값이 올바르지 않습니다.")
        return v.strip()[:maxlen]

    def log(self, task_id, user_id, action, note=None, progress=None):
        self.store.db.execute("INSERT INTO task_logs (task_id, user_id, action, note, progress, at) VALUES (?,?,?,?,?,?)",
                              (task_id, user_id, action, note, progress, now_iso()))

    # -- 상태·설치
    def status(self, ctx):
        s = self.store
        members = [public_user(u) for u in s.q("SELECT * FROM users WHERE active = 1 ORDER BY role DESC, id")]
        return {"setup_done": s.is_setup(), "family_name": s.meta("family_name"), "members": members,
                "version": APP_VERSION}

    def setup(self, ctx):
        s, b = self.store, ctx["body"]
        family = self.text(b, "family_name", True, 40)
        parent = b.get("parent") or {}
        children = b.get("children") or []
        if not isinstance(parent, dict) or not isinstance(children, list) or not children:
            raise ApiError(400, "부모 1명과 자녀 1명 이상이 필요합니다.")
        p_name = self.text(parent, "name", True, 20)
        if not valid_pin(parent.get("pin")):
            raise ApiError(400, "PIN 은 숫자 4~8자리입니다.")
        rows = []
        for i, c in enumerate(children):
            if not isinstance(c, dict):
                raise ApiError(400, "자녀 정보가 올바르지 않습니다.")
            if not valid_pin(c.get("pin")):
                raise ApiError(400, "자녀 PIN 은 숫자 4~8자리입니다.")
            rows.append((self.text(c, "name", True, 20), c["pin"], self.entry_year(c.get("entry_year")),
                         CHILD_COLORS[i % len(CHILD_COLORS)]))
        with s.lock, s.db:
            if s.is_setup():
                raise ApiError(409, "이미 설치되었습니다.")
            s.db.execute("INSERT INTO users (role, name, pin_hash, color, created_at) VALUES ('parent',?,?,?,?)",
                         (p_name, hash_pin(parent["pin"]), "#555b6e", now_iso()))
            for name, pin, year, color in rows:
                s.db.execute("INSERT INTO users (role, name, pin_hash, entry_year, color, created_at)"
                             " VALUES ('child',?,?,?,?,?)", (name, hash_pin(pin), year, color, now_iso()))
            for i, name in enumerate(DEFAULT_SUBJECTS):
                s.db.execute("INSERT OR IGNORE INTO subjects (name, sort) VALUES (?, ?)", (name, i))
            s.set_meta("family_name", family)
            s.set_meta("import_key", secrets.token_urlsafe(24))
            s.bump()
        return self.status(ctx)

    @staticmethod
    def entry_year(value):
        if value in (None, ""):
            return None
        try:
            year = int(value)
        except (TypeError, ValueError):
            raise ApiError(400, "입학년도가 올바르지 않습니다.")
        if not 2000 <= year <= today().year + 7:
            raise ApiError(400, "입학년도가 올바르지 않습니다.")
        return year

    # -- 로그인
    def login(self, ctx):
        s, b = self.store, ctx["body"]
        uid = b.get("user_id")
        pin = b.get("pin")
        u = s.one("SELECT * FROM users WHERE id = ? AND active = 1", (uid,)) if isinstance(uid, int) else None
        if not u:
            raise ApiError(404, "사용자를 찾을 수 없습니다.")
        with self.fail_lock:
            count, until = self.fail.get(u["id"], (0, 0))
            if until > time.time():
                raise ApiError(429, f"PIN 을 여러 번 틀렸습니다. {int(until - time.time()) + 1}초 후 다시 시도하세요.")
        if not isinstance(pin, str) or not check_pin(pin, u["pin_hash"]):
            with self.fail_lock:
                count += 1
                self.fail[u["id"]] = (count, time.time() + 60 if count >= 5 else 0)
            raise ApiError(401, "PIN 이 맞지 않습니다.")
        with self.fail_lock:
            self.fail.pop(u["id"], None)
        token = secrets.token_urlsafe(32)
        device = self.text(b, "device", False, 80)
        with s.lock, s.db:
            s.db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (token_hash(token), u["id"], device, now_iso(),
                                                                      now_iso()))
        return {"token": token, "user": public_user(u)}

    def logout(self, ctx):
        with self.store.lock, self.store.db:
            self.store.db.execute("DELETE FROM sessions WHERE token_hash = ?", (ctx["user"]["token_hash"],))
        return {"ok": True}

    def me(self, ctx):
        return {"user": public_user(ctx["user"]), "family_name": self.store.meta("family_name"),
                "rev": self.store.rev()}

    def get_rev(self, ctx):
        return {"rev": self.store.rev()}

    # -- 할 일
    def list_tasks(self, ctx):
        s, user, qs = self.store, ctx["user"], ctx["query"]
        s.ensure_routine_tasks()
        where, args = [], []
        if user["role"] == "child":
            where.append("t.child_id = ?")
            args.append(user["id"])
        elif qs.get("child_id"):
            where.append("t.child_id = ?")
            args.append(int(qs["child_id"]))
        if qs.get("status"):
            statuses = [x for x in qs["status"].split(",") if x in STATUSES]
            if statuses:
                where.append("t.status IN (%s)" % ",".join("?" * len(statuses)))
                args += statuses
        if qs.get("from") and valid_date(qs["from"]):
            where.append("(t.due_date >= ? OR t.status != 'done')")
            args.append(qs["from"])
        if qs.get("done_since") and valid_date(qs["done_since"]):
            where.append("(t.status != 'done' OR t.completed_at >= ?)")
            args.append(qs["done_since"])
        # 가장 최근의 상태 결정 기록이 '반려'면 그 메모를 함께 내려 카드에 바로 보이게 한다.
        last = ("(SELECT l.%s FROM task_logs l WHERE l.task_id = t.id AND l.action IN"
                " ('submit', 'reject', 'approve', 'reopen', 'cancel') ORDER BY l.id DESC LIMIT 1)")
        sql = ("SELECT t.*, c.name AS child_name, c.color AS child_color, u.name AS created_by_name, u.role AS"
               " created_by_role, " + last % "action" + " AS last_decision, " + last % "note" + " AS last_note"
               " FROM tasks t JOIN users c ON c.id = t.child_id LEFT JOIN users u ON u.id = t.created_by")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (t.due_date IS NULL), t.due_date, t.id LIMIT 1000"
        return {"tasks": s.q(sql, args), "rev": s.rev(), "today": today().isoformat()}

    def create_task(self, ctx):
        s, user, b = self.store, ctx["user"], ctx["body"]
        if user["role"] == "child":
            child_id = user["id"]
        else:
            child_id = b.get("child_id")
            if not isinstance(child_id, int):
                raise ApiError(400, "자녀를 선택하세요.")
            self.child_or_404(child_id)
        fields = self.task_fields(b, creating=True)
        with s.lock, s.db:
            cur = s.db.execute(
                "INSERT INTO tasks (child_id, title, subject, kind, memo, due_date, status, progress, source,"
                " created_by, created_at, updated_at) VALUES (?,?,?,?,?,?, 'todo', 0, 'manual', ?,?,?)",
                (child_id, fields["title"], fields.get("subject"), fields.get("kind", "homework"), fields.get("memo"),
                 fields.get("due_date"), user["id"], now_iso(), now_iso()))
            self.log(cur.lastrowid, user["id"], "create")
            s.bump()
        return {"task": s.one("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,))}

    def task_fields(self, b, creating=False):
        out = {}
        if creating or "title" in b:
            out["title"] = self.text(b, "title", True, 200)
        for key, maxlen in (("subject", 30), ("memo", 2000)):
            if key in b:
                out[key] = self.text(b, key, False, maxlen)
        if "kind" in b:
            if b["kind"] not in KINDS:
                raise ApiError(400, "종류가 올바르지 않습니다.")
            out["kind"] = b["kind"]
        if "due_date" in b:
            if not valid_date(b["due_date"]):
                raise ApiError(400, "마감일 형식은 YYYY-MM-DD 입니다.")
            out["due_date"] = b["due_date"] or None
        if "child_id" in b and not creating:
            if not isinstance(b["child_id"], int):
                raise ApiError(400, "자녀가 올바르지 않습니다.")
            self.child_or_404(b["child_id"])
            out["child_id"] = b["child_id"]
        return out

    def update_task(self, ctx, task_id):
        s, user = self.store, ctx["user"]
        t = self.task_for(user, task_id)
        if user["role"] == "child":
            if t["created_by"] != user["id"] or t["status"] in ("submitted", "done"):
                raise ApiError(403, "부모님이 등록했거나 완료 요청한 숙제는 내용을 고칠 수 없어요.")
            ctx["body"].pop("child_id", None)
        fields = self.task_fields(ctx["body"])
        if not fields:
            return {"task": t}
        fields["updated_at"] = now_iso()
        with s.lock, s.db:
            s.db.execute("UPDATE tasks SET %s WHERE id = ?" % ", ".join(f"{k} = ?" for k in fields),
                         (*fields.values(), task_id))
            self.log(task_id, user["id"], "edit")
            s.bump()
        return {"task": s.one("SELECT * FROM tasks WHERE id = ?", (task_id,))}

    def delete_task(self, ctx, task_id):
        s, user = self.store, ctx["user"]
        t = self.task_for(user, task_id)
        if user["role"] == "child" and (t["created_by"] != user["id"] or t["status"] == "done"):
            raise ApiError(403, "내가 등록한, 아직 끝나지 않은 숙제만 지울 수 있어요.")
        with s.lock, s.db:
            s.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            s.bump()
        return {"ok": True}

    # 상태 전이표: action -> (허용 역할, 허용 시작 상태, 결과 상태)
    TRANSITIONS = {
        "accept":   ({"parent"}, {"inbox"}, "todo"),
        "start":    ({"parent", "child"}, {"todo"}, "doing"),
        "progress": ({"parent", "child"}, {"todo", "doing"}, None),
        "submit":   ({"parent", "child"}, {"todo", "doing"}, "submitted"),
        "cancel":   ({"child", "parent"}, {"submitted"}, "doing"),
        "approve":  ({"parent"}, {"todo", "doing", "submitted"}, "done"),
        "reject":   ({"parent"}, {"submitted"}, "doing"),
        "reopen":   ({"parent"}, {"done"}, "doing"),
    }

    def task_action(self, ctx, task_id):
        s, user, b = self.store, ctx["user"], ctx["body"]
        t = self.task_for(user, task_id)
        action = b.get("action")
        if action not in self.TRANSITIONS:
            raise ApiError(400, "알 수 없는 동작입니다.")
        roles, from_states, to_state = self.TRANSITIONS[action]
        if user["role"] not in roles:
            raise ApiError(403, "부모님만 할 수 있어요.")
        if t["status"] not in from_states:
            raise ApiError(409, "지금 상태에서는 할 수 없는 동작입니다.")
        note = self.text(b, "note", False, 500)
        progress = t["progress"]
        if "progress" in b:
            if not isinstance(b["progress"], int) or not 0 <= b["progress"] <= 100:
                raise ApiError(400, "진행률은 0~100 입니다.")
            progress = b["progress"]
        status = to_state or t["status"]
        sets = {"status": status, "updated_at": now_iso()}
        if action == "progress" and status == "todo" and progress > 0:
            sets["status"] = status = "doing"
        if action == "submit":
            progress, sets["submitted_at"] = 100, now_iso()
        elif action == "approve":
            progress, sets["completed_at"], sets["verified_by"] = 100, now_iso(), user["id"]
        elif action == "reject" and "progress" not in b:
            progress = min(progress, 50)  # 다시 해야 하므로 '거의 끝남'으로 보이지 않게 한다
        elif action == "reopen":
            sets["completed_at"], sets["verified_by"] = None, None
        sets["progress"] = progress
        with s.lock, s.db:
            s.db.execute("UPDATE tasks SET %s WHERE id = ?" % ", ".join(f"{k} = ?" for k in sets),
                         (*sets.values(), task_id))
            self.log(task_id, user["id"], action, note, progress)
            s.bump()
        return {"task": s.one("SELECT * FROM tasks WHERE id = ?", (task_id,))}

    def task_logs(self, ctx, task_id):
        self.task_for(ctx["user"], task_id)
        return {"logs": self.store.q(
            "SELECT l.*, u.name AS user_name, u.role AS user_role FROM task_logs l LEFT JOIN users u ON u.id ="
            " l.user_id WHERE l.task_id = ? ORDER BY l.id", (task_id,))}

    # -- 구성원
    def list_members(self, ctx):
        return {"members": [public_user(u) for u in self.store.q("SELECT * FROM users ORDER BY role DESC, id")]}

    def create_member(self, ctx):
        s, b = self.store, ctx["body"]
        role = b.get("role")
        if role not in ("parent", "child"):
            raise ApiError(400, "역할이 올바르지 않습니다.")
        name = self.text(b, "name", True, 20)
        if not valid_pin(b.get("pin")):
            raise ApiError(400, "PIN 은 숫자 4~8자리입니다.")
        year = self.entry_year(b.get("entry_year")) if role == "child" else None
        with s.lock, s.db:
            n = s.db.execute("SELECT COUNT(*) FROM users WHERE role = 'child'").fetchone()[0]
            color = CHILD_COLORS[n % len(CHILD_COLORS)] if role == "child" else "#555b6e"
            cur = s.db.execute("INSERT INTO users (role, name, pin_hash, entry_year, color, created_at)"
                               " VALUES (?,?,?,?,?,?)", (role, name, hash_pin(b["pin"]), year, color, now_iso()))
            s.bump()
        return {"member": public_user(s.one("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)))}

    def update_member(self, ctx, member_id):
        s, b, me = self.store, ctx["body"], ctx["user"]
        u = s.one("SELECT * FROM users WHERE id = ?", (member_id,))
        if not u:
            raise ApiError(404, "구성원을 찾을 수 없습니다.")
        sets = {}
        if "name" in b:
            sets["name"] = self.text(b, "name", True, 20)
        if "pin" in b:
            if not valid_pin(b["pin"]):
                raise ApiError(400, "PIN 은 숫자 4~8자리입니다.")
            sets["pin_hash"] = hash_pin(b["pin"])
        if "entry_year" in b and u["role"] == "child":
            sets["entry_year"] = self.entry_year(b["entry_year"])
        if "color" in b and isinstance(b["color"], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", b["color"]):
            sets["color"] = b["color"]
        if "active" in b:
            if member_id == me["id"] and not b["active"]:
                raise ApiError(400, "자기 자신은 비활성화할 수 없습니다.")
            sets["active"] = 1 if b["active"] else 0
        if not sets:
            return {"member": public_user(u)}
        with s.lock, s.db:
            s.db.execute("UPDATE users SET %s WHERE id = ?" % ", ".join(f"{k} = ?" for k in sets),
                         (*sets.values(), member_id))
            if "pin_hash" in sets or sets.get("active") == 0:
                s.db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
                             (member_id, me["token_hash"]))
            s.bump()
        return {"member": public_user(s.one("SELECT * FROM users WHERE id = ?", (member_id,)))}

    # -- 과목
    def list_subjects(self, ctx):
        return {"subjects": self.store.q("SELECT * FROM subjects ORDER BY sort, id")}

    def create_subject(self, ctx):
        s = self.store
        name = self.text(ctx["body"], "name", True, 30)
        with s.lock, s.db:
            n = s.db.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM subjects").fetchone()[0]
            s.db.execute("INSERT OR IGNORE INTO subjects (name, sort) VALUES (?, ?)", (name, n))
            s.bump()
        return self.list_subjects(ctx)

    def delete_subject(self, ctx, subject_id):
        with self.store.lock, self.store.db:
            self.store.db.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
            self.store.bump()
        return self.list_subjects(ctx)

    # -- 반복 학습(루틴)
    def list_routines(self, ctx):
        user = ctx["user"]
        if user["role"] == "child":
            rows = self.store.q("SELECT * FROM routines WHERE child_id = ? ORDER BY id", (user["id"],))
        else:
            rows = self.store.q("SELECT * FROM routines ORDER BY child_id, id")
        return {"routines": rows}

    def routine_fields(self, b, creating=False):
        out = {}
        if creating or "child_id" in b:
            if not isinstance(b.get("child_id"), int):
                raise ApiError(400, "자녀를 선택하세요.")
            self.child_or_404(b["child_id"])
            out["child_id"] = b["child_id"]
        if creating or "title" in b:
            out["title"] = self.text(b, "title", True, 200)
        if "subject" in b:
            out["subject"] = self.text(b, "subject", False, 30)
        if "kind" in b:
            if b["kind"] not in KINDS:
                raise ApiError(400, "종류가 올바르지 않습니다.")
            out["kind"] = b["kind"]
        if creating or "weekdays" in b:
            days = b.get("weekdays")
            if not isinstance(days, list) or not days or not all(isinstance(d, int) and 1 <= d <= 7 for d in days):
                raise ApiError(400, "요일을 하나 이상 고르세요.")
            out["weekdays"] = ",".join(str(d) for d in sorted(set(days)))
        if "active" in b:
            out["active"] = 1 if b["active"] else 0
        return out

    def create_routine(self, ctx):
        s = self.store
        f = self.routine_fields(ctx["body"], creating=True)
        f.setdefault("kind", "study")
        f.update(created_by=ctx["user"]["id"], created_at=now_iso())
        with s.lock, s.db:
            cur = s.db.execute("INSERT INTO routines (%s) VALUES (%s)" % (",".join(f), ",".join("?" * len(f))),
                               tuple(f.values()))
            s.bump()
        s.ensure_routine_tasks()
        return {"routine": s.one("SELECT * FROM routines WHERE id = ?", (cur.lastrowid,))}

    def update_routine(self, ctx, routine_id):
        s = self.store
        if not s.one("SELECT id FROM routines WHERE id = ?", (routine_id,)):
            raise ApiError(404, "반복 학습을 찾을 수 없습니다.")
        f = self.routine_fields(ctx["body"])
        if f:
            with s.lock, s.db:
                s.db.execute("UPDATE routines SET %s WHERE id = ?" % ", ".join(f"{k} = ?" for k in f),
                             (*f.values(), routine_id))
                s.bump()
        return {"routine": s.one("SELECT * FROM routines WHERE id = ?", (routine_id,))}

    def delete_routine(self, ctx, routine_id):
        s = self.store
        with s.lock, s.db:
            # 이미 만들어진 할 일 기록은 남기고 연결만 끊는다.
            s.db.execute("UPDATE tasks SET routine_id = NULL WHERE routine_id = ? AND status = 'done'", (routine_id,))
            s.db.execute("DELETE FROM tasks WHERE routine_id = ? AND status != 'done'", (routine_id,))
            s.db.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
            s.bump()
        return {"ok": True}

    # -- 통계
    def stats(self, ctx):
        s, user, qs = self.store, ctx["user"], ctx["query"]
        days = max(1, min(int(qs.get("days", 7) or 7), 365))
        since = (today() - dt.timedelta(days=days - 1)).isoformat()
        args = [since]
        cond = ""
        if user["role"] == "child":
            cond, args = " AND child_id = ?", [since, user["id"]]
        rows = s.q("SELECT child_id, substr(completed_at, 1, 10) AS day, COUNT(*) AS n FROM tasks WHERE status ="
                   " 'done' AND completed_at >= ?" + cond + " GROUP BY child_id, day", args)
        overdue = s.q("SELECT child_id, COUNT(*) AS n FROM tasks WHERE status NOT IN ('done', 'inbox') AND"
                      " due_date < ?" + cond + " GROUP BY child_id", [today().isoformat()] + args[1:])
        return {"since": since, "done_by_day": rows, "overdue": overdue}

    # -- 설정·백업
    def settings(self, ctx):
        s = self.store
        return {"family_name": s.meta("family_name"), "addresses": [f"http://{a}:{self.port}" for a in lan_addresses()],
                "import_key": s.meta("import_key"), "version": APP_VERSION, "db_path": os.path.abspath(s.path),
                "app": app_version_info(self.apk),
                "devices": s.q("SELECT s.device, s.last_seen, u.name FROM sessions s JOIN users u ON u.id ="
                               " s.user_id ORDER BY s.last_seen DESC LIMIT 50")}

    def rotate_import_key(self, ctx):
        with self.store.lock, self.store.db:
            self.store.set_meta("import_key", secrets.token_urlsafe(24))
        return {"import_key": self.store.meta("import_key")}

    def export(self, ctx):
        s = self.store
        users = [{k: v for k, v in u.items() if k != "pin_hash"} for u in s.q("SELECT * FROM users")]
        return {"exported_at": now_iso(), "version": APP_VERSION, "family_name": s.meta("family_name"),
                "users": users, "subjects": s.q("SELECT * FROM subjects"), "routines": s.q("SELECT * FROM routines"),
                "tasks": s.q("SELECT * FROM tasks"), "task_logs": s.q("SELECT * FROM task_logs")}

    # -- 외부 가져오기 (문자·학교 알림앱 연동용 입구)
    def import_message(self, ctx):
        """외부 수집기(문자 전달 앱, 알림 수집 스크립트 등)가 숙제 메시지를 밀어 넣는 입구.

        헤더 X-Import-Key 로 인증한다. 들어온 항목은 status='inbox' 로 쌓이고,
        부모가 확인(accept)해야 자녀의 할 일 목록에 올라간다.
        """
        s, b = self.store, ctx["body"]
        key = ctx["headers"].get("X-Import-Key", "")
        expected = s.meta("import_key")
        if not expected or not hmac.compare_digest(key, expected):
            raise ApiError(401, "가져오기 키가 올바르지 않습니다.")
        text = self.text(b, "text", True, 4000)
        child = None
        if isinstance(b.get("child_id"), int):
            child = self.child_or_404(b["child_id"])
        elif isinstance(b.get("child"), str):
            child = s.one("SELECT * FROM users WHERE role = 'child' AND name = ?", (b["child"].strip(),))
        if not child:
            kids = s.q("SELECT * FROM users WHERE role = 'child' AND active = 1")
            if len(kids) != 1:
                raise ApiError(400, "자녀(child 또는 child_id)를 지정하세요.")
            child = kids[0]
        title = self.text(b, "title", False, 200) or guess_title(text)
        due = b.get("due_date") if valid_date(b.get("due_date")) and b.get("due_date") else guess_due(text)
        source = (self.text(b, "source", False, 30) or "import").lower()
        with s.lock, s.db:
            cur = s.db.execute(
                "INSERT INTO tasks (child_id, title, subject, kind, memo, due_date, status, source, source_text,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?, 'inbox', ?,?,?,?)",
                (child["id"], title, self.text(b, "subject", False, 30) or guess_subject(text, s), "homework", None,
                 due, source, text, now_iso(), now_iso()))
            self.log(cur.lastrowid, None, "import", source)
            s.bump()
        return {"task": s.one("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,))}


# ---------------------------------------------------------------- 가져오기 추정 (단순 규칙)

def guess_title(text):
    for line in text.splitlines():
        line = re.sub(r"^\s*(\[[^\]]*\]|\([^)]*\)|[-*•·]+)\s*", "", line).strip()
        if line:
            return line[:80]
    return "가져온 숙제"


def guess_due(text, base=None):
    base = base or today()
    if "모레" in text:
        return (base + dt.timedelta(days=2)).isoformat()
    if "내일" in text:
        return (base + dt.timedelta(days=1)).isoformat()
    if "오늘" in text:
        return base.isoformat()
    m = re.search(r"(\d{1,2})\s*[/.월]\s*(\d{1,2})\s*일?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = dt.date(base.year, month, day)
        except ValueError:
            return None
        if d < base - dt.timedelta(days=60):  # 연말에 받은 1월 날짜 등
            d = d.replace(year=base.year + 1)
        return d.isoformat()
    weekdays = "월화수목금토일"
    m = re.search(r"([월화수목금토일])요일", text)
    if m:
        delta = (weekdays.index(m.group(1)) - base.weekday()) % 7 or 7
        return (base + dt.timedelta(days=delta)).isoformat()
    return None


def guess_subject(text, store):
    for row in store.q("SELECT name FROM subjects ORDER BY sort"):
        if row["name"] != "기타" and row["name"] in text:
            return row["name"]
    return None


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    app = None  # make_server 가 채운다
    static_dir = STATIC_DIR
    server_version = "HomeworkTracker/" + APP_VERSION

    def log_message(self, fmt, *args):
        if os.environ.get("HW_QUIET"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def handle_api(self, method):
        url = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        body = {}
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if length > MAX_BODY:
                raise ApiError(413, "요청이 너무 큽니다.")
            if length:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ApiError(400, "JSON 객체가 필요합니다.")
            result = self.app.dispatch(method, url.path, query, body, self.headers)
            self.send_json(200, result)
        except ApiError as e:
            self.send_json(e.status, {"error": e.message})
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "요청 형식이 올바르지 않습니다."})
        except Exception as e:  # 서버가 죽지 않도록
            sys.stderr.write(f"[error] {method} {url.path}: {e!r}\n")
            self.send_json(500, {"error": "서버 오류가 발생했습니다."})

    def serve_static(self):
        path = urlparse(self.path).path
        if path in ("/", ""):
            path = "/index.html"
        root = self.static_dir
        full = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if not full.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(full):
            full = os.path.join(root, "index.html")  # SPA 폴백
        with open(full, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def serve_app(self, path):
        """집 서버가 안드로이드 앱 업데이트를 나눠 준다. 앱은 version.json 을 보고 새 APK 를 받는다."""
        info = app_version_info(self.app.apk)
        if not info:
            return self.send_json(404, {"error": "서버에 앱 파일이 없습니다."})
        if path == "/app/version.json":
            return self.send_json(200, info)
        size = os.path.getsize(self.app.apk["path"])
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.android.package-archive")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{APK_NAME}"')
        self.end_headers()
        with open(self.app.apk["path"], "rb") as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api("GET")
        elif path in ("/app/version.json", "/app/" + APK_NAME):
            self.serve_app(path)
        else:
            self.serve_static()

    def do_POST(self):
        self.handle_api("POST")

    def do_PATCH(self):
        self.handle_api("PATCH")

    def do_DELETE(self):
        self.handle_api("DELETE")


def app_version_info(apk):
    if not apk or not apk.get("path") or not os.path.isfile(apk["path"]):
        return None
    return {"versionCode": int(apk["versionCode"]), "versionName": apk.get("versionName", ""),
            "url": "/app/" + APK_NAME, "size": os.path.getsize(apk["path"])}


def load_apk_dir(apk_dir):
    """PC 서버용: apk 폴더에 릴리스의 homework-tracker.apk 와 version.json 을 두면 앱 업데이트를 배포한다."""
    meta = os.path.join(apk_dir, "version.json")
    path = os.path.join(apk_dir, APK_NAME)
    if not (os.path.isfile(meta) and os.path.isfile(path)):
        return None
    with open(meta, encoding="utf-8") as f:
        info = json.load(f)
    return {"path": path, "versionCode": int(info["versionCode"]), "versionName": info.get("versionName", "")}


def make_server(db_path, host="0.0.0.0", port=8080, static_dir=None, apk=None):
    store = Store(db_path)
    attrs = {"app": App(store, port, apk)}
    if static_dir:
        attrs["static_dir"] = static_dir
    handler = type("BoundHandler", (Handler,), attrs)
    return ThreadingHTTPServer((host, port), handler), store


def start_discovery(store, http_port, udp_port=DISCOVERY_PORT):
    """같은 와이파이의 앱이 브로드캐스트로 'HWT_DISCOVER' 를 보내면 서버 정보를 돌려준다."""
    if not udp_port:
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", udp_port))
    except OSError as e:
        sys.stderr.write(f"[discovery] UDP {udp_port} 사용 불가: {e}\n")
        sock.close()
        return None

    def loop():
        while True:
            try:
                data, addr = sock.recvfrom(512)
            except OSError:
                return  # 소켓을 닫으면 끝난다
            if data.strip() != DISCOVERY_REQUEST:
                continue
            reply = {"app": "homework-tracker", "name": store.meta("family_name") or "", "port": http_port,
                     "version": APP_VERSION}
            try:
                sock.sendto(json.dumps(reply, ensure_ascii=False).encode(), addr)
            except OSError:
                pass

    threading.Thread(target=loop, name="discovery", daemon=True).start()
    return sock


# ---------------------------------------------------------------- 안드로이드 앱 내장 실행 (Chaquopy)

_embedded = {}


def run_embedded(data_dir, static_dir, port=8080, apk_path=None, version_code=0, version_name=""):
    """안드로이드 앱의 서버 모드가 호출한다. 서버가 멈출 때까지 돌아오지 않는다.

    앱 자신의 APK 를 그대로 배포하므로, 서버 기기의 앱만 업데이트하면 다른 기기도 따라 업데이트된다.
    """
    apk = {"path": apk_path, "versionCode": version_code, "versionName": version_name} if apk_path else None
    httpd, store = make_server(os.path.join(data_dir, "homework.db"), "0.0.0.0", int(port), static_dir, apk)
    disc = start_discovery(store, int(port))
    _embedded["httpd"] = httpd
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        if disc:
            disc.close()
        store.db.close()


def stop_embedded():
    httpd = _embedded.pop("httpd", None)
    if httpd:
        httpd.shutdown()


def main():
    ap = argparse.ArgumentParser(description="숙제·학습 체크 서버")
    ap.add_argument("--host", default="0.0.0.0", help="수신 주소 (기본 0.0.0.0 = 집 와이파이 전체)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--data", default=os.path.join(HERE, "data"), help="데이터 폴더 (homework.db 가 생긴다)")
    ap.add_argument("--apk-dir", default=os.path.join(HERE, "apk"),
                    help="앱 업데이트 폴더 (homework-tracker.apk + version.json)")
    ap.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT, help="앱 자동 찾기 UDP 포트 (0=끔)")
    args = ap.parse_args()
    apk = load_apk_dir(args.apk_dir)
    httpd, store = make_server(os.path.join(args.data, "homework.db"), args.host, args.port, apk=apk)
    start_discovery(store, args.port, args.discovery_port)
    print(f"숙제 체크 서버 v{APP_VERSION} 시작")
    print(f"  데이터: {os.path.abspath(store.path)}")
    print("  접속 주소 (자녀 태블릿·부모 휴대폰 브라우저에 입력):")
    for a in lan_addresses() or ["127.0.0.1"]:
        print(f"    http://{a}:{args.port}")
    if apk:
        print(f"  앱 업데이트 배포 중: v{apk['versionName']} ({apk['path']})")
    if not store.is_setup():
        print("  ※ 처음 실행입니다. 위 주소로 접속해 가족 그룹을 만드세요.")
    print("  종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
