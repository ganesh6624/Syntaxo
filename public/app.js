/* Syntaxo SPA — vanilla JS, no build step. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const view = $('#view');
let ME = null;
let teardown = null;

// ───────────────────────── storage / api ─────────────────────────
// Storage that never throws (some embedded/sandboxed previews block localStorage)
const mem = {};
const safe = (kind) => ({
  get: (k) => { try { return window[kind].getItem(k); } catch { return mem[kind + k] ?? null; } },
  set: (k, v) => { try { window[kind].setItem(k, v); } catch { mem[kind + k] = v; } },
  del: (k) => { try { window[kind].removeItem(k); } catch { delete mem[kind + k]; } },
});
const LS = safe('localStorage'), SS = safe('sessionStorage');
// Theme: 'light' (Light Gold, default) or 'dark' (Dark Gold)
const theme = { get: () => LS.get('cq_theme') || 'light', set: (t) => { LS.set('cq_theme', t); document.documentElement.dataset.theme = t; } };
document.documentElement.dataset.theme = theme.get();
const themeBtn = () => `<button type="button" class="theme-btn" id="themeBtn" title="${theme.get() === 'light' ? 'Switch to Dark Gold theme' : 'Switch to Light Gold theme'}"><span class="tb-label">${theme.get() === 'light' ? 'Dark' : 'Light'}<span class="tb-word"> mode</span></span></button>`;
function bindThemeBtn() { const b = $('#themeBtn'); if (b) b.onclick = (e) => { e.stopPropagation(); theme.set(theme.get() === 'light' ? 'dark' : 'light'); renderNav(); }; }
let memToken = null; // in-memory copy: the session keeps working even if browser storage is blocked
const store = {
  get token() { return memToken || LS.get('cq_token'); },
  set token(v) { memToken = v || null; v ? LS.set('cq_token', v) : LS.del('cq_token'); },
};
async function api(path, { method = 'GET', body, timeout = 15000 } = {}) {
  const ctrl = new AbortController(); const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    const t = store.token;
    // Send the token two ways: some preview proxies strip the Authorization header, X-Auth-Token gets through.
    res = await fetch(path, { method, signal: ctrl.signal, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: 'Bearer ' + t, 'X-Auth-Token': t } : {}) }, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    throw Object.assign(new Error(e.name === 'AbortError' ? 'The server took too long to respond. Please try again.' : 'Cannot reach the server. Check your connection and that the app server is running.'), { status: 0 });
  } finally { clearTimeout(timer); }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && store.token && !path.startsWith('/api/auth/')) { logout(data.error || 'Your session expired. Please log in again.'); throw new Error(data.error || 'Session expired'); }
  if (res.status === 402 && data.code === 'SUBSCRIPTION_REQUIRED') {
    if (ME) { ME.access = data.access; renderNav(); }
    if (location.hash !== '#/plans') { toast(data.error, 'bad'); location.hash = '#/plans'; }
  }
  if (!res.ok) throw Object.assign(new Error(data.error || `Request failed (HTTP ${res.status}). Please try again.`), { status: res.status, field: data.field, code: data.code });
  return data;
}
async function loadMe() { try { ME = (await api('/api/me')).user; } catch { ME = null; } }
function logout(reason) {
  store.token = null; ME = null;
  fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
  if (reason) toast(reason, 'bad');
  location.hash = '#/login';
}

// ───────────────────────── ui helpers ─────────────────────────
function toast(msg, kind = '') { const t = document.createElement('div'); t.className = `toast ${kind}`; t.textContent = msg; $('#toasts').appendChild(t); setTimeout(() => t.remove(), 3500); }
function modal(html) { const root = $('#modal-root'); root.innerHTML = `<div class="modal-bg"><div class="modal card">${html}</div></div>`; return { el: root.firstChild, close: () => (root.innerHTML = '') }; }
const loading = (t = 'Loading…') => `<div class="loader"><div class="spin"></div>${esc(t)}</div>`;
const bar = (p, color) => `<div class="bar"><i style="width:${Math.max(0, Math.min(100, p))}%;${color ? `background:${color}` : ''}"></i></div>`;
const initials = (name) => String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
const COUNTRY_CODES = [['+91', 'India'], ['+1', 'USA / Canada'], ['+44', 'UK'], ['+61', 'Australia'], ['+65', 'Singapore'], ['+971', 'UAE'], ['+966', 'Saudi Arabia'], ['+974', 'Qatar'], ['+977', 'Nepal'], ['+880', 'Bangladesh'], ['+94', 'Sri Lanka'], ['+60', 'Malaysia'], ['+49', 'Germany'], ['+33', 'France'], ['+81', 'Japan']];
const ccOptions = (sel = '+91') => COUNTRY_CODES.map(([c, n]) => `<option value="${c}" ${c === sel ? 'selected' : ''}>${c} ${n}</option>`).join('');
function fmtMobile(m) {
  const cc = COUNTRY_CODES.map((x) => x[0]).sort((a, b) => b.length - a.length).find((c) => String(m).startsWith(c));
  if (!cc) return m; const num = String(m).slice(cc.length);
  return cc === '+91' && num.length === 10 ? `${cc} ${num.slice(0, 5)} ${num.slice(5)}` : `${cc} ${num}`;
}
function mobileRule(cc, v) {
  const num = String(v || '').replace(/[\s().-]/g, '').replace(/^0+/, '');
  if (!num) return 'Please enter your mobile number.';
  if (!/^\d+$/.test(num)) return 'Mobile number can contain digits only.';
  if (cc === '+91' ? !/^[6-9]\d{9}$/.test(num) : !/^\d{6,14}$/.test(num)) return cc === '+91' ? 'Enter a valid 10-digit Indian mobile number (starts with 6, 7, 8 or 9).' : 'Enter a valid mobile number (6–14 digits).';
  return '';
}
function mobileModal() {
  const m = modal(`<h2>Add your mobile number</h2><p class="muted small">We'll show it on your profile. Each number can be linked to one account.</p>
    <form id="mf" novalidate><div class="field"><label for="m-num">Mobile number</label><div class="phone-row"><select id="m-cc" name="countryCode" aria-label="Country code">${ccOptions()}</select><input class="input" id="m-num" name="mobile" inputmode="numeric" placeholder="98765 43210" autocomplete="tel-national"></div></div>
    <div class="form-error error hidden" role="alert"></div>
    <div class="row"><button type="button" class="btn ghost" id="mcancel">Cancel</button><div class="spacer"></div><button type="submit" class="btn" id="msave">Save number</button></div></form>`);
  const f = $('#mf', m.el), btn = $('#msave', m.el);
  $('#mcancel', m.el).onclick = m.close; $('#m-num', m.el).focus();
  bindSubmit(f, btn, async () => {
    const cc = $('#m-cc', m.el).value, v = $('#m-num', m.el).value; const bad = mobileRule(cc, v);
    setFieldError(f, 'mobile', bad); if (bad) return;
    btn.disabled = true;
    try { const r = await api('/api/me/mobile', { method: 'POST', body: { countryCode: cc, mobile: v } }); ME.mobile = r.mobile; m.close(); renderNav(); toast('Mobile number saved.', 'ok'); }
    catch (e) { setFieldError(f, 'mobile', e.message); btn.disabled = false; }
  });
}
const starsHtml = (n, max = 3) => `<span class="stars">${Array.from({ length: max }, (_, i) => (i < n ? '★' : '<span class="off">★</span>')).join('')}</span>`;
const fmtDate = (iso) => new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const fmtDay = (iso) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
function accessPill(a) {
  if (!a) return '';
  if (a.status === 'active') return `<a class="pill ok" href="#/plans" title="Subscription active until ${fmtDay(a.expiresAt)}">${esc(a.planName)} plan</a>`;
  if (a.status === 'trial') return `<a class="pill ${a.daysLeft <= 7 ? 'fire' : ''}" href="#/plans" title="Free trial ends ${fmtDay(a.trialEndsAt)}">Trial · ${a.daysLeft}d left</a>`;
  return `<a class="pill bad" href="#/plans">Subscribe</a>`;
}
function accessBanner(a, onPlans = false) {
  if (!a) return '';
  if (a.status === 'trial') {
    const used = Math.min(100, Math.round(((a.trialDays - a.daysLeft) / a.trialDays) * 100));
    return `<div class="banner row ${a.daysLeft <= 7 ? 'warn' : ''}"><div style="flex:1;min-width:220px"><b>Free trial — ${a.daysLeft} day${a.daysLeft === 1 ? '' : 's'} left</b> <span class="muted small">(ends ${fmtDay(a.trialEndsAt)})</span>
      <div class="muted small" style="margin:4px 0 6px">Full access to every language and game during your ${a.trialDays}-day trial. After that, a subscription is needed to keep learning.</div>${bar(used, a.daysLeft <= 7 ? '#f59e0b' : '')}</div>
      ${onPlans ? '' : `<a class="btn sm ${a.daysLeft <= 7 ? '' : 'ghost'}" href="#/plans">View subscription plans</a>`}</div>`;
  }
  if (a.status === 'active') return `<div class="banner row"><div style="flex:1"><b>${esc(a.planName)} plan active</b> <span class="muted small">— valid until ${fmtDay(a.expiresAt)} (${a.daysLeft} days left)</span></div>${onPlans ? '' : '<a class="btn ghost sm" href="#/plans">Manage</a>'}</div>`;
  return `<div class="card lockcard"><div style="font-size:2.6rem"></div><div style="flex:1;min-width:240px">
      <h2 style="margin:0 0 4px">${a.reason === 'subscription-expired' ? 'Your subscription has expired' : `Your ${a.trialDays}-day free trial has ended`}</h2>
      <p class="muted" style="margin:0">Your progress, XP and agent insights are saved. Subscribe to continue playing and learning.</p></div>
      <a class="btn lg" href="#/plans">Subscribe now</a></div>`;
}
const QTYPE = { mcq: 'Quiz', output: 'Predict the output', bug: 'Bug hunt', fill: 'Fill the blank' };

// tiny sound fx (WebAudio) — toggle stored in localStorage
let actx; const soundOn = () => LS.get('cq_sound') !== 'off';
function beep(kind) {
  if (!soundOn()) return;
  try {
    actx ||= new (window.AudioContext || window.webkitAudioContext)();
    const notes = { ok: [660, 880], bad: [220, 160], win: [523, 659, 784, 1046] }[kind];
    notes.forEach((f, i) => { const o = actx.createOscillator(), g = actx.createGain(); o.type = kind === 'bad' ? 'sawtooth' : 'triangle'; o.frequency.value = f; g.gain.setValueAtTime(0.08, actx.currentTime + i * 0.1); g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + i * 0.1 + 0.18); o.connect(g).connect(actx.destination); o.start(actx.currentTime + i * 0.1); o.stop(actx.currentTime + i * 0.1 + 0.2); });
  } catch { /* ignore */ }
}
function confetti() {
  const c = document.createElement('canvas'); c.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:70'; document.body.appendChild(c);
  const ctx = c.getContext('2d'); c.width = innerWidth; c.height = innerHeight;
  const cols = ['#d8b25a', '#f3dc9b', '#b88c2e', '#fff1c1', '#e0a806'];
  const P = Array.from({ length: 160 }, () => ({ x: Math.random() * c.width, y: -20 - Math.random() * c.height * 0.5, vx: (Math.random() - 0.5) * 4, vy: 2 + Math.random() * 4, r: 4 + Math.random() * 5, c: cols[(Math.random() * cols.length) | 0], a: Math.random() * 6 }));
  const t0 = performance.now();
  (function f(t) { ctx.clearRect(0, 0, c.width, c.height); P.forEach((p) => { p.x += p.vx; p.y += p.vy; p.a += 0.1; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a); ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 0.6); ctx.restore(); }); if (t - t0 < 3000) requestAnimationFrame(f); else c.remove(); })(t0);
}

// ───────────────────────── syntax highlighting ─────────────────────────
const KW = {
  python: 'def return if elif else for while in range print import from as class and or not None True False pass break continue lambda try except with type len',
  javascript: 'const let var function return if else for while of in switch case break continue default new typeof class true false null undefined console',
  java: 'public private protected static void class extends implements new return if else for while do int double char boolean String true false null this super break continue List Map ArrayList HashMap Integer System long byte short float final var switch case default abstract interface StringBuilder Arrays Collections Set TreeMap TreeSet HashSet',
  cpp: 'int void char double bool return if else for while do switch case break continue std cout endl string vector map set true false auto const unsigned long template typename static inline pair unordered_map multiset stack queue deque priority_queue',
  sql: 'SELECT FROM WHERE ORDER BY GROUP HAVING JOIN LEFT RIGHT INNER CROSS FULL OUTER ON AS DISTINCT LIMIT OFFSET LIKE IS NULL AND OR NOT BETWEEN COUNT AVG SUM MIN MAX DESC ASC IN CREATE TABLE INSERT INTO VALUES UPDATE SET DELETE ALTER ADD COLUMN DROP RENAME TRUNCATE PRIMARY KEY FOREIGN REFERENCES UNIQUE DEFAULT CHECK IF EXISTS BEGIN COMMIT ROLLBACK SAVEPOINT RELEASE TRANSACTION GRANT REVOKE TO WITH OPTION PRIVILEGES VIEW INDEX OVER PARTITION CASE WHEN THEN ELSE END UNION ALL INTERSECT EXCEPT INTEGER TEXT PRAGMA REPLACE IGNORE CONFLICT DO',
};
const KWSET = Object.fromEntries(Object.entries(KW).map(([k, v]) => [k, new Set(v.split(' ').map((w) => (k === 'sql' ? w.toUpperCase() : w)))]));
const COMMENT = { python: /#.*/.source, sql: /--.*/.source, cpp: /\/\/.*|#\w+/.source, javascript: /\/\/.*/.source, java: /\/\/.*|@\w+/.source };
const STR = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/.source;
function hlLine(line, lang) {
  const re = new RegExp(`(${COMMENT[lang] || COMMENT.javascript})|(${STR})|(_{4})|\\b(\\d+(?:\\.\\d+)?)\\b|\\b([A-Za-z_]\\w*)\\b`, 'g');
  let out = '', last = 0, m;
  while ((m = re.exec(line))) {
    out += esc(line.slice(last, m.index)); last = re.lastIndex;
    const [tok, c, s, blank, n, id] = m;
    if (c) out += `<span class="tk-c">${esc(tok)}</span>`;
    else if (s) out += `<span class="tk-s">${esc(tok)}</span>`;
    else if (blank) out += `<span class="blank">____</span>`;
    else if (n) out += `<span class="tk-n">${esc(tok)}</span>`;
    else if (id && KWSET[lang]?.has(lang === 'sql' ? tok.toUpperCase() : tok)) out += `<span class="tk-k">${esc(tok)}</span>`;
    else if (id && line[re.lastIndex] === '(') out += `<span class="tk-f">${esc(tok)}</span>`;
    else out += esc(tok);
  }
  return out + esc(line.slice(last));
}
const tick = (h) => h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
const codeBlock = (code, lang) => `<div class="code">${code.split('\n').map((l, i) => `<div class="ln"><span class="n">${i + 1}</span><pre>${hlLine(l, lang) || ' '}</pre></div>`).join('')}</div>`;

// ───────────────────────── nav ─────────────────────────
// bottom tab bar (phones & tablets — the top links are hidden there); not shown during a game
function renderTabbar() {
  let bar = $('#tabbar');
  const h = location.hash, show = !!ME && !h.startsWith('#/play/');
  document.body.classList.toggle('has-tabbar', show);
  if (!show) { if (bar) bar.remove(); return; }
  if (!bar) { bar = document.createElement('nav'); bar.id = 'tabbar'; bar.className = 'tabbar'; bar.setAttribute('aria-label', 'Main'); document.body.appendChild(bar); }
  const tab = (href, label, also = []) => {
    const on = h.startsWith(href) || also.some((a) => h.startsWith(a));
    return `<a href="${href}" class="${on ? 'active' : ''}"${on ? ' aria-current="page"' : ''}><span class="tb-dot"></span>${label}</a>`;
  };
  bar.innerHTML = tab('#/dashboard', 'Play', ['#/lang/', '#/learn/']) + tab('#/agent', 'Agent') + tab('#/chat', `Ask ${esc(ME.agent.name)}`) + tab('#/leaderboard', 'Ranks') + tab('#/plans', 'Plan');
}

function renderNav() {
  renderTabbar();
  const nav = $('#nav'); const h = location.hash;
  if (!ME) {
    nav.innerHTML = `<a class="logo" href="#/"><b>Syntaxo</b></a><div class="spacer"></div>${themeBtn()}
      <a class="btn ghost sm" href="#/login">Log in</a><a class="btn sm" href="#/register">Register</a>`;
    bindThemeBtn(); return;
  }
  const link = (href, label) => `<a class="link ${h.startsWith(href) ? 'active' : ''}" href="${href}">${label}</a>`;
  nav.innerHTML = `<a class="logo" href="#/dashboard"><b>Syntaxo</b></a>
    <div class="navlinks">${link('#/dashboard', 'Play')}${link('#/agent', 'My Agent')}${link('#/chat', `Ask ${esc(ME.agent.name)}`)}${link('#/leaderboard', 'Leaderboard')}${link('#/plans', 'Subscription')}</div>
    <div class="spacer"></div>
    ${themeBtn()}${accessPill(ME.access)}
    <span class="pill fire" title="Daily streak">${ME.stats.streak.current}-day streak</span>
    <span class="pill gold xp-pill" title="Experience points">${ME.stats.xp} XP</span>
    <div class="menu"><div class="avatar" id="av" title="Your profile">${esc(initials(ME.fullName))}</div>
      <div class="drop hidden" id="drop">
        <div class="profile-box"><div class="profile-name">${esc(ME.fullName)}</div>
          <div class="profile-row"><span>User ID</span><b>${esc(ME.userId)}</b></div>
          <div class="profile-row"><span>Email</span><b>${esc(ME.email)}</b></div>
          <div class="profile-row"><span>Mobile</span>${ME.mobile ? `<b>${esc(fmtMobile(ME.mobile))}</b>` : '<button type="button" class="linkbtn" id="addmob">Add number</button>'}</div>
          <div class="profile-row"><span>Username</span><b>${esc(ME.username)}</b></div>
          <div class="profile-row"><span>Rank</span><b>${esc(ME.rank.title)}</b></div></div>
        <a href="#/dashboard">Play</a><a href="#/agent">My Agent</a><a href="#/chat">Ask ${esc(ME.agent.name)}</a><a href="#/leaderboard">Leaderboard</a><a href="#/plans">Subscription</a>
        <button id="snd">${soundOn() ? 'Sound: on' : 'Sound: off'}</button><button id="lo">Log out</button>
      </div></div>`;
  bindThemeBtn();
  $('#av').onclick = (e) => { e.stopPropagation(); $('#drop').classList.toggle('hidden'); };
  $('#lo').onclick = () => { logout(); toast('Logged out. See you soon!'); };
  const am = $('#addmob'); if (am) am.onclick = (e) => { e.stopPropagation(); $('#drop').classList.add('hidden'); mobileModal(); };
  $('#snd').onclick = (e) => { e.stopPropagation(); LS.set('cq_sound', soundOn() ? 'off' : 'on'); renderNav(); };
}

// ───────────────────────── router ─────────────────────────
const routes = [
  [/^#?\/?$/, landing, 'public'],
  [/^#\/register$/, registerView, 'guest'],
  [/^#\/login$/, loginView, 'guest'],
  [/^#\/forgot$/, forgotView, 'guest'],
  [/^#\/dashboard$/, dashboard, 'auth'],
  [/^#\/lang\/(\w+)$/, languageView, 'auth'],
  [/^#\/learn\/(\w+)\/(\d+)$/, lessonView, 'paid'],
  [/^#\/play\/(\w+)\/(\d+)$/, playView, 'paid'],
  [/^#\/agent$/, agentView, 'auth'],
  [/^#\/chat$/, chatView, 'auth'],
  [/^#\/plans$/, plansView, 'auth'],
  [/^#\/leaderboard$/, leaderboardView, 'auth'],
];
async function router() {
  if (teardown) { teardown(); teardown = null; }
  $('#modal-root').innerHTML = '';
  const h = location.hash || '#/';
  for (const [re, fn, kind] of routes) {
    const m = h.match(re); if (!m) continue;
    if (!ME && (store.token || !router.triedCookie)) { router.triedCookie = true; await loadMe(); }
    if ((kind === 'auth' || kind === 'paid') && !ME) { location.hash = '#/login'; return; }
    if (kind === 'paid' && ME.access && !ME.access.canPlay) { toast('Your free trial has ended — subscribe to continue learning.', 'bad'); location.hash = '#/plans'; return; }
    if ((kind === 'guest' || kind === 'public') && ME) { location.hash = '#/dashboard'; return; }
    renderNav(); window.scrollTo(0, 0);
    try { await fn(...m.slice(1)); } catch (e) { view.innerHTML = `<div class="card center"><h2>Oops</h2><p class="muted">${esc(e.message)}</p><a class="btn" href="#/dashboard">Back</a></div>`; }
    return;
  }
  location.hash = '#/';
}
addEventListener('hashchange', router);
document.addEventListener('click', () => $('#drop')?.classList.add('hidden'));

// ───────────────────────── landing ─────────────────────────
async function landing() {
  view.innerHTML = `
  <section class="hero">
    <div>
      <span class="pill">Learn by playing — part by part</span>
      <h1 style="margin-top:14px">Level up your <em>coding skills</em> one game at a time.</h1>
      <p>Pick any language, learn it in bite-sized parts, and prove it in fast mini-games: quizzes, output prediction, bug hunts and fill-the-blank challenges. Your own AI-style coding agent tracks every score and tells you exactly what to practise next.</p>
      <div class="row" style="margin-top:22px"><a class="btn lg" href="#/register">Start 30-day free trial</a><a class="btn ghost lg" href="#/login">Log in</a></div>
      <div class="row muted small" style="margin-top:18px">✔ 30 days free &nbsp; ✔ No card needed &nbsp; ✔ 5-minute levels &nbsp; ✔ Personal agent</div>
    </div>
    <div class="terminal"><div class="bar2"><i></i><i></i><i></i><span class="muted small" style="margin-left:8px">bug_hunt.py</span></div>
      <div style="padding:14px">
        <div class="qtype">Bug hunt · Python · Part 1</div>
        ${codeBlock('name = "Ada"\nage = 36\nprint("Name: " + name)\nprint("Age: " + age)', 'python')}
        <div class="options" style="grid-template-columns:1fr 1fr"><div class="opt"><span class="key">1</span>Line 2</div><div class="opt correct"><span class="key">2</span>Line 4 ✓</div></div>
        <div class="agent-bubble" style="margin-top:14px"><div class="agent-face" style="width:44px;height:44px;font-size:1.2rem">B</div><div class="speech small">Nice catch! You can't add a str and an int. +145 pts combo ×2</div></div>
      </div></div>
  </section>
  <div class="section-title"><h2>How it works</h2></div>
  <div class="grid g4">
    ${[['', '1. Register', 'Create your account with a username, email and mobile number.'], ['', '2. Log in', 'Sign in with your username and password.'], ['', '3. Meet your agent', 'A personal agent tracks your progress and answers your coding questions.'], ['', '4. Play & learn', 'Clear parts, earn XP and stars, unlock the next part.']]
      .map(([i, t, d]) => `<div class="card feature">${i ? `<div class="ico">${i}</div>` : ''}<h3>${t}</h3><p class="muted small">${d}</p></div>`).join('')}
  </div>
  <div class="section-title"><h2>Languages</h2></div>
  <div class="row" id="langchips">${loading('')}</div>
  <div class="section-title"><h2>Game modes</h2></div>
  <div class="grid g4">${Object.entries({ 'Quiz': 'Concept questions with instant explanations.', 'Predict the output': 'Read code, guess what it prints.', 'Bug hunt': 'Spot the line that breaks the program.', 'Fill the blank': 'Type the missing keyword or method.' }).map(([k, v]) => `<div class="card"><h3>${k}</h3><p class="muted small">${v}</p></div>`).join('')}</div>`;
  try {
    const { languages } = await api('/api/public/languages');
    $('#langchips').innerHTML = languages.map((l) => `<span class="chip" style="border-color:${l.color}55">${esc(l.name)} <span class="muted small">${l.levels.length} parts</span></span>`).join('') + `<span class="chip muted">+ more coming</span>`;
  } catch { $('#langchips').innerHTML = ''; }
}

// ───────────────────────── form helpers ─────────────────────────
// Rules mirror the server (src/auth.js → validateRegistration)
const RULES = {
  fullName: (v) => (v.trim().length >= 2 ? '' : 'Please enter your full name (at least 2 characters).'),
  username: (v) => { v = v.trim(); if (v.length < 3 || v.length > 20) return 'Username must be 3–20 characters long.'; if (/\s/.test(v)) return 'No spaces allowed — try ' + v.replace(/\s+/g, '_').toLowerCase().slice(0, 20); if (!/^[a-zA-Z0-9_.-]+$/.test(v)) return 'Use only letters, numbers, _ . or -'; return ''; },
  email: (v) => (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()) ? '' : 'Please enter a valid email address, e.g. name@gmail.com.'),
  password: (v) => (v.length >= 6 ? '' : 'Password must be at least 6 characters.'),
};
function setFieldError(form, name, msg) {
  const input = form.querySelector(`[name="${name}"]`); if (!input) return;
  const field = input.closest('.field'); let hint = field.querySelector('.field-error');
  if (!hint) { hint = document.createElement('div'); hint.className = 'field-error'; field.appendChild(hint); }
  hint.textContent = msg || ''; field.classList.toggle('invalid', !!msg);
  if (!msg && input.value) field.classList.add('valid'); else field.classList.remove('valid');
}
function showFormError(form, msg) {
  const box = form.querySelector('.form-error'); box.innerHTML = msg ? `${esc(msg)}` : ''; box.classList.toggle('hidden', !msg);
}
function focusFirstInvalid(form) {
  const f = form.querySelector('.field.invalid input, .field.invalid select');
  if (f) { f.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(() => f.focus({ preventScroll: true }), 250); }
}
function pwStrength(v) {
  let s = 0; if (v.length >= 6) s++; if (v.length >= 10) s++; if (/[a-z]/i.test(v) && /\d/.test(v)) s++; if (/[^a-z0-9]/i.test(v)) s++;
  return [['', '#26315e'], ['Weak', '#ef4444'], ['Okay', '#f59e0b'], ['Good', '#22d3ee'], ['Strong', '#22c55e']][v ? Math.max(1, s) : 0];
}
// Run `handler` from both the submit event and a direct button click → works even where form submission is restricted
function bindSubmit(form, btn, handler) {
  let running = false;
  const go = async (e) => { e?.preventDefault(); if (running) return; running = true; try { await handler(); } finally { running = false; } };
  form.addEventListener('submit', go);
  btn.addEventListener('click', go);
  form.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') go(e); });
}
function pwToggle() { $$('[data-pw]').forEach((b) => (b.onclick = () => { const i = b.previousElementSibling; i.type = i.type === 'password' ? 'text' : 'password'; b.textContent = i.type === 'password' ? 'Show' : 'Hide'; })); }

// ───────────────────────── register ─────────────────────────
async function registerView() {
  let langs = [];
  try { langs = (await api('/api/public/languages')).languages; } catch { /* optional */ }
  view.innerHTML = `<div class="auth"><div class="card">
    <div class="steps"><span class="on"></span><span></span><span></span></div>
    <h2>Create your account</h2><p class="muted small">Step 1 of 3 — you'll log in with your <b>username</b> and password.</p>
    <form id="f" novalidate autocomplete="on">
      <div class="field"><label for="r-name">Full name</label><input class="input" id="r-name" name="fullName" placeholder="e.g. Rahul Verma" autocomplete="name"></div>
      <div class="field"><label for="r-user">Username</label><input class="input" id="r-user" name="username" placeholder="e.g. rahul_verma" autocomplete="username" autocapitalize="off" spellcheck="false">
        <div class="field-help">You'll use this to log in · 3–20 characters · letters, numbers, _ . - · no spaces</div></div>
      <div class="field"><label for="r-email">Email</label><input class="input" id="r-email" type="email" name="email" placeholder="e.g. rahul@gmail.com" autocomplete="email" autocapitalize="off"></div>
      <div class="field"><label for="r-mobile">Mobile number</label><div class="phone-row"><select id="r-cc" name="countryCode" aria-label="Country code">${ccOptions()}</select><input class="input" id="r-mobile" name="mobile" type="tel" inputmode="numeric" placeholder="e.g. 98765 43210" autocomplete="tel-national"></div></div>
      <div class="field"><label for="r-pw">Password</label>
        <div class="pw-wrap"><input class="input" id="r-pw" type="password" name="password" placeholder="At least 6 characters" autocomplete="new-password"><button type="button" data-pw>Show</button></div>
        <div class="pw-meter"><i id="pwbar"></i></div><div class="field-help" id="pwlabel">Use 6+ characters. Mixing letters, numbers & symbols makes it stronger.</div></div>
      <div class="field"><label for="r-cf">Confirm password</label><input class="input" id="r-cf" type="password" name="confirm" placeholder="Type the password again" autocomplete="new-password"></div>
      <div class="field"><label for="r-lang">Which language do you want to learn first?</label>
        <select id="r-lang" name="goalLanguage"><option value="">I'm not sure yet</option>${langs.map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join('')}</select></div>
      <div class="form-error error hidden" role="alert"></div>
      <button type="submit" class="btn lg" style="width:100%" id="sub">Register</button>
    </form>
    <p class="center muted small" style="margin-top:16px">Already registered? <a href="#/login">Log in with your username</a></p>
  </div></div>`;
  pwToggle();
  const form = $('#f'), btn = $('#sub');
  const val = (n) => form.querySelector(`[name="${n}"]`).value;
  const check = (n) => { const msg = n === 'confirm' ? (val('confirm') === val('password') ? '' : 'Passwords do not match.') : n === 'mobile' ? mobileRule(val('countryCode'), val('mobile')) : RULES[n](val(n)); setFieldError(form, n, msg); return !msg; };
  const touched = new Set();
  $('#r-cc').addEventListener('change', () => { if (touched.has('mobile')) check('mobile'); });
  $('#r-mobile').addEventListener('input', (e) => { e.target.value = e.target.value.replace(/[^\d\s-]/g, ''); });
  ['fullName', 'username', 'email', 'mobile', 'password', 'confirm'].forEach((n) => {
    const el = form.querySelector(`[name="${n}"]`);
    el.addEventListener('blur', () => { if (el.value) { touched.add(n); check(n); } });
    el.addEventListener('input', () => { showFormError(form, ''); if (touched.has(n)) check(n); if (n === 'password') { if (touched.has('confirm')) check('confirm'); const [lbl, col] = pwStrength(el.value); $('#pwbar').style.cssText = `width:${[0, 25, 50, 75, 100][['', 'Weak', 'Okay', 'Good', 'Strong'].indexOf(lbl)]}%;background:${col}`; $('#pwlabel').textContent = lbl ? `Strength: ${lbl}` : 'Use 6+ characters. Mixing letters, numbers & symbols makes it stronger.'; } });
  });

  bindSubmit(form, btn, async () => {
    showFormError(form, '');
    const names = ['fullName', 'username', 'email', 'mobile', 'password', 'confirm']; names.forEach((n) => touched.add(n));
    const ok = names.map(check).every(Boolean);
    if (!ok) { showFormError(form, 'Please fix the highlighted fields.'); focusFirstInvalid(form); return; }
    btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Creating account…';
    try {
      const d = Object.fromEntries(new FormData(form)); delete d.confirm;
      const r = await api('/api/auth/register', { method: 'POST', body: d });
      SS.set('cq_prefill', r.username);
      const m = modal(`<div class="steps"><span class="on"></span><span class="on"></span><span></span></div>
        <h2>Registration successful!</h2><p class="muted">Welcome, ${esc(r.fullName)}. Log in with your <b>username</b> and password:</p>
        <div class="userid">${esc(r.username)}</div>
        <div class="row" style="justify-content:center;margin-bottom:12px"><span class="muted small">User ID <b>${esc(r.userId)}</b></span><button type="button" class="btn ghost sm" id="cp">Copy username</button></div>
        <div class="banner small" style="margin-bottom:14px">Your <b>${r.trialDays}-day free trial</b> starts now — full access to every language.${r.emailSent ? `<br>We've also emailed your username to <b>${esc(r.email)}</b>.` : ''}<br>Forgot it later? Recover it anytime with your email.</div>
        <div class="agent-bubble"><div class="agent-face" style="border-color:${r.agent.color}">${esc(r.agent.name[0])}</div>
          <div class="speech"><b>${esc(r.agent.name)}</b> <span class="muted small">· ${esc(r.agent.title)}</span><br>I'm your personal coding agent! I'll track your scores in every game and guide your learning path. See you inside!</div></div>
        <button type="button" class="btn lg" style="width:100%;margin-top:20px" id="go">Continue to login →</button>`);
      $('#cp', m.el).onclick = async () => { try { await navigator.clipboard.writeText(r.username); toast('Username copied!', 'ok'); } catch { toast(`Your username is ${r.username} — please note it down.`); } };
      $('#go', m.el).onclick = () => { m.close(); location.hash = '#/login'; };
    } catch (err) {
      if (err.field) { setFieldError(form, err.field, err.message); focusFirstInvalid(form); }
      showFormError(form, err.message); toast(err.message, 'bad');
      btn.disabled = false; btn.textContent = 'Register';
    }
  });
}

// ───────────────────────── login ─────────────────────────
async function loginView() {
  const pre = SS.get('cq_prefill') || '';
  view.innerHTML = `<div class="auth"><div class="card">
    <div class="steps"><span class="on"></span><span class="on"></span><span class="on"></span></div>
    <h2>Welcome back</h2><p class="muted small">Log in with your <b>username</b> and password.</p>
    <form id="f" novalidate>
      <div class="field"><label for="l-id">Username</label><input class="input" id="l-id" name="identifier" value="${esc(pre)}" placeholder="e.g. rahul_verma" autocomplete="username" autocapitalize="off" spellcheck="false"></div>
      <div class="field"><label for="l-pw">Password</label><div class="pw-wrap"><input class="input" id="l-pw" type="password" name="password" autocomplete="current-password"><button type="button" data-pw>Show</button></div></div>
      <div class="row" style="margin:-4px 0 14px"><div class="spacer"></div><a href="#/forgot" class="small">Forgot username or password?</a></div>
      <div class="form-error error hidden" role="alert"></div>
      <button type="submit" class="btn lg" style="width:100%" id="sub">Log in & play</button>
    </form>
    <p class="center muted small" style="margin-top:16px">New here? <a href="#/register">Create an account</a></p>
  </div></div>`;
  pwToggle();
  const form = $('#f'), btn = $('#sub');
  (pre ? $('#l-pw') : $('#l-id')).focus();
  form.addEventListener('input', () => showFormError(form, ''));
  bindSubmit(form, btn, async () => {
    const d = Object.fromEntries(new FormData(form));
    setFieldError(form, 'identifier', d.identifier.trim() ? '' : 'Enter your username.');
    setFieldError(form, 'password', d.password ? '' : 'Enter your password.');
    if (!d.identifier.trim() || !d.password) { focusFirstInvalid(form); return; }
    btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Checking…';
    try {
      const r = await api('/api/auth/login', { method: 'POST', body: { identifier: d.identifier.trim(), password: d.password } });
      store.token = r.token; ME = r.user; SS.del('cq_prefill');
      if (!ME.access.canPlay) { toast('Welcome back! Your free trial has ended — choose a plan to continue.', 'bad'); location.hash = '#/plans'; return; }
      toast(`${ME.agent.name}: Welcome, ${ME.fullName}!` + (ME.access.status === 'trial' ? ` (${ME.access.daysLeft} trial days left)` : ''), 'ok');
      location.hash = '#/dashboard';
    } catch (err) { showFormError(form, err.message); toast(err.message, 'bad'); btn.disabled = false; btn.textContent = 'Log in & play'; }
  });
}

// ───────────────────────── dashboard ─────────────────────────
async function dashboard() {
  view.innerHTML = loading('Loading your quest…');
  const [{ languages, access }, rep] = await Promise.all([api('/api/languages'), api('/api/agent/report')]);
  ME.access = access; renderNav();
  const o = rep.overview; const top = access.canPlay ? rep.recommendations[0] : null;
  view.innerHTML = `${accessBanner(access)}
    <div class="grid g2" style="align-items:stretch">
      <div class="card"><h1 class="hey" style="font-size:1.7rem">Hey ${esc(ME.fullName)}</h1>
        <p class="muted" style="margin:0 0 14px">Username <b>${esc(ME.username)}</b> · ${esc(o.rank.title)}</p>
        <div class="row small muted"><span>${esc(o.rank.title)}</span><div class="spacer"></div><span>${o.rank.next ? `${o.xp} / ${o.rank.next} XP → ${o.rank.nextTitle}` : 'Max rank!'}</span></div>
        ${bar(o.rank.progress)}
        <div class="stat4" style="margin-top:16px">
          ${[['', o.xp, 'XP'], ['', o.streak.current, 'Streak'], ['', o.gamesPlayed, 'Games'], ['', o.accuracy + '%', 'Accuracy']].map(([i, v, k]) => `<div class="stat"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('')}
        </div></div>
      <div class="card"><div class="agent-bubble"><div class="agent-face" style="border-color:${rep.agent.color}">${esc(rep.agent.name[0])}</div>
        <div style="flex:1"><b>${esc(rep.agent.name)}</b> <span class="muted small">· your ${esc(rep.agent.title)}</span>
        <div class="speech" style="margin-top:8px">${esc(rep.headline)}${top ? `<br><br><b>${esc(top.text)}</b>` : ''}</div>
        <div class="row" style="margin-top:12px">${top && top.lang ? `<a class="btn sm" href="#/learn/${top.lang}/${top.level}">Do it now</a>` : ''}<a class="btn ghost sm" href="#/chat">Chat with ${esc(ME.agent.name)}</a><a class="btn ghost sm" href="#/agent">Full agent report</a></div></div></div></div>
    </div>
    <div class="section-title"><h2>Choose a language</h2><span class="muted small">Each language is split into parts. Pass a part (≥ 60%) to unlock the next.</span></div>
    <div class="grid g3 ${access.canPlay ? '' : 'locked-grid'}">${languages.map(langCard).join('')}</div>`;
  $$('[data-lang]').forEach((el) => (el.onclick = () => (access.canPlay ? (location.hash = `#/lang/${el.dataset.lang}`) : (location.hash = '#/plans'))));
}
function langCard(l) {
  const passed = l.levels.filter((lv) => lv.progress?.passed).length;
  const stars = l.levels.reduce((s, lv) => s + (lv.progress?.stars || 0), 0);
  const started = l.levels.some((lv) => lv.progress);
  return `<div class="card hover lang-card" data-lang="${l.id}">
    <div class="top"><div class="ico lang-code" style="background:${l.color}22;border:1px solid ${l.color}66;color:color-mix(in srgb, ${l.color} 72%, #000)">${esc(l.icon)}</div>
      <div><h3 style="margin:0">${esc(l.name)}</h3><div class="muted small">${esc(l.tagline)}</div></div></div>
    <div class="row small muted"><span>${passed}/${l.levels.length} parts</span><div class="spacer"></div><span class="stars">★</span> ${stars}/${l.levels.length * 3}</div>
    ${bar((passed / l.levels.length) * 100, l.color)}
    <div class="row" style="margin-top:14px"><span class="btn sm ${started ? '' : 'ghost'}">${passed === l.levels.length ? 'Mastered' : started ? 'Continue' : 'Start'}</span></div></div>`;
}

// ───────────────────────── language map ─────────────────────────
async function languageView(langId) {
  view.innerHTML = loading();
  const { languages, access } = await api('/api/languages');
  if (!access.canPlay) { location.hash = '#/plans'; return; }
  const l = languages.find((x) => x.id === langId); if (!l) throw new Error('Language not found');
  view.innerHTML = `<a href="#/dashboard" class="muted small">← All languages</a>
    <div class="row" style="margin:14px 0 4px"><div class="lang-card"><div class="ico lang-code" style="font-size:1.25rem;width:70px;height:70px;border-radius:20px;display:grid;place-items:center;background:${l.color}22;border:1px solid ${l.color}66;color:color-mix(in srgb, ${l.color} 72%, #000)">${esc(l.icon)}</div></div>
      <div><h1 style="margin:0">${esc(l.name)}</h1><div class="muted">${esc(l.tagline)}</div></div></div>
    <div class="path">${l.levels.map((lv) => {
      const p = lv.progress; const cls = p?.passed ? 'done' : lv.unlocked ? 'open' : 'locked';
      return `<div class="node ${cls}" data-lv="${lv.level}" data-unlocked="${lv.unlocked}">
        <div class="bubble">${p?.passed ? '✓' : lv.level}</div>
        <div style="flex:1"><div class="muted small">PART ${lv.level}</div>
          <h3 style="margin:2px 0">${esc(lv.title)}</h3>
          <div class="small muted">${lv.questionCount} questions · 10 per game · ${p ? `best ${p.bestAccuracy}% · ${p.attempts} attempt${p.attempts > 1 ? 's' : ''}` : lv.unlocked ? 'Ready to play' : `Pass Part ${lv.level - 1} to unlock`}</div></div>
        <div>${starsHtml(p?.stars || 0)}</div></div>`;
    }).join('')}</div>`;
  $$('.node').forEach((n) => (n.onclick = () => n.dataset.unlocked === 'true' ? (location.hash = `#/learn/${langId}/${n.dataset.lv}`) : toast(`Pass Part ${n.dataset.lv - 1} first to unlock this part.`, 'bad')));
}

// ───────────────────────── lesson ─────────────────────────
async function lessonView(langId, level) {
  view.innerHTML = loading();
  const { lesson: ls } = await api(`/api/lesson/${langId}/${level}`);
  if (!ls.unlocked) { toast('This part is locked.', 'bad'); location.hash = `#/lang/${langId}`; return; }
  view.innerHTML = `<a href="#/lang/${langId}" class="muted small">← ${esc(ls.languageName)} map</a>
    <div class="grid g2" style="margin-top:14px;align-items:start">
      <div class="card"><div class="qtype">Learn · ${esc(ls.languageName)} · Part ${ls.level}</div>
        <h1 style="font-size:1.8rem">${esc(ls.title)}</h1><p>${esc(ls.summary).replace(/`([^`]+)`/g, '<code class="inl">$1</code>')}</p>
        ${codeBlock(ls.code, langId)}
        ${ls.sheet && ls.sheet.length ? `<h3 style="margin-top:18px">Cheat sheet</h3><table class="sheet">${ls.sheet.map(([a, b]) => `<tr><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join('')}</table>` : ''}</div>
      <div class="card"><h3>The challenge</h3>
        <ul class="muted" style="line-height:1.9;padding-left:18px"><li>10 challenges drawn from a bank of <b>${ls.questionCount}</b> — a new mix every game</li><li>Quiz, predict-the-output, bug hunt & fill-the-blank</li><li>5 lives — each mistake costs one</li><li>30 s per challenge (45 s for long code) — faster = more points</li><li>Answer in a row to build a combo multiplier</li><li>Score 60%+ to pass and unlock the next part</li></ul>
        ${ls.topics && ls.topics.length ? `<div class="small muted">Topics in this part:</div><div class="topic-chips">${ls.topics.map((t) => `<span>${esc(t.replace(/-/g, ' '))}</span>`).join('')}</div>` : ''}
        <p class="small muted">Keyboard: number keys <kbd>1</kbd>, <kbd>2</kbd>, <kbd>3</kbd>… pick an answer, <kbd>Enter</kbd> submit / next.</p>
        <a class="btn lg green" style="width:100%" href="#/play/${langId}/${level}">Start game</a></div>
    </div>`;
}

// ───────────────────────── game ─────────────────────────
async function playView(langId, level) {
  view.innerHTML = loading('Preparing your challenges…');
  let s;
  try { s = await api('/api/game/start', { method: 'POST', body: { lang: langId, level: Number(level) } }); }
  catch (e) { view.innerHTML = `<div class="card center" style="max-width:520px;margin:40px auto"><h2>${e.status === 402 ? 'Subscription required' : 'Locked'}</h2><p class="muted">${esc(e.message)}</p><a class="btn" href="#/lang/${langId}">Back to map</a> ${e.status === 402 ? '<a class="btn ghost" href="#/plans">See plans</a>' : ''}</div>`; return; }

  const st = { sid: s.sessionId, lives: s.lives, score: 0, combo: 0, q: null, timer: null, answered: false, busy: false };
  view.innerHTML = `<div style="max-width:820px;margin:0 auto">
    <div class="hud"><a href="#/lang/${langId}" class="btn ghost sm" title="Quit">✕</a>
      <b>${esc(s.language)} · Part ${s.level}: ${esc(s.title)}</b><div class="spacer"></div>
      <span class="hearts" id="hearts"></span><span class="pill" id="prog"></span><span class="pill gold" id="score">Score 0</span><span class="pill fire hidden" id="combo"></span></div>
    <div class="timer" id="timer"><i style="width:100%"></i></div>
    <div class="card" id="qcard">${loading('')}</div></div>`;

  const hud = () => {
    $('#hearts').innerHTML = Array.from({ length: s.lives }, (_, i) => `<span class="${i < st.lives ? '' : 'lost'}">❤️</span>`).join('');
    $('#score').textContent = `Score ${st.score}`;
    const c = $('#combo'); c.classList.toggle('hidden', st.combo < 2); c.textContent = `Combo ×${st.combo}`;
    if (st.q) $('#prog').textContent = `${st.q.index + 1} / ${st.q.total}`;
  };
  const stopTimer = () => { clearInterval(st.timer); st.timer = null; };

  async function loadNext() {
    const r = await api('/api/game/next', { method: 'POST', body: { sessionId: st.sid } });
    if (r.done) return finish();
    st.q = r.question; st.answered = false; hud(); renderQ();
    const end = Date.now() + st.q.remainingMs;
    st.timer = setInterval(() => {
      const left = end - Date.now(); const t = $('#timer'); if (!t) return stopTimer();
      t.firstChild.style.width = `${Math.max(0, (left / st.q.timeLimitMs) * 100)}%`; t.classList.toggle('low', left < 8000);
      const sec = $('#secs'); if (sec) sec.textContent = `${Math.max(0, Math.ceil(left / 1000))}s`;
      if (left <= 0) { stopTimer(); submit(null); }
    }, 100);
  }

  function renderQ() {
    const q = st.q;
    $('#qcard').innerHTML = `<div class="row"><div class="qtype">${QTYPE[q.type]} · ${esc(q.topic.replace(/-/g, ' '))}</div><div class="spacer"></div><span class="muted small" id="secs"></span></div>
      <p class="qprompt">${tick(esc(q.prompt))}</p>${q.code ? codeBlock(q.code, langId) : ''}
      ${q.type === 'fill'
        ? `<form id="ff" class="row" style="margin-top:16px"><input class="input" id="fill" placeholder="Type the missing code…" autocomplete="off" spellcheck="false" style="flex:1;font-family:var(--mono)"><button class="btn">Submit</button></form>`
        : `<div class="options${q.options.some((o) => String(o).includes('\n')) ? ' tall' : ''}">${q.options.map((o, i) => `<button class="opt" data-i="${i}"><span class="key">${i + 1}</span><code>${esc(o)}</code></button>`).join('')}</div>`}
      <div id="fb"></div>`;
    if (q.type === 'fill') { $('#fill').focus(); $('#ff').onsubmit = (e) => { e.preventDefault(); const v = $('#fill').value.trim(); if (v) submit(v); }; }
    else $$('.opt').forEach((b) => (b.onclick = () => submit(Number(b.dataset.i))));
  }

  async function submit(ans) {
    if (st.answered || st.busy) return; st.answered = true; st.busy = true; stopTimer();
    $$('.opt').forEach((b) => (b.disabled = true)); const fi = $('#fill'); if (fi) fi.disabled = true;
    let r;
    try { r = await api('/api/game/answer', { method: 'POST', body: { sessionId: st.sid, answer: ans } }); }
    catch (e) { st.busy = false; toast(e.message, 'bad'); return; }
    st.busy = false; st.lives = r.lives; st.score = r.score; st.combo = r.combo; hud();
    if (st.q.type !== 'fill') {
      $$('.opt').forEach((b) => { const i = Number(b.dataset.i); if (i === r.correctAnswer) b.classList.add('correct'); else if (i === ans) b.classList.add('wrong'); });
    } else if (fi) { fi.style.borderColor = r.correct ? 'var(--ok)' : 'var(--bad)'; }
    beep(r.correct ? 'ok' : 'bad');
    const answerTxt = st.q.type === 'fill' ? r.correctAnswer : st.q.options[r.correctAnswer];
    $('#fb').innerHTML = `<div class="feedback ${r.correct ? 'ok' : 'bad'}">
      <div class="row" style="flex-wrap:wrap"><b style="font-size:1.1rem">${r.correct ? 'Correct!' : r.timedOut ? 'Time\'s up!' : 'Not quite'}</b>
        ${r.correct ? `<span class="points">+${r.points} pts</span>${r.combo >= 2 ? `<span class="combo">combo ×${r.combo}</span>` : ''}` : (String(answerTxt).includes('\n') ? `<span class="muted small" style="flex-basis:100%">Answer:<code class="ans-block">${esc(answerTxt)}</code></span>` : `<span class="muted small">Answer: <code class="ans">${esc(answerTxt)}</code></span>`)}
        <div class="spacer"></div><button class="btn sm" id="nx">${r.done ? 'See results' : 'Next →'}</button></div>
      <p style="margin:10px 0 0">${tick(esc(r.explain))}</p></div>`;
    $('#nx').focus();
    $('#nx').onclick = () => { if (st.busy) return; st.busy = true; (r.done ? finish() : loadNext()).finally(() => (st.busy = false)); };
  }

  async function finish() {
    stopTimer();
    $('#qcard').innerHTML = loading('Your agent is analysing this game…');
    const r = await api('/api/game/finish', { method: 'POST', body: { sessionId: st.sid } });
    ME.stats.xp = r.totalXp; ME.stats.streak = r.streak; ME.rank = r.rank; renderNav();
    renderResult(r, langId);
  }

  const onKey = (e) => {
    if (!st.q) return;
    if (!st.answered && st.q.type !== 'fill' && /^[1-9]$/.test(e.key)) { const i = Number(e.key) - 1; if (i < st.q.options.length) submit(i); }
    else if (e.key === 'Enter' && st.answered && $('#nx') && document.activeElement !== $('#nx')) $('#nx').click();
  };
  document.addEventListener('keydown', onKey);
  teardown = () => { stopTimer(); document.removeEventListener('keydown', onKey); };
  await loadNext();
}

function renderResult(r, langId) {
  const x = r.result; const f = r.agentFeedback;
  if (x.stars === 3) confetti();
  beep(x.passed ? 'win' : 'bad');
  view.innerHTML = `<div style="max-width:760px;margin:0 auto">
    <div class="card center">
      <div class="result-stars">${[0, 1, 2].map((i) => `<span style="color:${i < x.stars ? 'var(--gold)' : 'var(--star-off)'}">★</span>`).join('')}</div>
      <h1>${x.passed ? (x.stars === 3 ? 'Perfect run!' : 'Part cleared!') : r.result.livesLeft === 0 ? 'Out of lives!' : 'So close!'}</h1>
      <p class="muted">${esc(x.languageName)} · Part ${x.level}: ${esc(x.title)}</p>
      <div class="grid g4" style="margin:20px 0">
        ${[['Score', x.score + (x.newBest ? ' ' : '')], ['Accuracy', `${x.accuracy}%`], ['Correct', `${x.correct}/${x.total}`], ['XP earned', `+${r.xpEarned}`], ['Best combo', `${x.maxCombo}`], ['Avg time', `${x.avgTimeSec}s`]].map(([k, v]) => `<div class="stat"><div class="v" style="font-size:1.4rem">${v}</div><div class="k">${k}</div></div>`).join('')}
      </div>
      ${r.rankUp ? `<div class="banner"><b>Rank up!</b> You are now a <b>${esc(r.rank.title)}</b>.</div>` : ''}
      ${r.unlockedNext ? `<div class="banner"><b>Unlocked:</b> Part ${r.unlockedNext.level} — ${esc(r.unlockedNext.title)} </div>` : ''}
      ${!x.passed ? `<div class="banner">You need <b>60%</b> to pass. Re-read the lesson and try again!</div>` : ''}
    </div>
    <div class="card" style="margin-top:16px"><div class="agent-bubble"><div class="agent-face" style="border-color:${f.agent.color}">${esc(f.agent.name[0])}</div>
      <div style="flex:1"><b>${esc(f.agent.name)}</b> <span class="muted small">analysed your game</span>
      <div class="speech" style="margin-top:8px">${esc(f.message)}${f.tips.length ? `<ul style="margin:8px 0 0;padding-left:18px">${f.tips.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>` : ''}</div></div></div></div>
    <div class="row" style="justify-content:center;margin-top:20px">
      <a class="btn ghost" href="#/learn/${langId}/${x.level}">Replay</a>
      ${x.passed && r.hasNext ? `<a class="btn green" href="#/learn/${langId}/${x.level + 1}">Next part →</a>` : ''}
      <a class="btn ghost" href="#/lang/${langId}">Map</a><a class="btn cyan" href="#/agent">Agent report</a></div></div>`;
}

// ───────────────────────── agent report ─────────────────────────
async function agentView() {
  view.innerHTML = loading('Your agent is compiling your report…');
  const r = await api('/api/agent/report'); const o = r.overview; const a = r.agent;
  const trendIcon = { up: 'Improving', down: 'Dipping', steady: 'Steady', new: 'Just started' }[r.trendDirection];
  view.innerHTML = `
    <div class="card"><div class="row" style="gap:20px;align-items:flex-start">
      <div class="agent-face xl" style="border-color:${a.color};box-shadow:0 0 30px ${a.color}44">${esc(a.name[0])}</div>
      <div style="flex:1;min-width:240px"><div class="muted small">YOUR PERSONAL AGENT</div><h1 style="margin:2px 0">${esc(a.name)} <span class="muted" style="font-size:1rem;font-weight:500">· ${esc(a.title)}</span></h1>
        <div class="muted small">Tracking ${esc(ME.fullName)} (${esc(ME.userId)}) since ${new Date(a.assignedAt).toLocaleDateString()}</div>
        <div class="speech" style="margin-top:12px">${esc(r.headline)}</div>
        <a class="btn sm" href="#/chat" style="margin-top:12px">Chat with ${esc(a.name)}</a></div>
      <div class="center" style="min-width:150px"><div class="muted small">Engagement score</div><div style="font-size:2.4rem;font-weight:800">${r.engagement}</div>${bar(r.engagement, a.color)}<div class="muted small" style="margin-top:6px">${trendIcon}</div></div>
    </div></div>

    <div class="grid g4" style="margin-top:16px">
      ${[['XP', o.xp, `${o.rank.title}${o.rank.next ? ` · ${o.rank.next - o.xp} to ${o.rank.nextTitle}` : ''}`], ['Games', o.gamesPlayed, `${o.questionsAnswered} questions answered`], ['Accuracy', o.accuracy + '%', 'across all games'], ['Speed', o.avgTimeSec + 's', o.speedLabel], ['Streak', o.streak.current + (o.streak.current === 1 ? ' day' : ' days'), `best ${o.streak.best}`], ['Parts', `${o.levelsPassed}/${o.totalLevels}`, `${o.activeDays} active day${o.activeDays === 1 ? '' : 's'}`]]
        .map(([k, v, s]) => `<div class="card stat"><div class="k">${k}</div><div class="v">${v}</div><div class="muted small">${esc(s)}</div></div>`).join('')}
    </div>

    <div class="grid g2" style="margin-top:16px;align-items:start">
      <div class="card"><h3>Recommended next steps</h3>
        ${r.recommendations.length ? r.recommendations.map((x) => `<div class="rec"><span class="dot ${x.priority}"></span><div style="flex:1">${esc(x.text)}</div>${x.lang ? `<a class="btn sm" href="#/learn/${x.lang}/${x.level}">Go</a>` : ''}</div>`).join('') : '<p class="muted">Nothing pending — you are crushing it!</p>'}</div>
      <div class="card"><h3>Accuracy trend <span class="muted small">(last ${r.trend.length} games)</span></h3>${trendChart(r.trend, '#c9a13f')}</div>
    </div>

    <div class="card" style="margin-top:16px"><h3>Skill by language</h3>
      <div class="grid g2" style="margin-top:10px">${r.languages.map((l) => `<div>
        <div class="row small"><b>${esc(l.name)}</b><span class="pill ${l.status === 'mastered' ? 'ok' : ''}" style="font-size:.7rem">${l.status.replace('-', ' ')}</span><div class="spacer"></div><span>${l.skill}% skill · ${l.levelsPassed}/${l.totalLevels} parts</span></div>
        ${bar(l.skill, l.color)}
        <div class="row small muted" style="margin-top:6px;gap:6px">${l.levels.map((lv) => `<span title="${esc(lv.title)} — best ${lv.bestAccuracy}%" class="pill" style="font-size:.7rem;${lv.passed ? 'border-color:#22c55e88' : ''}">P${lv.level} ${starsHtml(lv.stars)}</span>`).join('')}</div></div>`).join('')}</div></div>

    <div class="grid g2" style="margin-top:16px;align-items:start">
      <div class="card"><h3>Strong topics</h3>${r.topics.strong.length ? r.topics.strong.map((t) => `<span class="topic-chip s">${esc(t.langName)} · ${esc(t.topic)} <b>${t.pct}%</b></span>`).join('') : '<p class="muted small">Play more games — I need at least 2 answers per topic.</p>'}
        <h3 style="margin-top:18px">Needs practice</h3>${r.topics.weak.length ? r.topics.weak.map((t) => `<span class="topic-chip w">${esc(t.langName)} · ${esc(t.topic)} <b>${t.pct}%</b></span>`).join('') : '<p class="muted small">No weak spots detected yet. </p>'}
        <div class="banner" style="margin:20px 0 0"><b>Plan insight:</b> ${esc(r.planSuggestion.reason)} <a href="#/plans">View plans →</a></div></div>
      <div class="card"><h3>${esc(a.name)}'s notes</h3><div class="timeline" style="margin-top:14px">
        ${r.log.map((e) => `<div class="item ${e.type}"><div class="muted small">${fmtDate(e.at)}</div><div>${esc(e.text)}</div></div>`).join('')}</div></div>
    </div>`;
}
function trendChart(points, color) {
  if (points.length < 2) return `<p class="muted">Play at least 2 games to see your trend line.</p>`;
  const W = 520, H = 190, P = 28; const n = points.length;
  const x = (i) => P + (i * (W - 2 * P)) / (n - 1); const y = (v) => H - P - (v / 100) * (H - 2 * P);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.accuracy).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">
    <defs><linearGradient id="tg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".35"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    ${[0, 60, 100].map((v) => `<line x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}" style="stroke:${v === 60 ? '#f59e0b88' : 'var(--border)'}" stroke-dasharray="${v === 60 ? '4 4' : ''}"/><text x="2" y="${y(v) + 4}" style="fill:var(--muted)" font-size="10">${v}%</text>`).join('')}
    <path d="${d} L${x(n - 1)},${H - P} L${x(0)},${H - P} Z" fill="url(#tg)"/><path d="${d}" fill="none" stroke="${color}" stroke-width="3" stroke-linejoin="round"/>
    ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.accuracy)}" r="4.5" style="fill:var(--panel)" stroke="${color}" stroke-width="2.5"><title>${esc(p.label)}: ${p.accuracy}%</title></circle>`).join('')}
  </svg><div class="muted small">Dashed line = 60% pass mark. Hover points for details.</div>`;
}

// ───────────────────────── subscription ─────────────────────────
async function plansView() {
  view.innerHTML = loading();
  const r = await api('/api/plans'); const a = r.access;
  ME.access = a; renderNav();
  const sugg = r.plans.find((p) => p.id === r.suggestion.plan);
  view.innerHTML = `<div class="center" style="margin-bottom:14px"><h1>Subscription</h1><p class="muted">One subscription unlocks every language, every part and every game.</p></div>
    ${accessBanner(a, true)}
    <div class="banner"><b>${esc(ME.agent.name)} recommends the ${esc(sugg.name)} plan</b> — ${esc(r.suggestion.reason)}</div>
    ${r.paymentMode === 'demo' ? `<div class="banner small"><b>Demo payment mode:</b> no real money is charged. Add Razorpay keys on the server to accept real payments (UPI, cards, net-banking).</div>` : ''}
    <div class="grid g3" id="plans-grid" style="margin-top:26px">${r.plans.map((p) => `<div class="card plan ${p.id === sugg.id ? 'hl' : ''}">
      ${p.id === sugg.id ? `<span class="ribbon">Recommended for you</span>` : p.badge ? `<span class="ribbon alt">${esc(p.badge)}</span>` : ''}
      <h3>${esc(p.name)}</h3><div class="price">₹${p.price.toLocaleString('en-IN')}<span class="muted" style="font-size:1rem">/${p.period}</span></div>
      <div class="muted small">${p.months > 1 ? `≈ ₹${Math.round(p.price / p.months)}/month` : 'Billed monthly'}</div>
      <ul>${p.features.map((f) => `<li>${esc(f)}</li>`).join('')}</ul>
      <button type="button" class="btn ${p.id === sugg.id ? '' : 'ghost'}" data-plan="${p.id}">${a.status === 'active' ? (a.plan === p.id ? 'Extend plan' : 'Switch & extend') : 'Subscribe'}</button></div>`).join('')}</div>
    ${r.history.length ? `<div class="card" style="margin-top:26px;overflow-x:auto"><h3>Payment history</h3><table><thead><tr><th>Date</th><th>Plan</th><th>Amount</th><th>Payment ID</th></tr></thead>
      <tbody>${r.history.map((h) => `<tr><td>${fmtDay(h.paidAt)}</td><td>${esc(r.plans.find((p) => p.id === h.plan)?.name || h.plan)}</td><td>₹${h.amount}</td><td class="small" style="font-family:var(--mono)">${esc(h.paymentId)}</td></tr>`).join('')}</tbody></table></div>` : ''}
    <p class="center muted small" style="margin-top:22px">Your progress, XP and agent history are always kept — even if your access lapses.</p>`;
  $$('[data-plan]').forEach((b) => (b.onclick = () => checkout(b.dataset.plan, b)));
  const cta = $('.lockcard a'); if (cta) cta.onclick = (e) => { e.preventDefault(); $('#plans-grid').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
}

function loadScript(src) { return new Promise((res, rej) => { if (document.querySelector(`script[src="${src}"]`)) return res(); const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('Could not load the payment window. Check your connection.')); document.head.appendChild(s); }); }

async function checkout(planId, btn) {
  const label = btn.textContent; btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Please wait…';
  const reset = () => { btn.disabled = false; btn.textContent = label; };
  let o;
  try { o = await api('/api/billing/order', { method: 'POST', body: { plan: planId } }); } catch (e) { toast(e.message, 'bad'); return reset(); }
  if (o.mode === 'razorpay') {
    try {
      await loadScript('https://checkout.razorpay.com/v1/checkout.js');
      new window.Razorpay({ key: o.keyId, amount: o.amount, currency: o.currency, order_id: o.orderId, name: 'Syntaxo', description: `${o.plan.name} subscription`,
        prefill: o.prefill, theme: { color: '#7c5cff' },
        handler: (resp) => completePayment({ orderId: resp.razorpay_order_id, paymentId: resp.razorpay_payment_id, signature: resp.razorpay_signature }),
        modal: { ondismiss: () => { toast('Payment cancelled.'); reset(); } } }).open();
    } catch (e) { toast(e.message, 'bad'); reset(); }
    return;
  }
  // Demo checkout
  reset();
  const m = modal(`<div class="row"><h2 style="margin:0">Checkout</h2><div class="spacer"></div><span class="pill small">Demo</span></div>
    <div class="banner" style="margin:14px 0"><div class="row"><b>${esc(o.plan.name)} plan</b><div class="spacer"></div><b style="font-size:1.3rem">₹${o.plan.price}</b></div>
      <div class="muted small">${o.plan.months} month${o.plan.months > 1 ? 's' : ''} of full access · ${esc(o.prefill.email)}</div></div>
    <div class="tabs"><button type="button" class="tab on" data-t="upi">UPI</button><button type="button" class="tab" data-t="card">Card</button></div>
    <div id="pay-upi"><div class="field"><label>UPI ID</label><input class="input" value="success@upi" id="upi"></div></div>
    <div id="pay-card" class="hidden"><div class="field"><label>Card number</label><input class="input" value="4111 1111 1111 1111"></div>
      <div class="row"><div class="field" style="flex:1"><label>Expiry</label><input class="input" value="12/30"></div><div class="field" style="flex:1"><label>CVV</label><input class="input" value="123"></div></div></div>
    <p class="muted small">This is a simulated payment — nothing is charged.</p>
    <div class="row"><button type="button" class="btn ghost" id="cancel">Cancel</button><div class="spacer"></div><button type="button" class="btn green lg" id="pay">Pay ₹${o.plan.price}</button></div>`);
  $$('.tab', m.el).forEach((t) => (t.onclick = () => { $$('.tab', m.el).forEach((x) => x.classList.toggle('on', x === t)); $('#pay-upi', m.el).classList.toggle('hidden', t.dataset.t !== 'upi'); $('#pay-card', m.el).classList.toggle('hidden', t.dataset.t !== 'card'); }));
  $('#cancel', m.el).onclick = () => { m.close(); toast('Payment cancelled.'); };
  $('#pay', m.el).onclick = async (e) => {
    e.target.disabled = true; e.target.innerHTML = '<span class="spin sm"></span> Processing…';
    await new Promise((r) => setTimeout(r, 1200));
    m.close(); completePayment({ orderId: o.orderId });
  };
}

async function completePayment(payload) {
  const m = modal(loading('Confirming your payment…'));
  try {
    const r = await api('/api/billing/verify', { method: 'POST', body: payload });
    await loadMe(); renderNav(); m.close(); confetti(); beep('win');
    const done = modal(`<div class="center"><div style="font-size:3rem"></div><h2>You're subscribed!</h2>
      <p class="muted">Your <b>${esc(r.access.planName)}</b> plan is active until <b>${fmtDay(r.access.expiresAt)}</b>.<br>A receipt has been sent to your email.</p>
      <p class="small muted">Payment ID: <code>${esc(r.paymentId)}</code></p>
      <button type="button" class="btn lg green" style="width:100%" id="go">Start learning</button></div>`);
    $('#go', done.el).onclick = () => { done.close(); location.hash = '#/dashboard'; };
  } catch (e) { m.close(); toast(e.message, 'bad'); }
}

// ───────────────────────── forgot user id / password ─────────────────────────
async function forgotView() {
  let email = '', resendTimer = null;
  const shell = (step, inner) => `<div class="auth"><div class="card">
    <div class="steps">${[1, 2, 3].map((i) => `<span class="${i <= step ? 'on' : ''}"></span>`).join('')}</div>${inner}
    <p class="center muted small" style="margin-top:16px"><a href="#/login">← Back to login</a></p></div></div>`;
  const devBox = (d) => (d ? `<div class="devmail"><div class="muted small"><b>Demo inbox</b> — email service isn't configured yet, so here is the email that would be sent:</div>
      <div class="small" style="margin-top:6px"><b>To:</b> ${esc(d.to)}<br><b>Subject:</b> ${esc(d.subject)}</div><pre>${esc(d.text)}</pre></div>` : '');
  teardown = () => clearInterval(resendTimer);

  function step1(prefill = '') {
    view.innerHTML = shell(1, `<h2>Forgot username or password?</h2>
      <p class="muted small">Enter the email you registered with. We'll email you your <b>username</b> and a code to reset your password.</p>
      <form id="f" novalidate><div class="field"><label for="fg-email">Registered email</label><input class="input" id="fg-email" name="email" type="email" value="${esc(prefill)}" placeholder="e.g. rahul@gmail.com" autocomplete="email" autocapitalize="off"></div>
      <div class="form-error error hidden" role="alert"></div><button type="submit" class="btn lg" style="width:100%" id="sub">Send recovery email</button></form>`);
    const form = $('#f'), btn = $('#sub'); $('#fg-email').focus();
    form.addEventListener('input', () => { showFormError(form, ''); setFieldError(form, 'email', ''); });
    bindSubmit(form, btn, async () => {
      const v = $('#fg-email').value.trim(); const bad = RULES.email(v);
      if (bad) { setFieldError(form, 'email', bad); focusFirstInvalid(form); return; }
      btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Sending…';
      try { const r = await api('/api/auth/forgot', { method: 'POST', body: { email: v } }); email = v; step2(r); }
      catch (e) { if (e.field) setFieldError(form, e.field, e.message); else showFormError(form, e.message); btn.disabled = false; btn.textContent = 'Send recovery email'; }
    });
  }

  function step2(info) {
    view.innerHTML = shell(2, `<h2>Check your email</h2>
      <p class="muted small">We sent your <b>username</b> and a 6-digit code to <b>${esc(info.sentTo)}</b>. The code expires in ${info.expiresInMin} minutes.</p>
      ${devBox(info.devPreview)}
      <form id="f" novalidate><div class="field"><label for="fg-code">Verification code</label><input class="input code-input" id="fg-code" name="code" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="one-time-code"></div>
      <div class="form-error error hidden" role="alert"></div><button type="submit" class="btn lg" style="width:100%" id="sub">Verify code</button></form>
      <div class="row small" style="margin-top:12px"><a href="javascript:void 0" id="chg">Use a different email</a><div class="spacer"></div><button type="button" class="btn ghost sm" id="resend" disabled></button></div>`);
    const form = $('#f'), btn = $('#sub'), rs = $('#resend'); $('#fg-code').focus();
    let left = info.resendIn; const tick = () => { rs.disabled = left > 0; rs.textContent = left > 0 ? `Resend in ${left}s` : 'Resend code'; left--; if (left < -1) clearInterval(resendTimer); };
    clearInterval(resendTimer); tick(); resendTimer = setInterval(tick, 1000);
    rs.onclick = async () => { rs.disabled = true; try { const r = await api('/api/auth/forgot', { method: 'POST', body: { email } }); toast('A new code has been sent.', 'ok'); step2(r); } catch (e) { toast(e.message, 'bad'); rs.disabled = false; } };
    $('#chg').onclick = () => { clearInterval(resendTimer); step1(email); };
    $('#fg-code').addEventListener('input', (e) => { e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6); showFormError(form, ''); setFieldError(form, 'code', ''); });
    bindSubmit(form, btn, async () => {
      const code = $('#fg-code').value.trim();
      if (code.length !== 6) { setFieldError(form, 'code', 'Enter the 6-digit code from the email.'); focusFirstInvalid(form); return; }
      btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Verifying…';
      try { const r = await api('/api/auth/verify-code', { method: 'POST', body: { email, code } }); clearInterval(resendTimer); step3(r); }
      catch (e) { if (e.field) setFieldError(form, e.field, e.message); else showFormError(form, e.message); btn.disabled = false; btn.textContent = 'Verify code'; }
    });
  }

  function step3(r) {
    SS.set('cq_prefill', r.username);
    view.innerHTML = shell(3, `<h2>Email verified</h2><p class="muted small">Hi ${esc(r.fullName)}, here is your username:</p>
      <div class="userid">${esc(r.username)}</div>
      <p class="center muted small" style="margin:-6px 0 10px">User ID ${esc(r.userId)}</p>
      <div class="row" style="justify-content:center;margin-bottom:18px"><button type="button" class="btn ghost sm" id="cp">Copy username</button>
        <a class="btn green sm" href="#/login" id="login-now">I remember my password → Log in</a></div>
      <h3 style="margin-top:6px">Set a new password <span class="muted small">(optional)</span></h3>
      <form id="f" novalidate>
        <div class="field"><label for="np">New password</label><div class="pw-wrap"><input class="input" id="np" type="password" name="password" placeholder="At least 6 characters" autocomplete="new-password"><button type="button" data-pw>Show</button></div></div>
        <div class="field"><label for="nc">Confirm new password</label><input class="input" id="nc" type="password" name="confirm" autocomplete="new-password"></div>
        <div class="form-error error hidden" role="alert"></div>
        <button type="submit" class="btn lg" style="width:100%" id="sub">Reset password & go to login</button></form>`);
    pwToggle();
    $('#cp').onclick = async () => { try { await navigator.clipboard.writeText(r.username); toast('Username copied!', 'ok'); } catch { toast(`Your username is ${r.username}`); } };
    const form = $('#f'), btn = $('#sub');
    form.addEventListener('input', () => showFormError(form, ''));
    bindSubmit(form, btn, async () => {
      const pw = $('#np').value, cf = $('#nc').value;
      setFieldError(form, 'password', RULES.password(pw)); setFieldError(form, 'confirm', pw === cf ? '' : 'Passwords do not match.');
      if (RULES.password(pw) || pw !== cf) { focusFirstInvalid(form); return; }
      btn.disabled = true; btn.innerHTML = '<span class="spin sm"></span> Saving…';
      try { await api('/api/auth/reset-password', { method: 'POST', body: { resetToken: r.resetToken, password: pw } }); toast('Password updated! Log in with your username and new password.', 'ok'); location.hash = '#/login'; }
      catch (e) { if (e.field) setFieldError(form, e.field, e.message); else showFormError(form, e.message); btn.disabled = false; btn.textContent = 'Reset password & go to login'; }
    });
  }
  step1();
}

// ───────────────────────── chat with your agent ─────────────────────────
/** Tiny, safe Markdown renderer for agent replies (escapes everything first). */
function mdInline(t) {
  const codes = [];   // protect inline code so * and _ inside it are never treated as formatting
  return esc(t)
    .replace(/`([^`\n]+)`/g, (m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; })
    .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[\s(])\*([^*\s][^*\n]*?)\*(?=[\s).,!?:;]|$)/g, '$1<i>$2</i>')
    .replace(/(^|[\s(])_([^_\s][^_\n]*?)_(?=[\s).,!?:;]|$)/g, '$1<i>$2</i>')
    .replace(/\u0000(\d+)\u0000/g, (m, k) => `<code>${codes[+k]}</code>`);
}
function chatCode(lang, code) {
  return `<div class="chat-code"><div class="cc-head"><span>${esc(lang || 'output')}</span><button type="button" class="cc-copy">Copy</button></div><pre><code>${esc(code)}</code></pre></div>`;
}
function md(text) {
  const out = []; const parts = String(text || '').split(/```([a-z+#]*)\n?([\s\S]*?)```/i);
  for (let i = 0; i < parts.length; i += 3) {
    const lines = parts[i].split('\n'); let list = null, table = null, para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${para.map(mdInline).join('<br>')}</p>`); para = []; } };
    const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((x) => `<li>${mdInline(x)}</li>`).join('')}</${list.tag}>`); list = null; } };
    const flushTable = () => { if (table) { const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r)).map((r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
      out.push(`<div class="chat-table"><table>${rows.map((r, ri) => `<tr>${r.map((c) => (ri === 0 ? `<th>${mdInline(c)}</th>` : `<td>${mdInline(c)}</td>`)).join('')}</tr>`).join('')}</table></div>`); table = null; } };
    for (const ln of lines) {
      const t = ln.trim();
      if (/^\|.*\|$/.test(t)) { flushPara(); flushList(); (table ||= []).push(t); continue; } else flushTable();
      let m;
      if ((m = t.match(/^#{1,4}\s+(.*)/))) { flushPara(); flushList(); out.push(`<h4>${mdInline(m[1])}</h4>`); }
      else if ((m = t.match(/^[-*•]\s+(.*)/))) { flushPara(); if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; } list.items.push(m[1]); }
      else if ((m = t.match(/^\d+[.)]\s+(.*)/))) { flushPara(); if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; } list.items.push(m[1]); }
      else if (t === '---') { flushPara(); flushList(); out.push('<hr>'); }
      else if (!t) { flushPara(); flushList(); }
      else { flushList(); para.push(t); }
    }
    flushPara(); flushList(); flushTable();
    if (i + 2 < parts.length) out.push(chatCode(parts[i + 1], parts[i + 2].replace(/\n$/, '')));
  }
  return out.join('');
}

async function chatView() {
  view.innerHTML = loading(`Opening your chat with ${ME.agent.name}…`);
  const d = await api('/api/agent/chat');
  const a = d.agent;
  view.innerHTML = `<div class="chat-wrap card">
    <div class="chat-head">
      <div class="agent-face" style="border-color:${a.color}">${esc(a.name[0])}</div>
      <div style="flex:1;min-width:0"><b>${esc(a.name)}</b> <span class="muted small">· ${esc(a.title)}</span>
        <div class="muted small">Your personal coding agent · ask about Python, JavaScript, Java, C++ and SQL</div></div>
      <span class="pill" title="${d.mode === 'ai' ? `AI model: ${esc(d.provider)} ${esc(d.model)}` : 'Answers from the Syntaxo knowledge base, lessons and question bank'}">${d.mode === 'ai' ? 'AI tutor' : 'Built-in tutor'}</span>
      <button type="button" class="btn ghost sm" id="clr">Clear chat</button>
    </div>
    <div class="chat-log" id="log" aria-live="polite"></div>
    <div class="chat-sugg" id="sugg"></div>
    <form class="chat-input" id="cf"><textarea id="msg" rows="1" maxlength="4000" placeholder="${innerWidth < 600 ? `Ask ${esc(a.name)} about coding…` : `Ask ${esc(a.name)} anything about coding… (Shift+Enter for a new line)`}" title="Enter sends · Shift+Enter adds a new line"></textarea><button class="btn" id="send" type="submit">Send</button></form>
  </div>`;
  const log = $('#log'), msg = $('#msg'), sendBtn = $('#send');
  let busy = false;
  const scroll = () => { log.scrollTop = log.scrollHeight; };
  const face = `<div class="agent-face sm" style="border-color:${a.color}">${esc(a.name[0])}</div>`;
  function renderMsg(m) {
    const el = document.createElement('div');
    if (m.role === 'user') { el.className = 'cmsg me'; el.innerHTML = `<div class="bubble">${esc(m.text).replace(/\n/g, '<br>')}</div>`; }
    else {
      el.className = 'cmsg bot';
      let html = md(m.text);
      if (m.quiz) {
        const q = m.quiz;
        html += `<div class="chat-quiz"><div class="cq-prompt">${mdInline(q.prompt)}</div>${q.code ? chatCode(q.codeLang, q.code) : ''}
          <div class="cq-opts">${q.options.map((o, i) => `<button type="button" class="cq-opt" data-send="${q.letters[i]}"><span class="key">${q.letters[i]}</span><span class="cq-text">${esc(o)}</span></button>`).join('')}</div></div>`;
      }
      if (m.actions?.length) html += `<div class="chat-actions">${m.actions.map((x) => (x.href ? `<a class="chip-btn" href="${esc(x.href)}">${esc(x.label)} →</a>` : `<button type="button" class="chip-btn" data-send="${esc(x.send)}">${esc(x.label)}</button>`)).join('')}</div>`;
      el.innerHTML = `${face}<div class="bubble">${html}</div>`;
    }
    log.appendChild(el); return el;
  }
  function renderSugg(list) { $('#sugg').innerHTML = (list || []).map((x) => `<button type="button" class="chip-btn" data-send="${esc(x)}">${esc(x)}</button>`).join(''); }
  function welcome() {
    renderMsg({ role: 'agent', text: `Hi ${ME.fullName}! I'm **${a.name}**, your personal coding agent. Ask me anything about the subjects you're learning here — concepts, methods, differences, pattern programs, error messages or your code. I can also quiz you and tell you how you're doing.` });
  }
  (d.history || []).forEach(renderMsg);
  if (!d.history?.length) welcome();
  renderSugg(d.history?.length ? d.suggestions.slice(0, 4) : d.suggestions);
  scroll();

  async function send(text) {
    text = String(text || '').trim(); if (!text || busy) return;
    busy = true; sendBtn.disabled = true; msg.value = ''; autosize();
    renderMsg({ role: 'user', text }); $('#sugg').innerHTML = '';
    const typing = document.createElement('div'); typing.className = 'cmsg bot'; typing.innerHTML = `${face}<div class="bubble typing"><i></i><i></i><i></i></div>`; log.appendChild(typing); scroll();
    try {
      const r = await api('/api/agent/chat', { method: 'POST', body: { message: text }, timeout: 60000 });
      typing.remove(); const el = renderMsg(r.reply);
      log.scrollTop = el.offsetTop - 12;
    } catch (e) {
      typing.remove(); renderMsg({ role: 'agent', text: `Sorry — ${e.message}` }); scroll();
      if (e.status !== 402) msg.value = text;
    } finally { busy = false; sendBtn.disabled = false; msg.focus(); }
  }
  function autosize() { msg.style.height = 'auto'; msg.style.height = Math.min(180, msg.scrollHeight) + 'px'; }
  msg.addEventListener('input', autosize);
  msg.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(msg.value); } });
  $('#cf').onsubmit = (e) => { e.preventDefault(); send(msg.value); };
  view.addEventListener('click', async (e) => {
    const cp = e.target.closest('.cc-copy');
    if (cp) { const code = cp.closest('.chat-code').querySelector('code').textContent; try { await navigator.clipboard.writeText(code); cp.textContent = 'Copied'; } catch { cp.textContent = 'Select & copy'; } setTimeout(() => (cp.textContent = 'Copy'), 1500); return; }
    const b = e.target.closest('[data-send]'); if (!b || busy) return;
    if (b.classList.contains('cq-opt')) { b.closest('.cq-opts').querySelectorAll('.cq-opt').forEach((x) => { x.disabled = true; }); b.classList.add('picked'); }
    send(b.dataset.send);
  });
  $('#clr').onclick = async () => {
    if (!confirm('Clear your whole chat history with ' + a.name + '?')) return;
    try { await api('/api/agent/chat/clear', { method: 'POST' }); log.innerHTML = ''; welcome(); renderSugg(d.suggestions); } catch (e) { toast(e.message, 'bad'); }
  };
  msg.focus();
}

// ───────────────────────── leaderboard ─────────────────────────
async function leaderboardView() {
  view.innerHTML = loading();
  const r = await api('/api/leaderboard');
  const medal = (p) => p;
  view.innerHTML = `<h1>Leaderboard</h1><p class="muted">You are #${r.myPos} of ${r.total} coders.</p>
    <div class="card" style="overflow-x:auto"><table><thead><tr><th>#</th><th>Coder</th><th>Rank</th><th>XP</th><th>Games</th><th>Best streak</th></tr></thead>
    <tbody>${r.top.map((u) => `<tr class="${u.me ? 'me' : ''}"><td style="font-size:1.2rem">${medal(u.pos)}</td><td><b>${esc(u.username)}</b>${u.me ? ' <span class="pill" style="font-size:.7rem">you</span>' : ''}</td><td>${esc(u.rank)}</td><td class="points">${u.xp}</td><td>${u.games}</td><td>${u.streak}</td></tr>`).join('')}</tbody></table></div>`;
}

// Never fail silently: surface unexpected errors to the user
addEventListener('error', (e) => toast('Something went wrong: ' + (e.message || 'unknown error'), 'bad'));
addEventListener('unhandledrejection', (e) => toast(e.reason?.message || 'Something went wrong. Please try again.', 'bad'));

router();
