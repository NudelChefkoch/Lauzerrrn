// Entry point: Streamlit bridge (component modes "game" and "podium") + standalone DEMO mode (python3 -m http.server;
// index.html?mode=podium shows the podium mode).
import { initEngine, setToastHandler, setBusyHandler, setIntroHandler, skipIntro, showPodium } from './engine.js';
import { DEFAULT_CFG } from './core.js';
import { createUI } from './ui.js';

const STANDALONE = (() => { try { return window.parent === window; } catch (e) { return false; } })();
const DEMO_MODE = (() => { try { return new URLSearchParams(location.search).get('mode') || 'game'; } catch (e) { return 'game'; } })();

/* =================================================================== engine (UI is created once the mode is known) */
const stage = document.getElementById('stage');
let engineOk = false;
try { initEngine(stage); engineOk = true; } catch (e) { console.warn('[game] 3D engine unavailable – UI runs without 3D', e); }

let lastNonce = 0;
const nextNonce = () => (lastNonce = Math.max(Date.now(), lastNonce + 1));
let ui = null, mode = null;
// the game UI (loading → title → creator → play → facts); built on the first "game" render (or at once in the demo)
function gameUI() {
  if (ui) return ui;
  mode = 'game';
  ui = createUI(document.getElementById('ui'), { send, engineOk, standalone: STANDALONE, onSkipIntro: () => { try { skipIntro(); } catch (e) { /* engine missing */ } } });
  try { setToastHandler((text, ms) => ui.toast(text, ms)); setBusyHandler(b => ui.setBusy(b)); setIntroHandler((step, data) => ui.intro(step, data)); } catch (e) { /* engine missing */ }
  return ui;
}

/* =================================================================== podium mode (analysis page: the twin as the agent) */
// Only the 3D character on its podium + an optional speech bubble in the game's style. No other UI.
const POD = { cfg: null, bubble: null, el: null, txt: null, waved: false };
function podium(args) {
  mode = 'podium';
  document.body.dataset.screen = 'podium';
  if (!POD.el) {
    POD.el = document.createElement('div'); POD.el.className = 'pod-bubble'; POD.el.setAttribute('aria-live', 'polite');
    POD.txt = document.createElement('span'); POD.txt.className = 'pb-t'; POD.el.appendChild(POD.txt);
    document.getElementById('ui').appendChild(POD.el);
    if (!engineOk) { const f = document.createElement('div'); f.className = 'pod-fallback'; f.textContent = '🙂'; document.getElementById('ui').appendChild(f); }
  }
  const cfg = { ...DEFAULT_CFG, ...(args.avatar && typeof args.avatar === 'object' ? args.avatar : {}) };
  const bubble = typeof args.bubble === 'string' && args.bubble.trim() ? args.bubble.trim() : null;
  const said = bubble !== POD.bubble;
  // waves once when it appears, and again whenever it says something new
  if (engineOk) try { showPodium(cfg, { wave: !POD.waved || (said && !!bubble) }); } catch (e) { console.warn('[game] podium failed', e); }
  POD.waved = true; POD.cfg = cfg;
  if (said) {
    POD.bubble = bubble;
    POD.txt.textContent = bubble || '';
    POD.el.classList.remove('on', 'pop'); void POD.el.offsetWidth;
    if (bubble) POD.el.classList.add('on', 'pop');
  }
  if (!STANDALONE) {
    const h = Math.max(160, Math.round(+args.height || 420));
    if (h !== lastH) { lastH = h; post('streamlit:setFrameHeight', { height: h }); }
  }
}

/* =================================================================== Streamlit bridge */
function post(type, data = {}) {
  try { window.parent.postMessage({ isStreamlitMessage: true, type, ...data }, '*'); } catch (e) { console.warn('[game] postMessage failed', e); }
}
let lastPayload = null, lastH = 0;
function parentHeight() { try { const h = window.parent.innerHeight; return h > 200 ? h : 0; } catch (e) { return 0; } }
function setHeight() {
  if (STANDALONE || mode !== 'game') return;
  const h = Math.round(parentHeight() || +(lastPayload && lastPayload.height) || 860);
  if (Math.abs(h - lastH) < 1) return;
  lastH = h; post('streamlit:setFrameHeight', { height: h });
}

function send(value) {
  const v = { ...value, nonce: nextNonce() };
  if (STANDALONE) { demoSend(v); return; }
  post('streamlit:setComponentValue', { value: v, dataType: 'json' });
}

if (!STANDALONE) {
  window.addEventListener('message', ev => {
    if (ev.source && ev.source !== window.parent) return;
    const d = ev.data; if (!d || d.type !== 'streamlit:render') return;
    const args = d.args || {};
    if (args.mode === 'podium' && mode !== 'game') { podium(args); return; }
    if (args.mode && args.mode !== 'game') return;
    if (mode === 'podium') return;
    const p = args.payload; if (!p || typeof p !== 'object') return;
    lastPayload = p; gameUI(); setHeight(); ui.render(p);
  });
  try { window.parent.addEventListener('resize', setHeight); } catch (e) { /* cross-origin parent */ }
  window.addEventListener('resize', setHeight);
  post('streamlit:componentReady', { apiVersion: 1 });
}

/* =================================================================== DEMO (standalone, made-up numbers) */
// A small year-by-year model that mimics the Python backend closely enough to try every UI feature without Streamlit:
// graduation → "looking" (job or gap year), card sliders (child / house / monthly costs), SKIP, retire from 60.
const PROFILES = [
  { id: 'P00001', name: 'Alexia', age: 20, status: 'in education', start_capital: 8000.0, typical_month: -1030.9 },
  { id: 'P00002', name: 'Noah', age: 20, status: 'in education', start_capital: 3500.0, typical_month: -420.0 },
  { id: 'P00003', name: 'Lea', age: 24, status: 'employed', start_capital: 15000.0, typical_month: 850.5 },
  { id: 'P00004', name: 'Luca', age: 20, status: 'part-time', start_capital: 11000.0, typical_month: 310.0 },
];
const STATUSES = [{ key: 'student', label: 'in education' }, { key: 'employed', label: 'employed' },
  { key: 'part_time', label: 'part-time' }, { key: 'self_employed', label: 'self-employed' }, { key: 'unemployed', label: 'without a job' }];
PROFILES.forEach(p => {
  const student = /education/i.test(p.status), income = student ? 2200 : 5200;
  p.ist = { basis: p.id, age: p.age, status: student ? 'student' : 'employed', income, expenses: Math.round(income - p.typical_month),
            rent: student ? 900 : 1500, cash: p.start_capital, portfolio: 0, debt: 0 };
});
const CATS = [
  { key: 'education', label: 'Education', emoji: '🎓', color: '#2a78d6' },
  { key: 'career', label: 'Career', emoji: '💼', color: '#eb6834' },
  { key: 'housing', label: 'Housing', emoji: '🏡', color: '#1baf7a' },
  { key: 'family', label: 'Family', emoji: '👪', color: '#e87ba4' },
  { key: 'timeoff', label: 'Time off', emoji: '🏝️', color: '#eda100' },
];
const LIFE_END = 85, MAX_STATIONS = 70, RETIRE_FROM = 60, RETIRE_FORCED = 70, CHILD_MONTHS = 216;
const DEGREE = {
  bachelor: { name: "Bachelor's degree", salary: 5200, exp: 800, years: 3, fee: 1500, side: 0 },
  master: { name: "Master's degree", salary: 6300, exp: 1000, years: 2, fee: 1500, side: 0 },
  lehre: { name: 'Apprenticeship done', salary: 5000, exp: 600, years: 3, fee: 0, side: 900 },
};
const PARAMS = {
  child: { cost: { label: 'Cost per month', min: 300, max: 3000, step: 100, default: 1100, unit: 'CHF' } },
  buy_house: { price: { label: 'Price', min: 400000, max: 2000000, step: 50000, default: 850000, unit: 'CHF' } },
  costs: { delta: { label: 'Change per month', min: -2000, max: 2000, step: 100, default: -300, unit: 'CHF' } },
};
const r0 = v => Math.round(v);
const grpD = n => String(Math.round(Math.abs(n))).replace(/\B(?=(\d{3})+(?!\d))/g, "'");
const chfD = v => (v < -0.5 ? 'CHF −' : 'CHF ') + grpD(v);
const chfSignedD = v => (v < -0.5 ? '−' : '+') + 'CHF ' + grpD(v);
const catLabel = k => (CATS.find(c => c.key === k) || {}).label || k;
const ageOf = s => s.startAge + s.turn;
const studying = s => s.job === 'studying' ? 'You are studying right now' : null;
const lastDegree = s => ['master', 'bachelor', 'lehre'].find(d => s.degrees.includes(d)) || null;
const notRetired = s => s.job === 'retired' ? 'You are retired' : null;

// cards: lock(s, pv) → reason | null, text(s, pv), apply(s, pv, anim). once defaults to true. pv = chosen params.
const CARDS = [
  { key: 'bachelor', cat: 'education', emoji: '🎓', title: 'Bachelor',
    text: () => "3 years of uni, CHF 1'500 fees/year. Afterwards you look for a job (CHF 5'200 with the degree).",
    lock: s => (s.taken.includes('bachelor') || s.taken.includes('lehre')) ? 'Already done' : studying(s) || notRetired(s) || (ageOf(s) > 45 ? 'Only up to age 45' : null),
    apply: (s, pv, anim) => startStudy(s, 'bachelor') },
  { key: 'master', cat: 'education', emoji: '🎓', title: 'Master',
    text: () => "2 years, CHF 1'500/year. Afterwards you look for a job (CHF 6'300 with the degree).",
    lock: s => s.taken.includes('master') ? 'Already done' : studying(s) || notRetired(s) || (s.degrees.includes('bachelor') ? null : 'Finish a bachelor first'),
    apply: s => startStudy(s, 'master') },
  { key: 'lehre', cat: 'education', emoji: '🛠️', title: 'Apprenticeship',
    text: () => "3 years, apprentice pay CHF 900. Afterwards you look for a job (CHF 5'000 as a skilled worker).",
    lock: s => (s.taken.includes('bachelor') || s.taken.includes('lehre')) ? 'Already done' : studying(s) || (ageOf(s) > 25 ? 'Only up to age 25' : null),
    apply: s => startStudy(s, 'lehre') },
  { key: 'grad_job', cat: 'career', emoji: '💼', title: 'Job after your degree', once: false,
    text: s => { const d = DEGREE[lastDegree(s) || 'bachelor']; return `Start with ${chfD(d.salary)} net per month, own flat +${chfD(d.exp)}/month.`; },
    lock: s => studying(s) || (!s.degrees.length ? 'Finish a degree first' : null) || (s.job === 'employed' ? 'You already have a job' : null) || notRetired(s),
    apply: (s, pv, anim) => { const d = DEGREE[lastDegree(s) || 'bachelor']; s.job = 'employed'; s.salary = d.salary; s.ptf = 1; s.expenses += d.exp; s.life.suit = true; anim({ type: 'job', label: 'First job!' }); } },
  { key: 'job_start', cat: 'career', emoji: '🛒', title: 'Entry job',
    text: () => "Earn money now: CHF 4'300 net, own flat +CHF 800/month.",
    lock: s => studying(s) || (s.job === 'employed' ? 'You already have a job' : null) || (s.job === 'retired' ? 'Already retired' : null),
    apply: (s, pv, anim) => { s.job = 'employed'; s.salary = 4300; s.ptf = 1; s.expenses += 800; s.life.suit = true; anim({ type: 'job', label: 'First job!' }); } },
  { key: 'switch', cat: 'career', emoji: '🚀', title: 'Job change', once: false,
    text: () => '+15 % salary, 1 month without income in between.',
    lock: s => s.job === 'employed' ? null : 'Only with a job',
    apply: (s, pv, anim) => { s.salary *= 1.15; s.cash -= s.salary; anim({ type: 'job', label: 'New job!' }); } },
  { key: 'parttime', cat: 'career', emoji: '⏳', title: 'Part-time 80 %',
    text: () => '20 % less salary, more free time.',
    lock: s => s.job === 'employed' ? null : 'Only with a job',
    apply: s => { s.ptf = 0.8; } },
  { key: 'retire', cat: 'career', emoji: '🪑', title: 'Retire',
    text: () => 'AHV + pension fund: about 60 % of your last salary.',
    lock: s => s.job === 'retired' ? 'Already retired' : (ageOf(s) < RETIRE_FROM ? `From age ${RETIRE_FROM}` : null),
    apply: (s, pv, anim) => { retire(s); anim({ type: 'retirement', label: 'Retired!' }); } },
  { key: 'buy_house', cat: 'housing', emoji: '🏡', title: 'Buy a home', params: 'buy_house',
    text: (s, pv) => `${chfD(pv.price)} property – 20 % down payment, UBS mortgage at 2 %.`,
    lock: (s, pv) => { const need = pv.price * 0.22, have = Math.max(0, s.cash + s.portfolio);
      return have >= need ? null : `Needs ${chfD(need)} (20 % + 2 % fees) – you have ${chfD(have)}`; },
    apply: (s, pv, anim) => { const need = pv.price * 0.22; const fromCash = Math.min(Math.max(0, s.cash), need);
      s.cash -= fromCash; s.portfolio -= need - fromCash; s.house += pv.price * 0.2;
      s.expenses += r0(pv.price * 0.8 * 0.03 / 12) - 1000; anim({ type: 'house', label: 'Your own home!' }); } },
  { key: 'flat', cat: 'housing', emoji: '🛋️', title: 'Rent a luxury flat',
    text: () => 'Bigger, nicer, central: +CHF 900 rent per month.',
    lock: s => s.job === 'employed' || s.job === 'retired' ? null : 'Needs a steady income first',
    apply: s => { s.expenses += 900; } },
  { key: 'costs', cat: 'housing', emoji: '🧾', title: 'Adjust monthly costs', once: false, params: 'costs',
    text: (s, pv) => `From now on ${chfSignedD(pv.delta)} per month (today ${chfD(s.expenses)}).`,
    lock: (s, pv) => !pv.delta ? 'Pick a change first' : (s.expenses + pv.delta < 500 ? "Costs can't go below CHF 500/month" : null),
    apply: (s, pv) => { s.expenses = Math.max(500, s.expenses + pv.delta); } },
  { key: 'wedding', cat: 'family', emoji: '💍', title: 'Get married',
    text: () => "Celebration for CHF 20'000. Your partner joins you on the road.",
    lock: s => ageOf(s) >= 22 ? null : 'From age 22',
    apply: (s, pv, anim) => { s.cash -= 20000; s.life.partner = true; anim({ type: 'wedding' }); } },
  { key: 'child', cat: 'family', emoji: '👶', title: 'Have a child', once: false, params: 'child',
    text: (s, pv) => `CHF 3'000 birth, then ${chfD(pv.cost)}/month until your child turns 18.`,
    lock: s => ageOf(s) < 22 ? 'From age 22' : (s.life.kids >= 2 ? 'At most 2 children in the game' : null),
    apply: (s, pv, anim) => { s.cash -= 3000; s.expenses += pv.cost; s.life.kids += 1;
      s.planned.push({ turn: s.turn + CHILD_MONTHS / 12, kind: 'child_leaves', amount: pv.cost }); anim({ type: 'child' }); } },
  { key: 'gap_year', cat: 'timeoff', emoji: '🎒', title: 'Gap year', once: false,
    text: s => s.job === 'employed' ? '12 months off without pay, then the same job.' : '12 months off without pay – you keep looking afterwards.',
    lock: s => studying(s) || notRetired(s) || (s.gap > 0 ? 'You are already off' : null),
    apply: (s, pv, anim) => { s.gap = 1; anim({ type: 'gapyear', label: 'Gap year' }); } },
];
const CARD = Object.fromEntries(CARDS.map(c => [c.key, c]));

const D = { seq: 1, phase: 'boot', avatar: { ...DEFAULT_CFG }, s: null, prof: null };

function startStudy(s, deg) { const d = DEGREE[deg]; s.job = 'studying'; s.study = { degree: deg, end: s.turn + d.years }; s.side = d.side; s.fee = d.fee; }
function retire(s) { const last = s.job === 'employed' ? s.salary * s.ptf : s.lastSalary; s.pension = r0(0.6 * (last || 0)); s.job = 'retired'; s.gap = 0; }
function incomeOf(s) {
  if (s.gap > 0) return 0;
  return s.job === 'employed' ? s.salary * s.ptf : s.job === 'studying' ? s.side : s.job === 'retired' ? s.pension : 0;
}
const demoNW = s => s.cash + s.portfolio + s.house - s.debt;
function clone(s) { return JSON.parse(JSON.stringify(s)); }
function num0(v, d) { return Number.isFinite(+v) ? +v : d; }

// one year: money flows, then the planned events of the new station (degree, child moves out, forced retirement)
function advance(s, noise, anim) {
  const save = 12 * (incomeOf(s) - s.expenses) - (s.job === 'studying' ? s.fee : 0);
  if (s.gap > 0) s.gap -= 1;
  const toInv = save > 0 ? save * s.invest : 0;
  s.cash += save - toInv;
  s.portfolio = s.portfolio * (1 + s.ret + (noise ? (Math.random() - .5) * s.vol : 0)) + toInv;
  s.house *= 1.015;
  if (s.debt > 0) s.debt *= 1.07;
  if (s.cash < 0) {
    const need = -s.cash; s.debt += need; s.cash = 0;
    s.monthsCredit += Math.min(12, Math.max(1, Math.ceil(need / Math.max(1, s.expenses))));
  } else if (s.debt > 0) { const pay = Math.min(s.debt, s.cash * .6); s.debt -= pay; s.cash -= pay; }
  s.maxCredit = Math.max(s.maxCredit, s.debt);
  if (s.job === 'employed') { s.salary *= 1.02; s.lastSalary = s.salary * s.ptf; }
  s.expenses *= 1.01;
  s.turn += 1;
  const events = [];
  if (s.job === 'studying' && s.turn >= s.study.end) {
    const d = s.study.degree; s.job = 'looking'; s.side = 0; s.fee = 0;
    if (!s.degrees.includes(d)) s.degrees.push(d);
    events.push(DEGREE[d].name); anim({ type: 'graduation', label: DEGREE[d].name });
  }
  for (const e of s.planned.filter(e => e.turn === s.turn && e.kind === 'child_leaves')) {
    s.expenses = Math.max(800, s.expenses - e.amount); events.push('Your child moves out');
    anim({ type: 'child_leaves', label: 'Your child moves out' });
  }
  if (ageOf(s) >= RETIRE_FORCED && s.job !== 'retired') { retire(s); events.push('Retirement'); anim({ type: 'retirement', label: 'Retirement' }); }
  return events;
}
// prof = status quo from the start form (monthly CHF)
function demoState(prof) {
  const startAge = Math.max(15, Math.min(80, num0(prof.age, 20)));
  const st = prof.status, student = st === 'student';
  const s = {
    startAge, K: Math.max(1, Math.min(LIFE_END - startAge, MAX_STATIONS)), turn: 0, prevTurn: 0, skipped: 0,
    job: student ? 'studying' : st === 'unemployed' ? 'looking' : 'employed',
    salary: student ? 0 : num0(prof.income, 4000), ptf: st === 'part_time' ? 0.8 : 1, side: student ? num0(prof.income, 900) : 0,
    lastSalary: student ? 0 : num0(prof.income, 4000), pension: 0, fee: 0, gap: 0,
    study: student ? { degree: 'bachelor', end: 2 } : null, degrees: [], taken: student ? ['bachelor'] : [], planned: [],
    cash: num0(prof.cash, 0), portfolio: num0(prof.portfolio, 0), house: 0, debt: num0(prof.debt, 0), expenses: num0(prof.expenses, 2000),
    invest: .5, ret: .04, vol: .14, params: {},
    history: [], choices: [], anims: [], lastAnims: [], aid: 0, badges: {},
    life: { suit: !student && st !== 'unemployed', kids: 0, partner: false }, past: [], maxCredit: 0, monthsCredit: 0, best: null, lazy: [],
  };
  if (s.ptf < 1) s.salary = s.salary / s.ptf;   // the form shows the part-time pay
  return s;
}
const noAnim = () => {};
function demoLazy(prof) {
  const s = demoState(prof), out = [demoNW(s)];
  while (s.turn < s.K) { advance(s, false, noAnim); out.push(demoNW(s)); }
  return out;
}
function paramVals(s, c) {
  const def = PARAMS[c.params]; if (!def) return {};
  const cur = s.params[c.key] || {}, out = {};
  for (const [n, p] of Object.entries(def)) out[n] = snapD(p, cur[n] !== undefined ? cur[n] : p.default);
  return out;
}
function snapD(p, v) { const x = Math.max(p.min, Math.min(p.max, Number.isFinite(+v) ? +v : p.default)); return p.min + Math.round((x - p.min) / p.step) * p.step; }
function lockReason(c, s, pv) { return (c.once !== false && s.taken.includes(c.key)) ? 'Already done' : c.lock(s, pv || paramVals(s, c)); }
// deterministic projection to the end of life (median), with or without a card
function projectEnd(s, c, pv) {
  const x = clone(s); if (c) c.apply(x, pv, noAnim);
  while (x.turn < x.K) advance(x, false, noAnim);
  return { nw: demoNW(x), credit: x.monthsCredit > s.monthsCredit ? Math.min(1, (x.monthsCredit - s.monthsCredit) / 24) : 0 };
}
function cardPayload(s, c, base) {
  const pv = paramVals(s, c), lock = lockReason(c, s, pv);
  const out = { key: c.key, cat: c.cat, emoji: c.emoji, title: c.title, text: c.text(s, pv), locked: lock };
  if (c.params) out.params = Object.fromEntries(Object.entries(PARAMS[c.params]).map(([n, p]) => [n, { ...p, value: pv[n] }]));
  if (lock && !c.params) return out;          // locked cards preview only when a slider can unlock them (house price)
  const pr = projectEnd(s, c, pv), yrs = Math.max(1, s.K - s.turn), spread = Math.max(15000, Math.abs(pr.nw) * .2) * Math.sqrt(yrs / 20);
  const delta = r0(pr.nw - base);
  Object.assign(out, { impact: impactOf(delta, base), delta, median: r0(pr.nw), p5: r0(pr.nw - spread), p95: r0(pr.nw + spread * 1.35), credit: pr.credit });
  return out;
}
// same rule as twin/game.py impact(): grey only below 1 % of the drive-on median and below CHF 20'000
function impactOf(delta, base) {
  if (Math.abs(delta) < Math.min(.01 * Math.abs(base), 20000)) return 'flat';
  return delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
}
function demoHealth(s) {
  if (s.debt > 1) return 'credit';
  return s.cash >= 3 * s.expenses ? 'ok' : 'thin';
}
function stateLabel(s) {
  const base = s.gap > 0 ? 'gap year' : ({ studying: 'studying', looking: s.degrees.length ? 'graduated · looking' : 'looking for a job',
    employed: s.ptf < 1 ? 'part-time' : 'employed', retired: 'retired' }[s.job] || s.job);
  return s.debt > 0 ? base + ' · with credit' : base;
}
function demoWorld(finale = false) {
  const s = D.s;
  return { avatar: D.avatar, turn: s.turn, prev_turn: s.prevTurn, skipped: s.skipped, start_age: s.startAge, K: s.K, badges: { ...s.badges },
           labels: Array.from({ length: s.K + 1 }, (_, i) => s.startAge + i),
           life: { ...s.life }, anims: s.lastAnims.slice(), finale, intro: s.turn === 0 && !s.choices.length && !finale };
}
function demoSkipOptions(s) {
  const left = s.K - s.turn, out = [];
  for (const y of [5, 10]) if (y <= left) out.push({ years: y, label: `+${y} years` });
  if (left >= 1) out.push({ until: 'event', label: 'Next event' });
  return out;
}
function demoPlay() {
  const s = D.s, nw = demoNW(s), base = projectEnd(s, null).nw;
  const avail = CARDS.filter(c => c.once === false || !s.taken.includes(c.key)).map(c => cardPayload(s, c, base));
  return {
    turn: s.turn, K: s.K, step: 1, start_age: s.startAge, end_age: s.startAge + s.K, age: ageOf(s),
    hud: { name: D.avatar.name, age: ageOf(s), net_worth: r0(nw), cash: r0(s.cash), portfolio: r0(s.portfolio), debt: r0(s.debt),
           income: r0(incomeOf(s)), state: stateLabel(s),
           net_worth_prev: s.turn > 0 ? r0(s.past[s.prevTurn]) : null, prev_age: s.turn > 0 ? s.startAge + s.prevTurn : null,
           expenses: r0(s.expenses), health: demoHealth(s) },
    world: demoWorld(false),
    categories: CATS.map(c => ({ ...c, open: avail.filter(k => k.cat === c.key && !k.locked).length })),
    cards: avail,
    stay: { key: 'stay', title: 'Drive on' },
    skip: demoSkipOptions(s),
    quests: [
      { name: 'Emergency fund', current: r0(s.cash), target: r0(3 * s.expenses), by_age: s.startAge + 5 },
      { name: "CHF 100'000 net worth", current: r0(Math.max(0, nw)), target: 100000, by_age: Math.min(s.startAge + 15, s.startAge + s.K) },
    ].map(q => ({ ...q, progress: Math.min(1, Math.max(0, q.current / Math.max(1, q.target))), done: q.current >= q.target })),
    history: s.history,
  };
}
function demoEnd() {
  const s = D.s, nw = demoNW(s), n = s.K + 1;
  const ages = Array.from({ length: n }, (_, i) => s.startAge + i);
  const lazy = s.lazy.map(r0), p50 = [], p5 = [], p95 = [];
  for (let i = 0; i < n; i++) {
    const m = lazy[i] + (s.past[i] - lazy[i]) * .85, sp = (6000 + Math.abs(m) * .22) * Math.sqrt(i / s.K + .05);
    p50.push(r0(m)); p5.push(r0(m - sp)); p95.push(r0(m + sp * 1.4));
  }
  const score = r0(Math.max(0, nw) / 1000);
  const pct = Math.max(3, Math.min(99, r0(50 + (nw - p50[n - 1]) / Math.max(1, p95[n - 1] - p5[n - 1]) * 80 + (nw > lazy[n - 1] ? 12 : -12))));
  return {
    world: demoWorld(true),
    summary: { name: D.avatar.name, age_end: s.startAge + s.K, score, stars: Math.max(1, Math.min(5, 1 + Math.floor(pct / 20))),
               percentile: pct, decisions: s.choices.length, choices: s.choices },
    facts: { net_worth: r0(nw), percentile: pct, p5: p5[n - 1], p95: p95[n - 1], lazy_median: lazy[n - 1], cash: r0(s.cash), portfolio: r0(s.portfolio),
             house_equity: r0(s.house), debt: r0(s.debt), max_credit: r0(s.maxCredit), months_with_credit: s.monthsCredit, decisions: s.choices.length,
             best: s.best, fan: { ages, past: s.past.map(r0), p5, p50, p95, lazy, now_index: n - 1 } },
  };
}
function demoPayload() {
  const ex = PROFILES[2];
  const p = { height: 860, seq: D.seq, phase: D.phase, avatar: D.avatar,
              boot: { example: { id: ex.id, name: ex.name, age: ex.age, status: ex.status, ist: ex.ist }, statuses: STATUSES, end_age: LIFE_END } };
  if (D.phase === 'play') p.play = demoPlay();
  if (D.phase === 'end') p.end = demoEnd();
  return JSON.parse(JSON.stringify(p));   // like the real bridge: plain JSON, no shared references
}
// one station: optional card, one year, random small fate. Returns the planned events that happened.
function demoStep(key, params) {
  const s = D.s;
  const anim = a => s.anims.push({ id: `demo-${++s.aid}`, ...a });
  let card = key === 'stay' ? null : CARD[key] || null;
  if (card && params && card.params) s.params[card.key] = { ...(s.params[card.key] || {}), ...params };
  const pv = card ? paramVals(s, card) : {};
  if (card && lockReason(card, s, pv)) card = null;
  const age = ageOf(s);
  if (card) {
    if (!s.taken.includes(card.key)) s.taken.push(card.key);
    const base = projectEnd(s, null).nw, delta = cardPayload(s, card, base).delta;
    card.apply(s, pv, anim);
    s.badges[String(s.turn + 1)] = card.emoji;
    s.history.push({ age, emoji: card.emoji, title: card.title });
    s.choices.push({ age, emoji: card.emoji, title: card.title, cat_label: catLabel(card.cat), delta, impact: impactOf(delta, base) });
    if (!s.best || delta > s.best.delta) s.best = { title: card.title, delta };
  }
  const events = advance(s, true, anim);
  if (!events.length && Math.random() < .2) {
    const f = [["🎁", "Inheritance: +CHF 5'000", x => { x.cash += 5000; }], ['🦷', "Dentist bill: −CHF 1'800", x => { x.cash -= 1800; }],
               ['📉', 'Market dip: −8 %', x => { x.portfolio *= .92; }], ['🔧', "Washing machine broke: −CHF 1'200", x => { x.cash -= 1200; }]][Math.floor(Math.random() * 4)];
    f[2](s); anim({ type: 'fate', emoji: f[0], label: f[1] });
  }
  s.past.push(r0(demoNW(s)));
  if (s.turn >= s.K) D.phase = 'end';
  return events;
}
function demoSend(v) {
  if (v.action === 'analyse') {
    setTimeout(() => { ui.setWaiting(false); ui.toast('📊 Your life review opens in the Streamlit app', 2800); }, 500);
    return;
  }
  setTimeout(() => {
    D.seq += 1;
    const s = D.s;
    if (v.action === 'start') {
      D.prof = v.ist || PROFILES[0].ist;
      D.avatar = { ...DEFAULT_CFG, ...(v.avatar || {}) };
      D.s = demoState(D.prof); D.s.lazy = demoLazy(D.prof); D.s.past.push(r0(demoNW(D.s)));
      D.phase = 'play';
    } else if (v.action === 'card_params' && s && D.phase === 'play') {
      const c = CARD[v.key];
      if (c && c.params && v.params) s.params[c.key] = paramVals({ params: { [c.key]: { ...(s.params[c.key] || {}), ...v.params } } }, c);
    } else if ((v.action === 'choose' || v.action === 'skip') && s && D.phase === 'play') {
      const before = s.turn, a0 = s.anims.length;
      let n = 1;
      if (v.action === 'choose') demoStep(v.key, v.params);
      else {
        const left = s.K - s.turn, max = v.until === 'event' ? Math.min(10, left) : Math.min(Math.max(1, Math.round(+v.years || 1)), left);
        for (n = 0; n < max && D.phase === 'play';) { const ev = demoStep('stay'); n += 1; if (v.until === 'event' && ev.length) break; }
      }
      s.prevTurn = before; s.skipped = v.action === 'skip' ? n : 0;
      s.lastAnims = s.anims.slice(a0).map(a => (s.skipped >= 2 ? { ...a, brief: true } : a));
    } else if (v.action === 'restart') { D.phase = 'boot'; D.s = null; }
    ui.render(demoPayload());
  }, v.action === 'card_params' ? 180 + Math.random() * 200 : 650 + Math.random() * 400);
}

if (STANDALONE && DEMO_MODE === 'podium') {
  console.info('[game] standalone DEMO – podium mode');
  const lines = ["Hi! I'm your twin. Ask me how you did with your money.", 'You kept a buffer most of your life – nice!',
                 'Your biggest lever: start investing earlier.'];
  let i = 0; podium({ avatar: DEFAULT_CFG, bubble: lines[0], height: 420 });
  setInterval(() => { i = (i + 1) % lines.length; podium({ avatar: DEFAULT_CFG, bubble: lines[i], height: 420 }); }, 6000);
} else if (STANDALONE) {
  console.info('[game] standalone DEMO mode – mock payloads, no Streamlit');
  gameUI().render(demoPayload());
}
