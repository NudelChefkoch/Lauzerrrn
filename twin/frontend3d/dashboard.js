// DASHBOARD overlay (after Juli's financial-twin dashboard: app.js, chart.js, timeline.js) in our game style.
// Everything shown is computed client-side from the payload `dashboard` block (CONTRACT "Extension"):
// metric tiles, projection chart with comparison modes, draggable decision timeline. All numbers come from our SDE.
import { esc, num, clamp, arr, chf, chfSigned, kfmt, series } from './fmt.js';

const MODES = [
  { key: 'savings', label: 'Savings plan' },
  { key: 'events', label: 'Life events' },
  { key: 'paths', label: 'Two life paths' },
];
const COL = {
  band: 'rgba(47,123,255,.20)', median: '#2f7bff', life: '#ff3d8b', comp: '#6b6394',
  alt: '#ff8a1f', altBand: 'rgba(255,138,31,.17)', grid: '#ebe6fb', text: '#6b6394', ink: '#1d1446', sel: '#ffb800',
};
const LANE_GAP = 132;     // px between chips on the same lane

function niceTicks(lo, hi, count = 5) {
  const raw = (hi - lo) / count, mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
  const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag, out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
  return out;
}

export function createDashboard({ onClose, onReset, onEdit } = {}) {
  const el = document.createElement('div');
  el.className = 'dash';
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `
  <div class="dash-panel" role="dialog" aria-label="Dashboard">
    <div class="res-tag">ANALYSIS</div>
    <div class="dash-top">
      <button type="button" class="btn btn-sm btn-purple dash-close">◀ BACK</button>
      <h2 class="res-h ol dash-h">DASHBOARD</h2>
      <span class="dash-badge">Simulated · same random world</span>
    </div>
    <div class="dash-body">
      <div class="dash-main">
        <div class="dash-metrics">
          <div class="tile dm"><div class="k">💰 Net worth today</div><div class="v dm-now">–</div><div class="s dm-now-s"></div></div>
          <div class="tile dm hero"><div class="k">🔮 Net worth at <select class="dage" aria-label="Age for the key figures"></select></div>
            <div class="v dm-fut">–</div><div class="s dm-fut-s"></div></div>
          <div class="tile dm"><div class="k dm-real-k">🛒 Purchasing power in today's CHF</div><div class="v dm-real">–</div><div class="s dm-real-s"></div></div>
          <div class="tile dm"><div class="k">🐷 Effect of the savings plan</div><div class="v dm-eff">–</div><div class="s">compared with the same future without a savings plan</div></div>
        </div>
        <section class="dbox dash-chart">
          <div class="dbox-head"><h3>📈 Net worth over time</h3>
            <div class="seg" role="group" aria-label="Comparison in the chart">${MODES.map(m =>
              `<button type="button" data-dmode="${m.key}" aria-pressed="false">${m.label}</button>`).join('')}</div></div>
          <p class="dbox-sub">Net worth in CHF · median and range p5–p95 of all simulated lives</p>
          <div class="dchart-wrap">
            <canvas class="dchart" tabindex="0" aria-label="Net worth over time. Use the arrow keys to pick an age." aria-describedby="dash-readout"></canvas>
            <div class="dtip" hidden></div>
            <div class="dload"><span class="dice">🎲</span><span>Calculating …</span></div>
            <p class="vh" id="dash-readout" aria-live="polite"></p>
          </div>
          <div class="legend dlegend"></div>
          <p class="dsum" aria-live="polite"></p>
        </section>
        <section class="dbox dash-tl">
          <div class="dbox-head"><h3>🧭 Your timeline</h3>
            <button type="button" class="btn btn-sm btn-yellow dash-reset">↺ Reset</button></div>
          <p class="dbox-sub">Drag a decision to another age (or use the arrow keys) – your twin calculates the second life path in the same simulated world.</p>
          <div class="tl-scroll"><div class="tl-track">
            <div class="tl-axis"></div><div class="tl-ticks" aria-hidden="true"></div><div class="tl-guide" hidden></div>
            <div class="tl-chips" role="group" aria-label="Decisions on the timeline"></div>
          </div></div>
          <p class="tl-note"></p>
        </section>
      </div>
      <aside class="dash-side"><div class="dash-chat-host"></div></aside>
    </div>
  </div>`;
  const q = s => el.querySelector(s);
  const R = {
    close: q('.dash-close'), reset: q('.dash-reset'), badge: q('.dash-badge'),
    now: q('.dm-now'), nowS: q('.dm-now-s'), age: q('.dage'), fut: q('.dm-fut'), futS: q('.dm-fut-s'),
    realK: q('.dm-real-k'), real: q('.dm-real'), realS: q('.dm-real-s'), eff: q('.dm-eff'),
    seg: q('.seg'), wrap: q('.dchart-wrap'), cv: q('.dchart'), tip: q('.dtip'), readout: q('#dash-readout'),
    legend: q('.dlegend'), sum: q('.dsum'),
    tlScroll: q('.tl-scroll'), track: q('.tl-track'), ticks: q('.tl-ticks'), chips: q('.tl-chips'), guide: q('.tl-guide'), note: q('.tl-note'),
    chatHost: q('.dash-chat-host'),
  };
  const S = { D: null, v: null, mode: 'savings', wantPaths: false, ageSel: null, hover: null, plot: null,
              tlSig: '', drag: null, loading: false, locked: false, lastAlt: null };

  /* ------------------------------------------------------------ view model */
  function view() {
    const D = S.D; if (!D) return null;
    const ages = arr(D.ages).map(a => num(a)), n = ages.length;
    if (n < 2) return { n, ages };
    const sr = D.series && typeof D.series === 'object' ? D.series : {};
    const plan = sr.plan || {}, alt = sr.alt && typeof sr.alt === 'object' ? sr.alt : null;
    let mode = S.mode; if (mode === 'paths' && !alt) mode = 'savings';
    const v = { n, ages, mode, hasAlt: !!alt,
                now: clamp(Math.round(num(D.now_index, 0)), 0, n - 1),
                p5: series(plan.p5, n), p50: series(plan.p50, n), p95: series(plan.p95, n), life: series(plan.life, n),
                noSave: series((sr.no_saving || {}).p50, n) };
    if (mode === 'savings') { v.comp = v.noSave; v.compLabel = 'Without savings plan'; }
    else if (mode === 'events') { v.comp = series((sr.no_events || {}).p50, n); v.compLabel = 'Without life events'; }
    else {
      v.comp = series(alt.p50, n); v.c5 = series(alt.p5, n); v.c95 = series(alt.p95, n); v.clife = series(alt.life, n);
      v.compLabel = String(D.alt_label || 'Second life path');
    }
    return v;
  }
  const at = (a, i) => (a && i !== null && i >= 0 && i < a.length) ? a[i] : null;

  /* ------------------------------------------------------------ metric tiles */
  function ageOptions(v) {
    const out = [];
    const first = v.now >= v.n - 1 ? 1 : v.now + 1;
    for (let i = Math.max(1, first); i < v.n; i++) out.push(i);
    return out.length ? out : [v.n - 1];
  }
  function renderMetrics(v) {
    const D = S.D, m = D.metrics || {};
    const curAge = num(m.current_age, v.ages[v.now]);
    R.now.textContent = chf(m.net_now !== undefined && m.net_now !== null ? m.net_now : at(v.life, v.now));
    R.now.classList.toggle('neg', num(m.net_now) < -0.5);
    R.nowS.textContent = `at age ${curAge} · cash, investments and home equity minus debt`;
    const opts = ageOptions(v);
    if (!opts.includes(S.ageSel)) S.ageSel = opts[opts.length - 1];
    const optHtml = opts.map(i => `<option value="${i}" ${i === S.ageSel ? 'selected' : ''}>${v.ages[i]} y</option>`).join('');
    if (R.age.dataset.sig !== optHtml) { R.age.innerHTML = optHtml; R.age.dataset.sig = optHtml; }
    R.age.value = String(S.ageSel);
    const i = S.ageSel, age = v.ages[i], val = at(v.p50, i);
    R.fut.textContent = val === null ? '–' : chf(val);
    R.futS.textContent = val === null ? '' : `Median · range ${kfmt(at(v.p5, i))} – ${kfmt(at(v.p95, i))}`;
    // purchasing power: in the end phase "today" is the start of the game (otherwise the factor would be > 1)
    const inf = num(D.inflation, 0.01), baseAge = v.now >= v.n - 1 ? v.ages[0] : curAge;
    const real = val === null ? null : val / Math.pow(1 + inf, Math.max(0, age - baseAge));
    R.realK.textContent = v.now >= v.n - 1 ? `🛒 Purchasing power in CHF of age ${baseAge}` : '🛒 Purchasing power in today\'s CHF';
    R.real.textContent = real === null ? '–' : chf(real);
    R.realS.textContent = `at ${(inf * 100).toLocaleString('en-US', { maximumFractionDigits: 1 })} % inflation per year`;
    const ns = at(v.noSave, i), eff = val === null || ns === null ? null : val - ns;
    R.eff.textContent = eff === null ? '–' : chfSigned(eff);
    R.eff.classList.toggle('pos', eff !== null && eff > 0.5);
    R.eff.classList.toggle('neg', eff !== null && eff < -0.5);
  }

  /* ------------------------------------------------------------ chart */
  function renderLegend(v) {
    const items = [
      `<span><i class="band"></i>Range p5–p95</span>`,
      `<span><i style="border-color:${COL.median}"></i>Median of your plan</span>`,
      `<span><i style="border-color:${COL.life}"></i>your life</span>`,
      `<span><i class="dash" style="border-color:${v.mode === 'paths' ? COL.alt : COL.comp}"></i>${esc(v.compLabel)}${v.mode === 'paths' ? ' (Median)' : ''}</span>`,
    ];
    if (v.mode === 'paths') items.push(`<span><i class="band alt"></i>Range of the second path</span>`);
    R.legend.innerHTML = items.join('');
  }
  function renderSummary(v) {
    const D = S.D, i = S.ageSel, age = v.ages[i];
    const a = at(v.p50, i), b = at(v.comp, i);
    let line = '';
    if (a !== null && b !== null) {
      if (v.mode === 'paths') {
        const d = b - a;
        line = Math.abs(d) < 0.5 ? `At ${age}, both life paths end with the same median net worth.`
          : `At ${age}, "${v.compLabel}" is ${chfSigned(d)} ${d > 0 ? 'above' : 'below'} your played plan in the median.`;
      } else {
        const d = a - b, what = v.mode === 'savings' ? 'the savings plan changes' : 'your life events change';
        line = Math.abs(d) < 0.5 ? `At ${age}, both variants end with the same median net worth.`
          : `At ${age}, ${what} your median net worth by ${chfSigned(d)}.`;
      }
    }
    R.sum.textContent = [D.summary ? String(D.summary) : '', line].filter(Boolean).join(' ');
  }

  function draw() {
    const cv = R.cv, v = S.v;
    const W = cv.clientWidth, H = cv.clientHeight; if (!W || !H) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    const g = cv.getContext('2d'); if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    g.font = '800 12px Nunito, system-ui, sans-serif'; g.textBaseline = 'middle';
    if (!v || v.n < 2) { g.fillStyle = COL.text; g.textAlign = 'center'; g.fillText('Noch keine Daten', W / 2, H / 2); S.plot = null; return; }
    const n = v.n, paths = v.mode === 'paths';
    const all = [v.p5, v.p50, v.p95, v.life, v.comp, v.c5, v.c95, v.clife].filter(Boolean);
    const vals = []; all.forEach(a => a.forEach(x => { if (x !== null) vals.push(x); }));
    if (!vals.length) { g.fillStyle = COL.text; g.textAlign = 'center'; g.fillText('Noch keine Daten', W / 2, H / 2); S.plot = null; return; }
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals); if (hi - lo < 1) hi = lo + 1;
    const pad = (hi - lo) * .06; if (lo < 0) lo -= pad; hi += pad;
    const ticks = niceTicks(lo, hi, H < 240 ? 4 : 5);
    const labW = Math.max(...ticks.map(t => g.measureText(kfmt(t)).width), 20);
    const L = Math.ceil(labW) + 16, Rr = 14, T = 14, B = 28;
    const X = i => L + (W - L - Rr) * i / (n - 1), Y = x => T + (H - T - B) * (1 - (x - lo) / (hi - lo));
    S.plot = { L, Rr, W, n, X, Y, T, B, H };
    // grid
    g.textAlign = 'right';
    for (const t of ticks) {
      const y = Y(t); if (y < T - 1 || y > H - B + 1) continue;
      g.strokeStyle = t === 0 ? 'rgba(29,20,70,.45)' : COL.grid; g.lineWidth = t === 0 ? 2 : 1; g.setLineDash([]);
      g.beginPath(); g.moveTo(L, y); g.lineTo(W - Rr, y); g.stroke();
      g.fillStyle = COL.text; g.fillText(kfmt(t), L - 7, y);
    }
    g.textAlign = 'left'; g.fillStyle = COL.text; g.fillText('CHF', 4, 6);
    // x labels
    g.textAlign = 'center';
    const span = v.ages[n - 1] - v.ages[0], step = span <= 12 ? 2 : span <= 25 ? 5 : 10;
    const used = [];
    const xl = [0, n - 1]; for (let i = 0; i < n; i++) if ((v.ages[i] - v.ages[0]) % step === 0) xl.push(i);
    for (const i of [...new Set(xl)].sort((a, b) => a - b)) {
      const x = X(i); if (used.some(u => Math.abs(u - x) < 34)) continue; used.push(x);
      g.fillStyle = COL.text; g.fillText(`${v.ages[i]} y`, clamp(x, L + 12, W - Rr - 14), H - B / 2 + 3);
    }
    // "today" + selected age markers
    const vline = (i, color, dash, w = 1.5) => { g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash); g.beginPath(); g.moveTo(X(i), T); g.lineTo(X(i), H - B); g.stroke(); g.setLineDash([]); };
    if (v.now > 0 && v.now < n - 1) {
      vline(v.now, 'rgba(29,20,70,.45)', [4, 4]);
      g.fillStyle = COL.ink; g.textAlign = 'left'; g.font = '900 11px Nunito, system-ui, sans-serif';
      g.fillText('today', X(v.now) + 4, T + 4); g.font = '800 12px Nunito, system-ui, sans-serif';
    }
    if (S.ageSel !== null && S.ageSel < n) vline(S.ageSel, 'rgba(255,184,0,.75)', [], 3);
    // bands
    const band = (lo5, hi95, fill, from = 0) => {
      g.beginPath(); let started = false;
      for (let i = from; i < n; i++) if (hi95[i] !== null) { const x = X(i), y = Y(hi95[i]); started ? g.lineTo(x, y) : g.moveTo(x, y); started = true; }
      for (let i = n - 1; i >= from; i--) if (lo5[i] !== null) g.lineTo(X(i), Y(lo5[i]));
      if (started) { g.closePath(); g.fillStyle = fill; g.fill(); }
    };
    band(v.p5, v.p95, COL.band);
    if (paths && v.c5 && v.c95) band(v.c5, v.c95, COL.altBand);
    const line = (a, color, width, dash = [], outline = 0, from = 0, to = n - 1, alpha = 1) => {
      const pts = []; for (let i = from; i <= to; i++) if (a && a[i] !== null) pts.push([X(i), Y(a[i])]);
      if (pts.length < 2) return pts;
      g.lineJoin = 'round'; g.lineCap = 'round'; g.globalAlpha = alpha;
      const stroke = (c, w) => { g.strokeStyle = c; g.lineWidth = w; g.setLineDash(dash); g.beginPath(); pts.forEach(([x, y], k) => k ? g.lineTo(x, y) : g.moveTo(x, y)); g.stroke(); };
      if (outline) stroke(COL.ink, width + outline); stroke(color, width); g.setLineDash([]); g.globalAlpha = 1; return pts;
    };
    if (paths && v.clife) line(v.clife, COL.alt, 2, [], 0, 0, n - 1, .55);
    line(v.comp, paths ? COL.alt : COL.comp, 2.8, [8, 6]);
    line(v.p50, COL.median, 3);
    // dein Leben: played part bold, the simulated rest of path 0 thinner
    if (v.now < n - 1) line(v.life, COL.life, 2.2, [2, 5], 0, v.now, n - 1, .9);
    const pp = line(v.life, COL.life, 4, [], 3, 0, v.now);
    const last = pp[pp.length - 1] || (at(v.life, v.now) !== null ? [X(v.now), Y(v.life[v.now])] : null);
    const dot = (x, y, fill, r) => { g.fillStyle = fill; g.strokeStyle = COL.ink; g.lineWidth = 2.5; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill(); g.stroke(); };
    if (last) dot(last[0], last[1], COL.life, 6);
    // hover
    const h = S.hover;
    if (h === null || h === undefined || h >= n) { R.tip.hidden = true; return; }
    vline(h, 'rgba(29,20,70,.6)', [], 1.5);
    const pts = [[v.comp, paths ? COL.alt : COL.comp], [v.life, COL.life], [v.p50, COL.median]];
    for (const [a, c] of pts) if (at(a, h) !== null) dot(X(h), Y(a[h]), c, 5);
    const rows = [
      ['Median of your plan', at(v.p50, h), COL.median],
      ['Range p5–p95', at(v.p5, h) !== null && at(v.p95, h) !== null ? `${kfmt(v.p5[h])} – ${kfmt(v.p95[h])}` : null, 'rgba(47,123,255,.5)'],
      ['your life', at(v.life, h), COL.life],
      [v.compLabel + (paths ? ' (Median)' : ''), at(v.comp, h), paths ? COL.alt : COL.comp],
    ];
    if (paths && v.clife) rows.push(['your life (second path)', at(v.clife, h), COL.alt]);
    const strong = document.createElement('strong');
    strong.textContent = `At age ${v.ages[h]}${h === v.now && v.now < n - 1 ? ' · today' : ''}`;
    const kids = [strong];
    for (const [k, val, c] of rows) {
      if (val === null) continue;
      const s = document.createElement('span'), i = document.createElement('i');
      i.style.background = c; s.append(i, `${k} · ${typeof val === 'string' ? val : chf(val)}`); kids.push(s);
    }
    R.tip.replaceChildren(...kids); R.tip.hidden = false;
    const x = X(h), tw = R.tip.offsetWidth, th = R.tip.offsetHeight;
    R.tip.style.left = Math.max(0, x + tw + 16 > W ? x - tw - 12 : x + 12) + 'px';
    const yTop = Math.min(...[at(v.p95, h), at(v.life, h), at(v.comp, h)].filter(z => z !== null).map(Y), H - B);
    R.tip.style.top = clamp(yTop - th - 8, 0, Math.max(0, H - B - th)) + 'px';
  }
  function setHover(i, announce = false) {
    S.hover = i; draw();
    if (announce) R.readout.textContent = R.tip.hidden ? '' : R.tip.innerText;
  }
  function pointerIdx(ev) {
    const p = S.plot; if (!p) return null;
    const x = ev.clientX - R.cv.getBoundingClientRect().left;
    return clamp(Math.round((x - p.L) / (p.W - p.L - p.Rr) * (p.n - 1)), 0, p.n - 1);
  }
  R.cv.addEventListener('pointermove', ev => { if (ev.pointerType === 'touch') return; const i = pointerIdx(ev); if (i !== S.hover) setHover(i); });
  R.cv.addEventListener('pointerdown', ev => { const i = pointerIdx(ev); if (i !== null) setHover(i); });
  R.cv.addEventListener('pointerleave', () => { if (S.hover !== null) setHover(null); });
  R.cv.addEventListener('blur', () => { if (S.hover !== null) setHover(null); });
  R.cv.addEventListener('keydown', ev => {
    if (!S.plot) return;
    const n = S.plot.n, cur = S.hover ?? (S.v ? S.v.now : 0);
    const next = { ArrowLeft: cur - 1, ArrowRight: cur + 1, Home: 0, End: n - 1 }[ev.key];
    if (ev.key === 'Escape' && S.hover !== null) { setHover(null); ev.preventDefault(); ev.stopPropagation(); return; }
    if (next === undefined) return;
    ev.preventDefault(); ev.stopPropagation();
    setHover(clamp(next, 0, n - 1), true);
  });

  /* ------------------------------------------------------------ timeline */
  function tlRange(v) { return { a0: v.ages[0], aN: v.ages[v.n - 1], lo: v.ages[0], hi: Math.max(v.ages[0], v.ages[v.n - 1] - 1) }; }
  const pct = (age, r) => ((age - r.a0) / Math.max(1, r.aN - r.a0) * 100);
  function renderTimeline(v, force = false) {
    if (S.drag) return;
    const items = arr(S.D.timeline).filter(t => t && t.id !== undefined && t.id !== null);
    const sig = JSON.stringify([items, v.ages[0], v.ages[v.n - 1], v.now, S.locked]);
    if (!force && sig === S.tlSig) return;
    S.tlSig = sig;
    const r = tlRange(v), span = Math.max(1, r.aN - r.a0);
    R.track.style.minWidth = Math.max(span * 46, 420) + 'px';
    const step = span <= 12 ? 2 : span <= 25 ? 5 : 10, tks = [];
    for (let a = r.a0; a <= r.aN; a++) if (a === r.a0 || a === r.aN || (a - r.a0) % step === 0) tks.push(a);
    R.ticks.innerHTML = tks.map(a => `<span style="left:${pct(a, r)}%">${a === r.a0 ? 'Start · ' + a : a + ' y'}</span>`).join('')
      + (v.now > 0 && v.now < v.n - 1 ? `<em class="tl-now" style="left:${pct(v.ages[v.now], r)}%">today</em>` : '');
    let moved = 0;
    R.chips.innerHTML = items.map(t => {
      const age = Math.round(num(t.age, r.a0));
      const alt = t.alt_age !== undefined && t.alt_age !== null && Number.isFinite(+t.alt_age) ? Math.round(+t.alt_age) : null;
      const shown = alt !== null ? alt : age, isMoved = alt !== null && alt !== age; if (isMoved) moved++;
      const movable = t.movable !== false && !S.locked;
      const desc = `${t.title || ''} at ${shown}${isMoved ? ` (played at ${age})` : ''}${t.movable === false ? ' · cannot be moved' : ' · drag or use the arrow keys to move'}`;
      const ghost = isMoved ? `<span class="tl-ghost" style="left:${pct(clamp(age, r.a0, r.aN), r)}%" title="${esc(`played at ${age}`)}"></span>` : '';
      return `${ghost}<button type="button" class="tl-chip ${isMoved ? 'moved' : ''} ${t.movable === false ? 'fixed' : ''}" data-id="${esc(t.id)}"
        data-age="${shown}" data-orig="${age}" data-movable="${movable ? 1 : 0}" style="left:${pct(clamp(shown, r.a0, r.aN), r)}%"
        title="${esc(desc)}" aria-label="${esc(desc)}"><span class="e">${esc(t.emoji || '•')}</span><span class="t">${esc(t.title || '')}</span><b>${shown}</b></button>`;
    }).join('');
    R.note.textContent = !items.length ? 'No decisions yet – as soon as you choose cards, they show up here.'
      : moved ? `${moved} ${moved === 1 ? 'decision moved' : 'decisions moved'} – compare in the "Two life paths" mode.`
      : '';
    layoutLanes();
  }
  function layoutLanes() {
    const w = R.track.clientWidth; if (!w) return;
    const chips = [...R.chips.querySelectorAll('.tl-chip')].map(b => ({ b, x: parseFloat(b.style.left) / 100 * w })).sort((a, b) => a.x - b.x);
    const lanes = [];
    for (const c of chips) {
      let lane = lanes.findIndex(x => c.x - x >= LANE_GAP); if (lane === -1) lane = lanes.length;
      lanes[lane] = c.x; c.b.style.setProperty('--lane', lane);
    }
    R.track.style.setProperty('--lanes', Math.max(1, lanes.length));
  }
  function commitMove(id, age) {
    if (S.locked) return;
    const items = arr(S.D && S.D.timeline);
    const moves = {};
    items.forEach(t => { if (t.alt_age !== undefined && t.alt_age !== null && Number.isFinite(+t.alt_age)) moves[String(t.id)] = Math.round(+t.alt_age); });
    moves[String(id)] = age;
    const allBack = Object.entries(moves).every(([k, a]) => { const t = items.find(x => String(x.id) === k); return t && Math.round(num(t.age)) === a; });
    if (allBack) { S.wantPaths = false; if (S.D.series && S.D.series.alt && onReset) onReset(); else renderTimeline(S.v, true); return; }
    S.wantPaths = true;
    if (onEdit) onEdit({ [String(id)]: age });
  }
  R.chips.addEventListener('pointerdown', ev => {
    const b = ev.target.closest('.tl-chip'); if (!b || ev.button !== 0 || S.drag) return;
    if (b.dataset.movable !== '1' || S.locked) return;
    S.drag = { id: b.dataset.id, pid: ev.pointerId, x: ev.clientX, sl: R.tlScroll.scrollLeft, from: +b.dataset.age, age: +b.dataset.age, moved: false, b };
    try { b.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
  });
  R.chips.addEventListener('pointermove', ev => {
    const d = S.drag; if (!d || d.pid !== ev.pointerId || !S.v) return;
    if (!d.moved && Math.abs(ev.clientX - d.x) < 5) return;
    d.moved = true;
    const box = R.tlScroll.getBoundingClientRect();
    if (ev.clientX > box.right - 28) R.tlScroll.scrollLeft += 16;
    if (ev.clientX < box.left + 28) R.tlScroll.scrollLeft -= 16;
    const r = tlRange(S.v), w = R.track.clientWidth || 1;
    const dx = ev.clientX - d.x + R.tlScroll.scrollLeft - d.sl;
    d.age = clamp(d.from + Math.round(dx / w * (r.aN - r.a0)), r.lo, r.hi);
    d.b.classList.add('dragging'); d.b.style.left = pct(d.age, r) + '%';
    const lab = d.b.querySelector('b'); if (lab) lab.textContent = d.age;
    R.guide.hidden = false; R.guide.style.left = pct(d.age, r) + '%'; R.guide.textContent = `${d.age} y`;
  });
  function endDrag(ev, commit) {
    const d = S.drag; if (!d || d.pid !== ev.pointerId) return;
    S.drag = null; R.guide.hidden = true; d.b.classList.remove('dragging');
    if (!d.moved) return;
    if (commit && d.age !== d.from) { d.b.classList.add('pending'); commitMove(d.id, d.age); return; }
    renderTimeline(S.v, true);
  }
  R.chips.addEventListener('pointerup', ev => endDrag(ev, true));
  R.chips.addEventListener('pointercancel', ev => endDrag(ev, false));
  R.chips.addEventListener('lostpointercapture', ev => endDrag(ev, false));
  R.chips.addEventListener('keydown', ev => {
    const b = ev.target.closest('.tl-chip'); if (!b || !S.v) return;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[ev.key]; if (!step) return;
    ev.preventDefault(); ev.stopPropagation();
    if (b.dataset.movable !== '1' || S.locked) return;
    const r = tlRange(S.v), age = clamp(+b.dataset.age + step, r.lo, r.hi);
    if (age !== +b.dataset.age) { b.classList.add('pending'); commitMove(b.dataset.id, age); }
  });

  /* ------------------------------------------------------------ controls */
  R.close.addEventListener('click', () => onClose && onClose());
  R.reset.addEventListener('click', () => { if (!R.reset.disabled && onReset) { S.wantPaths = false; onReset(); } });
  R.seg.addEventListener('click', ev => {
    const b = ev.target.closest('[data-dmode]'); if (!b || b.disabled) return;
    S.mode = b.dataset.dmode; S.hover = null; update();
  });
  R.age.addEventListener('change', () => { S.ageSel = +R.age.value; update(); });
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => draw()).observe(R.wrap);
    new ResizeObserver(() => layoutLanes()).observe(R.track);
  }

  function update() {
    const v = S.v = view(); if (!v) return;
    if (v.n >= 2) {
      if (S.mode === 'paths' && !v.hasAlt) S.mode = 'savings';
      R.seg.querySelectorAll('[data-dmode]').forEach(b => {
        const k = b.dataset.dmode, dis = k === 'paths' && !v.hasAlt;
        b.disabled = dis; b.setAttribute('aria-pressed', String(k === v.mode));
        b.title = dis ? 'Move a decision on the timeline or pick "Compare in the dashboard" in the chat' : '';
      });
      renderMetrics(v); renderLegend(v); renderSummary(v);
    }
    draw();
  }

  /** dash: payload dashboard block · opts: {loading, locked} */
  function render(dash, opts = {}) {
    if (!dash || typeof dash !== 'object') return;
    S.D = dash; S.locked = !!opts.locked; S.loading = !!opts.loading;
    const alt = dash.series && dash.series.alt ? JSON.stringify([dash.alt_label, dash.series.alt.p50]) : null;
    // a new (or changed) second life path -> show it; the user may switch away afterwards
    if (alt && (S.wantPaths || alt !== S.lastAlt)) S.mode = 'paths';
    if (!S.locked) S.wantPaths = false;
    S.lastAlt = alt;
    R.wrap.classList.toggle('loading', S.loading);
    R.reset.disabled = S.locked || !(dash.series && dash.series.alt);
    R.close.disabled = false;
    update();
    if (S.v && S.v.n >= 2) renderTimeline(S.v);
  }

  return {
    el, chatHost: R.chatHost, render,
    preferPaths() { S.wantPaths = true; },
    redraw() { draw(); layoutLanes(); },
    setLoading(on) { S.loading = !!on; R.wrap.classList.toggle('loading', S.loading); },
  };
}
