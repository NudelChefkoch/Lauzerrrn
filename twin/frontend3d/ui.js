// In-game UI: screens (Loading → Title → Creator → Play → Life summary → Financial facts), HUD, toasts, popups.
// Talks to the 3D engine via its public API (CONTRACT.md) and to Python via the `send` callback from main.js.
import { showCreator, setCreator, showWorld } from './engine.js';
import { OPTIONS, CAT_LABEL, NICE, DEFAULT_CFG, SKINS, HAIRC, COLORS } from './core.js';
import { createChat, chatTwinCount } from './chat.js';
import { createDashboard } from './dashboard.js';

/* =================================================================== helpers */
const RARITY = { COMMON: '#8e9ab3', UNCOMMON: '#2fbf68', RARE: '#2f86ff', EPIC: '#a24bff', LEGENDARY: '#ff9d14' };
const TIPS = [
  'Starting early pays off: compound interest loves patience.',
  'A rainy-day fund of 3–6 months of spending protects you from expensive loans.',
  'Consumer loans and credit cards easily cost 10 % interest or more.',
  'Broad ETFs spread the risk over hundreds of companies.',
  'Pillar 3a: save taxes and build your retirement at the same time.',
  'A higher salary does not have to mean higher spending – watch out for lifestyle inflation.',
  'If you know your spending, you can steer it: a budget works wonders.',
  'Ups and downs are part of investing – staying in for the long run often wins.',
  'Pay off high-interest debt first, then invest.',
  'Small amounts, saved regularly, grow large over the years.',
];
const WAIT_TXT = ['Life is rolling the dice', 'Simulating the future', 'Running a thousand lives', 'Chance is shuffling the cards'];

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v, d = 0) => (v === null || v === undefined || v === '' || !Number.isFinite(+v)) ? d : +v;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const grp = n => String(Math.round(Math.abs(num(n)))).replace(/\B(?=(\d{3})+(?!\d))/g, "'");
export const chf = v => (num(v) < -0.5 ? 'CHF −' : 'CHF ') + grp(v);
const chfSigned = v => (num(v) < -0.5 ? '−' : '+') + 'CHF ' + grp(v);
function kfmt(v) {
  const n = num(v), a = Math.abs(n), s = n < -0.5 ? '−' : '';
  if (a >= 1e6) return s + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M';
  if (a >= 1e4) return s + Math.round(a / 1e3) + 'k';
  return s + grp(a);
}
const chfShort = v => 'CHF ' + kfmt(v);
const chfShortSigned = v => (num(v) < -0.5 ? '−' : '+') + 'CHF ' + kfmt(Math.abs(num(v)));
const signed = v => (num(v) > 0 ? '+' : num(v) < 0 ? '−' : '±') + Math.abs(Math.round(num(v)));
const safeColor = (c, d = '#2f7bff') => (typeof c === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : d;
const nice = v => { const s = NICE[v] || String(v ?? ''); return s.charAt(0).toUpperCase() + s.slice(1); };
const arr = v => Array.isArray(v) ? v : [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
function rarityOf(r, xp) {
  const k = String(r || '').toUpperCase(); if (RARITY[k]) return k;
  const x = num(xp); return x <= 50 ? 'COMMON' : x <= 90 ? 'UNCOMMON' : x <= 140 ? 'RARE' : x < 200 ? 'EPIC' : 'LEGENDARY';
}
function profileEmoji(status, i) {
  const s = String(status || '').toLowerCase();
  if (/apprentice|lehre|ausbildung/.test(s)) return '🧰';
  if (/educat|stud|uni|hochschule/.test(s)) return '📚';
  if (/school|schul|gymi|gymnas/.test(s)) return '🎒';
  if (/self|selbst|gründ/.test(s)) return '🚀';
  if (/no job|unemploy|arbeitslos|such/.test(s)) return '🔎';
  if (/part|teilzeit/.test(s)) return '⏳';
  if (/employ|angestellt|job|beruf|arbeit/.test(s)) return '💼';
  return ['🙂', '😎', '🤓', '😄', '🥳', '😌'][i % 6];
}
const SWATCH = { skin: SKINS, hairColor: HAIRC, color: COLORS, car: COLORS };
const CATS = Object.keys(OPTIONS);

/* =================================================================== fan chart (canvas) */
function niceTicks(lo, hi, count = 4) {
  const raw = (hi - lo) / count, mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
  const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 5 ? 5 : 10) * mag, out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
  return out;
}
export function drawFan(cv, fan, opt = {}) {
  if (!cv) return;
  cv._fan = fan; cv._opt = opt;
  const W = cv.clientWidth, H = cv.clientHeight; if (!W || !H) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const small = !!opt.small;
  g.font = `800 ${small ? 10 : 12}px Nunito, system-ui, sans-serif`; g.textBaseline = 'middle';
  const msg = t => { g.fillStyle = '#6b6394'; g.textAlign = 'center'; g.fillText(t, W / 2, H / 2); };
  const ages = fan && Array.isArray(fan.ages) ? fan.ages : []; const n = ages.length;
  if (n < 2) return msg('No data yet');
  const A = k => { const a = arr(fan[k]); return Array.from({ length: n }, (_, i) => (a[i] === null || a[i] === undefined || !Number.isFinite(+a[i])) ? null : +a[i]); };
  const past = A('past'), p5 = A('p5'), p50 = A('p50'), p95 = A('p95'), lazy = opt.lazy ? A('lazy') : null;
  let lastPast = 0; past.forEach((v, i) => { if (v !== null) lastPast = i; });
  const ni = clamp(Number.isFinite(+fan.now_index) && fan.now_index !== null ? Math.round(+fan.now_index) : lastPast, 0, n - 1);
  const bf = ni >= n - 1 ? 0 : ni;
  const vals = [];
  past.forEach((v, i) => { if (v !== null && i <= ni) vals.push(v); });
  for (let i = bf; i < n; i++) for (const v of [p5[i], p50[i], p95[i]]) if (v !== null) vals.push(v);
  if (lazy) lazy.forEach(v => { if (v !== null) vals.push(v); });
  if (!vals.length) return msg('No data yet');
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals); if (hi - lo < 1) hi = lo + 1;
  const pad = (hi - lo) * .07; if (lo < 0) lo -= pad; hi += pad;
  const L = small ? 40 : 60, R = 10, T = 8, B = small ? 18 : 24;
  const X = i => L + (W - L - R) * i / (n - 1), Y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  // grid + y labels
  g.textAlign = 'right';
  for (const t of niceTicks(lo, hi, small ? 3 : 4)) {
    const y = Y(t); if (y < T - 1 || y > H - B + 1) continue;
    g.strokeStyle = t === 0 ? 'rgba(29,20,70,.45)' : '#ebe6fb'; g.lineWidth = t === 0 ? 2 : 1; g.setLineDash([]);
    g.beginPath(); g.moveTo(L, y); g.lineTo(W - R, y); g.stroke();
    g.fillStyle = '#6b6394'; g.fillText(kfmt(t), L - 6, y);
  }
  // x labels
  g.textAlign = 'center'; g.fillStyle = '#6b6394';
  const xl = new Set([0, n - 1]); if (ni > 0 && ni < n - 1) xl.add(ni);
  if (!small) for (let i = 0; i < n; i += Math.max(1, Math.round(n / 6))) xl.add(i);
  const used = [];
  for (const i of [...xl].sort((a, b) => a - b)) {
    const x = X(i); if (used.some(u => Math.abs(u - x) < (small ? 30 : 34))) continue; used.push(x);
    g.fillText(`${num(ages[i])} y`, clamp(x, L + 10, W - R - 12), H - B / 2 + 2);
  }
  const line = (a, from, to, color, width, dash = [], outline = 0) => {
    const pts = []; for (let i = from; i <= to; i++) if (a[i] !== null) pts.push([X(i), Y(a[i])]);
    if (pts.length < 2) return pts;
    g.lineJoin = 'round'; g.lineCap = 'round';
    const stroke = (c, w) => { g.strokeStyle = c; g.lineWidth = w; g.setLineDash(dash); g.beginPath(); pts.forEach(([x, y], k) => k ? g.lineTo(x, y) : g.moveTo(x, y)); g.stroke(); };
    if (outline) stroke('#1d1446', width + outline); stroke(color, width); g.setLineDash([]); return pts;
  };
  // band p5–p95
  g.beginPath(); let started = false;
  for (let i = bf; i < n; i++) if (p95[i] !== null) { const x = X(i), y = Y(p95[i]); started ? g.lineTo(x, y) : g.moveTo(x, y); started = true; }
  for (let i = n - 1; i >= bf; i--) if (p5[i] !== null) g.lineTo(X(i), Y(p5[i]));
  if (started) { g.closePath(); g.fillStyle = 'rgba(47,123,255,.22)'; g.fill(); }
  if (lazy) line(lazy, 0, n - 1, '#9a94b8', small ? 2 : 3);
  line(p50, bf, n - 1, '#2f7bff', small ? 2 : 2.6, [6, 5]);
  const pp = line(past, 0, ni, '#ff3d8b', small ? 3 : 4, [], 3);
  const last = pp[pp.length - 1] || (past[ni] !== null ? [X(ni), Y(past[ni])] : null);
  if (last) { g.fillStyle = '#ff3d8b'; g.strokeStyle = '#1d1446'; g.lineWidth = 3; g.beginPath(); g.arc(last[0], last[1], small ? 4.5 : 6, 0, Math.PI * 2); g.fill(); g.stroke(); }
}
const fanRO = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(es => es.forEach(e => { const c = e.target; if (c._fan) drawFan(c, c._fan, c._opt); })) : null;

function gaugeSvg(pct) {
  const p = clamp(num(pct), 0, 100), a = Math.PI * (1 - p / 100);
  const nx = (100 + 64 * Math.cos(a)).toFixed(1), ny = (100 - 64 * Math.sin(a)).toFixed(1);
  const arc = 'M16 100 A84 84 0 0 1 184 100';
  return `<svg viewBox="0 0 200 112" aria-hidden="true"><defs><linearGradient id="ggrad" x1="0" x2="1" y1="0" y2="0">
    <stop offset="0" stop-color="#ff5a7a"/><stop offset=".5" stop-color="#ffd23f"/><stop offset="1" stop-color="#2fd27a"/></linearGradient></defs>
    <path d="${arc}" fill="none" stroke="#1d1446" stroke-width="28" stroke-linecap="round"/>
    <path d="${arc}" fill="none" stroke="#ece8ff" stroke-width="19" stroke-linecap="round"/>
    <path d="${arc}" fill="none" stroke="url(#ggrad)" stroke-width="19" stroke-linecap="round" pathLength="100" stroke-dasharray="${p} 100"/>
    <line x1="100" y1="100" x2="${nx}" y2="${ny}" stroke="#1d1446" stroke-width="8" stroke-linecap="round"/>
    <circle cx="100" cy="100" r="11" fill="#1d1446"/><circle cx="100" cy="100" r="5" fill="#ffd23f"/></svg>`;
}

/* =================================================================== UI */
export function createUI(root, { send, engineOk = true, standalone = false } = {}) {
  const stage = document.getElementById('stage');
  const st = {
    screen: null, P: null, sig: null, loaded: false, cfg: { ...DEFAULT_CFG }, touched: false, cat: 'gender',
    pid: null, risk: null, selCat: null, trayOpen: true, sideOpen: window.innerWidth >= 1150,
    busy: false, busySince: 0, waiting: false, waitSeq: -1, waitPhase: null, waitTimer: 0,
    enginePhase: null, celebrated: new Set(), celPending: null,
    sideTab: 'info', waitKind: null, chatPending: null, chatSeen: 0, dashClosing: false, followUp: null,
  };
  const E = (fn, ...a) => { if (!engineOk) return; try { return fn(...a); } catch (e) { console.warn('[game] engine call failed', e); } };

  /* ---------------------------------------------------------------- DOM */
  root.innerHTML = `
  <section class="screen scr-loading" data-s="loading">
    <div class="floaters" aria-hidden="true">
      <span style="left:9%;top:16%">💰</span><span style="left:84%;top:20%;animation-delay:-1.4s">🏡</span>
      <span style="left:13%;top:72%;animation-delay:-2.6s">🎓</span><span style="left:80%;top:70%;animation-delay:-.7s">🪙</span>
      <span style="left:50%;top:86%;animation-delay:-3.3s">🚗</span>
    </div>
    <div class="load-wrap">
      <h1 class="logo logo-xl"><span class="l1">YOUR LIFE ·</span><span class="l2">YOUR CHOICE</span></h1>
      <div class="loadbar"><i></i></div>
      <div class="load-pct ol">0 %</div>
      <p class="tip"><b>TIP</b> <span></span></p>
    </div>
  </section>

  <section class="screen scr-title" data-s="title">
    <h1 class="logo logo-md"><span class="l1">YOUR LIFE ·</span><span class="l2">YOUR CHOICE</span></h1>
    <p class="tagline ol">Make choices. Live the consequences.</p>
    <div class="title-btns pe">
      <button class="btn btn-xl btn-green" data-act="toCreator">PLAY</button>
      <button class="btn btn-lg btn-blue" data-act="analyse" data-wlock>ANALYSIS</button>
    </div>
    <div class="hint">Drag the figure to turn it · Enter to play</div>
  </section>

  <section class="screen scr-creator" data-s="creator">
    <div class="cr-left">
      <div class="cr-top pe"><button class="btn-round sm blue" data-act="toTitle" title="Back">◀</button><h2 class="hdr ol">YOUR CHARACTER</h2></div>
      <div class="chips pe"></div>
      <button class="btn-round big arrow left pe" data-act="prev" title="Previous option (←)">◀</button>
      <button class="btn-round big arrow right pe" data-act="next" title="Next option (→)">▶</button>
      <div class="plate pe"><div class="plate-cat"></div><div class="plate-val"></div><div class="pips"></div></div>
      <div class="namebar pe">
        <div class="namefield"><label for="ylyc-name">NAME</label><input id="ylyc-name" maxlength="16" autocomplete="off" spellcheck="false" placeholder="Your name"></div>
        <button class="btn-round dicebtn" data-act="rand" title="Random character"><span>🎲</span></button>
      </div>
    </div>
    <aside class="cr-panel pe">
      <div class="panel-head"><span class="ol">STARTING LIFE</span></div>
      <div class="panel-body">
        <h3 class="sec">1 · Pick your starting life</h3><div class="grid-prof"></div>
        <h3 class="sec">2 · Pick your investing style</h3><div class="grid-risk"></div>
      </div>
      <div class="panel-foot"><button class="btn btn-xl btn-pink w100" data-act="start" data-wlock>LET'S GO</button></div>
    </aside>
  </section>

  <section class="screen scr-play" data-s="play">
    <header class="hud pe"></header>
    <aside class="side pe" data-tab="info">
      <div class="side-tabs" role="tablist">
        <button class="stab" role="tab" data-act="sideTab" data-t="info">🎯 Goals</button>
        <button class="stab" role="tab" data-act="sideTab" data-t="chat">💬 Twin<i class="udot"></i></button>
      </div>
      <div class="side-inner">
      <h3>🎯 Goals</h3><div class="quests"></div>
      <h3>🏆 Achievements <small class="achn"></small></h3><div class="achs"></div>
      <h3>📈 Your net worth</h3><div class="fanbox"><canvas class="fan-play"></canvas></div>
      <div class="legend"><span><i style="border-color:#ff3d8b"></i>so far</span><span><i class="dash" style="border-color:#2f7bff"></i>Median</span><span><i class="band"></i>p5–p95</span></div>
      <h3 class="hist-h">🧭 Your stations</h3><div class="hist"></div>
      </div>
      <div class="side-chat"></div>
    </aside>
    <div class="tray pe"><div class="tray-head"></div><div class="tray-row"></div></div>
    <div class="busy-pill">🎬 Life is happening …</div>
    <footer class="dock pe"><div class="cats"></div>
      <button class="btn btn-yellow btn-go" data-act="stay" data-lock>DRIVE ON</button>
    </footer>
  </section>

  <section class="screen scr-summary" data-s="summary">
    <div class="res-panel pe">
      <div class="res-tag">RESULTS</div>
      <h2 class="res-h ol">LIFE SUMMARY</h2>
      <div class="res-sub"></div>
      <div class="res-stats"></div>
      <div class="res-list"></div>
      <div class="res-foot"><button class="btn btn-lg btn-green" data-act="toFacts">NEXT ▶</button></div>
    </div>
  </section>

  <section class="screen scr-facts" data-s="facts">
    <div class="facts-panel pe">
      <div class="res-tag">RESULTS</div>
      <h2 class="res-h ol">FINANCIAL FACTS</h2>
      <div class="facts-body">
        <div class="facts-tiles"></div>
        <div class="facts-side">
          <div class="tile gauge"></div>
          <div class="tile chart"><div class="k">📈 Your life vs. just driving on</div>
            <div class="fanbox"><canvas class="fan-end"></canvas></div>
            <div class="legend"><span><i style="border-color:#ff3d8b"></i>your life</span><span><i class="dash" style="border-color:#2f7bff"></i>Median</span><span><i class="band"></i>range p5–p95</span><span><i style="border-color:#9a94b8"></i>just driving on</span></div>
          </div>
        </div>
      </div>
      <p class="disclaimer"></p>
      <div class="res-foot">
        <button class="btn btn-sm btn-purple" data-act="toSummary">◀ BACK</button>
        <button class="btn btn-lg btn-yellow" data-act="dashOpen" data-wlock>DASHBOARD</button>
        <button class="btn btn-lg btn-pink" data-act="restart" data-wlock>PLAY AGAIN</button>
        <button class="btn btn-lg btn-blue" data-act="analyse" data-wlock>ANALYSIS</button>
      </div>
    </div>
  </section>

  <div class="toasts"></div>
  <div class="waitbox"><div class="wcard"><span class="dice">🎲</span><span class="wtxt"><span class="wlabel"></span><span class="wdots"></span></span></div></div>
  <div class="celebrate"><div class="confetti"></div><div class="cel-card">
    <h3 class="cel-h ol">ACHIEVEMENT UNLOCKED!</h3><div class="cel-list"></div>
    <button class="btn btn-lg btn-yellow" data-act="celClose">AWESOME!</button></div></div>`;

  const $ = s => root.querySelector(s);
  const screens = {}; root.querySelectorAll('.screen').forEach(el => { screens[el.dataset.s] = el; });
  const R = {
    loadBar: $('.loadbar i'), loadPct: $('.load-pct'), tip: $('.tip'), tipTxt: $('.tip span'),
    chips: $('.chips'), plateCat: $('.plate-cat'), plateVal: $('.plate-val'), pips: $('.pips'), name: $('#ylyc-name'),
    prof: $('.grid-prof'), risk: $('.grid-risk'),
    hud: $('.hud'), side: $('.side'), quests: $('.quests'), achs: $('.achs'), achn: $('.achn'), fanPlay: $('.fan-play'), hist: $('.hist'), histH: $('.hist-h'),
    tray: $('.tray'), trayHead: $('.tray-head'), trayRow: $('.tray-row'), cats: $('.cats'),
    resSub: $('.res-sub'), resStats: $('.res-stats'), resList: $('.res-list'),
    factsTiles: $('.facts-tiles'), gauge: $('.gauge'), fanEnd: $('.fan-end'), disclaimer: $('.disclaimer'),
    toasts: $('.toasts'), waitLabel: $('.wlabel'), cel: $('.celebrate'), celList: $('.cel-list'), confetti: $('.confetti'),
    sideChat: $('.side-chat'), sideTabs: $('.side-tabs'),
  };
  if (fanRO) { fanRO.observe(R.fanPlay); fanRO.observe(R.fanEnd); }

  /* ---------------------------------------------------------------- Zwilling-Chat + DASHBOARD (CONTRACT "Extension") */
  const chat = createChat({
    onSend(text) {
      if (st.waiting) return false;
      st.chatPending = text;
      if (!act({ action: 'chat', message: text }, null, { quiet: true, kind: 'chat', ms: 60000 })) { st.chatPending = null; return false; }
      return true;
    },
    onCompare(sugg) {
      if (st.waiting || !sugg || !sugg.key) return;
      dash.preferPaths();
      const ok = act({ action: 'plan_alt', key: String(sugg.key) }, 'Calculating a second life path', { quiet: dashVisible(), kind: 'dash' });
      // Python opens the dashboard itself after plan_alt; if it did not (e.g. option no longer selectable), open it now
      if (ok) st.followUp = () => { const b = block(); if (b && !b.dashboard) openDash(); else { st.dashClosing = false; renderExtras(); } };
    },
  });
  const dash = createDashboard({
    onClose: () => closeDash(),
    onReset: () => { act({ action: 'plan_reset' }, null, { quiet: true, kind: 'dash' }) || renderExtras(); },
    onEdit: moves => { act({ action: 'plan_edit', moves }, null, { quiet: true, kind: 'dash' }) || renderExtras(); },
  });
  root.insertBefore(dash.el, R.toasts);
  R.sideChat.appendChild(chat.el);

  function block() {
    const p = st.P || {};
    return p.phase === 'play' ? (p.play || null) : p.phase === 'end' ? (p.end || null) : null;
  }
  function dashVisible() {
    const b = block();
    return !!(b && b.dashboard && typeof b.dashboard === 'object' && !st.dashClosing && ['play', 'summary', 'facts'].includes(st.screen));
  }
  function chatVisible() {
    return dashVisible() || (st.screen === 'play' && st.sideOpen && st.sideTab === 'chat');
  }
  function updateUnread() {
    const n = chatTwinCount((block() || {}).chat);
    if (n < st.chatSeen || chatVisible()) st.chatSeen = n;
    const unread = n > st.chatSeen;
    root.querySelectorAll('.chat-btn, .stab[data-t="chat"]').forEach(b => b.classList.toggle('unread', unread));
    root.querySelectorAll('.chat-btn').forEach(b => b.classList.toggle('on', chatVisible()));
  }
  function renderExtras() {
    const b = block() || {};
    if (!b.dashboard) st.dashClosing = false;
    const open = dashVisible();
    dash.el.classList.toggle('on', open); dash.el.setAttribute('aria-hidden', String(!open));
    root.classList.toggle('dash-open', open);
    const host = open ? dash.chatHost : R.sideChat;
    if (chat.el.parentNode !== host) host.appendChild(chat.el);
    if (open) dash.render(b.dashboard, { loading: st.waiting && st.waitKind === 'dash', locked: st.waiting });
    const av = (st.P && st.P.avatar) || st.cfg, hud = (b && b.hud) || {};
    chat.render(b.chat || null, {
      name: hud.name || av.name || st.cfg.name || '', color: safeColor(COLORS[av.color], '#7b4dff'), locked: st.waiting,
      pending: st.waiting && st.waitKind === 'chat' ? st.chatPending : null,
    });
    updateUnread();
  }
  function openDash() {
    const b = block(); if (!b || st.waiting) return;
    if (b.dashboard) { st.dashClosing = false; renderExtras(); return; }     // already computed (close still in flight)
    act({ action: 'dashboard', open: true }, 'Calculating your dashboard', { kind: 'dashopen' });
  }
  function closeDash() {
    if (!block() || !block().dashboard) return;
    st.dashClosing = true; renderExtras();
    const sendClose = () => { if (st.dashClosing) act({ action: 'dashboard', open: false }, null, { quiet: true, kind: 'dashclose' }); };
    if (st.waiting) st.followUp = sendClose; else sendClose();
  }

  /* ---------------------------------------------------------------- screens */
  function go(name) {
    if (st.screen === name) return;
    st.screen = name; document.body.dataset.screen = name;
    for (const [k, el] of Object.entries(screens)) el.classList.toggle('active', k === name);
    if (name === 'title' || name === 'creator') {
      stage.style.background = '';               // the retirement finale tints the stage; reset for the podium
      E(showCreator, st.cfg, name === 'title' ? 'gender' : st.cat);
    }
    if (name === 'creator') renderCreator();
    if (name === 'facts') requestAnimationFrame(() => drawFan(R.fanEnd, R.fanEnd._fan, R.fanEnd._opt));
    if (name === 'play') requestAnimationFrame(() => drawFan(R.fanPlay, R.fanPlay._fan, R.fanPlay._opt));
    if (name !== 'play') root.classList.remove('play-busy');
    updateLocks();
    if (st.loaded) renderExtras();
  }

  function route() {
    const p = st.P || {}; const phase = p.phase || 'boot';
    if (phase === 'play' && p.play) {
      const reset = st.enginePhase !== null && st.enginePhase !== 'play';
      st.enginePhase = 'play';
      E(showWorld, p.play.world || {}, { reset });
      go('play'); renderPlay(); queueCelebration();
    } else if (phase === 'end' && p.end) {
      const reset = st.enginePhase === 'boot';
      st.enginePhase = 'end';
      E(showWorld, p.end.world || {}, { reset });
      if (st.screen !== 'facts') go('summary');
      renderSummary(); renderFacts();
    } else {
      st.enginePhase = 'boot';
      if (st.screen === 'loading' || !st.screen) go('title');
      else if (st.screen === 'title' || st.screen === 'creator') renderStartPanel();
      else go('creator');
    }
  }

  /* ---------------------------------------------------------------- loading */
  function startLoading() {
    go('loading');
    root.classList.add('fonts-pending');
    const fontsP = Promise.all([
      document.fonts ? document.fonts.load('400 48px "Lilita One"') : null,
      document.fonts ? document.fonts.load('800 16px "Nunito"') : null,
    ]).catch(() => {}).then(() => (document.fonts ? document.fonts.ready : null)).catch(() => {});
    Promise.race([fontsP, sleep(900)]).then(() => root.classList.remove('fonts-pending'));
    let fontsDone = false; fontsP.then(() => { fontsDone = true; });
    const t0 = performance.now(), MIN = 2200;
    let tipI = Math.floor(Math.random() * TIPS.length);
    const showTip = t => { R.tip.classList.add('swap'); setTimeout(() => { R.tipTxt.textContent = t; R.tip.classList.remove('swap'); }, 260); };
    R.tipTxt.textContent = TIPS[tipI];
    const tipTimer = setInterval(() => { tipI = (tipI + 1) % TIPS.length; showTip(TIPS[tipI]); }, 2300);
    let shown = 0, connectMsg = false;
    const tick = () => {
      const el = performance.now() - t0, haveP = !!st.P || el > 9000;
      const ready = fontsDone && el >= MIN && haveP;
      const target = ready ? 100 : Math.min(92, (el / MIN) * 88 + (fontsDone ? 4 : 0));
      shown += (target - shown) * (ready ? .25 : .12);
      R.loadBar.style.width = shown.toFixed(1) + '%'; R.loadPct.textContent = Math.round(shown) + ' %';
      if (!haveP && el > MIN + 400 && !connectMsg) { connectMsg = true; showTip('Connecting to the simulation …'); }
      if (ready && shown > 99.2) {
        R.loadBar.style.width = '100%'; R.loadPct.textContent = '100 %';
        clearInterval(tipTimer); setTimeout(() => { st.loaded = true; route(); renderExtras(); }, 260); return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /* ---------------------------------------------------------------- creator */
  function renderCreator() {
    renderChips(); renderPlate(); renderStartPanel();
    if (document.activeElement !== R.name) R.name.value = st.cfg.name || '';
  }
  function renderChips() {
    R.chips.innerHTML = CATS.map(k => `<button class="chip ${k === st.cat ? 'on' : ''}" data-act="cat" data-k="${k}">${esc(CAT_LABEL[k] || k)}</button>`).join('');
  }
  function renderPlate() {
    const k = st.cat, list = OPTIONS[k] || [], i = Math.max(0, list.indexOf(st.cfg[k])), sw = SWATCH[k];
    R.plateCat.textContent = `${CAT_LABEL[k] || k} · ${i + 1}/${list.length}`;
    R.plateVal.textContent = nice(list[i]);
    R.pips.innerHTML = list.map((v, j) => `<button class="pip ${j === i ? 'on' : ''} ${sw ? 'sw' : ''}" data-act="pip" data-i="${j}" title="${esc(nice(v))}"${sw && sw[v] ? ` style="background:${safeColor(sw[v])}"` : ''}></button>`).join('');
  }
  function stepOpt(d) {
    const k = st.cat, list = OPTIONS[k]; if (!list) return;
    let i = list.indexOf(st.cfg[k]); if (i < 0) i = 0;
    setOpt((i + d + list.length) % list.length);
  }
  function setOpt(i) {
    const k = st.cat, list = OPTIONS[k]; if (!list || !list[i]) return;
    st.cfg = { ...st.cfg, [k]: list[i] }; st.touched = true;
    E(setCreator, st.cfg, st.cat); renderPlate();
  }
  function setCat(k) {
    if (!OPTIONS[k]) return;
    st.cat = k; E(setCreator, st.cfg, k);
    renderChips(); renderPlate();
  }
  function randomize() {
    const c = { ...st.cfg };
    for (const k of CATS) { const l = OPTIONS[k]; c[k] = l[Math.floor(Math.random() * l.length)]; }
    st.cfg = c; st.touched = true; E(setCreator, st.cfg, st.cat); renderPlate();
    const d = root.querySelector('.dicebtn'); if (d) { d.classList.remove('roll'); void d.offsetWidth; d.classList.add('roll'); }
  }
  function renderStartPanel() {
    const boot = (st.P && st.P.boot) || {};
    const profiles = arr(boot.profiles), risks = arr(boot.risks);
    if (!profiles.some(p => p.id === st.pid)) st.pid = profiles.length ? profiles[0].id : null;
    if (!risks.some(r => r.key === st.risk)) {
      const mid = risks.find(r => r.key === 'ausgewogen') || risks[Math.floor(risks.length / 2)];
      st.risk = mid ? mid.key : null;
    }
    R.prof.innerHTML = profiles.length ? profiles.map((p, i) => `
      <button class="mcard prof ${p.id === st.pid ? 'sel' : ''}" data-act="pid" data-id="${esc(p.id)}">
        <div class="mh">${esc(p.name)}${p.age !== undefined && p.age !== null ? ' · ' + num(p.age) : ''}</div>
        <div class="mb"><div class="emo">${profileEmoji(p.status_de, i)}</div>
          <div class="meta">${esc(p.status_de || '')}</div>
          <div class="meta">Start: <b>${chf(p.start_capital)}</b></div>
          <div class="meta">per month: <b>${chfSigned(p.typical_month)}</b></div></div>
      </button>`).join('') : '<div class="empty">Loading starting lives …</div>';
    R.risk.innerHTML = risks.length ? risks.map(r => `
      <button class="mcard risk ${r.key === st.risk ? 'sel' : ''}" data-act="risk" data-k="${esc(r.key)}">
        <div class="mh">${esc(r.title || r.key)}</div>
        <div class="mb"><div class="emo">${esc(r.emoji || '📊')}</div><div class="txt">${esc(r.text || '')}</div></div>
      </button>`).join('') : '<div class="empty">Loading investing styles …</div>';
  }
  function startGame() {
    const name = String(R.name.value || st.cfg.name || '').trim().slice(0, 16) || 'Alex';
    st.cfg = { ...st.cfg, name }; R.name.value = name;
    act({ action: 'start', avatar: { ...st.cfg }, pid: st.pid, risk: st.risk });
  }

  /* ---------------------------------------------------------------- play */
  function renderPlay() {
    const play = (st.P && st.P.play) || {};
    const h = play.hud || {};
    const K = num(play.K, 15), turn = num(play.turn);
    const av = (st.P && st.P.avatar) || st.cfg, avCol = safeColor(COLORS[av.color], '#7b4dff');
    const name = h.name || av.name || 'Alex';
    const nw = num(h.net_worth);
    R.hud.innerHTML = `
      <div class="pill name"><span class="av" style="background:${avCol}">${esc(String(name).trim().charAt(0).toUpperCase() || '?')}</span>
        <span class="big">${esc(name)}</span><span class="sub">· ${num(h.age, num(play.age))} y</span></div>
      <div class="pill money" title="Net worth"><span class="ico">💰</span><span class="big ${nw < 0 ? 'neg' : ''}">${chf(nw)}</span></div>
      <div class="pill" title="Joy"><span class="ico">${esc(h.joy_emoji || '🙂')}</span><span class="big">${Math.round(num(h.joy))}</span></div>
      <div class="pill" title="Achievements"><span class="ico">🏆</span><span class="big">${num(h.achievements_got)}/${num(h.achievements_total)}</span></div>
      <div class="grow"></div>
      <div class="pill station"><span class="big">Station ${clamp(turn + 1, 1, K)}/${K}</span>${h.state_de ? `<span class="sub">${esc(h.state_de)}</span>` : ''}</div>
      <button class="hbtn chat-btn" data-act="chatToggle" title="Twin chat"><span class="e">💬</span><span class="lbl">Twin</span><i class="udot"></i></button>
      <button class="hbtn yellow dash-btn" data-act="dashOpen" data-wlock title="Dashboard: net worth, comparisons, timeline"><span class="e">📊</span><span class="lbl">DASHBOARD</span></button>
      <button class="btn-round sm blue" data-act="side" title="Goals, achievements &amp; net worth">🎯</button>`;

    // categories
    const cats = arr(play.categories);
    if (!cats.some(c => c.key === st.selCat)) { const f = cats.find(c => num(c.open) > 0) || cats[0]; st.selCat = f ? f.key : null; }
    R.cats.innerHTML = cats.map((c, i) => `
      <button class="mcard cat ${c.key === st.selCat ? 'sel' : ''}" data-act="selcat" data-k="${esc(c.key)}" style="--cc:${safeColor(c.color)}" title="${esc(c.label)} (key ${i + 1})">
        <span class="badge ${num(c.open) ? '' : 'zero'}">${num(c.open)}</span>
        <div class="mh">${esc(c.label)}</div><div class="mb"><div class="emo">${esc(c.emoji)}</div></div>
      </button>`).join('');
    renderTray(); renderSide(); updateLocks(); updateUnread();
  }
  function renderTray() {
    const play = (st.P && st.P.play) || {};
    const cat = arr(play.categories).find(c => c.key === st.selCat);
    const ageEnd = num(play.start_age, 20) + num(play.K, 15);
    const cards = arr(play.cards).filter(c => c.cat === st.selCat).sort((a, b) => (a.locked ? 1 : 0) - (b.locked ? 1 : 0));
    R.trayHead.innerHTML = cat ? `<span class="tray-title ol">${esc(cat.emoji)} ${esc(cat.label)}</span>
      <button class="btn-round sm" data-act="tray" title="Show/hide cards">▾</button>` : '';
    R.trayRow.innerHTML = cards.length ? cards.map((c, i) => decisionCard(c, ageEnd, i)).join('')
      : `<div class="tray-empty">Nothing is open here right now – pick another category or drive on.</div>`;
    R.tray.classList.toggle('hide', !st.trayOpen || !cat || st.busy);
  }
  function decisionCard(c, ageEnd, i) {
    const r = rarityOf(c.rarity, c.xp), locked = !!c.locked;
    const chips = [];
    if (num(c.joy)) chips.push(`<span class="chip2 ${num(c.joy) > 0 ? 'pos' : 'neg'}" title="Joy">😊 ${signed(c.joy)}</span>`);
    if (c.delta !== undefined && c.delta !== null) chips.push(`<span class="chip2 ${num(c.delta) >= 0 ? 'pos' : 'neg'}" title="Difference to just driving on, at ${ageEnd}">💰 ${chfShortSigned(c.delta)}</span>`);
    if (c.credit !== undefined && c.credit !== null && Number.isFinite(+c.credit)) {
      const cr = Math.round(clamp(+c.credit, 0, 1) * 100);
      chips.push(`<span class="chip2 ${cr >= 50 ? 'neg' : ''}" title="Probability of needing a loan">💳 ${cr} %</span>`);
    }
    const proj = (c.median !== undefined && c.median !== null) ? `<div class="proj">At ${ageEnd}: <b>${chf(c.median)}</b><br>Range ${chfShort(c.p5)} – ${kfmt(c.p95)}</div>` : '';
    const reason = typeof c.locked === 'string' && c.locked.trim() ? c.locked : 'Still locked';
    const foot = locked ? `<div class="lockbox">🔒 ${esc(reason)}</div>`
      : `<button class="btn btn-green" data-act="choose" data-k="${esc(c.key)}" data-lock>CHOOSE</button>`;
    return `<div class="dcard ${locked ? 'locked' : ''}" style="--rc:${RARITY[r]};animation-delay:${Math.min(i, 8) * 55}ms">
      <span class="rtag">${r}</span><div class="band"><span>${esc(c.emoji || '🃏')}</span></div>
      <h4>${esc(c.title)}</h4><p>${esc(c.text || '')}</p>
      <div class="chips2">${chips.join('')}</div>${proj}${foot}</div>`;
  }
  function renderSide() {
    const play = (st.P && st.P.play) || {};
    R.side.classList.toggle('closed', !st.sideOpen); root.classList.toggle('play-side-open', st.sideOpen);
    R.side.dataset.tab = st.sideTab; root.classList.toggle('play-chat', st.sideOpen && st.sideTab === 'chat');
    R.sideTabs.querySelectorAll('.stab').forEach(b => { const on = b.dataset.t === st.sideTab; b.classList.toggle('on', on); b.setAttribute('aria-selected', String(on)); });
    const qs = arr(play.quests);
    R.quests.innerHTML = qs.length ? qs.map(q => {
      const pct = Math.round(clamp(num(q.progress, num(q.target) ? num(q.current) / num(q.target) : 0), 0, 1) * 100);
      return `<div class="quest ${q.done ? 'done' : ''}"><div class="qt"><span>${q.done ? '✅ ' : ''}${esc(q.name)}</span><span>${pct} %</span></div>
        <div class="qbar"><i style="width:${pct}%"></i></div>
        <div class="qs">${chf(q.current)} / ${chf(q.target)}${q.by_age !== undefined && q.by_age !== null ? ` · by ${num(q.by_age)}` : ''}</div></div>`;
    }).join('') : '<div class="qs">No active goals.</div>';
    const achs = arr(play.achievements);
    R.achn.textContent = `${achs.filter(a => a.got).length}/${achs.length}`;
    R.achs.innerHTML = achs.map(a => `<div class="ach ${a.got ? '' : 'off'}" data-t="${esc(a.title)}" title="${esc(a.title)}">${esc(a.emoji || '🏅')}</div>`).join('');
    const hist = arr(play.history);
    R.histH.style.display = hist.length ? '' : 'none';
    R.hist.innerHTML = hist.map(x => `<span title="${esc(`${num(x.age)} y · ${x.title || ''}`)}">${esc(x.emoji || '•')}</span>`).join('');
    if (play.fan) requestAnimationFrame(() => drawFan(R.fanPlay, play.fan, { small: true }));
  }

  /* ---------------------------------------------------------------- end: summary + facts */
  function renderSummary() {
    const end = (st.P && st.P.end) || {}, s = end.summary || {};
    const stars = clamp(Math.round(num(s.stars)), 0, 5);
    R.resSub.textContent = `${s.name || st.cfg.name || 'Alex'} · life up to ${num(s.age_end)}`;
    R.resStats.innerHTML = `
      <div class="stat"><div class="k">Score</div><div class="v">${grp(s.score)}</div><div class="s">points</div></div>
      <div class="stat"><div class="k">Stars</div><div class="v stars">${'★'.repeat(stars)}<span class="off">${'★'.repeat(5 - stars)}</span></div><div class="s">${stars} of 5</div></div>
      <div class="stat"><div class="k">Joy</div><div class="v">${esc(s.joy_emoji || '🙂')} ${Math.round(num(s.joy))}</div><div class="s">of 100</div></div>
      <div class="stat"><div class="k">Decisions</div><div class="v">${grp(arr(s.choices).length)}</div><div class="s">made</div></div>`;
    const ch = arr(s.choices);
    R.resList.innerHTML = ch.length ? ch.map((c, i) => {
      const r = rarityOf(c.rarity, c.xp);
      return `<div class="rrow" style="--rc:${RARITY[r]};animation-delay:${Math.min(i, 14) * 70}ms">
        <span class="rtag">${r}</span><span class="age">${num(c.age)} y</span><span class="e">${esc(c.emoji || '🃏')}</span>
        <div class="tt"><b>${esc(c.title)}</b><span>${esc(c.cat_label || '')}</span></div></div>`;
    }).join('') : '<div class="res-empty">You just kept driving on. That is a strategy too! 🚗</div>';
  }
  function renderFacts() {
    const end = (st.P && st.P.end) || {}, f = end.facts || {}, s = end.summary || {};
    const nw = num(f.net_worth), lazy = num(f.lazy_median), diff = nw - lazy, best = f.best || null;
    const tile = (k, v, sub = '', cls = '') => `<div class="tile ${cls}"><div class="k">${k}</div><div class="v">${v}</div>${sub ? `<div class="s">${sub}</div>` : ''}</div>`;
    R.factsTiles.innerHTML = [
      tile('💰 Net worth', chf(nw), `at age ${num(s.age_end) || num(arr((f.fan || {}).ages).slice(-1)[0])}`, 'hero'),
      tile('🚗 vs. just driving on', chfSigned(diff), `just driving on: ${chf(lazy)}`, diff >= 0 ? 'good' : 'bad'),
      tile('📏 Range p5–p95', `${kfmt(f.p5)} – ${kfmt(f.p95)}`, '90 % of simulated lives'),
      tile('💵 Cash', chf(f.cash)),
      tile('📈 Portfolio', chf(f.portfolio)),
      tile('🏡 Home equity', chf(f.house_equity)),
      tile('🧾 Debt', chf(f.debt), '', num(f.debt) > 0 ? 'bad' : ''),
      tile('💳 Largest loan', chf(f.max_credit)),
      tile('📅 Months with a loan', grp(f.months_with_credit), num(f.months_with_credit) ? 'months in the red' : 'never in the red 🎉'),
      tile('🃏 Decisions', grp(f.decisions)),
      tile('🌟 Best decision', best ? esc(best.title) : '–', best ? chfSigned(best.delta) : '', 'good'),
    ].join('');
    const pct = clamp(Math.round(num(f.percentile)), 0, 100);
    R.gauge.innerHTML = `${gaugeSvg(pct)}<div><div class="k">🏁 Percentile</div><div class="gv">${pct}th</div>
      <div class="gs">Better than ${pct} % of simulated lives</div></div>`;
    R.disclaimer.textContent = f.disclaimer || 'Synthetic data · not a forecast · not investment advice';
    drawFan(R.fanEnd, f.fan || null, { lazy: true });
  }

  /* ---------------------------------------------------------------- toasts */
  const tq = []; let tRunning = false;
  function toast(text, ms = 2600) {
    if (!text) return; tq.push([String(text), num(ms, 2600)]); if (tq.length > 4) tq.shift();
    if (!tRunning) nextToast();
  }
  function nextToast() {
    const it = tq.shift(); if (!it) { tRunning = false; return; }
    tRunning = true;
    const el = document.createElement('div'); el.className = 'toast'; el.textContent = it[0]; R.toasts.appendChild(el);
    const dur = clamp(it[1], 1200, 6000) / (tq.length ? 1.6 : 1);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => { el.remove(); nextToast(); }, 340); }, dur);
  }

  /* ---------------------------------------------------------------- celebration */
  function queueCelebration() {
    const p = st.P, list = arr(p && p.play && p.play.new_achievements);
    // key by turn + titles, not seq: chat/dashboard actions bump seq without new achievements
    const key = `${num(p.play.turn)}|${list.map(a => a.title).join('|')}`;
    if (!list.length || st.celebrated.has(key)) return;
    st.celebrated.add(key); st.celPending = list;
    setTimeout(() => showCelebration(false), 700);     // waits for the engine if an animation is running
    setTimeout(() => showCelebration(true), 15000);    // safety if busy never ends
  }
  function showCelebration(force = false) {
    const list = st.celPending; if (!list) return;
    if (st.screen !== 'play') { st.celPending = null; return; }
    if (st.busy && !force) return;                     // setBusy(false) calls us again
    st.celPending = null;
    R.celList.innerHTML = list.map((a, i) => `<div class="cel-item" style="animation-delay:${200 + i * 120}ms"><span class="e">${esc(a.emoji || '🏅')}</span>
      <span class="t">${esc(a.title)}</span></div>`).join('');
    const cols = ['#ff3d8b', '#ffd23f', '#2fd27a', '#2f7bff', '#ff8a1f', '#a24bff', '#ffffff'];
    R.confetti.innerHTML = Array.from({ length: 70 }, (_, i) =>
      `<i style="--x:${(Math.random() * 100).toFixed(1)}%;--c:${cols[i % cols.length]};--d:${(2.2 + Math.random() * 2).toFixed(2)}s;--s:${(-Math.random() * 3).toFixed(2)}s;--r:${Math.round(360 + Math.random() * 720)}deg"></i>`).join('');
    R.cel.classList.add('on');
    clearTimeout(st.celTimer); st.celTimer = setTimeout(closeCelebration, 7000);
  }
  function closeCelebration() { clearTimeout(st.celTimer); R.cel.classList.remove('on'); setTimeout(() => { if (!R.cel.classList.contains('on')) R.confetti.innerHTML = ''; }, 400); }

  /* ---------------------------------------------------------------- busy / waiting */
  function engineBusy() { return st.busy && performance.now() - st.busySince < 40000; }
  function updateLocks() {
    const lock = engineBusy() || st.waiting;
    root.querySelectorAll('[data-lock]').forEach(b => { b.disabled = lock; });
    root.querySelectorAll('[data-wlock]').forEach(b => { b.disabled = st.waiting; });
  }
  function setBusy(b) {
    b = !!b; if (b === st.busy) return;
    st.busy = b; if (b) st.busySince = performance.now();
    root.classList.toggle('play-busy', b && st.screen === 'play');
    if (st.screen === 'play') R.tray.classList.toggle('hide', !st.trayOpen || b || !st.selCat);
    updateLocks();
    if (b) setTimeout(updateLocks, 40500);
    if (!b && st.celPending) setTimeout(() => showCelebration(false), 350);
  }
  // opts: {quiet: no big overlay (chat, dashboard edits), kind: 'chat'|'dash'|'dashopen'|'dashclose', ms: timeout, silent: skip re-render}
  function setWaiting(on, label, opts = {}) {
    st.waiting = !!on; clearTimeout(st.waitTimer);
    st.waitKind = st.waiting ? (opts.kind || null) : null;
    const quiet = st.waiting && !!opts.quiet;
    root.classList.toggle('waiting', st.waiting && !quiet); root.classList.toggle('waiting-quiet', quiet);
    if (st.waiting) {
      st.waitSeq = st.P ? num(st.P.seq, -1) : -1; st.waitPhase = st.P ? st.P.phase : null;
      R.waitLabel.textContent = label || WAIT_TXT[Math.floor(Math.random() * WAIT_TXT.length)];
      st.waitTimer = setTimeout(() => {
        if (!st.waiting) return;
        const kind = st.waitKind; st.followUp = null;
        if (kind === 'dashclose') st.dashClosing = false;
        setWaiting(false);
        toast(kind === 'chat' ? '⏳ Your twin is not answering – please ask again' : '⏳ No answer – please try again', 3200);
      }, num(opts.ms, 25000));
    } else st.chatPending = null;
    updateLocks();
    if (st.loaded && !opts.silent) renderExtras();
  }
  function act(value, label, opts = {}) {
    if (st.waiting) return false;
    const labels = { start: 'Preparing your life', restart: 'A new life is waiting', analyse: 'Opening the analysis' };
    setWaiting(true, label || labels[value.action], opts);
    try { send(value); } catch (e) { console.warn('[game] send failed', e); setWaiting(false); return false; }
    return true;
  }

  /* ---------------------------------------------------------------- events */
  root.addEventListener('click', ev => {
    const b = ev.target.closest('[data-act]'); if (!b || !root.contains(b) || b.disabled) return;
    const a = b.dataset.act;
    switch (a) {
      case 'toCreator': go('creator'); break;
      case 'toTitle': go('title'); break;
      case 'analyse': act({ action: 'analyse' }); break;
      case 'cat': setCat(b.dataset.k); break;
      case 'prev': stepOpt(-1); break;
      case 'next': stepOpt(1); break;
      case 'pip': setOpt(+b.dataset.i); break;
      case 'rand': randomize(); break;
      case 'pid': st.pid = b.dataset.id; renderStartPanel(); break;
      case 'risk': st.risk = b.dataset.k; renderStartPanel(); break;
      case 'start': startGame(); break;
      case 'selcat':
        if (st.selCat === b.dataset.k) st.trayOpen = !st.trayOpen; else { st.selCat = b.dataset.k; st.trayOpen = true; }
        R.cats.querySelectorAll('.cat').forEach(el => el.classList.toggle('sel', el.dataset.k === st.selCat));
        renderTray(); updateLocks(); break;
      case 'tray': st.trayOpen = false; renderTray(); break;
      case 'side':
        if (st.sideOpen && st.sideTab === 'info') st.sideOpen = false; else { st.sideOpen = true; st.sideTab = 'info'; }
        renderSide(); updateUnread(); break;
      case 'sideTab': st.sideTab = b.dataset.t === 'chat' ? 'chat' : 'info'; renderSide(); updateUnread(); if (st.sideTab === 'chat') chat.scrollEnd(); break;
      case 'chatToggle':
        if (st.sideOpen && st.sideTab === 'chat') st.sideOpen = false; else { st.sideOpen = true; st.sideTab = 'chat'; }
        renderSide(); updateUnread();
        if (st.sideOpen) { chat.scrollEnd(); chat.focus(); }
        break;
      case 'dashOpen': openDash(); break;
      case 'choose': if (!engineBusy()) act({ action: 'choose', key: b.dataset.k }); break;
      case 'stay': if (!engineBusy()) act({ action: 'choose', key: ((st.P && st.P.play && st.P.play.stay) || {}).key || 'stay' }); break;
      case 'toFacts': go('facts'); break;
      case 'toSummary': go('summary'); break;
      case 'restart': act({ action: 'restart' }); break;
      case 'celClose': closeCelebration(); break;
    }
  });
  R.name.addEventListener('input', () => { st.cfg = { ...st.cfg, name: R.name.value.slice(0, 16) }; st.touched = true; });
  R.name.addEventListener('keydown', ev => { if (ev.key === 'Enter') R.name.blur(); });
  window.addEventListener('keydown', ev => {
    if (ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    if (R.cel.classList.contains('on') && (ev.key === 'Enter' || ev.key === 'Escape' || ev.key === ' ')) { closeCelebration(); ev.preventDefault(); return; }
    if (root.classList.contains('dash-open')) { if (ev.key === 'Escape') { closeDash(); ev.preventDefault(); } return; }
    if (st.screen === 'title' && ev.key === 'Enter') { go('creator'); ev.preventDefault(); }
    else if (st.screen === 'creator') {
      if (ev.key === 'ArrowLeft') { stepOpt(-1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { stepOpt(1); ev.preventDefault(); }
      else if (ev.key === 'ArrowUp' || ev.key === 'ArrowDown') {
        const i = CATS.indexOf(st.cat), d = ev.key === 'ArrowUp' ? -1 : 1; setCat(CATS[(i + d + CATS.length) % CATS.length]); ev.preventDefault();
      }
    } else if (st.screen === 'play' && /^[1-9]$/.test(ev.key)) {
      const c = arr(st.P && st.P.play && st.P.play.categories)[+ev.key - 1];
      if (c) { st.selCat = c.key; st.trayOpen = true; renderPlay(); }
    }
  });

  /* ---------------------------------------------------------------- public API */
  function render(p) {
    if (!p || typeof p !== 'object') return;
    const sig = `${p.seq}|${p.phase}`;
    if (sig === st.sig) return;
    st.sig = sig; st.P = p;
    if (p.phase === 'boot') st.celebrated.clear();
    if (st.waiting && (num(p.seq, -1) > st.waitSeq || p.phase !== st.waitPhase)) setWaiting(false, null, { silent: true });
    if (p.avatar && typeof p.avatar === 'object' && !st.touched) st.cfg = { ...DEFAULT_CFG, ...p.avatar };
    if (st.loaded) { route(); renderExtras(); }
    if (!st.waiting && st.followUp) { const f = st.followUp; st.followUp = null; setTimeout(f, 0); }
  }
  startLoading();
  return { render, toast, setBusy, setWaiting, get screen() { return st.screen; } };
}
