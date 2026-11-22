// Entry point: Streamlit bridge (component mode "game") + standalone DEMO mode (python3 -m http.server).
import { initEngine, setToastHandler, setBusyHandler } from './engine.js';
import { DEFAULT_CFG } from './core.js';
import { createUI, chf } from './ui.js';

const STANDALONE = (() => { try { return window.parent === window; } catch (e) { return false; } })();

/* =================================================================== engine + UI */
const stage = document.getElementById('stage');
let engineOk = false;
try { initEngine(stage); engineOk = true; } catch (e) { console.warn('[game] 3D engine unavailable – UI runs without 3D', e); }

let lastNonce = 0;
const nextNonce = () => (lastNonce = Math.max(Date.now(), lastNonce + 1));
const ui = createUI(document.getElementById('ui'), { send, engineOk, standalone: STANDALONE });
try { setToastHandler((text, ms) => ui.toast(text, ms)); setBusyHandler(b => ui.setBusy(b)); } catch (e) { /* engine missing */ }

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
  { id: 'P00001', name: 'Alexia', age: 20, status_de: 'in Ausbildung', start_capital: 8000.0, typical_month: -1030.9 },
  { id: 'P00002', name: 'Noah', age: 20, status_de: 'student', start_capital: 3500.0, typical_month: -420.0 },
  { id: 'P00003', name: 'Lea', age: 20, status_de: 'employed', start_capital: 15000.0, typical_month: 850.5 },
  { id: 'P00004', name: 'Luca', age: 20, status_de: 'apprenticeship done', start_capital: 11000.0, typical_month: 310.0 },
];
const RISKS = [
  { key: 'konservativ', title: 'Conservative', emoji: '🛡️', text: '25 % stocks, 6 months rainy-day fund' },
  { key: 'ausgewogen', title: 'Balanced', emoji: '⚖️', text: '50 % stocks, 4 months rainy-day fund' },
  { key: 'mutig', title: 'Bold', emoji: '🚀', text: '80 % stocks, 3 months rainy-day fund' },
];
const CATS = [
  { key: 'bildung', label: 'Education', emoji: '🎓', color: '#2a78d6' },
  { key: 'karriere', label: 'Career', emoji: '💼', color: '#eb6834' },
  { key: 'wohnen', label: 'Housing', emoji: '🏡', color: '#1baf7a' },
  { key: 'familie', label: 'Family', emoji: '👪', color: '#e87ba4' },
  { key: 'freizeit', label: 'Leisure', emoji: '🏝️', color: '#eda100' },
  { key: 'finanzen', label: 'Money', emoji: '📈', color: '#6250d6' },
];
const CARDS = [
  { key: 'bachelor', cat: 'bildung', emoji: '🎓', title: 'Bachelor', text: '3 years of studies – then much higher pay.', xp: 100, joy: 3, delta: 749054, credit: 1.0, cost: 9000, inc: 1.3, anim: { type: 'graduation' } },
  { key: 'weiterbildung', cat: 'bildung', emoji: '📚', title: 'Further training', text: 'Part-time course, +8 % pay.', xp: 60, joy: 1, delta: 118000, credit: .2, cost: 4000, inc: 1.08 },
  { key: 'master', cat: 'bildung', emoji: '🧪', title: 'Master', text: 'Two more years of uni for a career boost.', xp: 150, joy: 2, delta: 214000, credit: .6, cost: 12000, inc: 1.15, req: s => s.taken.has('bachelor') ? null : 'Only after the bachelor', anim: { type: 'graduation' } },
  { key: 'jobwechsel', cat: 'karriere', emoji: '💼', title: 'New job', text: '+15 % pay, a bit more stress.', xp: 80, joy: -2, delta: 262000, credit: 0, inc: 1.15, suit: true, anim: { type: 'job', label: 'New job!' } },
  { key: 'befoerderung', cat: 'karriere', emoji: '📣', title: 'Promotion', text: 'More responsibility, more pay.', xp: 120, joy: -3, delta: 305000, credit: 0, inc: 1.2, suit: true, req: s => s.turn >= 3 ? null : 'From station 4', anim: { type: 'job', label: 'Promotion!' } },
  { key: 'startup', cat: 'karriere', emoji: '🚀', title: 'Found a startup', text: 'High risk, high possible reward.', xp: 220, joy: 6, delta: 380000, credit: .8, cost: 15000, inc: .8, anim: { type: 'startup', label: 'Startup founded!' } },
  { key: 'teilzeit', cat: 'karriere', emoji: '⏳', title: 'Part-time 80 %', text: 'One more free day per week, less pay.', xp: 40, joy: 8, delta: -152000, credit: .1, inc: .82 },
  { key: 'wg', cat: 'wohnen', emoji: '🛋️', title: 'Shared flat', text: 'Cheap living and more saving.', xp: 30, joy: -1, delta: 91000, credit: 0, exp: .88 },
  { key: 'stadtwohnung', cat: 'wohnen', emoji: '🏙️', title: 'City flat', text: 'In the middle of it all – but pricier.', xp: 50, joy: 5, delta: -108000, credit: .2, exp: 1.12 },
  { key: 'eigenheim', cat: 'wohnen', emoji: '🏡', title: 'Buy a home', text: 'Mortgage with 20 % equity.', xp: 180, joy: 7, delta: 231000, credit: .4, cost: 45000, house: 45000, exp: .95, req: s => s.cash >= 45000 ? null : "Not enough equity (CHF 45'000 needed)", anim: { type: 'house' } },
  { key: 'kind', cat: 'familie', emoji: '👶', title: 'Have a child', text: 'Lots of love – and higher spending.', xp: 160, joy: 10, delta: -184000, credit: .3, exp: 1.18, kid: true, anim: { type: 'child' } },
  { key: 'heirat', cat: 'familie', emoji: '💍', title: 'Get married', text: 'Party, promises, shared budget.', xp: 120, joy: 8, delta: 42000, credit: .3, cost: 20000, anim: { type: 'fate', emoji: '💍', label: 'Wedding!' } },
  { key: 'haustier', cat: 'familie', emoji: '🐶', title: 'Pet', text: 'A fluffy family member.', xp: 40, joy: 5, delta: -26000, credit: 0, cost: 2000, exp: 1.03, anim: { type: 'fate', emoji: '🐶', label: 'New family member!' } },
  { key: 'weltreise', cat: 'freizeit', emoji: '🏝️', title: 'World trip', text: 'Half a year on the road.', xp: 90, joy: 12, delta: -61000, credit: .3, cost: 16000, anim: { type: 'vacation' } },
  { key: 'auto', cat: 'freizeit', emoji: '🚗', title: 'New car', text: 'Shiny, fast – and losing value.', xp: 50, joy: 4, delta: -72000, credit: .6, cost: 26000, anim: { type: 'fate', emoji: '🚗', label: 'New car!' } },
  { key: 'hobby', cat: 'freizeit', emoji: '🎸', title: 'Pricey hobby', text: 'Music, biking or diving – makes you happy.', xp: 30, joy: 6, delta: -39000, credit: .1, exp: 1.05 },
  { key: 'etf', cat: 'finanzen', emoji: '📈', title: 'ETF savings plan', text: 'Into the world market automatically every month.', xp: 90, joy: 0, delta: 311000, credit: 0, invest: .3 },
  { key: 'saeule3a', cat: 'finanzen', emoji: '🏦', title: 'Pillar 3a', text: 'Save taxes and plan for retirement.', xp: 70, joy: 0, delta: 96000, credit: 0, invest: .1 },
  { key: 'notgroschen', cat: 'finanzen', emoji: '🐷', title: 'Rainy-day fund', text: 'Put three months of spending aside.', xp: 50, joy: 2, delta: 31000, credit: -0, exp: .97 },
  { key: 'krypto', cat: 'finanzen', emoji: '🪙', title: 'Crypto gamble', text: 'Might double. Or halve.', xp: 150, joy: 2, delta: 8000, credit: .4, cost: 5000, crypto: true, anim: { type: 'fate', emoji: '🪙', label: 'Crypto rollercoaster!' } },
];
const ACH = [
  { key: 'first', emoji: '🚦', title: 'First decision', xp: 50, test: s => s.choices.length >= 1 },
  { key: 'grad', emoji: '🎓', title: 'Graduated', xp: 150, test: s => s.taken.has('bachelor') || s.taken.has('master') },
  { key: 'job', emoji: '💼', title: 'Career kick', xp: 100, test: s => s.taken.has('jobwechsel') || s.taken.has('befoerderung') },
  { key: 'home', emoji: '🏡', title: 'A home of your own', xp: 200, test: s => s.taken.has('eigenheim') },
  { key: 'family', emoji: '👶', title: 'Family grows', xp: 120, test: s => s.taken.has('kind') },
  { key: 'travel', emoji: '🏝️', title: 'Globetrotter', xp: 80, test: s => s.taken.has('weltreise') },
  { key: 'investor', emoji: '📈', title: 'Investor', xp: 120, test: s => s.portfolio >= 5000 },
  { key: 'nest', emoji: '🐷', title: 'Rainy-day fund: 3 months of spending', xp: 150, test: s => s.cash >= s.expenses / 4 },
  { key: 'k50', emoji: '💎', title: "CHF 50'000 net worth", xp: 200, test: s => demoNW(s) >= 50000 },
  { key: 'debtfree', emoji: '🧾', title: 'Debt-free from station 5', xp: 100, test: s => s.turn >= 5 && s.debt <= 0 },
    { key: 'joy80', emoji: '😄', title: 'Joy 80+', xp: 100, test: s => s.joy >= 80 },
];
const FATES = [
  { emoji: '🎁', label: "Inheritance: +CHF 5'000", fx: s => { s.cash += 5000; } },
  { emoji: '🦷', label: "Dentist bill: −CHF 1'800", fx: s => { s.cash -= 1800; } },
  { emoji: '📉', label: 'Market dip: −8 %', fx: s => { s.portfolio *= .92; } },
  { emoji: '🍀', label: 'Pay rise +5 %', fx: s => { s.income *= 1.05; } },
  { emoji: '🔧', label: "Washing machine broke: −CHF 1'200", fx: s => { s.cash -= 1200; } },
];
const TITLES = ['Rookie', 'Go-getter', 'Doer', 'Pro', 'Strategist', 'Legend'];
const XPL = 400;
const joyEmoji = j => j < 30 ? '😟' : j < 50 ? '😐' : j < 70 ? '🙂' : j < 85 ? '😄' : '🤩';
const rarity = xp => xp <= 50 ? 'COMMON' : xp <= 90 ? 'UNCOMMON' : xp <= 140 ? 'RARE' : xp < 200 ? 'EPIC' : 'LEGENDARY';
const demoNW = s => s.cash + s.portfolio + s.house - s.debt;
const r0 = v => Math.round(v);
const catLabel = k => (CATS.find(c => c.key === k) || {}).label || k;

const D = { seq: 1, phase: 'boot', avatar: { ...DEFAULT_CFG }, s: null, prof: null, risk: null,
            chat: [], chatMode: 'offline', dashOpen: false, alt: null };

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
function demoState(prof, risk) {
  const low = /ausbildung|stud/i.test(prof.status_de);
  const income = low ? 26000 : 62000;
  return {
    startAge: num0(prof.age, 20), K: 10, turn: 0, prevTurn: 0, low,
    cash: prof.start_capital, portfolio: 0, house: 0, debt: 0, income, expenses: income - prof.typical_month * 12,
    invest: { konservativ: .1, ausgewogen: .2, mutig: .35 }[risk.key] ?? .2,
    ret: { konservativ: .025, ausgewogen: .045, mutig: .065 }[risk.key] ?? .045,
    vol: { konservativ: .06, ausgewogen: .14, mutig: .26 }[risk.key] ?? .14,
    xp: 0, joy: 60, taken: new Set(), history: [], choices: [], anims: [], aid: 0, badges: {}, got: new Set(), newAch: [],
    life: { suit: false, kids: 0 }, past: [], maxCredit: 0, monthsCredit: 0, best: null, lazy: [], tl: [],
  };
}
function num0(v, d) { return Number.isFinite(+v) ? +v : d; }
function demoLazy(prof, risk) {
  const s = demoState(prof, risk), out = [demoNW(s)];
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
           life: { ...s.life }, anims: s.anims.slice(-6), finale };
}
function demoPlay() {
  const s = D.s, nw = demoNW(s), lvl = Math.floor(s.xp / XPL) + 1, proj = projection(s), endMed = proj.p50[s.K];
  const ages = Array.from({ length: s.K + 1 }, (_, i) => s.startAge + i);
  const avail = CARDS.filter(c => !s.taken.has(c.key));
  return {
    turn: s.turn, K: s.K, start_age: s.startAge, age: s.startAge + s.turn,
    hud: { name: D.avatar.name, age: s.startAge + s.turn, level: lvl, level_title: TITLES[Math.min(lvl - 1, TITLES.length - 1)],
           xp_in_level: s.xp % XPL, xp_per_level: XPL, xp_total: s.xp, joy: r0(s.joy), joy_emoji: joyEmoji(s.joy), net_worth: r0(nw),
           cash: r0(s.cash), portfolio: r0(s.portfolio), debt: r0(s.debt), income: r0(s.income),
           state_de: s.debt > 0 ? 'with a loan' : s.taken.has('startup') ? 'self-employed' : (s.low && s.turn < 2) ? D.prof.status_de : 'employed',
           achievements_got: s.got.size, achievements_total: ACH.length },
    world: demoWorld(false),
    categories: CATS.map(c => ({ ...c, open: avail.filter(k => k.cat === c.key && !lockReason(k, s)).length })),
    cards: avail.map(c => {
      const med = r0(endMed + c.delta * .35), spread = Math.max(15000, Math.abs(med) * .28) * (c.crypto ? 2.4 : 1);
      return { key: c.key, cat: c.cat, emoji: c.emoji, title: c.title, text: c.text, locked: lockReason(c, s), xp: c.xp, joy: c.joy,
               delta: c.delta, median: med, p5: r0(med - spread), p95: r0(med + spread * 1.3), credit: Math.abs(c.credit || 0), rarity: rarity(c.xp) };
    }),
    stay: { key: 'stay', title: 'Drive on', xp: 10 },
    quests: [
      { name: 'Rainy-day fund', current: r0(s.cash), target: 12800, by_age: s.startAge + 5 },
      { name: 'First investment', current: r0(s.portfolio), target: 5000, by_age: s.startAge + 6 },
      { name: "CHF 100'000 net worth", current: r0(Math.max(0, nw)), target: 100000, by_age: s.startAge + s.K },
    ].map(q => ({ ...q, progress: Math.min(1, Math.max(0, q.current / q.target)), done: q.current >= q.target })),
    achievements: ACH.map(a => ({ key: a.key, emoji: a.emoji, title: a.title, got: s.got.has(a.key) })),
    new_achievements: s.newAch,
    history: s.history,
    fan: { ages, past: s.past.slice(), p5: proj.p5, p50: proj.p50, p95: proj.p95, now_index: s.turn },
  };
}
function endFan(s) {
  const n = s.K + 1, lazy = s.lazy.map(r0), p50 = [], p5 = [], p95 = [];
  for (let i = 0; i < n; i++) {
    const m = lazy[i] + (s.past[i] - lazy[i]) * .85, sp = (6000 + Math.abs(m) * .22) * Math.sqrt(i / s.K + .05);
    p50.push(r0(m)); p5.push(r0(m - sp)); p95.push(r0(m + sp * 1.4));
  }
  return { lazy, p5, p50, p95 };
}
function demoEnd() {
  const s = D.s, nw = demoNW(s), lvl = Math.floor(s.xp / XPL) + 1, n = s.K + 1;
  const ages = Array.from({ length: n }, (_, i) => s.startAge + i);
  const { lazy, p5, p50, p95 } = endFan(s);
  const score = r0(Math.max(0, nw) / 400 + s.xp + s.joy * 8);
  const pct = Math.max(3, Math.min(99, r0(50 + (nw - p50[n - 1]) / Math.max(1, p95[n - 1] - p5[n - 1]) * 80 + (nw > lazy[n - 1] ? 12 : -12))));
  return {
    world: demoWorld(true),
    summary: { name: D.avatar.name, age_end: s.startAge + s.K, score, stars: Math.max(1, Math.min(5, 1 + Math.floor(score / 700))),
               level: lvl, level_title: TITLES[Math.min(lvl - 1, TITLES.length - 1)], joy: r0(s.joy), joy_emoji: joyEmoji(s.joy), xp_total: s.xp,
               choices: s.choices, achievements: ACH.map(a => ({ key: a.key, emoji: a.emoji, title: a.title, got: s.got.has(a.key) })) },
    facts: { net_worth: r0(nw), percentile: pct, p5: p5[n - 1], p95: p95[n - 1], lazy_median: lazy[n - 1], cash: r0(s.cash), portfolio: r0(s.portfolio),
             house_equity: r0(s.house), debt: r0(s.debt), max_credit: r0(s.maxCredit), months_with_credit: s.monthsCredit, decisions: s.choices.length,
             best: s.best, fan: { ages, past: s.past.map(r0), p5, p50, p95, lazy, now_index: n - 1 },
             disclaimer: 'Synthetic data · not a forecast · not investment advice' },
  };
}
/* ---- DEMO: Zwilling-Chat + dashboard (CONTRACT "Extension"; made-up numbers, offline rules) */
const PROMPTS_PLAY = ['Can I afford a house?', 'What matters most?', 'What is my best next step?'];
const PROMPTS_END = ['What matters most?', 'What if I skipped my biggest decision?', 'Where was my biggest risk?'];
const chfDelta = v => (v < 0 ? '−' : '+') + chf(Math.abs(v));
function demoChatBlock() {
  return { available: false, model: 'qwen3:4b', mode: D.chatMode, messages: D.chat.slice(-30),
           prompts: D.phase === 'end' ? PROMPTS_END : PROMPTS_PLAY };
}
function demoOpener() {
  const s = D.s, age = s.startAge + s.turn;
  const msg = D.phase === 'end'
    ? { stage: 'Review', text: `Review: your life up to ${s.startAge + s.K} is played. Want to know which decision paid off most?` }
    : s.turn === 0
      ? { stage: `Station ${age} · First job`, text: `Hi ${D.avatar.name || 'there'}! I'm your twin. I check every question with the simulation – what do you want to know?` }
      : { stage: `Station ${age}`, text: `New year, new chances. You now have ${chf(demoNW(s))}. Shall I show you which card pays off most?` };
  D.chat.push({ role: 'twin', tools: [], suggestion: null, ...msg });
}
function demoAnswer(text) {
  const s = D.s, t = text.toLowerCase(), endAge = s.startAge + s.K;
  const open = CARDS.filter(c => !s.taken.has(c.key) && !lockReason(c, s)).sort((a, b) => b.delta - a.delta);
  const best = open[0];
  if (D.phase === 'end') {
    if (/risk|loan|debt|credit|tight/.test(t)) return { text: `Your biggest risk was the loan: at most ${chf(s.maxCredit)}, ${s.monthsCredit} months in the red.`, tools: [{ name: 'check_life_plan', args: '', result: `max. loan ${chf(s.maxCredit)}, ${s.monthsCredit} months` }], suggestion: null };
    return { text: s.best ? `"${s.best.title}" paid off most: ${chfDelta(s.best.delta)} at ${endAge} compared with just driving on.` : 'You always drove on – so no single decision stands out.',
             tools: [{ name: 'what_matters', args: '', result: s.best ? `${s.best.title}: ${chfDelta(s.best.delta)}` : 'no decisions' }], suggestion: null };
  }
  if (/house|home|flat|apartment|property/.test(t)) {
    const c = CARDS.find(x => x.key === 'eigenheim'), lock = lockReason(c, s), taken = s.taken.has('eigenheim');
    return { text: taken ? 'You already own a home – congratulations! Now it is about paying off the mortgage calmly.'
               : lock ? `Not yet: you have ${chf(s.cash)} cash, a home needs CHF 45'000 of equity. An ETF savings plan gets you there faster.`
               : `Yes, with ${chf(s.cash)} cash the equity is enough. At ${endAge} that is ${chfDelta(c.delta)} in the model compared with just driving on.`,
             tools: [{ name: 'compare_option', args: 'eigenheim', result: `${chfDelta(c.delta)} at ${endAge}, loan ${Math.round(c.credit * 100)} %` }],
             suggestion: !taken && !lock ? { key: 'eigenheim', title: c.title } : (!s.taken.has('etf') ? { key: 'etf', title: 'ETF savings plan' } : null) };
  }
  if (best && /matter|important|most|best|next|step|do/.test(t)) {
    const top = open.slice(0, 3).map(c => `${c.title} ${chfDelta(c.delta)}`).join(' · ');
    return { text: `"${best.title}" pays off most right now: ${chfDelta(best.delta)} at ${endAge} compared with just driving on.`,
             tools: [{ name: /step|next/.test(t) ? 'best_next_step' : 'what_matters', args: '', result: top }],
             suggestion: { key: best.key, title: best.title } };
  }
  return { text: `Right now you have ${chf(demoNW(s))} net worth and earn ${chf(s.income)} a year. Ask me about a card or your best next step!`,
           tools: [{ name: 'check_life_plan', args: '', result: `net worth ${chf(demoNW(s))}, income ${chf(s.income)}/year` }], suggestion: null };
}
function demoDash() {
  const s = D.s; if (!D.dashOpen || !s) return null;
  const end = D.phase === 'end', n = s.K + 1, ages = Array.from({ length: n }, (_, i) => s.startAge + i);
  const now = end ? n - 1 : s.turn;
  const f = end ? endFan(s) : projection(s), lazy = s.lazy.map(r0);
  const life = f.p50.map((v, i) => i <= now ? r0(s.past[i] ?? v) : r0(v * (1 + .07 * Math.sin(i * 1.7 + s.K))));
  const eff = i => r0(Math.abs(f.p50[n - 1]) * .16 * Math.pow(i / (n - 1), 1.6) + 1500 * i);
  const shiftFor = () => {
    if (!D.alt) return null;
    if (D.alt.kind === 'option') {
      const c = CARDS.find(x => x.key === D.alt.key) || { delta: 0, title: D.alt.key };
      return { label: `Plan + ${c.title} at ${s.startAge + now}`, d: i => i <= now ? 0 : c.delta * .35 * Math.pow((i - now) / Math.max(1, n - 1 - now), 1.2) };
    }
    const moved = Object.entries(D.alt.moves).map(([id, age]) => ({ t: s.tl.find(x => x.id === id), age })).filter(x => x.t && x.age !== x.t.age);
    if (!moved.length) return { label: 'Plan unchanged', d: () => 0 };
    return { label: moved.map(x => `${x.t.title} at ${x.age} instead of ${x.t.age}`).join(' · '),
             d: i => moved.reduce((a, x) => { const from = Math.min(x.age, x.t.age) - s.startAge; return a + (i <= from ? 0 : -(x.age - x.t.age) * .05 * Math.abs(f.p50[i]) * Math.min(1, (i - from) / 3)); }, 0) };
  };
  const sh = shiftFor();
  const alt = sh ? { p5: f.p5.map((v, i) => r0(v + sh.d(i) * 1.2)), p50: f.p50.map((v, i) => r0(v + sh.d(i))),
                     p95: f.p95.map((v, i) => r0(v + sh.d(i) * .9)), life: life.map((v, i) => r0(v + sh.d(i))) } : null;
  let summary = `With your plan, your net worth at ${ages[n - 1]} is ${chf(f.p50[n - 1])} (range ${chf(f.p5[n - 1])} to ${chf(f.p95[n - 1])}).`;
  if (alt) summary += ` Variant "${sh.label}": ${chf(alt.p50[n - 1])} (${chfDelta(alt.p50[n - 1] - f.p50[n - 1])} in the median).`;
  const moves = D.alt && D.alt.kind === 'moves' ? D.alt.moves : {};
  return {
    ages, now_index: now, inflation: 0.01,
    series: { plan: { p5: f.p5, p50: f.p50, p95: f.p95, life },
              no_saving: { p50: f.p50.map((v, i) => r0(v - eff(i))), life: life.map((v, i) => r0(v - eff(i))) },
              no_events: { p50: lazy, life: lazy.map((v, i) => r0(v * (1 + .05 * Math.sin(i)))) },
              alt },
    alt_label: alt ? sh.label : null, summary,
    timeline: s.tl.map(t => ({ id: t.id, emoji: t.emoji, title: t.title, age: t.age, cat: t.cat, movable: true, alt_age: moves[t.id] ?? null })),
    metrics: { net_now: r0(demoNW(s)), current_age: s.startAge + now },
  };
}
function demoPayload() {
  const p = { height: 860, seq: D.seq, phase: D.phase, avatar: D.avatar, boot: { profiles: PROFILES, risks: RISKS } };
  if (D.phase === 'play') p.play = { ...demoPlay(), chat: demoChatBlock(), dashboard: demoDash() };
  if (D.phase === 'end') p.end = { ...demoEnd(), chat: demoChatBlock(), dashboard: demoDash() };
  return JSON.parse(JSON.stringify(p));   // like the real bridge: plain JSON, no shared references
}
function demoChoose(key) {
  const s = D.s; s.prevTurn = s.turn; s.newAch = [];
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
    s.joy = Math.max(0, Math.min(100, s.joy + card.joy)); s.xp += card.xp;
    if (card.anim) anim(card.anim);
    s.badges[String(s.turn + 1)] = card.emoji;
    s.history.push({ age, emoji: card.emoji, title: card.title });
    s.tl.push({ id: `d${s.tl.length + 1}`, emoji: card.emoji, title: card.title, age, cat: card.cat });
    s.choices.push({ age, emoji: card.emoji, title: card.title, cat_label: catLabel(card.cat), rarity: rarity(card.xp), xp: card.xp });
    if (!s.best || card.delta > s.best.delta) s.best = { title: card.title, delta: card.delta };
  } else { s.xp += 10; s.joy = Math.max(0, s.joy - 1); }
  s.turn += 1; demoYear(s);
  if (s.turn === 2 && s.low) { s.income *= 1.6; anim({ type: 'fate', emoji: '🎉', label: 'Training completed!' }); }
  else if (Math.random() < .3) { const f = FATES[Math.floor(Math.random() * FATES.length)]; f.fx(s); anim({ type: 'fate', emoji: f.emoji, label: f.label }); }
  s.past.push(r0(demoNW(s)));
  for (const a of ACH) if (!s.got.has(a.key) && a.test(s)) { s.got.add(a.key); s.xp += a.xp; s.newAch.push({ emoji: a.emoji, title: a.title, xp: a.xp }); }
  if (s.turn >= s.K) { anim({ type: 'retirement' }); D.phase = 'end'; D.dashOpen = false; }
  if (D.alt && D.alt.kind === 'option') D.alt = null;   // like Python: "this option now" is stale, moves stay
  demoOpener();
}
function demoSend(v) {
  if (v.action === 'analyse') {
    setTimeout(() => { ui.setWaiting(false); ui.toast('📊 The analysis lives in the Streamlit app', 2800); }, 500);
    return;
  }
  const slow = v.action === 'chat' ? 900 : 0;
  setTimeout(() => {
    D.seq += 1;
    if (v.action === 'chat' && D.s) {
      const m = String(v.message || '').trim().slice(0, 400);
      if (m) D.chat.push({ role: 'user', text: m, tools: [], suggestion: null }, { role: 'twin', mode: D.chatMode, ...demoAnswer(m) });
    } else if (v.action === 'dashboard') D.dashOpen = !!v.open && !!D.s && D.phase !== 'boot';
    else if (v.action === 'plan_alt' && D.s && D.phase === 'play') {
      const c = CARDS.find(x => x.key === v.key);
      if (c && !D.s.taken.has(c.key) && !lockReason(c, D.s)) { D.alt = { kind: 'option', key: c.key }; D.dashOpen = true; }
    } else if (v.action === 'plan_edit' && D.s) {
      const prev = D.alt && D.alt.kind === 'moves' ? D.alt.moves : {};
      D.alt = { kind: 'moves', moves: { ...prev, ...(v.moves || {}) } }; D.dashOpen = true;
    } else if (v.action === 'plan_reset') D.alt = null;
    else if (v.action === 'start') {
      D.prof = PROFILES.find(p => p.id === v.pid) || PROFILES[0];
      D.risk = RISKS.find(r => r.key === v.risk) || RISKS[1];
      D.avatar = { ...DEFAULT_CFG, ...(v.avatar || {}) };
      D.s = demoState(D.prof, D.risk); D.s.lazy = demoLazy(D.prof, D.risk); D.s.past.push(r0(demoNW(D.s)));
      D.phase = 'play'; D.chat = []; D.dashOpen = false; D.alt = null; demoOpener();
    } else if (v.action === 'choose' && D.s && D.phase === 'play') demoChoose(v.key);
    else if (v.action === 'restart') { D.phase = 'boot'; D.s = null; D.chat = []; D.dashOpen = false; D.alt = null; }
    ui.render(demoPayload());
  }, 650 + slow + Math.random() * 400);
}

if (STANDALONE) {
  console.info('[game] standalone DEMO mode – mock payloads, no Streamlit');
  ui.render(demoPayload());
}
