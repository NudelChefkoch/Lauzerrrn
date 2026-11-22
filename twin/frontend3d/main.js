// Entry point: Streamlit bridge (component mode "game") + standalone DEMO mode (python3 -m http.server).
import { initEngine, setToastHandler, setBusyHandler, setIntroHandler, setRideHandler, skipIntro } from './engine.js';
import { DEFAULT_CFG } from './core.js';
import { createUI } from './ui.js';

const STANDALONE = (() => { try { return window.parent === window; } catch (e) { return false; } })();

/* =================================================================== engine + UI */
const stage = document.getElementById('stage');
let engineOk = false;
try { initEngine(stage); engineOk = true; } catch (e) { console.warn('[game] 3D engine unavailable – UI runs without 3D', e); }

let lastNonce = 0;
const nextNonce = () => (lastNonce = Math.max(Date.now(), lastNonce + 1));
const ui = createUI(document.getElementById('ui'), { send, engineOk, standalone: STANDALONE, onSkipIntro: () => { try { skipIntro(); } catch (e) { /* engine missing */ } } });
try { setToastHandler((text, ms) => ui.toast(text, ms)); setBusyHandler(b => ui.setBusy(b)); setIntroHandler((step, data) => ui.intro(step, data)); setRideHandler((step, data) => ui.rideEvent(step, data)); } catch (e) { /* engine missing */ }

/* =================================================================== Streamlit bridge */
function post(type, data = {}) {
  try { window.parent.postMessage({ isStreamlitMessage: true, type, ...data }, '*'); } catch (e) { console.warn('[game] postMessage failed', e); }
}
let lastPayload = null, lastH = 0;
function parentHeight() { try { const h = window.parent.innerHeight; return h > 200 ? h : 0; } catch (e) { return 0; } }
function setHeight() {
  if (STANDALONE) return;
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
    if (args.mode && args.mode !== 'game') return;
    const p = args.payload; if (!p || typeof p !== 'object') return;
    lastPayload = p; setHeight(); ui.render(p);
  });
  try { window.parent.addEventListener('resize', setHeight); } catch (e) { /* cross-origin parent */ }
  window.addEventListener('resize', setHeight);
  post('streamlit:componentReady', { apiVersion: 1 });
  setHeight();
}

/* =================================================================== DEMO (standalone, made-up numbers) */
const PROFILES = [
  { id: 'P00001', name: 'Alexia', age: 20, status: 'in education', start_capital: 8000.0, typical_month: -1030.9 },
  { id: 'P00002', name: 'Noah', age: 20, status: 'in education', start_capital: 3500.0, typical_month: -420.0 },
  { id: 'P00003', name: 'Lea', age: 20, status: 'employed', start_capital: 15000.0, typical_month: 850.5 },
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
const CARDS = [
  { key: 'bachelor', cat: 'education', emoji: '🎓', title: 'Bachelor', text: '3 years of study – then a clearly higher salary.', delta: 749054, credit: 1.0, cost: 9000, inc: 1.3, anim: { type: 'graduation' } },
  { key: 'training', cat: 'education', emoji: '📚', title: 'Further training', text: 'Part-time course, +8 % salary.', delta: 118000, credit: .2, cost: 4000, inc: 1.08 },
  { key: 'master', cat: 'education', emoji: '🧪', title: 'Master', text: 'Two more years of uni as a career turbo.', delta: 214000, credit: .6, cost: 12000, inc: 1.15, req: s => s.taken.has('bachelor') ? null : 'Only after the bachelor', anim: { type: 'graduation' } },
  { key: 'entryjob', cat: 'career', emoji: '🛒', title: 'Entry job', text: 'Earn money right away.', delta: 120000, credit: 0, inc: 1.1, suit: true, anim: { type: 'job', label: 'First job!' } },
  { key: 'newjob', cat: 'career', emoji: '🚀', title: 'Job change', text: '+15 % salary, a bit more stress.', delta: 262000, credit: 0, inc: 1.15, suit: true, anim: { type: 'job', label: 'New job!' } },
  { key: 'parttime', cat: 'career', emoji: '⏳', title: 'Part-time 80 %', text: 'One more free day per week, less salary.', delta: -152000, credit: .1, inc: .82 },
  { key: 'home', cat: 'housing', emoji: '🏡', title: 'Buy a home', text: 'UBS mortgage with 20 % down payment.', delta: 231000, credit: .4, cost: 45000, house: 45000, exp: .95, req: s => s.cash >= 45000 ? null : "Not enough down payment (CHF 45'000 needed)", anim: { type: 'house' } },
  { key: 'luxflat', cat: 'housing', emoji: '🛋️', title: 'Rent a luxury flat', text: 'Bigger, nicer, central.', delta: -95000, credit: .1, exp: 1.12 },
  { key: 'child', cat: 'family', emoji: '👶', title: 'Have a child', text: 'Lots of love – and higher expenses.', delta: -184000, credit: .3, exp: 1.18, kid: true, anim: { type: 'child' } },
  { key: 'wedding', cat: 'family', emoji: '💍', title: 'Get married', text: 'Celebration, promises, a shared budget.', delta: 42000, credit: .3, cost: 20000, partner: true, anim: { type: 'wedding' } },
  { key: 'pet', cat: 'family', emoji: '🐶', title: 'Pet', text: 'A fluffy family member.', delta: -26000, credit: 0, cost: 2000, exp: 1.03, anim: { type: 'fate', emoji: '🐶', label: 'New family member!' } },
  { key: 'worldtrip', cat: 'timeoff', emoji: '🏝️', title: 'World trip', text: 'Half a year on the road.', delta: -61000, credit: .3, cost: 16000, anim: { type: 'vacation' } },
  { key: 'car', cat: 'timeoff', emoji: '🚗', title: 'New car', text: 'Shiny, fast – and losing value.', delta: -72000, credit: .6, cost: 26000, anim: { type: 'fate', emoji: '🚗', label: 'New car!' } },
  { key: 'hobby', cat: 'timeoff', emoji: '🎸', title: 'Pricey hobby', text: 'Music, bike or diving – makes you happy.', delta: -39000, credit: .1, exp: 1.05 },
];
const FATES = [
  { emoji: '🎁', label: "Inheritance: +CHF 5'000", fx: s => { s.cash += 5000; } },
  { emoji: '🦷', label: "Dentist bill: −CHF 1'800", fx: s => { s.cash -= 1800; } },
  { emoji: '📉', label: 'Market dip: −8 %', fx: s => { s.portfolio *= .92; } },
  { emoji: '🍀', label: 'Pay rise +5 %', fx: s => { s.income *= 1.05; } },
  { emoji: '🔧', label: "Washing machine broke: −CHF 1'200", fx: s => { s.cash -= 1200; } },
];
const demoNW = s => s.cash + s.portfolio + s.house - s.debt;
const r0 = v => Math.round(v);
const catLabel = k => (CATS.find(c => c.key === k) || {}).label || k;

const D = { seq: 1, phase: 'boot', avatar: { ...DEFAULT_CFG }, s: null, prof: null };

function demoYear(s, noise = true) {
  const save = s.income - s.expenses;
  const toInv = save > 0 ? save * s.invest : 0;
  s.cash += save - toInv;
  s.portfolio = s.portfolio * (1 + s.ret + (noise ? (Math.random() - .5) * s.vol : 0)) + toInv;
  s.house *= 1.02;
  if (s.debt > 0) s.debt *= 1.07;
  if (s.cash < 0) {
    const need = -s.cash; s.debt += need; s.cash = 0;
    s.monthsCredit += Math.min(12, Math.max(1, Math.ceil(need / Math.max(1, s.expenses / 12))));
  } else if (s.debt > 0) { const pay = Math.min(s.debt, s.cash * .6); s.debt -= pay; s.cash -= pay; }
  s.maxCredit = Math.max(s.maxCredit, s.debt);
  s.income *= 1.025; s.expenses *= 1.015;
}
// prof = Ist-Zustand from the start form (monthly CHF); the demo has no investment style (invests a fixed share)
function demoState(prof) {
  const low = prof.status === 'student';
  const income = num0(prof.income, 2000) * 12;
  return {
    startAge: num0(prof.age, 20), K: 10, turn: 0, prevTurn: 0, low, status: (STATUSES.find(x => x.key === prof.status) || {}).label || 'employed',
    cash: num0(prof.cash, 0), portfolio: num0(prof.portfolio, 0), house: 0, debt: num0(prof.debt, 0), income, expenses: num0(prof.expenses, 2000) * 12,
    invest: .2, ret: .045, vol: .14,
    taken: new Set(), history: [], choices: [], anims: [], aid: 0, badges: {},
    life: { suit: false, kids: 0, partner: false }, past: [], maxCredit: 0, monthsCredit: 0, best: null, lazy: [],
  };
}
function num0(v, d) { return Number.isFinite(+v) ? +v : d; }
function demoLazy(prof) {
  const s = demoState(prof), out = [demoNW(s)];
  for (let t = 1; t <= s.K; t++) { demoYear(s, false); if (t === 2 && s.low) s.income *= 1.6; out.push(demoNW(s)); }
  return out;
}
function lockReason(c, s) { return c.req ? c.req(s) : null; }
function projection(s) {
  // simple forward projection from "now": mean path + widening band
  const n = s.K + 1, nw = demoNW(s), save = s.income - s.expenses;
  const p5 = [], p50 = [], p95 = [];
  for (let i = 0; i < n; i++) {
    if (i < s.turn) { const v = s.past[i]; p5.push(v); p50.push(v); p95.push(v); continue; }
    const y = i - s.turn, mu = nw + save * y * 1.05 + s.portfolio * (Math.pow(1 + s.ret, y) - 1) + save * s.invest * y * y * s.ret * .5;
    const spread = (Math.abs(nw) * .06 + 7000 + s.portfolio * s.vol) * Math.sqrt(y);
    p50.push(r0(mu)); p5.push(r0(mu - spread)); p95.push(r0(mu + spread * 1.35));
  }
  return { p5, p50, p95 };
}
function demoWorld(finale = false) {
  const s = D.s;
  return { avatar: D.avatar, turn: s.turn, prev_turn: s.prevTurn, start_age: s.startAge, K: s.K, badges: { ...s.badges },
           life: { ...s.life }, anims: s.anims.slice(-6), finale, intro: s.turn === 0 && !s.choices.length && !finale };
}
function demoPlay() {
  const s = D.s, nw = demoNW(s), proj = projection(s), endMed = proj.p50[s.K];
  const ages = Array.from({ length: s.K + 1 }, (_, i) => s.startAge + i);
  const avail = CARDS.filter(c => !s.taken.has(c.key));
  return {
    turn: s.turn, K: s.K, start_age: s.startAge, age: s.startAge + s.turn,
    hud: { name: D.avatar.name, age: s.startAge + s.turn, style: 'Demo', net_worth: r0(nw),
           cash: r0(s.cash), portfolio: r0(s.portfolio), debt: r0(s.debt), income: r0(s.income),
           state: s.debt > 0 ? 'with credit' : s.taken.has('startup') ? 'self-employed' : (s.low && s.turn < 2) ? s.status : 'employed' },
    world: demoWorld(false),
    categories: CATS.map(c => ({ ...c, open: avail.filter(k => k.cat === c.key && !lockReason(k, s)).length })),
    cards: avail.map(c => {
      const med = r0(endMed + c.delta * .35), spread = Math.max(15000, Math.abs(med) * .28) * (c.crypto ? 2.4 : 1);
      return { key: c.key, cat: c.cat, emoji: c.emoji, title: c.title, text: c.text, locked: lockReason(c, s),
               delta: c.delta, median: med, p5: r0(med - spread), p95: r0(med + spread * 1.3), credit: Math.abs(c.credit || 0) };
    }),
    stay: { key: 'stay', title: 'Drive on' },
    quests: [
      { name: 'Emergency fund', current: r0(s.cash), target: 12800, by_age: s.startAge + 5 },
      { name: 'First investment', current: r0(s.portfolio), target: 5000, by_age: s.startAge + 6 },
      { name: "CHF 100'000 net worth", current: r0(Math.max(0, nw)), target: 100000, by_age: s.startAge + s.K },
    ].map(q => ({ ...q, progress: Math.min(1, Math.max(0, q.current / q.target)), done: q.current >= q.target })),
    history: s.history,
    fan: { ages, past: s.past.slice(), p5: proj.p5, p50: proj.p50, p95: proj.p95, now_index: s.turn },
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
    summary: { name: D.avatar.name, age_end: s.startAge + s.K, score, stars: Math.max(1, Math.min(5, 1 + Math.floor(score / 700))),
               style: 'Demo', percentile: pct, decisions: s.choices.length, choices: s.choices },
    facts: { net_worth: r0(nw), percentile: pct, p5: p5[n - 1], p95: p95[n - 1], lazy_median: lazy[n - 1], cash: r0(s.cash), portfolio: r0(s.portfolio),
             house_equity: r0(s.house), debt: r0(s.debt), max_credit: r0(s.maxCredit), months_with_credit: s.monthsCredit, decisions: s.choices.length,
             best: s.best, fan: { ages, past: s.past.map(r0), p5, p50, p95, lazy, now_index: n - 1 },
             disclaimer: 'Synthetic data · not a forecast · not investment advice' },
  };
}
function demoPayload() {
  const p = { height: 860, seq: D.seq, phase: D.phase, avatar: D.avatar, boot: { example: { id: PROFILES[2].id, name: PROFILES[2].name, age: PROFILES[2].age, status: PROFILES[2].status, ist: PROFILES[2].ist }, statuses: STATUSES, retire_age: 65 } };
  if (D.phase === 'play') p.play = demoPlay();
  if (D.phase === 'end') p.end = demoEnd();
  return JSON.parse(JSON.stringify(p));   // like the real bridge: plain JSON, no shared references
}
function demoChoose(key) {
  const s = D.s; s.prevTurn = s.turn;
  const anim = a => s.anims.push({ id: `demo-${++s.aid}`, ...a });
  let card = key === 'stay' ? null : CARDS.find(c => c.key === key);
  if (card && (s.taken.has(card.key) || lockReason(card, s))) card = null;
  const age = s.startAge + s.turn;
  if (card) {
    s.taken.add(card.key); s.cash -= card.cost || 0;
    if (card.inc) s.income *= card.inc; if (card.exp) s.expenses *= card.exp;
    if (card.invest) s.invest = Math.min(.7, s.invest + card.invest);
    if (card.house) s.house += card.house;
    if (card.crypto) s.cash += Math.random() < .5 ? 6000 : -2500;
    if (card.suit) s.life.suit = true;
    if (card.kid) s.life.kids += 1;
    if (card.partner) s.life.partner = true;
    if (card.anim) anim(card.anim);
    s.badges[String(s.turn + 1)] = card.emoji;
    s.history.push({ age, emoji: card.emoji, title: card.title });
    s.choices.push({ age, emoji: card.emoji, title: card.title, cat_label: catLabel(card.cat), delta: card.delta });
    if (!s.best || card.delta > s.best.delta) s.best = { title: card.title, delta: card.delta };
  }
  s.turn += 1; demoYear(s);
  if (s.turn === 2 && s.low) { s.income *= 1.6; anim({ type: 'fate', emoji: '🎉', label: 'Education finished!' }); }
  else if (Math.random() < .3) { const f = FATES[Math.floor(Math.random() * FATES.length)]; f.fx(s); anim({ type: 'fate', emoji: f.emoji, label: f.label }); }
  s.past.push(r0(demoNW(s)));
  if (s.turn >= s.K) { anim({ type: 'retirement' }); D.phase = 'end'; }
}
function demoSend(v) {
  if (v.action === 'analyse') {
    setTimeout(() => { ui.setWaiting(false); ui.toast('📊 The analysis is available in the Streamlit app', 2800); }, 500);
    return;
  }
  setTimeout(() => {
    D.seq += 1;
    if (v.action === 'ride' || v.action === 'ride_play') { ui.toast('🎬 The film ride needs the Streamlit app (python backend)', 3200); ui.render(demoPayload()); return; }
    if (v.action === 'start') {
      D.prof = v.ist || PROFILES[0].ist;
      D.avatar = { ...DEFAULT_CFG, ...(v.avatar || {}) };
      D.s = demoState(D.prof); D.s.lazy = demoLazy(D.prof); D.s.past.push(r0(demoNW(D.s)));
      D.phase = 'play';
    } else if (v.action === 'choose' && D.s && D.phase === 'play') demoChoose(v.key);
    else if (v.action === 'restart') { D.phase = 'boot'; D.s = null; }
    ui.render(demoPayload());
  }, 650 + Math.random() * 400);
}

if (STANDALONE) {
  console.info('[game] standalone DEMO mode – mock payloads, no Streamlit');
  ui.render(demoPayload());
}
