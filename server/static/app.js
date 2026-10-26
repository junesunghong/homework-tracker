/* 숙제 체크 — 클라이언트 (프레임워크 없음, 서버가 그대로 내려준다) */
'use strict';

const STATUS = { inbox: '가져옴·확인 필요', todo: '할 일', doing: '하는 중', submitted: '완료 요청', done: '완료' };
const STATUS_CHIP = { inbox: 'warn', todo: 'gray', doing: '', submitted: 'ok', done: 'ok' };
const KIND = { homework: '숙제', study: '학습', prepare: '준비물', exam: '시험', etc: '기타' };
const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일'];
const ACTION_LABEL = {
  create: '등록', edit: '수정', import: '외부에서 가져옴', accept: '확인(목록에 추가)', start: '시작',
  progress: '진행 업데이트', submit: '완료 요청', cancel: '완료 요청 취소', approve: '완료 확인',
  reject: '다시 하기(반려)', reopen: '다시 열기',
};
const POLL_MS = 5000;
// 안드로이드 앱(WebView) 안에서 열렸으면 앱이 넣어 준 다리 객체가 있다.
const NATIVE = window.HomeworkApp || null;

const S = {
  token: localStorage.getItem('hw_token'),
  user: null, family: '', status: null,
  tasks: [], subjects: [], members: [], routines: [], today: '',
  rev: -1, tab: 'active', child: 'all', pickUser: null, pin: '',
  period: store('hw_period') || 'today', withMonday: store('hw_mon') === '1',
};

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* 사생활 보호 모드 등 — 기억만 못 할 뿐 동작엔 지장 없음 */ }
  return null;
}

// ------------------------------------------------------------ 공통
const $ = (sel) => document.querySelector(sel);
const h = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (S.token) headers.Authorization = 'Bearer ' + S.token;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new Error('서버에 연결할 수 없습니다. 집 와이파이에 연결되어 있는지 확인하세요.');
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && S.token && path !== '/api/login') {
    logoutLocal();
    throw new Error(data.error || '다시 로그인하세요.');
  }
  if (!res.ok) throw new Error(data.error || `오류 (${res.status})`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
}

async function run(fn) {
  try { await fn(); } catch (e) { toast(e.message); }
}

function isoDate(d) {
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function addDays(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return isoDate(d); }
function dayDiff(iso) {
  if (!iso) return null;
  return Math.round((new Date(iso + 'T00:00:00') - new Date(S.today + 'T00:00:00')) / 86400000);
}
function dueLabel(t) {
  if (!t.due_date) return '<span class="chip gray">마감 없음</span>';
  const d = dayDiff(t.due_date);
  const md = t.due_date.slice(5).replace('-', '/');
  const wd = WEEKDAYS[(new Date(t.due_date + 'T00:00:00').getDay() + 6) % 7];
  if (t.status === 'done') return `<span>${md}(${wd})</span>`;
  if (d < 0) return `<span class="chip danger">${-d}일 지남 · ${md}</span>`;
  if (d === 0) return `<span class="chip warn">오늘까지</span>`;
  if (d === 1) return `<span class="chip">내일까지</span>`;
  return `<span>${md}(${wd}) · D-${d}</span>`;
}
function initial(name) { return h((name || '?').slice(0, 1)); }
function avatar(u, cls = '') {
  return `<span class="avatar ${cls}" style="background:${h(u.color || '#888')}">${initial(u.name)}</span>`;
}
function kids() { return S.members.filter((m) => m.role === 'child' && m.active); }
function memberById(id) { return S.members.find((m) => m.id === id); }
function gradeLabel(u) { return u && u.grade ? u.grade.label : ''; }

// ------------------------------------------------------------ 시작·로그인
async function boot() {
  await run(async () => {
    S.status = await api('GET', '/api/status');
    S.family = S.status.family_name || '';
    S.members = S.status.members;
    if (!S.status.setup_done) return renderSetup();
    if (S.token) {
      try {
        const me = await api('GET', '/api/me');
        S.user = me.user;
        return enterApp();
      } catch (e) { /* 토큰 만료 → 로그인 화면 */ }
    }
    renderLogin();
  });
}

function logoutLocal() {
  S.token = null; S.user = null; S.rev = -1;
  localStorage.removeItem('hw_token');
  closeModal();
  boot();
}

function renderLogin() {
  const u = S.pickUser;
  if (!u) {
    const list = S.members.map((m) => `
      <button class="profile" data-act="pick" data-id="${m.id}">
        ${avatar(m, 'lg')}<b>${h(m.name)}</b>
        <span class="small muted">${m.role === 'parent' ? '부모' : h(gradeLabel(m))}</span>
      </button>`).join('');
    $('#app').innerHTML = `<div class="login">
      <h1>${h(S.family)} 숙제 체크</h1><p class="muted">누구인가요?</p>
      <div class="profiles">${list}</div>
      ${NATIVE ? '<button class="btn ghost small" data-act="app-settings">⚙ 앱 설정 (서버·접속 변경)</button>' : ''}</div>`;
    return;
  }
  const dots = Array.from({ length: Math.max(4, S.pin.length) }, (_, i) => `<i class="${i < S.pin.length ? 'on' : ''}"></i>`).join('');
  const keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'back', '0', 'ok']
    .map((k) => `<button data-act="pin" data-k="${k}">${k === 'back' ? '⌫' : k === 'ok' ? '✓' : k}</button>`).join('');
  $('#app').innerHTML = `<div class="login">
    ${avatar(u, 'lg')}<h2>${h(u.name)}</h2><p class="muted">PIN 을 입력하세요</p>
    <div class="pin-dots">${dots}</div><div class="pinpad">${keys}</div>
    <p><button class="btn ghost" data-act="pick-back">다른 사람 선택</button></p></div>`;
}

async function tryLogin() {
  const device = `${navigator.platform || ''} ${/Mobi|Android|iPhone|iPad/.test(navigator.userAgent) ? '모바일' : 'PC'}`.trim();
  try {
    const r = await api('POST', '/api/login', { user_id: S.pickUser.id, pin: S.pin, device });
    S.token = r.token; S.user = r.user;
    localStorage.setItem('hw_token', r.token);
    S.pickUser = null; S.pin = '';
    enterApp();
  } catch (e) {
    S.pin = ''; renderLogin(); toast(e.message);
  }
}

// ------------------------------------------------------------ 최초 설치(가족 그룹 만들기)
function renderSetup() {
  const year = new Date().getFullYear();
  $('#app').innerHTML = `<div class="wrap" style="max-width:640px">
    <h1>가족 그룹 만들기</h1>
    <p class="muted">이 기기가 <b>서버</b>입니다. 다른 기기(자녀 태블릿, 부모 휴대폰)는 같은 와이파이에서 이 서버 주소로 접속합니다.</p>
    <div class="card">
      <label>가족 이름</label><input id="s-family" placeholder="예: 우리집" maxlength="40">
      <label>부모 이름</label><input id="s-pname" placeholder="예: 아빠" maxlength="20">
      <label>부모 PIN (숫자 4~8자리)</label><input id="s-ppin" inputmode="numeric" type="password" maxlength="8">
    </div>
    <div class="section-title">자녀</div>
    <div id="s-kids"></div>
    <button class="btn" data-act="setup-add-kid">+ 자녀 추가</button>
    <p class="small muted">입학년도는 <b>초등학교 1학년 입학년도</b>입니다. 학년(초·중·고)은 매년 3월에 자동으로 바뀝니다.
      예: ${year}년 현재 초6 → ${year - 5}년 입학.</p>
    <div class="foot"><button class="btn primary" data-act="setup-save">만들기</button></div>
  </div>`;
  addSetupKid();
}
function addSetupKid() {
  const box = document.createElement('div');
  box.className = 'card s-kid';
  box.style.marginBottom = '10px';
  box.innerHTML = `<div class="row"><div class="grow"><label>자녀 이름</label><input class="k-name" maxlength="20"></div>
    <div style="width:120px"><label>초1 입학년도</label><input class="k-year" inputmode="numeric" maxlength="4" placeholder="${new Date().getFullYear() - 5}"></div></div>
    <label>자녀 PIN (숫자 4~8자리)</label><input class="k-pin" inputmode="numeric" type="password" maxlength="8">`;
  $('#s-kids').appendChild(box);
}
async function saveSetup() {
  const children = [...document.querySelectorAll('.s-kid')].map((el) => ({
    name: el.querySelector('.k-name').value, pin: el.querySelector('.k-pin').value,
    entry_year: el.querySelector('.k-year').value || null,
  })).filter((c) => c.name.trim());
  await run(async () => {
    await api('POST', '/api/setup', {
      family_name: $('#s-family').value,
      parent: { name: $('#s-pname').value, pin: $('#s-ppin').value },
      children,
    });
    toast('가족 그룹을 만들었습니다. 로그인하세요.');
    boot();
  });
}

// ------------------------------------------------------------ 데이터
async function loadAll() {
  const since = addDays(isoDate(new Date()), -30);
  const [tasks, subjects, members, routines] = await Promise.all([
    api('GET', '/api/tasks?done_since=' + since),
    api('GET', '/api/subjects'),
    api('GET', '/api/members'),
    api('GET', '/api/routines'),
  ]);
  S.tasks = tasks.tasks; S.today = tasks.today; S.rev = tasks.rev;
  S.subjects = subjects.subjects; S.members = members.members; S.routines = routines.routines;
}

let pollTimer;
function enterApp() {
  run(async () => {
    await loadAll();
    render();
    clearInterval(pollTimer);
    pollTimer = setInterval(poll, POLL_MS);
  });
}
async function poll() {
  if (!S.token || document.hidden) return;
  try {
    const r = await api('GET', '/api/rev');
    if (r.rev !== S.rev) { await loadAll(); render(); }
  } catch (e) { /* 잠시 끊김은 무시 */ }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

async function refresh() { await loadAll(); render(); }

function render() {
  if (!S.user) return renderLogin();
  if (S.user.role === 'parent') renderParent(); else renderChild();
}

// ------------------------------------------------------------ 할 일 카드
function taskCard(t, opts = {}) {
  const isParent = S.user.role === 'parent';
  const subj = t.subject ? `<span class="chip">${h(t.subject)}</span>` : '';
  const kind = t.kind !== 'homework' ? `<span class="chip gray">${KIND[t.kind] || ''}</span>` : '';
  const who = opts.showChild ? `<span class="chip" style="background:${h(t.child_color)};color:#fff">${h(t.child_name)}</span>` : '';
  const by = t.source === 'manual'
    ? (t.created_by_role === 'parent' ? '<span class="small">부모 등록</span>' : '')
    : `<span class="small">${t.source === 'routine' ? '반복' : '가져옴(' + h(t.source) + ')'}</span>`;
  const st = `<span class="chip ${STATUS_CHIP[t.status]}">${STATUS[t.status]}${t.status === 'doing' ? ' ' + t.progress + '%' : ''}</span>`;
  const btn = (act, label, cls = '') => `<button class="btn sm ${cls}" data-act="${act}" data-id="${t.id}">${label}</button>`;
  const acts = [];
  if (isParent) {
    if (t.status === 'inbox') acts.push(btn('accept', '목록에 추가', 'primary'), btn('edit', '고치기'), btn('del', '버리기', 'danger'));
    if (t.status === 'submitted') acts.push(btn('approve', '확인 완료 ✓', 'ok'), btn('reject', '다시 하기', 'danger'));
    if (t.status === 'todo' || t.status === 'doing') acts.push(btn('approve', '바로 완료', ''));
    if (t.status === 'done') acts.push(btn('reopen', '다시 열기', 'ghost'));
  } else {
    if (t.status === 'todo') acts.push(btn('start', '시작하기', 'primary'));
    if (t.status === 'doing') {
      [25, 50, 75].forEach((p) => { if (p > t.progress) acts.push(`<button class="btn sm" data-act="prog" data-id="${t.id}" data-p="${p}">${p}%</button>`); });
    }
    if (t.status === 'todo' || t.status === 'doing') acts.push(btn('submit', '다 했어요 ✓', 'ok'));
    if (t.status === 'submitted') acts.push('<span class="small muted">부모님 확인을 기다리는 중</span>', btn('cancel', '취소', 'ghost'));
  }
  return `<div class="card task ${t.status}" style="border-left-color:${h(t.child_color || 'var(--primary)')}">
    <div class="meta">${who}${subj}${kind}${st}${by}</div>
    <div class="title" data-act="detail" data-id="${t.id}">${h(t.title)}</div>
    <div class="meta">${dueLabel(t)}${t.memo ? '<span>· 메모 있음</span>' : ''}</div>
    ${t.last_decision === 'reject' && ['todo', 'doing'].includes(t.status)
      ? `<div class="reject-note">↩ 다시 하기${t.last_note ? ': ' + h(t.last_note) : ''}</div>` : ''}
    ${t.status === 'done' || t.status === 'inbox' ? '' : `<div class="bar"><i style="width:${t.progress}%"></i></div>`}
    <div class="actions">${acts.join('')}</div></div>`;
}

function section(title, list, opts = {}) {
  if (!list.length && !opts.showEmpty) return '';
  const body = list.length ? `<div class="grid">${list.map((t) => taskCard(t, opts)).join('')}</div>`
    : `<div class="empty">${opts.empty || '없음'}</div>`;
  return `<div class="section-title">${title}${list.length ? ` <span class="badge" style="background:var(--muted)">${list.length}</span>` : ''}</div>${body}`;
}

function groupActive(list) {
  const late = [], today = [], soon = [], later = [], none = [];
  for (const t of list) {
    const d = dayDiff(t.due_date);
    if (d === null) none.push(t);
    else if (d < 0) late.push(t);
    else if (d === 0) today.push(t);
    else if (d <= 3) soon.push(t);
    else later.push(t);
  }
  return { late, today, soon, later, none };
}

function activeSections(list, opts) {
  const g = groupActive(list);
  return section('⚠️ 마감 지남', g.late, opts) + section('오늘까지', g.today, opts)
    + section('3일 안에', g.soon, opts) + section('그 이후', g.later, opts) + section('마감 없음', g.none, opts);
}

function recentDone(list) {
  return list.filter((t) => t.status === 'done').sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));
}

// ------------------------------------------------------------ 기간 요약 (오늘 / 주말까지 / 이번 주)
function md(iso) {
  return `${Number(iso.slice(5, 7))}/${Number(iso.slice(8))}(${WEEKDAYS[(new Date(iso + 'T00:00:00').getDay() + 6) % 7]})`;
}
function periodRange() {
  const t = S.today || isoDate(new Date());
  const dow = (new Date(t + 'T00:00:00').getDay() + 6) % 7; // 월=0 … 일=6
  const sunday = addDays(t, 6 - dow);
  if (S.period === 'weekend') {
    const to = S.withMonday ? addDays(sunday, 1) : sunday;
    return { from: t, to, label: `주말까지 · ~${md(to)}` };
  }
  if (S.period === 'week') {
    const from = addDays(t, -dow);
    return { from, to: sunday, label: `이번 주 · ${md(from)}~${md(sunday)}` };
  }
  return { from: t, to: t, label: `오늘 · ${md(t)}` };
}

// 기간 안에 마감인 할 일 + 마감이 지났는데 아직 안 끝난 할 일.
// 완료 = 부모 확인까지 끝난 것. 자녀가 "다 했어요"만 누른 것은 '확인 대기'로 따로 센다.
function summarize(childId) {
  const { from, to } = periodRange();
  const list = S.tasks.filter((t) => t.child_id === childId && t.status !== 'inbox' && t.due_date
    && ((t.due_date >= from && t.due_date <= to) || (t.due_date < S.today && t.status !== 'done')));
  const done = list.filter((t) => t.status === 'done').length;
  const waiting = list.filter((t) => t.status === 'submitted').length;
  const left = list.filter((t) => t.status === 'todo' || t.status === 'doing');
  const overdue = left.filter((t) => t.due_date < S.today).length;
  return { total: list.length, done, waiting, left, overdue };
}

function periodTabs() {
  const tabs = [['today', '오늘'], ['weekend', '주말까지'], ['week', '이번 주']]
    .map(([k, l]) => `<button class="tab ${S.period === k ? 'on' : ''}" data-act="period" data-p="${k}">${l}</button>`).join('');
  const mon = S.period === 'weekend'
    ? `<label class="mon"><input type="checkbox" data-act="with-monday" ${S.withMonday ? 'checked' : ''}> 월요일 마감 포함</label>` : '';
  return `<div class="tabs period">${tabs}${mon}</div>`;
}

function summaryCard(child, opts = {}) {
  const s = summarize(child.id);
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  const waitPct = s.total ? Math.round((s.waiting / s.total) * 100) : 0;
  const word = { today: '오늘', weekend: '주말까지', week: '이번 주' }[S.period];
  let headline;
  if (!s.total) headline = `<span class="muted">${word} 마감인 할 일이 없어요</span>`;
  else if (!s.left.length && !s.waiting) headline = `<b class="all-done">🎉 ${word} 할 일 모두 완료</b>`;
  else if (!s.left.length) headline = `<b>다 했어요 · 부모 확인 ${s.waiting}개 남음</b>`;
  else headline = `<b>${s.left.length}개 남음</b>`;
  const names = s.left.slice(0, 3).map((t) => h(t.title)).join(', ') + (s.left.length > 3 ? ` 외 ${s.left.length - 3}개` : '');
  return `<div class="card sum ${opts.selected ? 'selected' : ''}" ${opts.click ? `data-act="child" data-id="${child.id}"` : ''}>
    <div class="row">${avatar(child)}<div class="grow"><b>${h(child.name)}</b> <span class="small muted">${h(gradeLabel(child))}</span>
      <div>${headline}</div></div><div class="big">${s.done}<span class="small muted">/${s.total}</span></div></div>
    <div class="bar stack"><i class="ok" style="width:${pct}%"></i><i class="wait" style="width:${waitPct}%"></i></div>
    <div class="nums">완료 <b>${s.done}</b> · 확인 대기 <b>${s.waiting}</b> · 남음 <b>${s.left.length}</b>${s.overdue ? ` · <b class="late">마감 지남 ${s.overdue}</b>` : ''}</div>
    ${s.left.length ? `<div class="small left">남은 일: ${names}</div>` : ''}</div>`;
}

function summaryBlock(children, opts = {}) {
  return `<div class="sum-head"><span class="section-title" style="margin:0">${periodRange().label}</span></div>
    ${periodTabs()}<div class="summary">${children.map((c) => summaryCard(c, { click: opts.click, selected: opts.selected === c.id })).join('')}</div>`;
}

// ------------------------------------------------------------ 자녀 화면
function renderChild() {
  const me = S.user;
  const active = S.tasks.filter((t) => ['todo', 'doing'].includes(t.status));
  const waiting = S.tasks.filter((t) => t.status === 'submitted');
  const done = recentDone(S.tasks);
  const tabs = [['active', '해야 할 일', active.length], ['waiting', '확인 기다림', waiting.length], ['done', '끝낸 일', 0]];
  let body = '';
  if (S.tab === 'waiting') body = section('부모님 확인을 기다리는 중', waiting, { showEmpty: true, empty: '없어요' });
  else if (S.tab === 'done') body = section('최근 30일 동안 끝낸 일', done, { showEmpty: true, empty: '아직 없어요' });
  else body = active.length ? activeSections(active, {}) : '<div class="empty" style="margin-top:16px">🎉 할 일을 모두 끝냈어요!</div>';
  $('#app').innerHTML = `<div class="wrap">
    <div class="top"><div class="grow"><h1>${h(S.family)}</h1></div>
      <button class="btn ghost" data-act="logout">나가기</button></div>
    ${summaryBlock([me])}
    <div class="tabs" style="margin-top:14px">${tabs.map(([k, l, n]) => `<button class="tab ${S.tab === k ? 'on' : ''}" data-act="tab" data-tab="${k}">${l}${n ? `<span class="badge">${n}</span>` : ''}</button>`).join('')}</div>
    ${body}
  </div><button class="btn primary fab" data-act="new">+ 숙제 추가</button>`;
}

// ------------------------------------------------------------ 부모 화면
function renderParent() {
  const sel = S.child === 'all' ? null : Number(S.child);
  const mine = S.tasks.filter((t) => !sel || t.child_id === sel);
  const multi = kids().length > 1 && !sel;
  const opts = { showChild: multi };
  const inbox = mine.filter((t) => t.status === 'inbox');
  const submitted = mine.filter((t) => t.status === 'submitted');
  const active = mine.filter((t) => ['todo', 'doing'].includes(t.status));
  const done = recentDone(mine);
  const needs = inbox.length + submitted.length;

  const tabs = [['active', '확인·진행', needs], ['done', '완료 기록', 0]];
  let body;
  if (S.tab === 'done') body = section('최근 30일 완료', done, { ...opts, showEmpty: true, empty: '완료 기록이 없습니다' });
  else {
    body = section('📥 가져온 숙제 — 확인 필요', inbox, opts)
      + section('✅ 완료 요청 — 확인해 주세요', submitted, opts)
      + (active.length ? activeSections(active, opts) : '<div class="empty" style="margin-top:16px">진행 중인 할 일이 없습니다</div>');
  }
  $('#app').innerHTML = `<div class="wrap">
    <div class="top"><div class="grow"><h1>${h(S.family)}</h1><div class="small muted">${h(S.user.name)} (부모)</div></div>
      <button class="btn" data-act="settings">⚙ 설정</button><button class="btn ghost" data-act="logout">나가기</button></div>
    <div class="tabs"><button class="tab ${!sel ? 'on' : ''}" data-act="child" data-id="all">전체</button>
      ${kids().map((k) => `<button class="tab ${sel === k.id ? 'on' : ''}" data-act="child" data-id="${k.id}">${h(k.name)}</button>`).join('')}</div>
    ${summaryBlock(sel ? kids().filter((k) => k.id === sel) : kids(), { click: true, selected: sel })}
    <div class="tabs" style="margin-top:14px">${tabs.map(([k, l, n]) => `<button class="tab ${S.tab === k ? 'on' : ''}" data-act="tab" data-tab="${k}">${l}${n ? `<span class="badge">${n}</span>` : ''}</button>`).join('')}</div>
    ${body}
  </div><button class="btn primary fab" data-act="new">+ 할 일 추가</button>`;
}

// ------------------------------------------------------------ 모달
function openModal(html) {
  $('#modal-root').innerHTML = `<div class="modal-bg" data-act="modal-bg"><div class="modal" role="dialog">${html}</div></div>`;
}
function closeModal() { $('#modal-root').innerHTML = ''; }

function subjectOptions(cur) {
  const names = S.subjects.map((s) => s.name);
  if (cur && !names.includes(cur)) names.push(cur);
  return `<option value="">(선택 안 함)</option>` + names.map((n) => `<option ${n === cur ? 'selected' : ''}>${h(n)}</option>`).join('');
}

function taskForm(t) {
  const isParent = S.user.role === 'parent';
  const editing = !!t;
  t = t || { kind: 'homework', due_date: addDays(S.today || isoDate(new Date()), 1) };
  const defChild = t.child_id || (S.child !== 'all' ? Number(S.child) : kids()[0]?.id);
  const childSel = isParent ? `<label>누구의 할 일?</label><select id="f-child">${kids().map((k) => `<option value="${k.id}" ${k.id === defChild ? 'selected' : ''}>${h(k.name)}</option>`).join('')}</select>` : '';
  const base = S.today || isoDate(new Date());
  const quick = [['오늘', 0], ['내일', 1], ['모레', 2], ['일주일 뒤', 7]]
    .map(([l, n]) => `<button class="btn sm" data-act="quick-due" data-d="${addDays(base, n)}">${l}</button>`).join('');
  openModal(`<h2>${editing ? '할 일 고치기' : (isParent ? '할 일 추가' : '숙제 추가')}</h2>
    ${childSel}
    <label>무엇을 해야 하나요?</label><input id="f-title" maxlength="200" value="${h(t.title)}" placeholder="예: 수학익힘책 34~35쪽">
    <div class="row"><div class="grow"><label>과목</label><select id="f-subject">${subjectOptions(t.subject)}</select></div>
      <div class="grow"><label>종류</label><select id="f-kind">${Object.entries(KIND).map(([k, l]) => `<option value="${k}" ${k === t.kind ? 'selected' : ''}>${l}</option>`).join('')}</select></div></div>
    <label>마감일</label><input id="f-due" type="date" value="${h(t.due_date || '')}">
    <div class="quick">${quick}<button class="btn sm ghost" data-act="quick-due" data-d="">마감 없음</button></div>
    <label>메모</label><textarea id="f-memo" maxlength="2000">${h(t.memo)}</textarea>
    ${t.source_text ? `<label>가져온 원문</label><pre>${h(t.source_text)}</pre>` : ''}
    <div class="foot"><button class="btn ghost" data-act="close">취소</button>
      <button class="btn primary" data-act="save-task" data-id="${editing ? t.id : ''}">저장</button></div>`);
  setTimeout(() => $('#f-title')?.focus(), 50);
}

async function saveTask(id) {
  const body = {
    title: $('#f-title').value, subject: $('#f-subject').value || null, kind: $('#f-kind').value,
    due_date: $('#f-due').value || null, memo: $('#f-memo').value || null,
  };
  if ($('#f-child')) body.child_id = Number($('#f-child').value);
  await run(async () => {
    if (id) await api('PATCH', '/api/tasks/' + id, body);
    else await api('POST', '/api/tasks', body);
    closeModal(); toast('저장했습니다'); await refresh();
  });
}

async function showDetail(id) {
  const t = S.tasks.find((x) => x.id === id);
  if (!t) return;
  await run(async () => {
    const { logs } = await api('GET', `/api/tasks/${id}/logs`);
    const isParent = S.user.role === 'parent';
    const canEdit = isParent || (t.created_by === S.user.id && !['submitted', 'done'].includes(t.status));
    const canDel = isParent || (t.created_by === S.user.id && t.status !== 'done');
    const slider = ['todo', 'doing'].includes(t.status)
      ? `<label>진행률 <b id="d-pv">${t.progress}%</b></label><input id="d-prog" type="range" min="0" max="100" step="5" value="${t.progress}">
         <label>한마디 (선택)</label><input id="d-note" maxlength="500" placeholder="예: 3번 문제가 어려워요">
         <div class="foot" style="justify-content:flex-start"><button class="btn primary" data-act="save-prog" data-id="${t.id}">진행 저장</button></div>` : '';
    const logHtml = logs.map((l) => `<div class="log"><b>${h(l.user_name || '외부')}</b> · ${ACTION_LABEL[l.action] || h(l.action)}
      ${l.progress != null && ['progress', 'start'].includes(l.action) ? ` (${l.progress}%)` : ''}
      <span class="small muted">${h(l.at.replace('T', ' ').slice(5, 16))}</span>${l.note ? `<div>“${h(l.note)}”</div>` : ''}</div>`).join('');
    openModal(`<div class="meta small muted">${h(t.child_name)} · ${t.subject ? h(t.subject) + ' · ' : ''}${KIND[t.kind]} · ${STATUS[t.status]}</div>
      <h2>${h(t.title)}</h2><div class="meta">${dueLabel(t)}</div>
      ${t.memo ? `<p style="white-space:pre-wrap">${h(t.memo)}</p>` : ''}
      ${t.source_text ? `<label>가져온 원문 (${h(t.source)})</label><pre>${h(t.source_text)}</pre>` : ''}
      ${slider}
      <div class="section-title">기록</div>${logHtml || '<p class="muted">기록 없음</p>'}
      <div class="foot">${canDel ? `<button class="btn danger" data-act="del" data-id="${t.id}">삭제</button>` : ''}
        ${canEdit ? `<button class="btn" data-act="edit" data-id="${t.id}">고치기</button>` : ''}
        <button class="btn primary" data-act="close">닫기</button></div>`);
    const r = $('#d-prog');
    if (r) r.oninput = () => { $('#d-pv').textContent = r.value + '%'; };
  });
}

async function act(id, action, extra = {}) {
  await run(async () => {
    await api('POST', `/api/tasks/${id}/action`, { action, ...extra });
    const msg = { submit: '완료 요청을 보냈어요! 👍', approve: '완료 처리했습니다', reject: '다시 하기로 돌려보냈습니다', accept: '목록에 추가했습니다' }[action];
    if (msg) toast(msg);
    await refresh();
  });
}

function rejectForm(id) {
  openModal(`<h2>다시 하기</h2><p class="muted">무엇을 더 해야 하는지 적어 주세요.</p>
    <input id="r-note" maxlength="500" placeholder="예: 2번 풀이 과정을 써 주세요">
    <div class="foot"><button class="btn ghost" data-act="close">취소</button>
    <button class="btn danger" data-act="reject-go" data-id="${id}">돌려보내기</button></div>`);
}

// ------------------------------------------------------------ 설정 (부모)
async function openSettings() {
  await run(async () => {
    const st = await api('GET', '/api/settings');
    const members = S.members.map((m) => `<div class="list-row">${avatar(m)}<div class="grow"><b>${h(m.name)}</b>
      <span class="small muted">${m.role === 'parent' ? '부모' : h(gradeLabel(m)) + (m.entry_year ? ` · ${m.entry_year}년 입학` : '')}${m.active ? '' : ' · 비활성'}</span></div>
      <button class="btn sm" data-act="member-edit" data-id="${m.id}">수정</button></div>`).join('');
    const routines = S.routines.map((r) => `<div class="list-row"><div class="grow"><b>${h(r.title)}</b>
      <div class="small muted">${h(memberById(r.child_id)?.name)} · ${r.subject ? h(r.subject) + ' · ' : ''}${r.weekdays.split(',').map((d) => WEEKDAYS[d - 1]).join('')}${r.active ? '' : ' · 중지됨'}</div></div>
      <button class="btn sm" data-act="routine-toggle" data-id="${r.id}" data-on="${r.active ? 0 : 1}">${r.active ? '중지' : '재개'}</button>
      <button class="btn sm danger" data-act="routine-del" data-id="${r.id}">삭제</button></div>`).join('');
    const subjects = S.subjects.map((s) => `<span class="chip" style="margin:2px;padding:4px 8px">${h(s.name)}
      <button class="btn ghost sm" style="min-height:0;padding:0 2px" data-act="subject-del" data-id="${s.id}">×</button></span>`).join('');
    const base = st.addresses[0] || location.origin;
    openModal(`<h2>설정</h2>
      <div class="section-title">구성원</div><div class="card">${members}
        <div class="row" style="margin-top:8px"><button class="btn sm" data-act="member-new" data-role="child">+ 자녀</button>
        <button class="btn sm" data-act="member-new" data-role="parent">+ 부모</button></div></div>
      <div class="section-title">반복 학습 (매일·요일별 자동 등록)</div><div class="card">${routines || '<p class="muted small">없음 — 예: 매일 영단어 30개, 월수금 수학 문제집 2쪽</p>'}
        <button class="btn sm" data-act="routine-new">+ 반복 학습 추가</button></div>
      <div class="section-title">과목</div><div class="card">${subjects}
        <div class="row" style="margin-top:8px"><input id="sub-new" class="grow" style="width:auto" maxlength="30" placeholder="새 과목 (예: 기술가정)">
        <button class="btn sm" data-act="subject-add">추가</button></div></div>
      <div class="section-title">서버 · 접속</div><div class="card small">
        <div>다른 기기에서 접속할 주소:</div>${st.addresses.map((a) => `<div class="mono"><b>${h(a)}</b></div>`).join('') || '<div class="muted">주소를 찾지 못했습니다</div>'}
        <div class="muted" style="margin-top:6px">버전 ${h(st.version)} · 데이터 파일 <span class="mono">${h(st.db_path)}</span></div>
        <div style="margin-top:8px"><b>로그인된 기기</b></div>
        ${st.devices.map((d) => `<div>${h(d.name)} · ${h(d.device || '알 수 없음')} · <span class="muted">${h(d.last_seen.replace('T', ' ').slice(0, 16))}</span></div>`).join('')}</div>
      <div class="section-title">외부 가져오기 (문자·학교 알림앱 연동 준비)</div><div class="card small">
        <div>가져오기 키: <span class="mono">${h(st.import_key)}</span></div>
        <p class="muted">외부 수집기가 아래처럼 보내면 “가져온 숙제 — 확인 필요”에 쌓이고, 부모가 확인해야 자녀 목록에 올라갑니다.</p>
        <pre>curl -X POST ${h(base)}/api/import \\
  -H "X-Import-Key: ${h(st.import_key)}" \\
  -H "Content-Type: application/json" \\
  -d '{"child":"${h(kids()[0]?.name || '자녀이름')}","source":"sms","text":"[OO초] 내일까지 수학익힘책 34쪽"}'</pre>
        <button class="btn sm danger" data-act="rotate-key">키 새로 만들기</button></div>
      <div class="section-title">안드로이드 앱</div><div class="card small">${appSection(st)}</div>
      <div class="section-title">백업</div><div class="card small">
        <p class="muted">데이터 파일(homework.db)을 복사해 두거나 아래 JSON 을 내려받아 보관하세요.</p>
        <button class="btn sm" data-act="export">JSON 내려받기</button></div>
      <div class="foot"><button class="btn primary" data-act="close">닫기</button></div>`);
  });
}

function appSection(st) {
  if (NATIVE) {
    return `<div>이 기기 앱 버전: <b>${h(NATIVE.appVersion())}</b>${st.app ? ` · 서버 배포 버전: <b>${h(st.app.versionName)}</b>` : ''}</div>
      <div class="row" style="margin-top:8px"><button class="btn sm" data-act="app-update">업데이트 확인</button>
      <button class="btn sm" data-act="app-settings">앱 설정 (서버·접속 변경)</button></div>`;
  }
  if (!st.app) return '<p class="muted">서버에 앱 파일이 없습니다. 안드로이드 기기를 서버로 쓰거나, PC 서버의 apk 폴더에 릴리스 APK 를 넣으세요.</p>';
  const base = st.addresses[0] || location.origin;
  return `<div>안드로이드 태블릿·휴대폰 브라우저에서 아래 주소를 열어 설치하세요. (v${h(st.app.versionName)})</div>
    <div class="mono" style="margin:6px 0"><b>${h(base)}${h(st.app.url)}</b></div>
    <a class="btn sm" href="${h(st.app.url)}" download>APK 내려받기</a>`;
}

function memberForm(m, role) {
  const editing = !!m;
  role = m ? m.role : role;
  openModal(`<h2>${editing ? '구성원 수정' : (role === 'child' ? '자녀 추가' : '부모 추가')}</h2>
    <label>이름</label><input id="m-name" maxlength="20" value="${h(m?.name)}">
    ${role === 'child' ? `<label>초등학교 1학년 입학년도</label><input id="m-year" inputmode="numeric" maxlength="4" value="${h(m?.entry_year || '')}">` : ''}
    <label>${editing ? '새 PIN (바꿀 때만 입력)' : 'PIN (숫자 4~8자리)'}</label><input id="m-pin" type="password" inputmode="numeric" maxlength="8">
    ${editing && m.id !== S.user.id ? `<label><input type="checkbox" id="m-active" style="width:auto" ${m.active ? 'checked' : ''}> 사용 중</label>` : ''}
    <div class="foot"><button class="btn ghost" data-act="settings">뒤로</button>
    <button class="btn primary" data-act="member-save" data-id="${editing ? m.id : ''}" data-role="${role}">저장</button></div>`);
}

async function saveMember(id, role) {
  const body = { name: $('#m-name').value };
  if ($('#m-year')) body.entry_year = $('#m-year').value || null;
  if ($('#m-pin').value || !id) body.pin = $('#m-pin').value;
  if ($('#m-active')) body.active = $('#m-active').checked;
  await run(async () => {
    if (id) await api('PATCH', '/api/members/' + id, body);
    else await api('POST', '/api/members', { ...body, role });
    await loadAll(); render(); openSettings(); toast('저장했습니다');
  });
}

function routineForm() {
  const base = S.child !== 'all' ? Number(S.child) : kids()[0]?.id;
  openModal(`<h2>반복 학습 추가</h2>
    <label>누구?</label><select id="rt-child">${kids().map((k) => `<option value="${k.id}" ${k.id === base ? 'selected' : ''}>${h(k.name)}</option>`).join('')}</select>
    <label>내용</label><input id="rt-title" maxlength="200" placeholder="예: 영단어 30개 외우기">
    <div class="row"><div class="grow"><label>과목</label><select id="rt-subject">${subjectOptions()}</select></div>
    <div class="grow"><label>종류</label><select id="rt-kind">${Object.entries(KIND).map(([k, l]) => `<option value="${k}" ${k === 'study' ? 'selected' : ''}>${l}</option>`).join('')}</select></div></div>
    <label>요일</label><div class="weekdays">${WEEKDAYS.map((w, i) => `<label><input type="checkbox" class="rt-day" value="${i + 1}" ${i < 5 ? 'checked' : ''}>${w}</label>`).join('')}</div>
    <p class="small muted">선택한 요일마다 그날 마감인 할 일이 자동으로 생깁니다.</p>
    <div class="foot"><button class="btn ghost" data-act="settings">뒤로</button><button class="btn primary" data-act="routine-save">저장</button></div>`);
}

async function saveRoutine() {
  const body = {
    child_id: Number($('#rt-child').value), title: $('#rt-title').value,
    subject: $('#rt-subject').value || null, kind: $('#rt-kind').value,
    weekdays: [...document.querySelectorAll('.rt-day:checked')].map((x) => Number(x.value)),
  };
  await run(async () => { await api('POST', '/api/routines', body); await loadAll(); render(); openSettings(); toast('추가했습니다'); });
}

async function exportJson() {
  await run(async () => {
    const data = await api('GET', '/api/export');
    const name = `homework-backup-${isoDate(new Date())}.json`;
    if (NATIVE) { NATIVE.saveFile(name, JSON.stringify(data, null, 2)); return; }  // WebView 는 blob 다운로드를 못 한다
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
}

// ------------------------------------------------------------ 이벤트 (위임)
const handlers = {
  pick: (el) => { S.pickUser = S.members.find((m) => m.id === Number(el.dataset.id)); S.pin = ''; renderLogin(); },
  'pick-back': () => { S.pickUser = null; S.pin = ''; renderLogin(); },
  pin: (el) => {
    const k = el.dataset.k;
    if (k === 'back') S.pin = S.pin.slice(0, -1);
    else if (k === 'ok') { if (S.pin.length >= 4) return tryLogin(); }
    else if (S.pin.length < 8) S.pin += k;
    renderLogin();
  },
  'setup-add-kid': addSetupKid,
  'setup-save': saveSetup,
  logout: () => run(async () => { await api('POST', '/api/logout').catch(() => {}); clearInterval(pollTimer); logoutLocal(); }),
  tab: (el) => { S.tab = el.dataset.tab; render(); },
  child: (el) => { S.child = el.dataset.id; render(); },
  period: (el) => { S.period = el.dataset.p; store('hw_period', S.period); render(); },
  'with-monday': (el) => { S.withMonday = el.checked; store('hw_mon', S.withMonday ? '1' : '0'); render(); },
  new: () => taskForm(null),
  edit: (el) => taskForm(S.tasks.find((t) => t.id === Number(el.dataset.id))),
  detail: (el) => showDetail(Number(el.dataset.id)),
  'save-task': (el) => saveTask(el.dataset.id ? Number(el.dataset.id) : null),
  'quick-due': (el) => { $('#f-due').value = el.dataset.d; },
  del: (el) => {
    if (!confirm('정말 삭제할까요?')) return;
    run(async () => { await api('DELETE', '/api/tasks/' + el.dataset.id); closeModal(); await refresh(); toast('삭제했습니다'); });
  },
  start: (el) => act(Number(el.dataset.id), 'start'),
  prog: (el) => act(Number(el.dataset.id), 'progress', { progress: Number(el.dataset.p) }),
  'save-prog': (el) => {
    const p = Number($('#d-prog').value), note = $('#d-note').value || null;
    closeModal();
    act(Number(el.dataset.id), 'progress', { progress: p, note });
  },
  submit: (el) => act(Number(el.dataset.id), 'submit'),
  cancel: (el) => act(Number(el.dataset.id), 'cancel'),
  accept: (el) => act(Number(el.dataset.id), 'accept'),
  approve: (el) => act(Number(el.dataset.id), 'approve'),
  reject: (el) => rejectForm(Number(el.dataset.id)),
  'reject-go': (el) => { const note = $('#r-note').value || null; closeModal(); act(Number(el.dataset.id), 'reject', { note }); },
  reopen: (el) => act(Number(el.dataset.id), 'reopen'),
  close: closeModal,
  'modal-bg': (el, ev) => { if (ev.target === el) closeModal(); },
  settings: openSettings,
  'member-new': (el) => memberForm(null, el.dataset.role),
  'member-edit': (el) => memberForm(memberById(Number(el.dataset.id))),
  'member-save': (el) => saveMember(el.dataset.id ? Number(el.dataset.id) : null, el.dataset.role),
  'routine-new': routineForm,
  'routine-save': saveRoutine,
  'routine-toggle': (el) => run(async () => { await api('PATCH', '/api/routines/' + el.dataset.id, { active: el.dataset.on === '1' }); await loadAll(); render(); openSettings(); }),
  'routine-del': (el) => {
    if (!confirm('반복 학습을 삭제할까요? (끝내지 않은 반복 할 일도 함께 지워집니다)')) return;
    run(async () => { await api('DELETE', '/api/routines/' + el.dataset.id); await loadAll(); render(); openSettings(); });
  },
  'subject-add': () => run(async () => { await api('POST', '/api/subjects', { name: $('#sub-new').value }); await loadAll(); openSettings(); }),
  'subject-del': (el) => run(async () => { await api('DELETE', '/api/subjects/' + el.dataset.id); await loadAll(); openSettings(); }),
  'rotate-key': () => { if (confirm('키를 바꾸면 기존 연동이 끊깁니다. 계속할까요?')) run(async () => { await api('POST', '/api/settings/import-key'); openSettings(); }); },
  export: exportJson,
  'app-settings': () => NATIVE && NATIVE.openAppSettings(),
  'app-update': () => NATIVE && NATIVE.checkUpdate(),
};

// 안드로이드 뒤로 가기: 열린 창이 있으면 닫고 true, 없으면 false(앱이 종료 처리)
window.hwBack = () => {
  if ($('#modal-root').innerHTML) { closeModal(); return true; }
  if (S.pickUser && !S.user) { S.pickUser = null; S.pin = ''; renderLogin(); return true; }
  return false;
};

document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  const fn = handlers[el.dataset.act];
  if (fn) fn(el, ev);
});
document.addEventListener('keydown', (ev) => {
  if (S.pickUser && !S.user && !$('#modal-root').innerHTML) {
    if (/^\d$/.test(ev.key) && S.pin.length < 8) { S.pin += ev.key; renderLogin(); }
    else if (ev.key === 'Backspace') { S.pin = S.pin.slice(0, -1); renderLogin(); }
    else if (ev.key === 'Enter' && S.pin.length >= 4) tryLogin();
  } else if (ev.key === 'Escape') closeModal();
});

boot();
