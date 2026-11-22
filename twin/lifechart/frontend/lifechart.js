// Life chart: Streamlit component (static, no build step, no CDN) after Juli's financial-twin chart.js/timeline.js
// and our dashboard.js port. Canvas with: p5–p95 band, median of the plan, one simulated life, a dashed comparison
// line ("two life paths"), event markers with labels, hover/keyboard readout per month and age.
// All numbers come from twin.engine.simulate (passed in as args.data, see twin/lifechart/__init__.py).
(function () {
  'use strict';

  const STANDALONE = (() => { try { return window.parent === window; } catch (e) { return false; } })();
  const $ = s => document.querySelector(s);
  const R = {
    root: document.documentElement, seg: $('.lc-seg'), band: $('.lc-band'), wrap: $('.lc-wrap'), cv: $('.lc-canvas'),
    tip: $('.lc-tip'), readout: $('#lc-readout'), legend: $('.lc-legend'), summary: $('.lc-summary'),
  };
  const S = { D: null, comp: null, band: true, hover: null, plot: null, sig: '' };

  /* ------------------------------------------------------------ formatting */
  const grp = v => Math.round(Math.abs(v)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  const chf = v => (v < -0.5 ? 'CHF −' : 'CHF ') + grp(v);
  const chfSigned = v => (v > 0.5 ? '+' : v < -0.5 ? '−' : '±') + 'CHF ' + grp(v);
  function kfmt(v) {
    const a = Math.abs(v), s = v < -0.5 ? '−' : '';
    if (a >= 1e6) return s + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (a >= 1e3) return s + (a / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'k';
    return s + Math.round(a);
  }
  const num = (v, d = 0) => (typeof v === 'number' && isFinite(v) ? v : d);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const series = (a, n) => {
    if (!Array.isArray(a)) return null;
    const out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = typeof a[i] === 'number' && isFinite(a[i]) ? a[i] : null;
    return out;
  };
  const at = (a, i) => (a && i !== null && i >= 0 && i < a.length ? a[i] : null);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function ageText(m, start) {
    const y = Math.floor(m / 12), mo = m % 12;
    const when = m === 0 ? 'today' : `in ${y ? y + ' y' : ''}${y && mo ? ' ' : ''}${mo ? mo + ' mo' : ''}`;
    return `Age ${start + y}${mo ? ` + ${mo} mo` : ''} · ${when}`;
  }
  function niceTicks(lo, hi, count) {
    const raw = (hi - lo) / count, mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
    const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag, out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
    return out;
  }
  const css = name => getComputedStyle(R.root).getPropertyValue(name).trim();
  function alpha(hex, a) {
    const m = /^#([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return `rgba(42,120,214,${a})`;
    const n = parseInt(m[1], 16);
    return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
  }

  /* ------------------------------------------------------------ view model */
  function view() {
    const D = S.D; if (!D) return null;
    const plan = D.plan || {};
    const n = Array.isArray(plan.p50) ? plan.p50.length : 0;
    if (n < 2) return { n };
    const comps = Array.isArray(D.comps) ? D.comps.filter(c => c && c.key) : [];
    const c = comps.find(x => x.key === S.comp) || null;
    const v = {
      n, start: Math.round(num(D.start_age, 0)), planLabel: String(plan.label || 'Your plan'),
      p5: series(plan.p5, n), p50: series(plan.p50, n), p95: series(plan.p95, n), life: series(plan.life, n),
      comp: c ? series(c.p50, n) : null, c5: c ? series(c.p5, n) : null, c95: c ? series(c.p95, n) : null,
      compLabel: c ? String(c.label) : '',
    };
    // events: one marker per month, labels joined
    const byMonth = new Map();
    for (const e of Array.isArray(D.events) ? D.events : []) {
      const m = Math.round(num(e && e.month, -1));
      if (m < 0 || m >= n) continue;
      const lbl = String(e.label || '').trim(); if (!lbl) continue;
      if (!byMonth.has(m)) byMonth.set(m, []);
      if (!byMonth.get(m).includes(lbl)) byMonth.get(m).push(lbl);
    }
    v.events = [...byMonth.entries()].sort((a, b) => a[0] - b[0]).map(([month, labels]) => ({ month, labels }));
    return v;
  }

  /* ------------------------------------------------------------ controls */
  function renderControls() {
    const D = S.D, comps = Array.isArray(D.comps) ? D.comps.filter(c => c && c.key) : [];
    if (S.comp !== null && !comps.some(c => c.key === S.comp)) S.comp = null;
    const items = [...comps.map(c => ({ key: c.key, label: c.label })), { key: '', label: 'No comparison' }];
    const sig = JSON.stringify(items);
    if (R.seg.dataset.sig !== sig) {
      R.seg.innerHTML = items.map(i => `<button type="button" data-k="${esc(i.key)}">${esc(i.label)}</button>`).join('');
      R.seg.dataset.sig = sig;
    }
    R.seg.hidden = comps.length === 0;
    for (const b of R.seg.querySelectorAll('button')) b.setAttribute('aria-pressed', String((b.dataset.k || null) === S.comp));
    R.band.checked = S.band;
  }
  R.seg.addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    S.comp = b.dataset.k || null; render();
  });
  R.band.addEventListener('change', () => { S.band = R.band.checked; render(); });

  function renderLegend(v) {
    const items = [`<span><i class="ln"></i>${esc(v.planLabel)} (median)</span>`];
    if (S.band) items.push(`<span><i class="bd"></i>90 % of the simulated lives (p5–p95)</span>`);
    if (v.life) items.push(`<span><i class="ln life"></i>One simulated life</span>`);
    if (v.comp) {
      items.push(`<span><i class="ln comp"></i>${esc(v.compLabel)} (median)</span>`);
      if (S.band && v.c5 && v.c95) items.push(`<span><i class="bd comp"></i>Its range</span>`);
    }
    if (v.events.length) items.push(`<span><i class="ev"></i>Life events</span>`);
    R.legend.innerHTML = items.join('');
  }
  function renderSummary(v) {
    const D = S.D, last = v.n - 1, endAge = v.start + Math.floor(last / 12);
    const a = at(v.p50, last), b = at(v.comp, last), parts = [];
    if (D.summary) parts.push(String(D.summary));
    if (a !== null && b !== null) {
      const d = a - b;
      parts.push(Math.abs(d) < 0.5 ? `At ${endAge}, both life paths end with the same median net worth.`
        : `At ${endAge}, ${v.planLabel.toLowerCase()} ends ${chf(Math.abs(d))} ${d > 0 ? 'above' : 'below'} “${v.compLabel}” in the median.`);
    } else if (a !== null) {
      parts.push(`At ${endAge}, the median net worth of ${v.planLabel.toLowerCase()} is ${chf(a)} (90 % range ${kfmt(at(v.p5, last))} – ${kfmt(at(v.p95, last))}).`);
    }
    R.summary.textContent = parts.join(' ');
  }

  /* ------------------------------------------------------------ chart */
  function draw() {
    const cv = R.cv, v = S.v;
    const W = cv.clientWidth, H = cv.clientHeight; if (!W || !H) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    const g = cv.getContext('2d'); if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const C = { ink: css('--ink'), muted: css('--muted'), grid: css('--grid'), zero: css('--zero'), plan: css('--plan'),
                comp: css('--comp'), life: css('--life'), event: css('--event') };
    const font = css('--font') || 'system-ui, sans-serif';
    g.font = `12px ${font}`; g.textBaseline = 'middle';
    if (!v || v.n < 2) {
      g.fillStyle = C.muted; g.textAlign = 'center'; g.fillText('No data yet', W / 2, H / 2); S.plot = null; return;
    }
    const n = v.n, last = n - 1, band = S.band;
    const all = [v.p50, v.life, v.comp].concat(band ? [v.p5, v.p95, v.c5, v.c95] : []).filter(Boolean);
    let lo = 0, hi = 0;
    for (const a of all) for (const x of a) if (x !== null) { if (x < lo) lo = x; if (x > hi) hi = x; }
    if (hi - lo < 1) hi = lo + 1;
    const pad = (hi - lo) * 0.05; if (lo < 0) lo -= pad; hi += pad;
    const ticks = niceTicks(lo, hi, H < 280 ? 4 : 5);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);

    // event label lanes (computed before the plot area so the top padding fits them)
    const L = Math.max(44, Math.ceil(Math.max(...ticks.map(t => g.measureText(kfmt(t)).width))) + 14);
    const Rr = 16, B = 32;
    const X0 = i => L + (W - L - Rr) * i / last;
    g.font = `600 11px ${font}`;
    const lanes = [], placed = [];
    for (const e of v.events) {
      let text = e.labels.join(' · ');
      const maxW = Math.max(60, W * 0.34);
      while (text.length > 4 && g.measureText(text).width > maxW) text = text.slice(0, -2);
      if (text !== e.labels.join(' · ')) text = text.replace(/\s+\S?$/, '') + '…';
      const w = g.measureText(text).width + 8, x = X0(e.month);
      const x0 = x + w + 4 > W - 2 ? x - w : x;               // flip to the left near the right edge
      let lane = lanes.findIndex(end => x0 >= end + 6);
      if (lane === -1) { lane = lanes.length; lanes.push(-1e9); }
      lanes[lane] = x0 + w;
      placed.push({ e, text, x0, w, lane, flip: x0 !== x });
    }
    const laneN = Math.min(lanes.length, 4), laneH = 15;
    const T = 16 + laneN * laneH;
    const X = X0, Y = x => T + (H - T - B) * (1 - (x - lo) / (hi - lo));
    S.plot = { L, Rr, W, n, X, Y, T, B, H };

    // grid + y labels
    g.font = `12px ${font}`; g.textAlign = 'right';
    for (const t of ticks) {
      const y = Y(t); if (y < T - 1 || y > H - B + 1) continue;
      g.strokeStyle = t === 0 ? C.zero : C.grid; g.lineWidth = t === 0 ? 1.5 : 1; g.setLineDash([]);
      g.beginPath(); g.moveTo(L, y); g.lineTo(W - Rr, y); g.stroke();
      g.fillStyle = C.muted; g.fillText(kfmt(t), L - 8, y);
    }
    g.textAlign = 'left'; g.fillText('CHF', 2, 8);
    // x labels: ages
    g.textAlign = 'center';
    const years = last / 12, step = years <= 6 ? 1 : years <= 12 ? 2 : years <= 30 ? 5 : 10;
    const used = [];
    for (let m = 0; m <= last; m += 12) {
      const yr = m / 12;
      if (m !== 0 && m !== last - (last % 12) && yr % step !== 0) continue;
      const x = X(m); if (used.some(u => Math.abs(u - x) < 30)) continue; used.push(x);
      g.fillStyle = C.muted; g.fillText(String(v.start + yr), clamp(x, L + 8, W - Rr - 8), H - B + 15);
    }
    g.textAlign = 'right'; g.fillText('Age', W - Rr, H - 6);

    // bands
    const fillBand = (a5, a95, fill) => {
      g.beginPath(); let started = false;
      for (let i = 0; i < n; i++) if (a95[i] !== null) { const x = X(i), y = Y(a95[i]); started ? g.lineTo(x, y) : g.moveTo(x, y); started = true; }
      for (let i = n - 1; i >= 0; i--) if (a5[i] !== null) g.lineTo(X(i), Y(a5[i]));
      if (started) { g.closePath(); g.fillStyle = fill; g.fill(); }
    };
    if (band && v.p5 && v.p95) fillBand(v.p5, v.p95, alpha(C.plan, 0.16));
    if (band && v.comp && v.c5 && v.c95) fillBand(v.c5, v.c95, alpha(C.comp, 0.12));

    // event markers (dashed line to the median, label at the top)
    g.font = `600 11px ${font}`; g.textBaseline = 'middle';
    for (const p of placed) {
      const x = X(p.e.month);
      g.strokeStyle = alpha(C.event, 0.45); g.lineWidth = 1; g.setLineDash([3, 4]);
      g.beginPath(); g.moveTo(x, T - 2); g.lineTo(x, H - B); g.stroke(); g.setLineDash([]);
      if (p.lane < laneN) {
        const ly = 9 + p.lane * laneH;
        g.fillStyle = C.event; g.textAlign = 'left';
        g.beginPath(); g.arc(x, ly, 2.5, 0, Math.PI * 2); g.fill();
        g.fillStyle = C.muted;
        g.fillText(p.text, p.flip ? p.x0 : x + 5, ly);
      }
    }

    // lines
    const line = (a, color, width, dash = []) => {
      if (!a) return;
      g.strokeStyle = color; g.lineWidth = width; g.lineJoin = 'round'; g.lineCap = 'round'; g.setLineDash(dash);
      g.beginPath(); let started = false;
      for (let i = 0; i < n; i++) { if (a[i] === null) continue; const x = X(i), y = Y(a[i]); started ? g.lineTo(x, y) : g.moveTo(x, y); started = true; }
      g.stroke(); g.setLineDash([]);
    };
    line(v.life, alpha(C.life, 0.75), 1.2);
    line(v.comp, C.comp, 2, [7, 5]);
    line(v.p50, C.plan, 2.7);

    const dot = (i, a, fill, r) => {
      const val = at(a, i); if (val === null) return;
      g.beginPath(); g.arc(X(i), Y(val), r, 0, Math.PI * 2); g.fillStyle = fill; g.fill();
      g.strokeStyle = 'white'; g.lineWidth = 1.5; g.stroke();
    };
    for (const e of v.events) dot(e.month, v.p50, C.event, 4);
    dot(last, v.p50, C.plan, 4.5);
    if (v.comp) dot(last, v.comp, C.comp, 4);

    // hover readout
    const h = S.hover;
    if (h === null || h > last) { R.tip.hidden = true; return; }
    g.strokeStyle = alpha(C.muted, 0.8); g.lineWidth = 1;
    g.beginPath(); g.moveTo(X(h), T); g.lineTo(X(h), H - B); g.stroke();
    if (v.comp) dot(h, v.comp, C.comp, 4);
    if (v.life) dot(h, v.life, C.life, 3.5);
    dot(h, v.p50, C.plan, 5);

    const kids = [];
    const add = (tag, text, color, cls) => {
      const el = document.createElement(tag);
      if (color) { const i = document.createElement('i'); i.style.background = color; el.append(i); }
      el.append(text); if (cls) el.className = cls; kids.push(el);
    };
    add('strong', ageText(h, v.start));
    const med = at(v.p50, h);
    if (med !== null) add('span', `${v.planLabel} · ${chf(med)}`, C.plan);
    if (band && at(v.p5, h) !== null && at(v.p95, h) !== null) add('span', `Range p5–p95 · ${kfmt(v.p5[h])} – ${kfmt(v.p95[h])}`, alpha(C.plan, 0.4), 'd');
    if (at(v.life, h) !== null) add('span', `One simulated life · ${chf(v.life[h])}`, C.life);
    const cv2 = at(v.comp, h);
    if (cv2 !== null) {
      add('span', `${v.compLabel} · ${chf(cv2)}`, C.comp);
      if (med !== null) add('span', `Difference · ${chfSigned(med - cv2)}`, null, 'd');
    }
    const yr = Math.floor(h / 12);
    const evs = v.events.filter(e => Math.floor(e.month / 12) === yr).flatMap(e => e.labels);
    if (evs.length) add('em', `📍 ${evs.join(' · ')}`);
    R.tip.replaceChildren(...kids); R.tip.hidden = false;
    const x = X(h), tw = R.tip.offsetWidth, th = R.tip.offsetHeight;
    R.tip.style.left = Math.max(0, x + tw + 16 > W ? x - tw - 12 : x + 12) + 'px';
    const tops = [at(v.p50, h), at(v.comp, h), at(v.life, h)].filter(z => z !== null).map(Y);
    const yTop = Math.min(...tops, H - B);
    R.tip.style.top = clamp(yTop - th - 10, 0, Math.max(0, H - B - th)) + 'px';
  }

  function setHover(i, announce) {
    S.hover = i; draw();
    if (announce) R.readout.textContent = R.tip.hidden ? '' : R.tip.innerText.replace(/\n+/g, ' · ');
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
    const n = S.plot.n, cur = S.hover ?? 0, jump = ev.shiftKey ? 12 : 1;
    if (ev.key === 'Escape') { setHover(null); return; }
    const next = { ArrowLeft: cur - jump, ArrowRight: cur + jump, Home: 0, End: n - 1 }[ev.key];
    if (next === undefined) return;
    ev.preventDefault();
    setHover(clamp(next, 0, n - 1), true);
  });

  /* ------------------------------------------------------------ render + Streamlit bridge */
  function post(type, data) {
    if (STANDALONE) return;
    try { window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, data || {}), '*'); } catch (e) { /* ignore */ }
  }
  let lastH = 0;
  function setHeight() {
    const h = Math.ceil(document.body.scrollHeight) + 4;
    if (Math.abs(h - lastH) < 2) return;
    lastH = h; post('streamlit:setFrameHeight', { height: h });
  }
  function applyTheme(t) {
    if (!t || typeof t !== 'object') return;
    const dark = t.base === 'dark';
    R.root.dataset.theme = dark ? 'dark' : 'light';
    if (t.textColor) R.root.style.setProperty('--ink', t.textColor);
    if (t.font) R.root.style.setProperty('--font', `${t.font}, system-ui, sans-serif`);
  }
  function render() {
    if (!S.D) return;
    renderControls();
    S.v = view();
    if (S.v && S.v.n >= 2) { renderLegend(S.v); renderSummary(S.v); }
    draw();
    setHeight();
  }
  function setData(D) {
    const sig = JSON.stringify(D);
    if (sig === S.sig) return;
    const first = !S.sig;
    S.sig = sig; S.D = D;
    const comps = Array.isArray(D.comps) ? D.comps : [];
    if (first || (S.comp !== null && !comps.some(c => c && c.key === S.comp))) {
      S.comp = D.default_comp && comps.some(c => c && c.key === D.default_comp) ? D.default_comp : (comps[0] ? comps[0].key : null);
    }
    if (first && typeof D.show_band === 'boolean') S.band = D.show_band;
    S.hover = null; R.readout.textContent = '';
    if (D.height) R.cv.style.height = Math.max(200, Math.round(num(D.height, 330))) + 'px';
    render();
  }

  new ResizeObserver(() => { draw(); setHeight(); }).observe(R.wrap);

  if (!STANDALONE) {
    window.addEventListener('message', ev => {
      const d = ev.data; if (!d || d.type !== 'streamlit:render') return;
      applyTheme(d.theme);
      const D = d.args && d.args.data;
      if (D && typeof D === 'object') setData(D);
    });
    post('streamlit:componentReady', { apiVersion: 1 });
  } else {
    // opened directly (python3 -m http.server): made-up demo data so the chart can be checked without Streamlit
    const n = 121, p50 = [], p5 = [], p95 = [], life = [], c50 = [], c5 = [], c95 = [];
    for (let i = 0; i < n; i++) {
      const base = 12000 + i * 520 + (i > 48 ? -60000 + (i - 48) * 300 : 0), s = 900 * Math.sqrt(i);
      p50.push(base); p5.push(base - 1.6 * s); p95.push(base + 1.9 * s); life.push(base + s * Math.sin(i / 7));
      c50.push(12000 + i * 610); c5.push(12000 + i * 610 - 1.5 * s); c95.push(12000 + i * 610 + 1.8 * s);
    }
    setData({ start_age: 26, plan: { label: 'Your plan', p5, p50, p95, life },
              comps: [{ key: 'none', label: 'Without life events', p5: c5, p50: c50, p95: c95 }],
              events: [{ month: 48, label: 'House purchase' }, { month: 50, label: 'Wedding' }, { month: 84, label: 'Child' }],
              summary: 'Demo data.' });
  }
})();
