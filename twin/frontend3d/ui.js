// In-game UI: screens (Loading → Title → Creator → Play → Finale → Financial facts → life review), HUD, toasts.
// Talks to the 3D engine via its public API (CONTRACT.md) and to Python via the `send` callback from main.js.
import { showCreator, setCreator, showWorld } from './engine.js';
import { OPTIONS, CAT_LABEL, NICE, DEFAULT_CFG, SKINS, HAIRC, COLORS } from './core.js';

/* =================================================================== helpers */
const TIPS = [
  'Start early: compound interest loves patience.',
  'An emergency fund of 3–6 months of expenses keeps you away from expensive credit.',
  'Consumer loans and credit cards quickly cost 10 % interest or more.',
  'Broad ETFs spread the risk over hundreds of companies.',
  'Pillar 3a: save taxes and build your retirement at the same time.',
  'A higher salary does not have to mean higher spending – watch out for lifestyle inflation.',
  'If you know your expenses, you can steer them: a budget works wonders.',
  'Ups and downs are part of investing – staying in for the long run usually pays.',
  'Pay off high-interest debt first, then invest.',
  'Small amounts saved regularly grow big over the years.',
]
const WAIT_TXT = ['Life is rolling the dice', 'Simulating your future', 'Crunching a thousand lives', 'Chance is shuffling the cards'];

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (v, d = 0) => (v === null || v === undefined || v === '' || !Number.isFinite(+v)) ? d : +v;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const grp = n => String(Math.round(Math.abs(num(n)))).replace(/\B(?=(\d{3})+(?!\d))/g, "'");
export const chf = v => (num(v) < -0.5 ? 'CHF −' : 'CHF ') + grp(v);
const chfSigned = v => (num(v) < -0.5 ? '−' : '+') + 'CHF ' + grp(v);
function kfmt(v) {
  const n = num(v), a = Math.abs(n), s = n < -0.5 ? '−' : '';
  if (a >= 1e6) return s + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + ' Mio.';
  if (a >= 1e4) return s + Math.round(a / 1e3) + 'k';
  return s + grp(a);
}
const chfShortSigned = v => (num(v) < -0.5 ? '−' : '+') + 'CHF ' + kfmt(Math.abs(num(v)));
const signed = v => (num(v) > 0 ? '+' : num(v) < 0 ? '−' : '±') + Math.abs(Math.round(num(v)));
const safeColor = (c, d = '#2f7bff') => (typeof c === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : d;
const nice = v => { const s = NICE[v] || String(v ?? ''); return s.charAt(0).toUpperCase() + s.slice(1); };
const arr = v => Array.isArray(v) ? v : [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
// Ist-Zustand form (start panel): field, label, kind
const IST_FIELDS = [
  ['age', 'Age', 'int'], ['status', 'Situation', 'status'],
  ['income', 'Net income / month', 'chf'], ['expenses', 'Expenses / month (all)', 'chf'],
  ['rent', 'of which rent / month', 'chf'], ['cash', 'UBS account & cash', 'chf'],
  ['portfolio', 'Investments (securities)', 'chf'], ['debt', 'Debt / loans', 'chf'],
];
function profileEmoji(status, i) {
  const s = String(status || '').toLowerCase();
  if (/apprentice|lehre/.test(s)) return '🧰';
  if (/education|stud|uni/.test(s)) return '📚';
  if (/self|startup/.test(s)) return '🚀';
  if (/without|unemployed|looking/.test(s)) return '🔎';
  if (/part/.test(s)) return '⏳';
  if (/retired/.test(s)) return '🌅';
  if (/employ|job|work/.test(s)) return '💼';
  return ['🙂', '😎', '🤓', '😄', '🥳', '😌'][i % 6];
}
const SWATCH = { skin: SKINS, hairColor: HAIRC, color: COLORS, car: COLORS };
// adjustable card parameters (card.params = {name: {label, min, max, step, default, unit, value}})
function paramList(c) {
  const ps = c && c.params && typeof c.params === 'object' ? c.params : null;
  return ps ? Object.entries(ps).filter(([, p]) => p && typeof p === 'object' && Number.isFinite(+p.min) && Number.isFinite(+p.max) && +p.max > +p.min) : [];
}
function snapParam(p, v) {
  const lo = +p.min, hi = +p.max, step = num(p.step, 0) > 0 ? +p.step : 1;
  const x = clamp(num(v, num(p.default, lo)), lo, hi);
  const k = Math.round((x - lo) / step), d = (String(step).split('.')[1] || '').length;
  return clamp(+(lo + k * step).toFixed(d), lo, hi);
}
const isChf = p => /chf/i.test(String(p.unit || ''));
function fmtParam(p, v) {
  if (isChf(p)) return num(p.min) < 0 ? chfSigned(v) : chf(v);
  const u = p.unit ? ' ' + p.unit : '';
  return (num(p.min) < 0 ? signed(v) : grp(v)) + u;
}
function fmtParamShort(p, v) {
  const s = num(v) < -0.5 ? '−' : (num(p.min) < 0 && num(v) > 0.5 ? '+' : '');
  return s + kfmt(Math.abs(num(v)));
}
const CATS = Object.keys(OPTIONS);
// card effect on the net worth at the end, shown as ONE arrow (twin/game.py impact(); numbers only at the end)
const IMPACT = {
  up: { arrow: '▲', label: 'Better for your money' },
  down: { arrow: '▼', label: 'Costs you money' },
  flat: { arrow: '●', label: 'About the same' },
};
function cardImpact(c) {
  if (c && IMPACT[c.impact]) return c.impact;
  if (!c || c.delta === undefined || c.delta === null || !Number.isFinite(+c.delta)) return null;   // older payloads
  const d = +c.delta, base = Math.abs(num(c.median) - d);
  if (Math.abs(d) < Math.min(.01 * base, 20000)) return 'flat';
  return d > 0 ? 'up' : d < 0 ? 'down' : 'flat';
}
// money-health badge of the "Where you stand" tile (hud.health)
const HEALTH = {
  ok: { dot: '🟢', label: 'Buffer OK', tip: 'Your cash covers at least 3 months of expenses and you owe nothing' },
  thin: { dot: '🟡', label: 'Thin buffer', tip: 'Less than 3 months of expenses in cash – one surprise bill could push you into credit' },
  credit: { dot: '🔴', label: 'On credit', tip: 'You are living on a loan right now – expensive interest eats your money' },
};

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
  // x labels: first, last and "now" first, then round ages (every 1/2/5/10/20 years, whatever fits the width)
  g.textAlign = 'center'; g.fillStyle = '#6b6394';
  const gap = small ? 30 : 40, a0 = num(ages[0]), a1 = num(ages[n - 1]), span = Math.max(1, a1 - a0);
  const every = [1, 2, 5, 10, 20, 50].find(e => (W - L - R) * e / span >= gap * 1.15) || 50;
  const prio = [0, n - 1]; if (ni > 0 && ni < n - 1) prio.push(ni);
  for (let i = 1; i < n - 1; i++) if (Number.isFinite(+ages[i]) && Math.round(+ages[i]) % every === 0) prio.push(i);
  const used = [];
  for (const i of prio) {
    const x = X(i); if (used.some(u => Math.abs(u - x) < gap)) continue; used.push(x);
    g.fillStyle = '#d9d2f5'; g.fillRect(Math.round(x) - .5, H - B, 1, 4);
    g.fillStyle = i === ni && ni < n - 1 ? '#ff3d8b' : '#6b6394';
    g.fillText(`${num(ages[i])}${small ? '' : ' y'}`, clamp(x, L + 10, W - R - 12), H - B / 2 + 2);
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
export function createUI(root, { send, engineOk = true, standalone = false, onSkipIntro = null } = {}) {
  const stage = document.getElementById('stage');
  const st = {
    screen: null, P: null, sig: null, loaded: false, cfg: { ...DEFAULT_CFG }, touched: false, cat: 'gender',
    ist: null, istBuilt: false, styleHinted: false, selCat: null, trayOpen: true, sideOpen: window.innerWidth >= 1150,
    busy: false, busySince: 0, waiting: false, waitSeq: -1, waitPhase: null, waitTimer: 0,
    enginePhase: null, intro: false, introTimers: [], finTimer: 0, finSince: 0,
    waitTurn: null, softTimer: 0, skipOpen: false, trayKey: '',
    // card params: local values the player is changing (key → {name: value}), revision counters, debounce timers
    lp: {}, lpRev: {}, lpSent: {}, pTimers: {}, updating: {}, quiet: [], dragging: false, trayDirty: false,
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
        <button class="btn-round dicebtn" data-act="rand" title="Random look"><span>🎲</span></button>
      </div>
    </div>
    <aside class="cr-panel pe">
      <div class="panel-head"><span class="ol">YOUR START</span></div>
      <div class="panel-body">
        <h3 class="sec">Your status quo</h3>
        <p class="ist-note">Enter your own numbers as they are today. No numbers at hand? Load the example data set.</p>
        <div class="ist-ex"></div>
        <div class="ist-form"></div>
        <p class="ist-note">🛣️ Your road runs year by year from your age to <b class="ret-age">85</b> – retire whenever you
          like from 60 (at 70 at the latest). 📊 How to invest is compared later in the analysis – with tips for your data.</p>
      </div>
      <div class="panel-foot"><button class="btn btn-xl btn-pink w100" data-act="start" data-wlock>LET'S GO</button></div>
    </aside>
  </section>

  <section class="screen scr-play" data-s="play">
    <header class="hud pe"></header>
    <aside class="side pe"><div class="side-inner">
      <h3>📍 Where you stand</h3><div class="stand"></div>
      <h3>🎯 Goals</h3><div class="quests"></div>
      <h3 class="hist-h">🧭 Your stations</h3><div class="hist"></div>
    </div></aside>
    <div class="tray pe"><div class="tray-head"></div><div class="tray-row"></div></div>
    <div class="busy-pill">🎬 Life is happening …</div>
    <footer class="dock pe"><div class="cats"></div>
      <div class="gobox">
        <button class="btn btn-yellow btn-go" data-act="stay" data-lock>DRIVE ON</button>
        <div class="skipbox" hidden>
          <button class="btn btn-sm btn-purple btn-skip" data-act="skipMenu" data-lock title="Fast-forward several years" aria-haspopup="menu" aria-expanded="false">SKIP ▶▶</button>
          <div class="skipmenu" role="menu"></div>
        </div>
      </div>
    </footer>
  </section>

  <section class="screen scr-finale" data-s="finale">
    <div class="fin-tag pe"><span class="ol">🏁 THE FINISH LINE</span><small class="fin-sub"></small></div>
    <button class="btn btn-sm btn-purple fin-skip pe" data-act="toFacts" title="Show your financial facts (Space)">RESULTS ▶▶</button>
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
      <div class="res-foot">
        <button class="btn btn-lg btn-purple" data-act="restart" data-wlock>PLAY AGAIN</button>
        <button class="btn btn-xl btn-pink btn-review" data-act="analyse" data-wlock title="Your timeline, what went well, what could be better – and your twin to talk to">YOUR LIFE REVIEW ▶</button>
      </div>
    </div>
  </section>

  <div class="intro" aria-live="polite">
    <div class="intro-banner"><div class="ib-tag"><span class="ib-name"></span><span class="ib-ages"></span></div>
      <div class="ib-bar"><span class="ib-text"></span></div></div>
    <div class="intro-howto"><div class="ih-head">HOW TO PLAY</div><ul class="ih-list"></ul></div>
    <div class="intro-count"><span></span></div>
    <button class="btn btn-sm btn-purple intro-skip" data-act="skipIntro" title="Skip the intro (Space)">SKIP ▶▶</button>
  </div>
  <div class="toasts"></div>
  <div class="waitbox"><div class="wcard"><span class="dice">🎲</span><span class="wtxt"><span class="wlabel"></span><span class="wdots"></span></span></div></div>
`;

  const $ = s => root.querySelector(s);
  const screens = {}; root.querySelectorAll('.screen').forEach(el => { screens[el.dataset.s] = el; });
  const R = {
    loadBar: $('.loadbar i'), loadPct: $('.load-pct'), tip: $('.tip'), tipTxt: $('.tip span'),
    chips: $('.chips'), plateCat: $('.plate-cat'), plateVal: $('.plate-val'), pips: $('.pips'), name: $('#ylyc-name'),
    istEx: $('.ist-ex'), istForm: $('.ist-form'), retAge: $('.ret-age'),
    hud: $('.hud'), side: $('.side'), stand: $('.stand'), quests: $('.quests'), hist: $('.hist'), histH: $('.hist-h'),
    tray: $('.tray'), trayHead: $('.tray-head'), trayRow: $('.tray-row'), cats: $('.cats'),
    skipBox: $('.skipbox'), skipBtn: $('.btn-skip'), skipMenu: $('.skipmenu'), busyPill: $('.busy-pill'),
    finSub: $('.fin-sub'), factsTiles: $('.facts-tiles'), gauge: $('.gauge'), fanEnd: $('.fan-end'),
    intro: $('.intro'), ibName: $('.ib-name'), ibAges: $('.ib-ages'), ibText: $('.ib-text'), ihList: $('.ih-list'),
    count: $('.intro-count span'),
    toasts: $('.toasts'), waitLabel: $('.wlabel'),
  };
  if (fanRO) fanRO.observe(R.fanEnd);

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
    if (name !== 'finale') clearTimeout(st.finTimer);
    if (name !== 'play') { root.classList.remove('play-busy'); if (st.intro) intro('end'); }
    updateLocks();
  }

  function route() {
    const p = st.P || {}; const phase = p.phase || 'boot';
    if (phase === 'play' && p.play) {
      const reset = st.enginePhase !== null && st.enginePhase !== 'play';
      st.enginePhase = 'play';
      E(showWorld, p.play.world || {}, { reset });
      go('play'); renderPlay();
    } else if (phase === 'end' && p.end) {
      // end of life: the retirement finale plays on the island, then the financial facts (no life summary screen)
      const reset = st.enginePhase === 'boot';
      st.enginePhase = 'end';
      E(showWorld, p.end.world || {}, { reset });
      renderFacts();
      if (st.screen !== 'facts' && st.screen !== 'finale') startFinale();
    } else {
      // boot (also an old "ride" phase: the film ride has no entry in the game any more)
      st.enginePhase = 'boot'; st.styleHinted = false;
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
        clearInterval(tipTimer); setTimeout(() => { st.loaded = true; route(); }, 260); return;
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
    const ex = boot.example, statuses = arr(boot.statuses);
    R.retAge.textContent = num(boot.end_age, num(boot.life_end, 85));
    R.istEx.innerHTML = ex ? `
      <button class="exchip ${st.ist && st.ist.basis === ex.id ? 'on' : ''}" data-act="ex">
        <span class="e">📋</span><span><b>Load example data</b><small>${esc(ex.name)} · ${num(ex.age)} · ${esc(ex.status || '')}</small></span>
      </button>` : '<div class="empty">Loading …</div>';
    if (!st.istBuilt && statuses.length) {
      R.istForm.innerHTML = IST_FIELDS.map(([k, label, kind]) => `
        <label class="ist-f ${kind === 'status' ? 'wide' : ''}"><span>${esc(label)}</span>${kind === 'status'
          ? `<select data-ist="${k}">${statuses.map(o => `<option value="${esc(o.key)}" ${o.key === 'employed' ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`
          : `<span class="inp">${kind === 'chf' ? '<i>CHF</i>' : ''}<input data-ist="${k}" type="number" inputmode="numeric" min="${kind === 'int' ? 15 : 0}" max="${kind === 'int' ? 70 : 9999999}" step="${kind === 'int' ? 1 : 50}" placeholder="${kind === 'int' ? 'e.g. 24' : '0'}"></span>`}
        </label>`).join('');
      st.istBuilt = true; fillIst();
    }
  }
  function fillIst() {
    if (!st.ist) return;
    R.istForm.querySelectorAll('[data-ist]').forEach(el => {
      const v = st.ist[el.dataset.ist]; if (v !== undefined && v !== null && document.activeElement !== el) el.value = v;
    });
  }
  function readIst() {
    const out = { ...(st.ist || {}) };
    R.istForm.querySelectorAll('[data-ist]').forEach(el => {
      out[el.dataset.ist] = el.tagName === 'SELECT' ? el.value : Math.max(0, num(el.value));
    });
    return out;
  }
  // the status quo must be entered (or the example loaded): age, income and expenses are required
  function istReady() {
    const v = {}; R.istForm.querySelectorAll('[data-ist]').forEach(el => { v[el.dataset.ist] = el.value; });
    const missing = ['age', 'income', 'expenses'].filter(k => v[k] === undefined || String(v[k]).trim() === '');
    if (missing.length) { toast('✏️ Please enter your status quo (age, income, expenses) – or load the example data', 3600); return false; }
    return true;
  }
  function takeName() {
    const name = String(R.name.value || st.cfg.name || '').trim().slice(0, 16) || 'Alex';
    st.cfg = { ...st.cfg, name }; R.name.value = name;
  }
  function startGame() {
    if (!istReady()) return;
    takeName(); st.ist = readIst(); st.styleHinted = false;
    act({ action: 'start', avatar: { ...st.cfg }, ist: { ...st.ist } });
  }
  /* ---------------------------------------------------------------- play */
  function renderPlay() {
    const play = (st.P && st.P.play) || {};
    const h = play.hud || {};
    const K = num(play.K, 15), turn = num(play.turn);
    const av = (st.P && st.P.avatar) || st.cfg, avCol = safeColor(COLORS[av.color], '#7b4dff');
    const name = h.name || av.name || 'Alex';
    const nw = num(h.net_worth), stNow = clamp(turn + 1, 1, Math.max(1, K));
    const age = num(h.age, num(play.age)), endAge = num(play.end_age, num(play.start_age, 20) + K);
    const skipped = num((play.world || {}).skipped);
    R.busyPill.textContent = skipped >= 2 ? `⏩ Fast-forward: ${skipped} years …` : '🎬 Life is happening …';
    R.hud.innerHTML = `
      <div class="pill name"><span class="av" style="background:${avCol}">${esc(String(name).trim().charAt(0).toUpperCase() || '?')}</span>
        <span class="big">${esc(name)}</span><span class="sub">· age ${age}</span></div>
      <div class="pill money" title="Net worth"><span class="ico">💰</span><span class="big ${nw < 0 ? 'neg' : ''}">${chf(nw)}</span></div>
      <div class="grow"></div>
      <div class="pill station" title="${esc(`Age ${age} · life runs to ${endAge}`)}"><span class="st-col">
        <span class="st-top"><span class="big">Station ${stNow}<small>/${K}</small></span>${h.state ? `<span class="sub">${esc(h.state)}</span>` : ''}</span>
        <i class="st-bar"><b style="width:${(stNow / Math.max(1, K) * 100).toFixed(1)}%"></b></i></span></div>
      <button class="btn-round sm blue" data-act="side" title="Where you stand, goals & your stations">📊</button>`;

    // categories
    const cats = arr(play.categories);
    // the investment style is asked later (from station 2): jump to its category once and say why
    if (play.focus_cat && !st.styleHinted && cats.some(c => c.key === play.focus_cat)) {
      st.styleHinted = true; st.selCat = play.focus_cat; st.trayOpen = true;
      if (play.hint) setTimeout(() => toast(play.hint, 4200), 400);
    }
    if (!cats.some(c => c.key === st.selCat)) { const f = cats.find(c => num(c.open) > 0) || cats[0]; st.selCat = f ? f.key : null; }
    R.cats.innerHTML = cats.map((c, i) => `
      <button class="mcard cat ${c.key === st.selCat ? 'sel' : ''}" data-act="selcat" data-k="${esc(c.key)}" style="--cc:${safeColor(c.color)}" title="${esc(c.label)} (key ${i + 1})">
        <span class="badge ${num(c.open) ? '' : 'zero'}">${num(c.open)}</span>
        <div class="mh">${esc(c.label)}</div><div class="mb"><div class="emo">${esc(c.emoji)}</div></div>
      </button>`).join('');
    renderTray(); renderSide(); renderSkip(); updateLocks();
  }
  function renderTray() {
    if (st.dragging) { st.trayDirty = true; return; }   // never rebuild a slider under the player's finger
    st.trayDirty = false;
    const play = (st.P && st.P.play) || {};
    const cat = arr(play.categories).find(c => c.key === st.selCat);
    const ageEnd = num(play.end_age, num(play.start_age, 20) + num(play.K, 15));
    const cards = arr(play.cards).filter(c => c.cat === st.selCat).sort((a, b) => (a.locked ? 1 : 0) - (b.locked ? 1 : 0));
    R.trayHead.innerHTML = cat ? `<span class="tray-title ol">${esc(cat.emoji)} ${esc(cat.label)}</span>
      <button class="btn-round sm" data-act="tray" title="Show / hide cards">▾</button>` : '';
    const color = safeColor(cat && cat.color);
    // same station + same category (e.g. a slider update): keep the scroll position, focus and skip the card pop-in
    const key = `${num(play.turn)}|${st.selCat}`, same = key === st.trayKey; st.trayKey = key;
    const ae = document.activeElement, focus = ae && root.contains(ae) && ae.dataset && ae.dataset.pk ? [ae.dataset.pk, ae.dataset.pn] : null;
    const sl = R.trayRow.scrollLeft;
    R.trayRow.classList.toggle('still', same);
    R.trayRow.innerHTML = cards.length ? cards.map((c, i) => decisionCard(c, ageEnd, i, color)).join('')
      : `<div class="tray-empty">Nothing open here right now – pick another category or drive on.</div>`;
    if (same) R.trayRow.scrollLeft = sl;
    if (focus) {
      const el = [...R.trayRow.querySelectorAll('input[data-pk]')].find(x => x.dataset.pk === focus[0] && x.dataset.pn === focus[1]);
      if (el) try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    }
    R.tray.classList.toggle('hide', !st.trayOpen || !cat || st.busy);
  }
  const cardByKey = k => arr(st.P && st.P.play && st.P.play.cards).find(c => c.key === k) || null;
  // current values of a card's params: what the player is setting right now, else the stored value, else the default
  function paramValues(c) {
    const out = {}, loc = st.lp[c.key] || {};
    for (const [n, p] of paramList(c)) out[n] = snapParam(p, loc[n] !== undefined ? loc[n] : (p.value !== undefined && p.value !== null ? p.value : p.default));
    return out;
  }
  function paramBox(c) {
    const ps = paramList(c); if (!ps.length) return '';
    const vals = paramValues(c), k = esc(c.key);
    return `<div class="params">${ps.map(([n, p]) => {
      const v = vals[n], nn = esc(n), lbl = esc(p.label || n), step = num(p.step, 0) > 0 ? +p.step : 1;
      return `<div class="prm">
        <div class="prm-top"><span class="prm-l">${lbl}</span><b class="prm-v" data-pv="${nn}">${esc(fmtParam(p, v))}</b></div>
        <div class="prm-row">
          <button class="pstep" data-act="pstep" data-k="${k}" data-n="${nn}" data-d="-1" title="Less" aria-label="${lbl}: less">−</button>
          <input class="prm-r" type="range" data-pk="${k}" data-pn="${nn}" min="${+p.min}" max="${+p.max}" step="${step}" value="${v}" aria-label="${lbl}">
          <button class="pstep" data-act="pstep" data-k="${k}" data-n="${nn}" data-d="1" title="More" aria-label="${lbl}: more">+</button>
        </div>
        <div class="prm-mm"><span>${esc(fmtParamShort(p, p.min))}</span><span>${esc(fmtParamShort(p, p.max))}</span></div></div>`;
    }).join('')}</div>`;
  }
  function decisionCard(c, ageEnd, i, color) {
    const locked = !!c.locked, hasP = paramList(c).length > 0, upd = !!st.updating[c.key];
    // no numbers on the cards: ONE arrow for the effect on your net worth at the end (numbers come at the end)
    const im = cardImpact(c), I = im && IMPACT[im];
    const badge = I ? `<span class="imp-badge ${im}" role="img" aria-label="${esc(I.label)}" title="${esc(`${I.label} – your net worth at ${ageEnd} compared with just driving on`)}">${I.arrow}</span>` : '';
    const words = I ? `<div class="imp-words ${im}">${esc(I.label)}</div>` : '';
    const reason = typeof c.locked === 'string' && c.locked.trim() ? c.locked : 'Locked';
    const foot = locked ? `<div class="lockbox">🔒 ${esc(reason)}</div>`
      : `<button class="btn btn-green" data-act="choose" data-k="${esc(c.key)}" data-lock>CHOOSE</button>`;
    return `<div class="dcard ${locked ? 'locked' : ''} ${hasP ? 'has-params' : ''} ${upd ? 'updating' : ''}" data-card="${esc(c.key)}" style="--rc:${color};animation-delay:${Math.min(i, 8) * 55}ms">
      <div class="band"><span>${esc(c.emoji || '🃏')}</span>${badge}</div>
      <h4>${esc(c.title)}</h4><p>${esc(c.text || '')}</p>${paramBox(c)}
      <div class="prev">${words}<span class="upd">updating …</span></div>${foot}</div>`;
  }
  /* ---------------------------------------------------------------- card params (quiet updates, no wait screen) */
  function cardEl(k) { return [...R.trayRow.querySelectorAll('.dcard[data-card]')].find(el => el.dataset.card === k) || null; }
  function markUpdating(k, on) {
    if (on) st.updating[k] = performance.now(); else delete st.updating[k];
    const el = cardEl(k); if (el) el.classList.toggle('updating', !!on);
  }
  function setParam(k, n, raw, input = null) {
    const c = cardByKey(k); if (!c) return;
    const p = (c.params || {})[n]; if (!p) return;
    const v = snapParam(p, raw);
    st.lp[k] = { ...paramValues(c), [n]: v }; st.lpRev[k] = num(st.lpRev[k]) + 1;
    const el = cardEl(k);
    if (el) {
      const out = [...el.querySelectorAll('[data-pv]')].find(x => x.dataset.pv === n); if (out) out.textContent = fmtParam(p, v);
      const r = input || [...el.querySelectorAll('input[data-pk]')].find(x => x.dataset.pn === n); if (r && +r.value !== v) r.value = v;
    }
    markUpdating(k, true);
    clearTimeout(st.pTimers[k]);
    st.pTimers[k] = setTimeout(() => flushParams(k), 350);
  }
  function flushParams(k) {
    clearTimeout(st.pTimers[k]); delete st.pTimers[k];
    if (!st.lp[k] || !cardByKey(k)) { delete st.lp[k]; markUpdating(k, false); return; }
    if (st.waiting) { st.pTimers[k] = setTimeout(() => flushParams(k), 500); return; }   // Python is busy: send afterwards
    st.lpSent[k] = st.lpRev[k];
    sendQuiet({ action: 'card_params', key: k, params: { ...st.lp[k] } });
    setTimeout(() => { if (st.updating[k] && performance.now() - st.updating[k] > 7500) markUpdating(k, false); }, 8000);
  }
  function sendQuiet(value) {
    st.quiet.push(performance.now());
    try { send(value); } catch (e) { console.warn('[game] send failed', e); st.quiet.pop(); }
  }
  // a new payload arrived: local values that were sent and answered are now owned by the server again
  function settleParams() {
    const now = performance.now();
    st.quiet = st.quiet.filter(t => now - t < 6000); st.quiet.shift();
    for (const k of Object.keys(st.lp)) {
      if (st.pTimers[k]) continue;
      if (st.lpSent[k] === st.lpRev[k] && !st.quiet.length) { delete st.lp[k]; delete st.updating[k]; }
    }
    for (const k of Object.keys(st.updating)) if (!st.lp[k]) delete st.updating[k];
  }
  function chooseCard(k) {
    const c = cardByKey(k), v = { action: 'choose', key: k };
    if (c && paramList(c).length) { v.params = paramValues(c); clearTimeout(st.pTimers[k]); delete st.pTimers[k]; st.lpSent[k] = st.lpRev[k]; }
    act(v);
  }
  /* ---------------------------------------------------------------- skip (fast-forward several years) */
  function skipOptions() {
    const play = (st.P && st.P.play) || {};
    return arr(play.skip).filter(o => o && (o.until === 'event' || num(o.years) >= 1));
  }
  function renderSkip() {
    const opts = skipOptions();
    R.skipBox.hidden = !opts.length;
    if (!opts.length) st.skipOpen = false;
    R.skipMenu.innerHTML = opts.map((o, i) => `<button class="skipopt" role="menuitem" data-act="skip" data-i="${i}" data-lock>${o.until === 'event' ? '⏭️' : '⏩'} ${esc(o.label || (o.until === 'event' ? 'Next event' : `+${num(o.years)} years`))}</button>`).join('');
    showSkipMenu(st.skipOpen);
  }
  function showSkipMenu(on) {
    st.skipOpen = !!on && !engineBusy() && !st.waiting && !R.skipBox.hidden;
    R.skipBox.classList.toggle('open', st.skipOpen);
    R.skipBtn.setAttribute('aria-expanded', st.skipOpen ? 'true' : 'false');
  }
  function doSkip(i) {
    const o = skipOptions()[i]; showSkipMenu(false); if (!o || engineBusy()) return;
    const v = o.until === 'event' ? { action: 'skip', until: 'event' } : { action: 'skip', years: Math.max(1, Math.round(num(o.years, 1))) };
    act(v, o.until === 'event' ? 'Driving to the next event' : `Skipping ${v.years} years`);
  }
  function renderSide() {
    const play = (st.P && st.P.play) || {};
    R.side.classList.toggle('closed', !st.sideOpen); root.classList.toggle('play-side-open', st.sideOpen);
    const qs = arr(play.quests);
    R.quests.innerHTML = qs.length ? qs.map(q => {
      const pct = Math.round(clamp(num(q.progress, num(q.target) ? num(q.current) / num(q.target) : 0), 0, 1) * 100);
      return `<div class="quest ${q.done ? 'done' : ''}"><div class="qt"><span>${q.done ? '✅ ' : ''}${esc(q.name)}</span><span>${pct} %</span></div>
        <div class="qbar"><i style="width:${pct}%"></i></div>
        <div class="qs">${chf(q.current)} / ${chf(q.target)}${q.by_age !== undefined && q.by_age !== null ? ` · by ${num(q.by_age)}` : ''}</div></div>`;
    }).join('') : '<div class="qs">No active goals.</div>';
    const hist = arr(play.history);
    R.histH.style.display = hist.length ? '' : 'none';
    R.hist.innerHTML = hist.map(x => `<span class="hi" title="${esc(`age ${num(x.age)} · ${x.title || ''}`)}"><em>${esc(x.emoji || '•')}</em><small>${num(x.age)}</small></span>`).join('');
    R.hist.scrollTop = R.hist.scrollHeight;
    renderStand(play.hud || {});
  }
  // "Where you stand": net worth today, change since the last stop (arrow), money-health badge. No forecast.
  function renderStand(h) {
    const nw = num(h.net_worth), hasPrev = h.net_worth_prev !== undefined && h.net_worth_prev !== null && Number.isFinite(+h.net_worth_prev);
    const d = hasPrev ? nw - num(h.net_worth_prev) : 0, dir = !hasPrev ? null : d > 0.5 ? 'up' : d < -0.5 ? 'down' : 'flat';
    const since = h.prev_age !== undefined && h.prev_age !== null ? `since age ${num(h.prev_age)}` : 'since the last station';
    const H = HEALTH[h.health] || null, exp = num(h.expenses);
    const tip = H ? `${H.tip}${exp > 0 ? ` (3 months = ${chf(3 * exp)})` : ''}` : '';
    R.stand.innerHTML = `
      <div class="stand-k">Net worth today</div>
      <div class="stand-v ${nw < 0 ? 'neg' : ''}">${chf(nw)}</div>
      <div class="stand-d ${dir || 'none'}">${dir ? `<b class="imp-dot ${dir}" aria-hidden="true">${IMPACT[dir].arrow}</b><span>${dir === 'flat' ? 'about the same' : chfShortSigned(d)} <small>${esc(since)}</small></span>`
        : '<span>Your first station – off you go!</span>'}</div>
      ${H ? `<div class="health ${esc(h.health)}" title="${esc(tip)}"><i aria-hidden="true">${H.dot}</i><span>${esc(H.label)}</span></div>` : ''}`;
  }

  /* ---------------------------------------------------------------- end: retirement finale → financial facts */
  // the engine plays the finale (drive to the last station + rocking chair); when it is done → FINANCIAL FACTS.
  function startFinale() {
    const end = (st.P && st.P.end) || {}, s = end.summary || {};
    R.finSub.textContent = `${s.name || st.cfg.name || 'Alex'} · life up to ${num(s.age_end, 85)}`;
    go('finale');
    if (!engineOk) { go('facts'); return; }
    st.finSince = performance.now();
    finaleCheck(2600);
  }
  function finaleCheck(ms) {
    clearTimeout(st.finTimer);
    st.finTimer = setTimeout(() => {
      if (st.screen !== 'finale') return;
      const el = performance.now() - st.finSince;
      if (engineBusy() && el < 30000) { finaleCheck(800); return; }   // still driving / rocking: wait
      go('facts');
    }, ms);
  }
  function renderFacts() {
    const end = (st.P && st.P.end) || {}, f = end.facts || {}, s = end.summary || {};
    const nw = num(f.net_worth), lazy = num(f.lazy_median), diff = nw - lazy, best = f.best || null;
    // long values (CHF 19'457'412) get a smaller font instead of being cut off
    const tile = (k, v, sub = '', cls = '') => { const long = String(v).replace(/<[^>]*>/g, '').length > 12 ? ' long' : '';
      return `<div class="tile ${cls}"><div class="k">${k}</div><div class="v${long}">${v}</div>${sub ? `<div class="s">${sub}</div>` : ''}</div>`; };
    const bestUp = best && num(best.delta) > 0.5;          // "best" only if a choice actually raised the net worth
    R.factsTiles.innerHTML = [
      tile('💰 Net worth', chf(nw), `at age ${num(s.age_end) || num(arr((f.fan || {}).ages).slice(-1)[0])}`, 'hero'),
      tile('🚗 vs. just driving on', chfSigned(diff), `just driving on: ${chf(lazy)}`, diff >= 0 ? 'good' : 'bad'),
      tile('📏 Range p5–p95', `${kfmt(f.p5)} – ${kfmt(f.p95)}`, '90 % of the simulated lives'),
      tile('💵 Cash', chf(f.cash)),
      tile('📈 Portfolio', chf(f.portfolio)),
      tile('🏡 Home equity', chf(f.house_equity)),
      tile('🧾 Debt', chf(f.debt), '', num(f.debt) > 0 ? 'bad' : ''),
      tile('💳 Highest credit', chf(f.max_credit)),
      tile('📅 Months with credit', grp(f.months_with_credit), num(f.months_with_credit) ? 'months in the red' : 'never in the red 🎉'),
      tile('🃏 Decisions', grp(f.decisions)),
      bestUp ? tile('🌟 Best decision', esc(best.title), chfSigned(best.delta), 'good')
             : tile('🌟 Best decision', '–', best ? 'none of your choices raised your net worth' : 'no choices made'),
    ].join('');
    const pct = clamp(Math.round(num(f.percentile)), 0, 100);
    R.gauge.innerHTML = `${gaugeSvg(pct)}<div><div class="k">🏁 Percentile</div><div class="gv">${pct}.</div>
      <div class="gs">Better than ${pct} % of the simulated lives</div></div>`;
    drawFan(R.fanEnd, f.fan || null, { lazy: true });
  }

  /* ---------------------------------------------------------------- intro (engine drives the timing) */
  function intro(step, data = {}) {
    const later = (ms, fn) => st.introTimers.push(setTimeout(fn, ms));
    const clear = () => { st.introTimers.forEach(clearTimeout); st.introTimers = []; };
    if (step === 'title') {
      clear(); st.intro = true; root.classList.add('intro-on'); R.intro.className = 'intro on s-title';
      const play = (st.P && st.P.play) || {}, name = ((play.hud || {}).name || st.cfg.name || 'Alex').toUpperCase();
      const from = num(data.from, num(play.start_age, 20)), to = num(data.to, num(play.end_age, from + num(play.K, 15)));
      const step = Math.max(1, num(data.step, num(play.step, 1))), yrs = step === 1 ? 'one year' : `${step} years`;
      R.ibName.textContent = `${name}'S LIFE`; R.ibAges.textContent = `AGE ${from} → ${to}`;
      R.ibText.textContent = `${num(data.stations, 15)} stations · one choice every ${step === 1 ? 'year' : step + ' years'} · all the way to ${to}!`;
      R.ihList.innerHTML = [
        ['🛣️', `Every station is ${yrs} of your life – from ${from} to ${to}.`],
        ['🃏', 'Pick one card per station – or just drive on. SKIP ▶▶ fast-forwards several years.'],
        ['🎚️', 'Some cards have sliders: the price of a home, the cost of a child, your monthly budget.'],
        ['⬆️', `A green ▲ on a card means more money for you at ${to}, a red ▼ costs you money. The numbers come at the end.`],
        ['🪑', 'Retire whenever you like from 60 – at 70 at the latest.'],
      ].map(([e, t], i) => `<li style="animation-delay:${300 + i * 260}ms"><span>${e}</span>${esc(t)}</li>`).join('');
    } else if (step === 'howto') {
      R.intro.className = 'intro on s-howto';
    } else if (step === 'countdown') {
      R.intro.className = 'intro on s-count';
      const show = (t, cls = '') => { R.count.textContent = t; R.count.className = cls; void R.count.offsetWidth; R.count.classList.add('pop'); };
      show('READY?', 'small'); later(1300, () => show('3')); later(2000, () => show('2')); later(2700, () => show('1'));
      later(3400, () => show('GO!', 'go'));
    } else if (step === 'end') {
      clear(); st.intro = false; R.intro.className = 'intro'; root.classList.remove('intro-on');
      if (st.screen === 'play') renderPlay();
    }
  }
  function skipIntro() { if (st.intro && onSkipIntro) onSkipIntro(); }

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
    if (!b && st.screen === 'finale') finaleCheck(2000);       // finale done: a short look, then the facts
    if (b) showSkipMenu(false);
    updateLocks();
    if (b) setTimeout(updateLocks, 40500);
  }
  // waitTurn: for choose / skip the wait ends when the station changes (a quiet slider answer in between does not count)
  function setWaiting(on, label, waitTurn = null) {
    st.waiting = !!on; root.classList.toggle('waiting', st.waiting); clearTimeout(st.waitTimer); clearTimeout(st.softTimer);
    st.waitTurn = st.waiting ? waitTurn : null;
    if (st.waiting) {
      showSkipMenu(false);
      st.waitSeq = st.P ? num(st.P.seq, -1) : -1; st.waitPhase = st.P ? st.P.phase : null;
      R.waitLabel.textContent = label || WAIT_TXT[Math.floor(Math.random() * WAIT_TXT.length)];
      st.waitTimer = setTimeout(() => { if (st.waiting) { setWaiting(false); toast('⏳ No answer – please try again', 3200); } }, 25000);
    }
    updateLocks();
  }
  function act(value, label) {
    if (st.waiting) return;
    const labels = { start: 'Preparing your life', restart: 'A new life is waiting', analyse: 'Opening your life review',
                     skip: 'Fast-forwarding your life' };
    const play = st.P && st.P.phase === 'play' && st.P.play;
    const waitTurn = play && (value.action === 'choose' || value.action === 'skip') ? num(play.turn) : null;
    setWaiting(true, label || labels[value.action], waitTurn);
    try { send(value); } catch (e) { console.warn('[game] send failed', e); setWaiting(false); }
  }

  /* ---------------------------------------------------------------- events */
  root.addEventListener('click', ev => {
    if (st.skipOpen && !ev.target.closest('.skipbox')) showSkipMenu(false);
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
      case 'ex': {
        const ex = st.P && st.P.boot && st.P.boot.example;
        if (ex && ex.ist) { st.ist = { ...ex.ist }; fillIst(); renderStartPanel(); toast(`📋 Example data loaded (${ex.name}) – adjust it as you like`, 2600); }
        break;
      }
      case 'start': startGame(); break;
      case 'selcat':
        if (st.selCat === b.dataset.k) st.trayOpen = !st.trayOpen; else { st.selCat = b.dataset.k; st.trayOpen = true; }
        R.cats.querySelectorAll('.cat').forEach(el => el.classList.toggle('sel', el.dataset.k === st.selCat));
        renderTray(); updateLocks(); break;
      case 'tray': st.trayOpen = false; renderTray(); break;
      case 'side': st.sideOpen = !st.sideOpen; renderSide(); break;
      case 'choose': if (!engineBusy()) chooseCard(b.dataset.k); break;
      case 'pstep': {
        const c = cardByKey(b.dataset.k), p = c && (c.params || {})[b.dataset.n]; if (!p) break;
        const cur = paramValues(c)[b.dataset.n], step = num(p.step, 0) > 0 ? +p.step : 1;
        setParam(b.dataset.k, b.dataset.n, cur + step * (+b.dataset.d < 0 ? -1 : 1)); break;
      }
      case 'skipMenu': showSkipMenu(!st.skipOpen); break;
      case 'skip': doSkip(+b.dataset.i); break;
      case 'stay': if (!engineBusy()) act({ action: 'choose', key: ((st.P && st.P.play && st.P.play.stay) || {}).key || 'stay' }); break;
      case 'toFacts': go('facts'); break;
      case 'restart': act({ action: 'restart' }); break;
      case 'skipIntro': skipIntro(); break;
    }
  });
  // card sliders: live label, debounced quiet update; no tray rebuild while a slider is being dragged
  root.addEventListener('input', ev => {
    const r = ev.target.closest && ev.target.closest('input[data-pk]'); if (!r) return;
    setParam(r.dataset.pk, r.dataset.pn, +r.value, r);
  });
  root.addEventListener('pointerdown', ev => { if (ev.target.closest && ev.target.closest('input[data-pk]')) st.dragging = true; });
  const endDrag = () => { if (!st.dragging) return; st.dragging = false; if (st.trayDirty && st.screen === 'play') renderTray(); };
  window.addEventListener('pointerup', endDrag); window.addEventListener('pointercancel', endDrag); window.addEventListener('blur', endDrag);
  R.name.addEventListener('input', () => { st.cfg = { ...st.cfg, name: R.name.value.slice(0, 16) }; st.touched = true; });
  R.name.addEventListener('keydown', ev => { if (ev.key === 'Enter') R.name.blur(); });
  R.istForm.addEventListener('input', ev => {
    const el = ev.target.closest('[data-ist]'); if (!el) return;
    st.ist = readIst();
  });
  window.addEventListener('keydown', ev => {
    if (ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    if (st.intro && (ev.key === 'Enter' || ev.key === 'Escape' || ev.key === ' ')) { skipIntro(); ev.preventDefault(); return; }
    if (st.skipOpen && ev.key === 'Escape') { showSkipMenu(false); ev.preventDefault(); return; }
    if (st.screen === 'finale' && (ev.key === ' ' || ev.key === 'Enter' || ev.key === 'Escape')) { go('facts'); ev.preventDefault(); return; }
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
    settleParams();
    if (p.phase !== 'play') { st.lp = {}; st.updating = {}; st.skipOpen = false; }
    if (st.waiting && (num(p.seq, -1) > st.waitSeq || p.phase !== st.waitPhase)) {
      const turnNow = p.play ? num(p.play.turn) : null;
      if (st.waitTurn === null || p.phase !== st.waitPhase || p.error || turnNow !== st.waitTurn) setWaiting(false);
      else { clearTimeout(st.softTimer); st.softTimer = setTimeout(() => { if (st.waiting) setWaiting(false); }, 4000); }
    }
    if (p.error) setTimeout(() => toast('⚠️ ' + p.error, 5000), 300);
    if (p.avatar && typeof p.avatar === 'object' && !st.touched) st.cfg = { ...DEFAULT_CFG, ...p.avatar };
    if (st.loaded) route();
  }
  startLoading();
  return { render, toast, setBusy, setWaiting, intro, get screen() { return st.screen; } };
}
