// In-game UI: screens (Loading → Title → Creator → Play → Life summary → Financial facts), HUD, toasts, popups.
// Talks to the 3D engine via its public API (CONTRACT.md) and to Python via the `send` callback from main.js.
import { showCreator, setCreator, showWorld } from './engine.js';
import { OPTIONS, CAT_LABEL, NICE, DEFAULT_CFG, SKINS, HAIRC, COLORS } from './core.js';

/* =================================================================== helpers */
const TIPS = [
  'Früh anfangen lohnt sich: Der Zinseszins liebt Geduld.',
  'Ein Notgroschen von 3–6 Monatsausgaben schützt vor teuren Krediten.',
  'Konsumkredite und Kreditkarten kosten schnell 10 % Zins und mehr.',
  'Breit gestreute ETFs verteilen das Risiko auf hunderte Firmen.',
  'Säule 3a: Steuern sparen und gleichzeitig fürs Alter vorsorgen.',
  'Mehr Lohn heisst nicht automatisch mehr ausgeben – Vorsicht vor Lifestyle-Inflation.',
  'Wer seine Ausgaben kennt, kann sie steuern: Ein Budget wirkt Wunder.',
  'Schwankungen gehören zum Anlegen – wer lange dabeibleibt, gewinnt oft.',
  'Erst Schulden mit hohem Zins abbauen, dann investieren.',
  'Kleine Beträge, regelmässig gespart, werden über Jahre gross.',
];
const WAIT_TXT = ['Das Leben würfelt', 'Die Zukunft wird simuliert', 'Tausend Leben werden durchgerechnet', 'Der Zufall mischt die Karten'];

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
const chfShort = v => 'CHF ' + kfmt(v);
const chfShortSigned = v => (num(v) < -0.5 ? '−' : '+') + 'CHF ' + kfmt(Math.abs(num(v)));
const signed = v => (num(v) > 0 ? '+' : num(v) < 0 ? '−' : '±') + Math.abs(Math.round(num(v)));
const safeColor = (c, d = '#2f7bff') => (typeof c === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : d;
const nice = v => { const s = NICE[v] || String(v ?? ''); return s.charAt(0).toUpperCase() + s.slice(1); };
const arr = v => Array.isArray(v) ? v : [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
// Ist-Zustand form (start panel): field, label, kind
const IST_FIELDS = [
  ['age', 'Alter', 'int'], ['status', 'Situation', 'status'],
  ['income', 'Netto-Einkommen / Monat', 'chf'], ['expenses', 'Ausgaben / Monat (alles)', 'chf'],
  ['rent', 'davon Miete / Monat', 'chf'], ['cash', 'Konto & Bargeld', 'chf'],
  ['portfolio', 'Anlagen (Wertschriften)', 'chf'], ['debt', 'Schulden / Kredite', 'chf'],
];
function profileEmoji(status, i) {
  const s = String(status || '').toLowerCase();
  if (/lehre|ausbildung/.test(s)) return '🧰';
  if (/stud|uni|hochschule/.test(s)) return '📚';
  if (/schul|gymi|gymnas/.test(s)) return '🎒';
  if (/selbst|gründ/.test(s)) return '🚀';
  if (/arbeitslos|such/.test(s)) return '🔎';
  if (/teilzeit/.test(s)) return '⏳';
  if (/angestellt|job|beruf|arbeit/.test(s)) return '💼';
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
  if (n < 2) return msg('Noch keine Daten');
  const A = k => { const a = arr(fan[k]); return Array.from({ length: n }, (_, i) => (a[i] === null || a[i] === undefined || !Number.isFinite(+a[i])) ? null : +a[i]); };
  const past = A('past'), p5 = A('p5'), p50 = A('p50'), p95 = A('p95'), lazy = opt.lazy ? A('lazy') : null;
  let lastPast = 0; past.forEach((v, i) => { if (v !== null) lastPast = i; });
  const ni = clamp(Number.isFinite(+fan.now_index) && fan.now_index !== null ? Math.round(+fan.now_index) : lastPast, 0, n - 1);
  const bf = ni >= n - 1 ? 0 : ni;
  const vals = [];
  past.forEach((v, i) => { if (v !== null && i <= ni) vals.push(v); });
  for (let i = bf; i < n; i++) for (const v of [p5[i], p50[i], p95[i]]) if (v !== null) vals.push(v);
  if (lazy) lazy.forEach(v => { if (v !== null) vals.push(v); });
  if (!vals.length) return msg('Noch keine Daten');
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
    g.fillText(`${num(ages[i])} J.`, clamp(x, L + 10, W - R - 12), H - B / 2 + 2);
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
    ist: null, istBuilt: false, styleHinted: false, selCat: null, trayOpen: true, sideOpen: window.innerWidth >= 1150,
    busy: false, busySince: 0, waiting: false, waitSeq: -1, waitPhase: null, waitTimer: 0,
    enginePhase: null, celebrated: new Set(), celPending: null,
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
      <p class="tip"><b>TIPP</b> <span></span></p>
    </div>
  </section>

  <section class="screen scr-title" data-s="title">
    <h1 class="logo logo-md"><span class="l1">YOUR LIFE ·</span><span class="l2">YOUR CHOICE</span></h1>
    <p class="tagline ol">Triff Entscheidungen. Erlebe die Folgen.</p>
    <div class="title-btns pe">
      <button class="btn btn-xl btn-green" data-act="toCreator">SPIELEN</button>
      <button class="btn btn-lg btn-blue" data-act="analyse" data-wlock>ANALYSE</button>
    </div>
    <div class="hint">Figur ziehen zum Drehen · Enter zum Spielen</div>
  </section>

  <section class="screen scr-creator" data-s="creator">
    <div class="cr-left">
      <div class="cr-top pe"><button class="btn-round sm blue" data-act="toTitle" title="Zurück">◀</button><h2 class="hdr ol">DEINE FIGUR</h2></div>
      <div class="chips pe"></div>
      <button class="btn-round big arrow left pe" data-act="prev" title="Vorherige Option (←)">◀</button>
      <button class="btn-round big arrow right pe" data-act="next" title="Nächste Option (→)">▶</button>
      <div class="plate pe"><div class="plate-cat"></div><div class="plate-val"></div><div class="pips"></div></div>
      <div class="namebar pe">
        <div class="namefield"><label for="ylyc-name">NAME</label><input id="ylyc-name" maxlength="16" autocomplete="off" spellcheck="false" placeholder="Dein Name"></div>
        <button class="btn-round dicebtn" data-act="rand" title="Zufällige Figur"><span>🎲</span></button>
      </div>
    </div>
    <aside class="cr-panel pe">
      <div class="panel-head"><span class="ol">DEIN START</span></div>
      <div class="panel-body">
        <h3 class="sec">1 · Wo stehst du heute?</h3>
        <p class="ist-note">Trag deine aktuellen Zahlen ein – oder übernimm ein Beispiel und pass es an.</p>
        <div class="ist-ex"></div>
        <h3 class="sec">2 · Dein Ist-Zustand</h3>
        <div class="ist-form"></div>
        <p class="ist-note">📊 Deinen Anlagestil wählst du später im Spiel – ab Station 2 unter „Geld“.</p>
      </div>
      <div class="panel-foot"><button class="btn btn-xl btn-pink w100" data-act="start" data-wlock>LOSFAHREN</button></div>
    </aside>
  </section>

  <section class="screen scr-play" data-s="play">
    <header class="hud pe"></header>
    <aside class="side pe"><div class="side-inner">
      <h3>🎯 Ziele</h3><div class="quests"></div>
      <h3>🏆 Erfolge <small class="achn"></small></h3><div class="achs"></div>
      <h3>📈 Dein Vermögen</h3><div class="fanbox"><canvas class="fan-play"></canvas></div>
      <div class="legend"><span><i style="border-color:#ff3d8b"></i>bisher</span><span><i class="dash" style="border-color:#2f7bff"></i>Median</span><span><i class="band"></i>p5–p95</span></div>
      <h3 class="hist-h">🧭 Deine Stationen</h3><div class="hist"></div>
    </div></aside>
    <div class="tray pe"><div class="tray-head"></div><div class="tray-row"></div></div>
    <div class="busy-pill">🎬 Das Leben passiert …</div>
    <footer class="dock pe"><div class="cats"></div>
      <button class="btn btn-yellow btn-go" data-act="stay" data-lock>WEITERFAHREN</button>
    </footer>
  </section>

  <section class="screen scr-summary" data-s="summary">
    <div class="res-panel pe">
      <div class="res-tag">RESULTS</div>
      <h2 class="res-h ol">LIFE SUMMARY</h2>
      <div class="res-sub"></div>
      <div class="res-stats"></div>
      <div class="res-list"></div>
      <div class="res-foot"><button class="btn btn-lg btn-green" data-act="toFacts">WEITER ▶</button></div>
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
          <div class="tile chart"><div class="k">📈 Dein Leben vs. nur weitergefahren</div>
            <div class="fanbox"><canvas class="fan-end"></canvas></div>
            <div class="legend"><span><i style="border-color:#ff3d8b"></i>dein Leben</span><span><i class="dash" style="border-color:#2f7bff"></i>Median</span><span><i class="band"></i>Spanne p5–p95</span><span><i style="border-color:#9a94b8"></i>nur weitergefahren</span></div>
          </div>
        </div>
      </div>
      <p class="disclaimer"></p>
      <div class="res-foot">
        <button class="btn btn-sm btn-purple" data-act="toSummary">◀ ZURÜCK</button>
        <button class="btn btn-lg btn-pink" data-act="restart" data-wlock>NOCHMAL SPIELEN</button>
        <button class="btn btn-lg btn-blue" data-act="analyse" data-wlock>ANALYSE</button>
      </div>
    </div>
  </section>

  <div class="toasts"></div>
  <div class="waitbox"><div class="wcard"><span class="dice">🎲</span><span class="wtxt"><span class="wlabel"></span><span class="wdots"></span></span></div></div>
  <div class="celebrate"><div class="confetti"></div><div class="cel-card">
    <h3 class="cel-h ol">ERFOLG FREIGESCHALTET!</h3><div class="cel-list"></div>
    <button class="btn btn-lg btn-yellow" data-act="celClose">SUPER!</button></div></div>`;

  const $ = s => root.querySelector(s);
  const screens = {}; root.querySelectorAll('.screen').forEach(el => { screens[el.dataset.s] = el; });
  const R = {
    loadBar: $('.loadbar i'), loadPct: $('.load-pct'), tip: $('.tip'), tipTxt: $('.tip span'),
    chips: $('.chips'), plateCat: $('.plate-cat'), plateVal: $('.plate-val'), pips: $('.pips'), name: $('#ylyc-name'),
    istEx: $('.ist-ex'), istForm: $('.ist-form'),
    hud: $('.hud'), side: $('.side'), quests: $('.quests'), achs: $('.achs'), achn: $('.achn'), fanPlay: $('.fan-play'), hist: $('.hist'), histH: $('.hist-h'),
    tray: $('.tray'), trayHead: $('.tray-head'), trayRow: $('.tray-row'), cats: $('.cats'),
    resSub: $('.res-sub'), resStats: $('.res-stats'), resList: $('.res-list'),
    factsTiles: $('.facts-tiles'), gauge: $('.gauge'), fanEnd: $('.fan-end'), disclaimer: $('.disclaimer'),
    toasts: $('.toasts'), waitLabel: $('.wlabel'), cel: $('.celebrate'), celList: $('.cel-list'), confetti: $('.confetti'),
  };
  if (fanRO) { fanRO.observe(R.fanPlay); fanRO.observe(R.fanEnd); }

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
      if (!haveP && el > MIN + 400 && !connectMsg) { connectMsg = true; showTip('Verbinde mit der Simulation …'); }
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
    const profiles = arr(boot.profiles), statuses = arr(boot.statuses);
    if (!st.ist && boot.ist) st.ist = { ...boot.ist };
    R.istEx.innerHTML = profiles.length ? profiles.map((p, i) => `
      <button class="exchip ${st.ist && st.ist.basis === p.id ? 'on' : ''}" data-act="ex" data-id="${esc(p.id)}"
        title="${esc(`Start: ${chf(p.start_capital)} · pro Monat: ${chfSigned(p.typical_month)}`)}">
        <span class="e">${profileEmoji(p.status_de, i)}</span><span><b>${esc(p.name)}${p.age !== undefined && p.age !== null ? ' · ' + num(p.age) : ''}</b><small>${esc(p.status_de || '')}</small></span>
      </button>`).join('') : '<div class="empty">Beispiele werden geladen …</div>';
    if (!st.istBuilt && statuses.length) {
      R.istForm.innerHTML = IST_FIELDS.map(([k, label, kind]) => `
        <label class="ist-f ${kind === 'status' ? 'wide' : ''}"><span>${esc(label)}</span>${kind === 'status'
          ? `<select data-ist="${k}">${statuses.map(o => `<option value="${esc(o.key)}">${esc(o.label)}</option>`).join('')}</select>`
          : `<span class="inp">${kind === 'chf' ? '<i>CHF</i>' : ''}<input data-ist="${k}" type="number" inputmode="numeric" min="${kind === 'int' ? 15 : 0}" max="${kind === 'int' ? 70 : 9999999}" step="${kind === 'int' ? 1 : 50}"></span>`}
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
  function startGame() {
    const name = String(R.name.value || st.cfg.name || '').trim().slice(0, 16) || 'Alex';
    st.cfg = { ...st.cfg, name }; R.name.value = name;
    st.ist = readIst(); st.styleHinted = false;
    act({ action: 'start', avatar: { ...st.cfg }, ist: { ...st.ist } });
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
        <span class="big">${esc(name)}</span><span class="sub">· ${num(h.age, num(play.age))} J.</span></div>
      <div class="pill style" title="Anlagestil (ab Station 2 unter Geld wählbar)"><span class="ico">📊</span><span class="sub">Anlagestil</span><span class="big">${esc(h.style_de || 'noch offen')}</span></div>
      <div class="pill money" title="Nettovermögen"><span class="ico">💰</span><span class="big ${nw < 0 ? 'neg' : ''}">${chf(nw)}</span></div>
      <div class="pill" title="Lebensfreude"><span class="ico">${esc(h.joy_emoji || '🙂')}</span><span class="big">${Math.round(num(h.joy))}</span></div>
      <div class="pill" title="Erfolge"><span class="ico">🏆</span><span class="big">${num(h.achievements_got)}/${num(h.achievements_total)}</span></div>
      <div class="grow"></div>
      <div class="pill station"><span class="big">Station ${clamp(turn + 1, 1, K)}/${K}</span>${h.state_de ? `<span class="sub">${esc(h.state_de)}</span>` : ''}</div>
      <button class="btn-round sm blue" data-act="side" title="Ziele, Erfolge & Vermögen">📊</button>`;

    // categories
    const cats = arr(play.categories);
    // the investment style is asked later (from station 2): jump to its category once and say why
    if (play.focus_cat && !st.styleHinted && cats.some(c => c.key === play.focus_cat)) {
      st.styleHinted = true; st.selCat = play.focus_cat; st.trayOpen = true;
      if (play.hint) setTimeout(() => toast(play.hint, 4200), 400);
    }
    if (!cats.some(c => c.key === st.selCat)) { const f = cats.find(c => num(c.open) > 0) || cats[0]; st.selCat = f ? f.key : null; }
    R.cats.innerHTML = cats.map((c, i) => `
      <button class="mcard cat ${c.key === st.selCat ? 'sel' : ''}" data-act="selcat" data-k="${esc(c.key)}" style="--cc:${safeColor(c.color)}" title="${esc(c.label)} (Taste ${i + 1})">
        <span class="badge ${num(c.open) ? '' : 'zero'}">${num(c.open)}</span>
        <div class="mh">${esc(c.label)}</div><div class="mb"><div class="emo">${esc(c.emoji)}</div></div>
      </button>`).join('');
    renderTray(); renderSide(); updateLocks();
  }
  function renderTray() {
    const play = (st.P && st.P.play) || {};
    const cat = arr(play.categories).find(c => c.key === st.selCat);
    const ageEnd = num(play.start_age, 20) + num(play.K, 15);
    const cards = arr(play.cards).filter(c => c.cat === st.selCat).sort((a, b) => (a.locked ? 1 : 0) - (b.locked ? 1 : 0));
    R.trayHead.innerHTML = cat ? `<span class="tray-title ol">${esc(cat.emoji)} ${esc(cat.label)}</span>
      <button class="btn-round sm" data-act="tray" title="Karten ein-/ausklappen">▾</button>` : '';
    const color = safeColor(cat && cat.color);
    R.trayRow.innerHTML = cards.length ? cards.map((c, i) => decisionCard(c, ageEnd, i, color)).join('')
      : `<div class="tray-empty">Hier ist gerade nichts offen – wähle eine andere Kategorie oder fahr weiter.</div>`;
    R.tray.classList.toggle('hide', !st.trayOpen || !cat || st.busy);
  }
  function decisionCard(c, ageEnd, i, color) {
    const locked = !!c.locked;
    const chips = [];
    if (num(c.joy)) chips.push(`<span class="chip2 ${num(c.joy) > 0 ? 'pos' : 'neg'}" title="Lebensfreude">😊 ${signed(c.joy)}</span>`);
    if (c.delta !== undefined && c.delta !== null) chips.push(`<span class="chip2 ${num(c.delta) >= 0 ? 'pos' : 'neg'}" title="Unterschied zu „nur weitergefahren“ mit ${ageEnd}">💰 ${chfShortSigned(c.delta)}</span>`);
    if (c.credit !== undefined && c.credit !== null && Number.isFinite(+c.credit)) {
      const cr = Math.round(clamp(+c.credit, 0, 1) * 100);
      chips.push(`<span class="chip2 ${cr >= 50 ? 'neg' : ''}" title="Wahrscheinlichkeit, einen Kredit zu brauchen">💳 ${cr} %</span>`);
    }
    const proj = (c.median !== undefined && c.median !== null) ? `<div class="proj">Mit ${ageEnd}: <b>${chf(c.median)}</b><br>Spanne ${chfShort(c.p5)} – ${kfmt(c.p95)}</div>` : '';
    const reason = typeof c.locked === 'string' && c.locked.trim() ? c.locked : 'Noch gesperrt';
    const foot = locked ? `<div class="lockbox">🔒 ${esc(reason)}</div>`
      : `<button class="btn btn-green" data-act="choose" data-k="${esc(c.key)}" data-lock>WÄHLEN</button>`;
    return `<div class="dcard ${locked ? 'locked' : ''}" style="--rc:${color};animation-delay:${Math.min(i, 8) * 55}ms">
      <div class="band"><span>${esc(c.emoji || '🃏')}</span></div>
      <h4>${esc(c.title)}</h4><p>${esc(c.text || '')}</p>
      <div class="chips2">${chips.join('')}</div>${proj}${foot}</div>`;
  }
  function renderSide() {
    const play = (st.P && st.P.play) || {};
    R.side.classList.toggle('closed', !st.sideOpen); root.classList.toggle('play-side-open', st.sideOpen);
    const qs = arr(play.quests);
    R.quests.innerHTML = qs.length ? qs.map(q => {
      const pct = Math.round(clamp(num(q.progress, num(q.target) ? num(q.current) / num(q.target) : 0), 0, 1) * 100);
      return `<div class="quest ${q.done ? 'done' : ''}"><div class="qt"><span>${q.done ? '✅ ' : ''}${esc(q.name)}</span><span>${pct} %</span></div>
        <div class="qbar"><i style="width:${pct}%"></i></div>
        <div class="qs">${chf(q.current)} / ${chf(q.target)}${q.by_age !== undefined && q.by_age !== null ? ` · bis ${num(q.by_age)}` : ''}</div></div>`;
    }).join('') : '<div class="qs">Keine Ziele aktiv.</div>';
    const achs = arr(play.achievements);
    R.achn.textContent = `${achs.filter(a => a.got).length}/${achs.length}`;
    R.achs.innerHTML = achs.map(a => `<div class="ach ${a.got ? '' : 'off'}" data-t="${esc(a.title)}" title="${esc(a.title)}">${esc(a.emoji || '🏅')}</div>`).join('');
    const hist = arr(play.history);
    R.histH.style.display = hist.length ? '' : 'none';
    R.hist.innerHTML = hist.map(x => `<span title="${esc(`${num(x.age)} J. · ${x.title || ''}`)}">${esc(x.emoji || '•')}</span>`).join('');
    if (play.fan) requestAnimationFrame(() => drawFan(R.fanPlay, play.fan, { small: true }));
  }

  /* ---------------------------------------------------------------- end: summary + facts */
  function renderSummary() {
    const end = (st.P && st.P.end) || {}, s = end.summary || {};
    const stars = clamp(Math.round(num(s.stars)), 0, 5);
    R.resSub.textContent = `${s.name || st.cfg.name || 'Alex'} · Leben bis ${num(s.age_end)}`;
    R.resStats.innerHTML = `
      <div class="stat"><div class="k">Score</div><div class="v">${grp(s.score)}</div><div class="s">Punkte</div></div>
      <div class="stat"><div class="k">Sterne</div><div class="v stars">${'★'.repeat(stars)}<span class="off">${'★'.repeat(5 - stars)}</span></div><div class="s">${stars} von 5</div></div>
      <div class="stat"><div class="k">Lebensfreude</div><div class="v">${esc(s.joy_emoji || '🙂')} ${Math.round(num(s.joy))}</div><div class="s">von 100</div></div>
      <div class="stat"><div class="k">Anlagestil</div><div class="v">📊</div><div class="s">${esc(s.style_de || 'nie festgelegt')}</div></div>`;
    const ch = arr(s.choices);
    R.resList.innerHTML = ch.length ? ch.map((c, i) => {
      const d = c.delta === undefined || c.delta === null ? null : num(c.delta);
      return `<div class="rrow" style="animation-delay:${Math.min(i, 14) * 70}ms">
        <span class="age">${num(c.age)} J.</span><span class="e">${esc(c.emoji || '🃏')}</span>
        <div class="tt"><b>${esc(c.title)}</b><span>${esc(c.cat_label || '')}</span></div>
        <div class="reward ${d !== null && d < 0 ? 'lg' : ''}" title="Unterschied zu „nur weitergefahren“ (Median, Zeitpunkt der Entscheidung)">${d === null ? '–' : '💰 ' + chfShortSigned(d)}</div></div>`;
    }).join('') : '<div class="res-empty">Du bist einfach immer weitergefahren. Auch das ist eine Strategie! 🚗</div>';
  }
  function renderFacts() {
    const end = (st.P && st.P.end) || {}, f = end.facts || {}, s = end.summary || {};
    const nw = num(f.net_worth), lazy = num(f.lazy_median), diff = nw - lazy, best = f.best || null;
    const tile = (k, v, sub = '', cls = '') => `<div class="tile ${cls}"><div class="k">${k}</div><div class="v">${v}</div>${sub ? `<div class="s">${sub}</div>` : ''}</div>`;
    R.factsTiles.innerHTML = [
      tile('💰 Nettovermögen', chf(nw), `mit ${num(s.age_end) || num(arr((f.fan || {}).ages).slice(-1)[0])} Jahren`, 'hero'),
      tile('🚗 vs. nur weitergefahren', chfSigned(diff), `nur weitergefahren: ${chf(lazy)}`, diff >= 0 ? 'good' : 'bad'),
      tile('📏 Spanne p5–p95', `${kfmt(f.p5)} – ${kfmt(f.p95)}`, '90 % der simulierten Leben'),
      tile('💵 Cash', chf(f.cash)),
      tile('📈 Portfolio', chf(f.portfolio)),
      tile('🏡 Wohneigentum', chf(f.house_equity)),
      tile('🧾 Schulden', chf(f.debt), '', num(f.debt) > 0 ? 'bad' : ''),
      tile('💳 Höchster Kredit', chf(f.max_credit)),
      tile('📅 Monate mit Kredit', grp(f.months_with_credit), num(f.months_with_credit) ? 'Monate im Minus' : 'nie im Minus 🎉'),
      tile('🃏 Entscheidungen', grp(f.decisions)),
      tile('🌟 Beste Entscheidung', best ? esc(best.title) : '–', best ? chfSigned(best.delta) : '', 'good'),
    ].join('');
    const pct = clamp(Math.round(num(f.percentile)), 0, 100);
    R.gauge.innerHTML = `${gaugeSvg(pct)}<div><div class="k">🏁 Perzentil</div><div class="gv">${pct}.</div>
      <div class="gs">Besser als ${pct} % der simulierten Leben</div></div>`;
    R.disclaimer.textContent = f.disclaimer || 'Synthetische Daten · keine Prognose · keine Anlageberatung';
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
    if (!list.length || st.celebrated.has(p.seq)) return;
    st.celebrated.add(p.seq); st.celPending = list;
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
  function setWaiting(on, label) {
    st.waiting = !!on; root.classList.toggle('waiting', st.waiting); clearTimeout(st.waitTimer);
    if (st.waiting) {
      st.waitSeq = st.P ? num(st.P.seq, -1) : -1; st.waitPhase = st.P ? st.P.phase : null;
      R.waitLabel.textContent = label || WAIT_TXT[Math.floor(Math.random() * WAIT_TXT.length)];
      st.waitTimer = setTimeout(() => { if (st.waiting) { setWaiting(false); toast('⏳ Keine Antwort – bitte nochmal versuchen', 3200); } }, 25000);
    }
    updateLocks();
  }
  function act(value, label) {
    if (st.waiting) return;
    const labels = { start: 'Dein Leben wird vorbereitet', restart: 'Ein neues Leben wartet', analyse: 'Analyse wird geöffnet' };
    setWaiting(true, label || labels[value.action]);
    try { send(value); } catch (e) { console.warn('[game] send failed', e); setWaiting(false); }
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
      case 'ex': {
        const pr = arr(st.P && st.P.boot && st.P.boot.profiles).find(p => p.id === b.dataset.id);
        if (pr && pr.ist) { st.ist = { ...pr.ist }; fillIst(); renderStartPanel(); }
        break;
      }
      case 'start': startGame(); break;
      case 'selcat':
        if (st.selCat === b.dataset.k) st.trayOpen = !st.trayOpen; else { st.selCat = b.dataset.k; st.trayOpen = true; }
        R.cats.querySelectorAll('.cat').forEach(el => el.classList.toggle('sel', el.dataset.k === st.selCat));
        renderTray(); updateLocks(); break;
      case 'tray': st.trayOpen = false; renderTray(); break;
      case 'side': st.sideOpen = !st.sideOpen; renderSide(); break;
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
  R.istForm.addEventListener('input', ev => {
    const el = ev.target.closest('[data-ist]'); if (!el) return;
    st.ist = readIst();
  });
  window.addEventListener('keydown', ev => {
    if (ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
    if (R.cel.classList.contains('on') && (ev.key === 'Enter' || ev.key === 'Escape' || ev.key === ' ')) { closeCelebration(); ev.preventDefault(); return; }
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
    if (st.waiting && (num(p.seq, -1) > st.waitSeq || p.phase !== st.waitPhase)) setWaiting(false);
    if (p.avatar && typeof p.avatar === 'object' && !st.touched) st.cfg = { ...DEFAULT_CFG, ...p.avatar };
    if (st.loaded) route();
  }
  startLoading();
  return { render, toast, setBusy, setWaiting, get screen() { return st.screen; } };
}
