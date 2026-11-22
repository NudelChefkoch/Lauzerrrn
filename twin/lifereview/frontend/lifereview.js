// Life review: Streamlit component (static, no build step, no CDN) with three views, chosen by args.view:
//   "timeline"    – the played life from the start age to 85 with ALL events; decisions can be dragged to another
//                   age, removed or restored, new events added ("+ Add event"); posts move/remove/restore/add/reset.
//                   data.mode === 'plan': the analysis page's own life plan (no game) – same chips and actions, no
//                   reset, wording without "played" / "new path"; data.empty = text when there are no events
//   "suggestions" – the twin's suggestion cards (▲ green / ▼ red with the CHF effect at 85); posts apply
//   "chart"       – expected net worth (after Juli's financial-twin chart.js and our dashboard.js port): p5–p95 band,
//                   median of the played path (blue), the second path (orange), "your life" (pink), event markers,
//                   hover / arrow-key readout, legend, summary line; posts nothing
// Every posted value is {action, nonce, ...}; the Python wrapper (twin/lifereview/__init__.py) drops repeated nonces.
// Opened directly (outside Streamlit) it shows all three views with made-up demo data and applies actions locally.
(function () {
  'use strict';

  const STANDALONE = (() => { try { return window.parent === window; } catch (e) { return false; } })();
  const $ = s => document.querySelector(s);
  const BODY = document.body;

  /* ================================================================ formatting */
  const grp = v => Math.round(Math.abs(v)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  const chf = v => (v < -0.5 ? '−CHF ' : 'CHF ') + grp(v);
  const chfSigned = v => (v > 0.5 ? '+' : v < -0.5 ? '−' : '±') + 'CHF ' + grp(v);
  function kfmt(v) {
    const a = Math.abs(v), s = v < -0.5 ? '−' : '';
    if (a >= 1e6) return s + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
    if (a >= 1e3) return s + (a / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'k';
    return s + Math.round(a);
  }
  const isNum = v => typeof v === 'number' && isFinite(v);
  const num = (v, d = 0) => (isNum(v) ? v : (typeof v === 'string' && v.trim() !== '' && isFinite(+v) ? +v : d));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const arr = a => (Array.isArray(a) ? a : []);
  const esc = s => String(s === undefined || s === null ? '' : s)
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const series = (a, n) => {
    if (!Array.isArray(a)) return null;
    const out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = isNum(a[i]) ? a[i] : null;
    return out.some(x => x !== null) ? out : null;
  };
  const at = (a, i) => (a && i !== null && i >= 0 && i < a.length ? a[i] : null);
  const ageInt = a => Math.floor(a + 1e-6);
  const ARROW = { up: ['▲', 'Better for your money'], down: ['▼', 'Costs you money'], flat: ['●', 'About the same'] };
  const impactOf = v => (v === 'up' || v === 'down' || v === 'flat' ? v : null);

  /** Greedy lanes like Juli's timeline: boxes [{l, r}] in any order -> lane index per box (input order). */
  function assignLanes(boxes, gap = 8) {
    const order = boxes.map((b, i) => i).sort((a, b) => boxes[a].l - boxes[b].l || a - b);
    const ends = [], out = new Array(boxes.length);
    for (const i of order) {
      let lane = ends.findIndex(end => boxes[i].l >= end + gap);
      if (lane === -1) { lane = ends.length; ends.push(0); }
      ends[lane] = boxes[i].r; out[i] = lane;
    }
    return out;
  }
  /** Ticks every 5 years plus start and end (multiples of 5 too close to either end are skipped). */
  function ticks5(a0, aN) {
    const out = [a0];
    for (let a = Math.ceil((a0 + 1) / 5) * 5; a < aN; a += 5) if (a - a0 >= 2 && aN - a >= 2) out.push(a);
    if (aN > a0) out.push(aN);
    return out;
  }

  /* ================================================================ Streamlit bridge */
  const S = { view: null, sig: '', seq: 0, lastSent: '', lastSentT: 0, busy: false, busyTimer: 0, frameH: 0, minH: 0 };
  function post(type, data) {
    if (STANDALONE) return;
    try { window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, data || {}), '*'); } catch (e) { /* ignore */ }
  }
  function setHeight() {
    const h = Math.max(S.minH, Math.ceil(BODY.scrollHeight) + 2);
    if (Math.abs(h - S.frameH) < 2) return;
    S.frameH = h; post('streamlit:setFrameHeight', { height: h });
  }
  function nonce() { return Date.now().toString(36) + '-' + (++S.seq) + '-' + Math.random().toString(36).slice(2, 8); }
  /** Post one action to Python. The same action twice within 700 ms (double click) is sent once. */
  function send(action) {
    const key = JSON.stringify(action), now = Date.now();
    if (key === S.lastSent && now - S.lastSentT < 700) return false;
    S.lastSent = key; S.lastSentT = now;
    const value = Object.assign({}, action, { nonce: nonce() });
    if (STANDALONE) { DEMO.apply(value); return true; }
    post('streamlit:setComponentValue', { value, dataType: 'json' });
    setBusy(true);
    return true;
  }
  function setBusy(on) {
    S.busy = !!on;
    clearTimeout(S.busyTimer);
    if (on) S.busyTimer = setTimeout(() => { setBusy(false); rerender(); }, 6000);   // page did not answer: undo visuals
    TL.busy(S.busy); SG.busy(S.busy);
  }

  /* ================================================================ (1) TIMELINE */
  const TL = (() => {
    const q = s => $('.tl ' + s);
    const R = {
      root: $('.tl'), title: q('.tl-title'), hint: q('.tl-hint'), add: q('.tl-add'), reset: q('.tl-reset'),
      panel: q('.tl-addpanel'), grid: q('.ap-grid'), form: q('.ap-form'), close: q('.ap-close'),
      scroll: q('.tl-scroll'), track: q('.tl-track'), ticks: q('.tl-ticks'), ghosts: q('.tl-ghosts'), guide: q('.tl-guide'),
      items: q('.tl-items'), events: q('.tl-events'), info: q('.tl-info'), legend: q('.tl-legend'),
    };
    const LANE_H = 46, CHIP_H = 34, EV_H = 32, MAX_LANES = 5, MAX_EV_LANES = 4;
    const T = { M: null, geo: null, drag: null, key: null, open: false, sel: null, selAge: null, selParams: {}, gridSig: '', focusId: null };

    function model(D) {
      const a0 = Math.round(num(D.start_age, 25)), aN = Math.max(a0 + 1, Math.round(num(D.end_age, 85)));
      const all = arr(D.items).filter(t => t && t.id !== undefined && t.id !== null).map(t => {
        const age = clamp(num(t.age, a0), a0, aN);
        const alt = t.alt_age === undefined || t.alt_age === null || !isFinite(+t.alt_age) ? null : clamp(+t.alt_age, a0, aN);
        const kind = t.kind === 'event' || t.kind === 'added' ? t.kind : 'decision';
        return {
          id: String(t.id), kind, key: t.key === undefined ? '' : String(t.key), emoji: t.emoji ? String(t.emoji) : (kind === 'event' ? '📍' : '📌'),
          title: String(t.title || t.key || ''), cat: t.cat ? String(t.cat) : '', age, alt,
          shown: alt !== null ? alt : age, moved: kind !== 'added' && alt !== null && Math.abs(alt - age) > 0.01,
          removed: !!t.removed, movable: t.movable !== false, impact: impactOf(t.impact),
          follows: t.follows === undefined || t.follows === null ? null : String(t.follows),
        };
      });
      const byId = new Map(all.map(t => [t.id, t]));
      for (const t of all) if (t.kind === 'event' && t.follows && byId.has(t.follows) && byId.get(t.follows).removed) t.removed = true;
      const addable = arr(D.addable).filter(o => o && o.key).map(o => ({
        key: String(o.key), emoji: o.emoji ? String(o.emoji) : '➕', title: String(o.title || o.key), cat: o.cat ? String(o.cat) : '',
        min: Math.max(a0, Math.round(num(o.min_age, a0))), max: Math.min(aN - 1, Math.round(num(o.max_age, aN - 1))),
        params: paramList(o.params),
      })).filter(o => o.min <= o.max);
      return { a0, aN, all, byId, decisions: all.filter(t => t.kind !== 'event'), events: all.filter(t => t.kind === 'event'),
               addable, hasAlt: !!D.has_alt, title: D.title ? String(D.title) : 'YOUR TIMELINE', hint: D.hint ? String(D.hint) : '',
               plan: D.mode === 'plan', empty: D.empty ? String(D.empty) : '' };
    }
    function paramList(p) {
      const list = Array.isArray(p) ? p : (p && typeof p === 'object' ? Object.entries(p).map(([name, s]) => Object.assign({ name }, s || {})) : []);
      return list.filter(s => s && s.name !== undefined).map(s => {
        const min = num(s.min, 0), max = Math.max(min, num(s.max, min)), step = num(s.step, 1) > 0 ? num(s.step, 1) : 1;
        const def = clamp(num(s.value, num(s.default, min)), min, max);
        return { name: String(s.name), label: String(s.label || s.name), min, max, step, def, unit: s.unit === undefined ? 'CHF' : String(s.unit || '') };
      });
    }
    const fmtParam = (p, v) => (p.unit === 'CHF' ? (p.min < 0 ? chfSigned(v) : chf(v)) : `${v}${p.unit ? ' ' + p.unit : ''}`);
    function range(t) {
      const M = T.M; let lo = M.a0, hi = M.aN - 1;
      if (t.kind === 'added') { const o = M.addable.find(x => x.key === t.key); if (o) { lo = o.min; hi = o.max; } }
      return [lo, hi];
    }
    const removable = t => t.kind !== 'event' && (t.movable || t.kind === 'added');
    const canMove = t => t.kind !== 'event' && t.movable && !t.removed && !S.busy;

    /* ---------------------------------------------------------- render */
    function render(D) {
      const M = T.M = model(D);
      R.title.textContent = M.title;
      if (M.hint) R.hint.textContent = M.hint;
      R.reset.disabled = !M.hasAlt || S.busy;
      R.reset.hidden = M.plan;
      R.add.hidden = !M.addable.length;
      R.ticks.innerHTML = ticks5(M.a0, M.aN).map(a =>
        `<span class="${a === M.aN ? 'end' : ''}" style="left:${((a - M.a0) / (M.aN - M.a0) * 100).toFixed(3)}%">${a === M.a0 ? 'Start · ' + a : a}</span>`).join('');
      R.items.innerHTML = M.decisions.map(chipHtml).join('');
      R.events.innerHTML = M.events.map(evHtml).join('');
      if (!M.decisions.length && !M.events.length) R.info.textContent = M.empty || 'No events yet – play a life first.';
      renderLegend(M);
      renderAddPanel();
      layout();
      if (T.focusId) {   // keep keyboard focus on the chip that was just moved
        const b = R.items.querySelector(`.tl-chip[data-id="${cssId(T.focusId)}"]`);
        if (b) { try { b.focus({ preventScroll: true }); } catch (e) { b.focus(); } }
        T.focusId = null;
      }
      if (!S.busy && (M.decisions.length || M.events.length)) R.info.innerHTML = summaryInfo(M);
    }
    const cssId = id => String(id).replace(/["\\]/g, '\\$&');
    function chipHtml(t) {
      const imp = t.impact || 'none', arrow = ARROW[t.impact];
      const cls = ['tl-chip', imp, t.moved ? 'moved' : '', t.removed ? 'removed' : '', t.kind === 'added' ? 'added' : ''].filter(Boolean).join(' ');
      const shownAge = ageInt(t.shown);
      const label = describe(t);
      const x = t.removed
        ? `<button type="button" class="tl-x restore" data-x="restore" data-id="${esc(t.id)}" aria-label="${esc('Bring back ' + t.title)}" title="Bring back">↺</button>`
        : removable(t) ? `<button type="button" class="tl-x" data-x="remove" data-id="${esc(t.id)}" aria-label="${esc('Remove ' + t.title + (T.M && T.M.plan ? ' from your plan' : ' from the new path'))}" title="${T.M && T.M.plan ? 'Remove from your plan' : 'Remove from the new path'}">✕</button>` : '';
      return `<div class="tl-item" role="listitem" data-id="${esc(t.id)}"><button type="button" class="${cls}" data-id="${esc(t.id)}" ` +
        `data-movable="${t.movable && !t.removed ? 1 : 0}" aria-label="${esc(label)}" title="${esc(label)}">` +
        (t.kind === 'added' ? '<span class="plus" aria-hidden="true">+</span>' : '') +
        `<span class="e" aria-hidden="true">${esc(t.emoji)}</span><span class="t">${esc(t.title)}</span>` +
        `<span class="a">${shownAge}</span>${arrow ? `<span class="ar" aria-hidden="true">${arrow[0]}</span>` : ''}</button>${x}</div>`;
    }
    function evHtml(t) {
      const label = describe(t);
      return `<div class="tl-ev ${t.moved ? 'moved' : ''} ${t.removed ? 'removed' : ''}" role="listitem" tabindex="0" data-id="${esc(t.id)}" ` +
        `data-follows="${esc(t.follows || '')}" title="${esc(label)}" aria-label="${esc(label)}"><span class="ei" aria-hidden="true">${esc(t.emoji)}</span>` +
        `<span class="t">${esc(t.title)}</span><span class="a">${ageInt(t.shown)}</span></div>`;
    }
    function describe(t) {
      const parts = [`${t.title}`];
      if (t.kind === 'added') parts.push(`added in the new path at ${ageInt(t.shown)}`);
      else if (t.moved) parts.push(`played at ${ageInt(t.age)}, new path at ${ageInt(t.alt)}`);
      else parts.push(`at ${ageInt(t.age)}`);
      if (t.removed) parts.push('removed in the new path');
      if (t.kind === 'event' && t.follows && T.M && T.M.byId.has(t.follows)) parts.push(`follows from “${T.M.byId.get(t.follows).title}”`);
      if (t.impact) parts.push(ARROW[t.impact][1]);
      if (t.kind !== 'event') {
        if (t.removed) parts.push('press Enter to bring it back');
        else if (t.movable) parts.push('drag or use the arrow keys to move, Delete removes it');
        else parts.push('cannot be moved');
      }
      return parts.join(' · ');
    }
    function summaryInfo(M) {
      const moved = M.decisions.filter(t => t.moved).length, removed = M.decisions.filter(t => t.removed).length;
      const added = M.decisions.filter(t => t.kind === 'added').length;
      if (!moved && !removed && !added) return '';
      const bits = [];
      if (moved) bits.push(`${moved} moved`);
      if (removed) bits.push(`${removed} removed`);
      if (added) bits.push(`${added} added`);
      return `🧭 <b>Your new path:</b> ${esc(bits.join(' · '))} – compare the net worth below.`;
    }
    function renderLegend(M) {
      const imps = new Set(M.decisions.map(t => t.impact).filter(Boolean));
      const out = Object.entries(ARROW).filter(([k]) => imps.has(k))
        .map(([k, [a, w]]) => `<span class="${k}"><i>${a}</i>${esc(w)}</span>`);
      if (M.decisions.some(t => t.moved)) out.push('<span><i class="sw" style="--bg:#ffc185"></i>Moved (dashed ring = played age)</span>');
      if (M.decisions.some(t => t.kind === 'added')) out.push('<span><i class="sw" style="--bg:#fff6c9"></i>Added by you</span>');
      if (M.decisions.some(t => t.removed)) out.push('<span><i class="sw" style="--bg:#eceaf6"></i>Removed</span>');
      if (M.events.length) out.push('<span><i class="sw" style="--bg:#fff;border-radius:50%"></i>What followed</span>');
      R.legend.innerHTML = out.join('');
    }

    /* ---------------------------------------------------------- layout (px, lanes) */
    function layout() {
      const M = T.M; if (!M) return;
      const base = Math.max(320, (R.scroll.clientWidth || 900) - 112);
      const chips = [...R.items.querySelectorAll('.tl-chip')].map(b => ({ b, t: M.byId.get(b.dataset.id), w: b.offsetWidth || estimateW(b) }));
      const evs = [...R.events.querySelectorAll('.tl-ev')].map(b => ({ b, t: M.byId.get(b.dataset.id), w: b.offsetWidth || estimateW(b) }));
      const place = (list, W, pad) => {
        const ppy = W / (M.aN - M.a0);
        const boxes = list.map(c => {
          const x = (c.t.shown - M.a0) * ppy, l = clamp(x - c.w / 2, -pad, W + pad - c.w);
          return { x, l, r: l + c.w };
        });
        return { boxes, lanes: assignLanes(boxes, 8) };
      };
      let W = base, P = place(chips, W, 46);
      for (const f of [1.5, 2.2, 3.2, 4.5]) {            // crowded years: a wider, scrolling track
        if (Math.max(-1, ...P.lanes) < MAX_LANES) break;
        W = Math.round(base * f); P = place(chips, W, 46);
      }
      R.track.style.width = W > base ? W + 'px' : '';
      const nUp = Math.max(1, Math.max(-1, ...P.lanes) + 1), axisY = 18 + nUp * LANE_H;
      R.track.style.setProperty('--axis-y', axisY + 'px');
      const ppy = W / (M.aN - M.a0), X = age => (age - M.a0) * ppy;
      let dots = '';
      chips.forEach((c, k) => {
        const box = P.boxes[k], lane = P.lanes[k], top = axisY - 18 - CHIP_H - lane * LANE_H;
        c.b.style.left = box.l + 'px'; c.b.style.top = top + 'px';
        c.b.style.setProperty('--sx', (box.x - box.l) + 'px');
        c.b.style.setProperty('--stem', (14 + lane * LANE_H) + 'px');
        c.b.dataset.left = box.l; c.b.dataset.top = top;
        const x = c.b.parentNode && c.b.parentNode.querySelector('.tl-x');
        if (x) { x.style.left = (box.l + c.w - 13) + 'px'; x.style.top = (top - 11) + 'px'; x.style.visibility = ''; }
        const t = c.t;
        dots += `<span class="tl-dot ${t.impact || 'none'}" style="left:${box.x}px;top:${axisY + 6}px${t.removed ? ';opacity:.4' : ''}"></span>`;
        if (t.moved) dots += `<span class="tl-ghost" style="left:${X(t.age)}px;top:${axisY + 6}px" title="${esc(`${t.title}: played at ${ageInt(t.age)}`)}"><span>was ${ageInt(t.age)}</span></span>`;
      });
      R.ghosts.innerHTML = dots;
      // events below the axis
      const E = place(evs, W, 40), evTop0 = axisY + 44;
      const nEv = Math.min(MAX_EV_LANES, Math.max(-1, ...E.lanes) + 1);
      evs.forEach((c, k) => {
        const box = E.boxes[k], lane = Math.min(E.lanes[k], MAX_EV_LANES - 1), top = evTop0 + lane * EV_H;
        c.b.style.left = box.l + 'px'; c.b.style.top = top + 'px';
        c.b.style.setProperty('--sx', (box.x - box.l) + 'px');
        c.b.style.setProperty('--stem', (top - axisY - 18) + 'px');
        c.b.dataset.left = box.l;
      });
      R.track.style.height = (nEv ? evTop0 + nEv * EV_H + 4 : axisY + 44) + 'px';
      T.geo = { W, ppy, axisY, X };
      setHeight();
    }
    const estimateW = b => Math.min(176, 46 + (b.textContent || '').length * 7.2);

    /* ---------------------------------------------------------- moving (drag + keys) */
    function followers(id) { return [...R.events.querySelectorAll('.tl-ev')].filter(e => e.dataset.follows === String(id)); }
    function preview(b, t, age) {        // show a chip (and its follow-up events) at `age` without posting yet
      const g = T.geo; if (!g) return;
      const dx = (age - t.shown) * g.ppy;
      b.style.left = (num(+b.dataset.left) + dx) + 'px';
      const x = b.parentNode && b.parentNode.querySelector('.tl-x'); if (x) x.style.visibility = 'hidden';
      const lab = b.querySelector('.a'); if (lab) lab.textContent = String(age);
      for (const e of followers(t.id)) { e.style.left = (num(+e.dataset.left) + dx) + 'px'; e.classList.add('linked'); }
      R.guide.hidden = false; R.guide.style.left = g.X(age) + 'px'; R.guide.style.height = (g.axisY + 14) + 'px';
      R.guide.textContent = `${age} y`;
      if (!t.moved && t.kind !== 'added' && !(T.M && T.M.plan) && !R.ghosts.querySelector('.tl-ghost.tmp')) {
        R.ghosts.insertAdjacentHTML('beforeend', `<span class="tl-ghost tmp" style="left:${g.X(t.age)}px;top:${g.axisY + 6}px"><span>was ${ageInt(t.age)}</span></span>`);
      }
      R.info.innerHTML = `${esc(t.emoji)} <b>${esc(t.title)}</b> → age ${age}` + (t.kind !== 'added' ? ` <span>(${T.M && T.M.plan ? 'was' : 'played at'} ${ageInt(t.age)})</span>` : '');
    }
    function cancelPreview() {
      R.guide.hidden = true;
      R.events.querySelectorAll('.linked').forEach(e => e.classList.remove('linked'));
      R.ghosts.querySelectorAll('.tl-ghost.tmp').forEach(e => e.remove());
      layout();
      if (T.M) R.info.innerHTML = summaryInfo(T.M);
    }
    function commitMove(t, age) {
      R.guide.hidden = true;
      const from = Math.round(t.shown);
      if (age === from) { cancelPreview(); return; }
      const b = R.items.querySelector(`.tl-chip[data-id="${cssId(t.id)}"]`); if (b) b.classList.add('pending');
      T.focusId = t.id;
      send({ action: 'move', id: t.id, age: Math.round(age) });
    }

    R.items.addEventListener('pointerdown', ev => {
      const b = ev.target.closest('.tl-chip'); if (!b || ev.button !== 0 || T.drag) return;
      const t = T.M && T.M.byId.get(b.dataset.id); if (!t || !canMove(t)) return;
      const from = Math.round(t.shown);
      T.drag = { t, b, pid: ev.pointerId, x0: ev.clientX, sl: R.scroll.scrollLeft, from, age: from, moved: false };
      try { b.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ }
    });
    R.items.addEventListener('pointermove', ev => {
      const d = T.drag; if (!d || d.pid !== ev.pointerId || !T.geo) return;
      if (!d.moved && Math.abs(ev.clientX - d.x0) < 5) return;
      if (!d.moved) { d.moved = true; d.b.classList.add('dragging'); }
      const box = R.scroll.getBoundingClientRect();
      if (ev.clientX > box.right - 28) R.scroll.scrollLeft += 14;
      if (ev.clientX < box.left + 28) R.scroll.scrollLeft -= 14;
      const [lo, hi] = range(d.t);
      const dx = ev.clientX - d.x0 + R.scroll.scrollLeft - d.sl;
      d.age = clamp(d.from + Math.round(dx / T.geo.ppy), lo, hi);
      preview(d.b, d.t, d.age);
    });
    function endDrag(ev, commit) {
      const d = T.drag; if (!d || d.pid !== ev.pointerId) return;
      T.drag = null; d.b.classList.remove('dragging');
      if (!d.moved) return;                    // a plain click: focus shows the info line
      if (commit && d.age !== d.from) commitMove(d.t, d.age); else cancelPreview();
    }
    R.items.addEventListener('pointerup', ev => endDrag(ev, true));
    R.items.addEventListener('pointercancel', ev => endDrag(ev, false));
    R.items.addEventListener('lostpointercapture', ev => endDrag(ev, false));

    function flushKey() {
      const k = T.key; if (!k) return;
      clearTimeout(k.timer); T.key = null;
      if (k.age !== k.from) commitMove(k.t, k.age); else cancelPreview();
    }
    R.items.addEventListener('keydown', ev => {
      const b = ev.target.closest('.tl-chip'); if (!b || !T.M) return;
      const t = T.M.byId.get(b.dataset.id); if (!t) return;
      const step = { ArrowLeft: -1, ArrowRight: 1 }[ev.key];
      if (step) {
        ev.preventDefault(); ev.stopPropagation();
        if (!canMove(t)) return;
        const [lo, hi] = range(t);
        if (!T.key || T.key.t.id !== t.id) { flushKey(); T.key = { t, b, from: Math.round(t.shown), age: Math.round(t.shown), timer: 0 }; }
        const k = T.key;
        k.age = clamp(k.age + step * (ev.shiftKey ? 5 : 1), lo, hi);
        preview(b, t, k.age);
        clearTimeout(k.timer); k.timer = setTimeout(flushKey, 700);
        return;
      }
      if (ev.key === 'Enter' && T.key && T.key.t.id === t.id) { ev.preventDefault(); flushKey(); return; }
      if (ev.key === 'Escape' && T.key) { ev.preventDefault(); clearTimeout(T.key.timer); T.key = null; cancelPreview(); return; }
      if ((ev.key === 'Delete' || ev.key === 'Backspace') && !S.busy) {
        ev.preventDefault();
        if (t.removed) send({ action: 'restore', id: t.id });
        else if (removable(t)) { b.classList.add('pending'); send({ action: 'remove', id: t.id }); }
        return;
      }
      if ((ev.key === 'Enter' || ev.key === ' ') && t.removed && !S.busy) { ev.preventDefault(); send({ action: 'restore', id: t.id }); }
    });
    R.items.addEventListener('click', ev => {
      const x = ev.target.closest('.tl-x'); if (!x || S.busy) return;
      const t = T.M && T.M.byId.get(x.dataset.id); if (!t) return;
      if (x.dataset.x === 'restore') send({ action: 'restore', id: t.id });
      else if (removable(t)) {
        const b = x.parentNode.querySelector('.tl-chip'); if (b) b.classList.add('pending');
        send({ action: 'remove', id: t.id });
      }
    });
    // info line + linked follow-up events on hover / focus
    function showInfo(t) {
      if (!t || S.busy || T.drag || T.key) return;
      R.events.querySelectorAll('.linked').forEach(e => e.classList.remove('linked'));
      if (t.kind !== 'event') followers(t.id).forEach(e => e.classList.add('linked'));
      R.info.innerHTML = `${esc(t.emoji)} ${esc(describe(t)).replace(/^([^·]+)/, '<b>$1</b>')}`;
    }
    function clearInfo() {
      if (S.busy || T.drag || T.key || !T.M) return;
      R.events.querySelectorAll('.linked').forEach(e => e.classList.remove('linked'));
      if (T.M.decisions.length || T.M.events.length) R.info.innerHTML = summaryInfo(T.M);
    }
    const itemOf = ev => { const b = ev.target.closest && ev.target.closest('.tl-chip, .tl-ev'); return b && T.M ? T.M.byId.get(b.dataset.id) : null; };
    for (const host of [R.items, R.events]) {
      host.addEventListener('focusin', ev => showInfo(itemOf(ev)));
      host.addEventListener('focusout', clearInfo);
      host.addEventListener('pointerover', ev => { const t = itemOf(ev); if (t) showInfo(t); });
      host.addEventListener('pointerleave', clearInfo);
    }

    /* ---------------------------------------------------------- add menu */
    function renderAddPanel() {
      const M = T.M;
      R.add.setAttribute('aria-expanded', String(T.open));
      R.panel.hidden = !T.open || !M.addable.length;
      const sig = JSON.stringify(M.addable.map(o => [o.key, o.title, o.min, o.max]));
      if (sig !== T.gridSig) {
        T.gridSig = sig;
        R.grid.innerHTML = M.addable.map(o => `<button type="button" class="ap-opt" data-key="${esc(o.key)}" aria-pressed="false">` +
          `<span class="e" aria-hidden="true">${esc(o.emoji)}</span><span>${esc(o.title)}<small>${esc(o.cat ? o.cat + ' · ' : '')}age ${o.min}–${o.max}</small></span></button>`).join('');
      }
      if (T.sel && !M.addable.some(o => o.key === T.sel)) T.sel = null;
      R.grid.querySelectorAll('.ap-opt').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.key === T.sel)));
      renderForm();
    }
    function renderForm() {
      const o = T.sel && T.M.addable.find(x => x.key === T.sel);
      if (!o) { R.form.hidden = true; R.form.innerHTML = ''; return; }
      T.selAge = clamp(Math.round(num(T.selAge, o.min)), o.min, o.max);
      for (const p of o.params) if (!(p.name in T.selParams)) T.selParams[p.name] = p.def;
      const field = (name, label, min, max, step, val, out) =>
        `<label class="ap-field"><span>${esc(label)} <output data-o="${esc(name)}">${esc(out)}</output></span>` +
        `<input type="range" data-p="${esc(name)}" min="${min}" max="${max}" step="${step}" value="${val}" aria-label="${esc(label)}"></label>`;
      R.form.innerHTML = `<div class="ap-sel">${esc(o.emoji)} ${esc(o.title)}${o.cat ? `<small>${esc(o.cat)}</small>` : ''}</div>` +
        field('__age', 'At age', o.min, o.max, 1, T.selAge, String(T.selAge)) +
        o.params.map(p => field(p.name, p.label, p.min, p.max, p.step, T.selParams[p.name], fmtParam(p, T.selParams[p.name]))).join('') +
        `<div class="ap-go-wrap"><button type="button" class="btn btn-green ap-go">ADD AT ${T.selAge}</button></div>`;
      R.form.hidden = false;
      setHeight();
    }
    R.add.addEventListener('click', () => {
      T.open = !T.open;
      renderAddPanel(); setHeight();
      if (T.open) { const f = R.grid.querySelector('.ap-opt'); if (f) f.focus(); }
    });
    R.close.addEventListener('click', () => { T.open = false; renderAddPanel(); setHeight(); R.add.focus(); });
    R.panel.addEventListener('keydown', ev => { if (ev.key === 'Escape') { T.open = false; renderAddPanel(); setHeight(); R.add.focus(); } });
    R.grid.addEventListener('click', ev => {
      const b = ev.target.closest('.ap-opt'); if (!b) return;
      if (T.sel !== b.dataset.key) { T.sel = b.dataset.key; T.selParams = {}; T.selAge = null; }
      renderAddPanel();
      const r = R.form.querySelector('input'); if (r) r.focus();
    });
    R.form.addEventListener('input', ev => {
      const inp = ev.target.closest('input[data-p]'); if (!inp) return;
      const o = T.M.addable.find(x => x.key === T.sel); if (!o) return;
      const v = +inp.value, name = inp.dataset.p, out = R.form.querySelector(`output[data-o="${cssId(name)}"]`);
      if (name === '__age') {
        T.selAge = v; if (out) out.textContent = String(v);
        const go = R.form.querySelector('.ap-go'); if (go) go.textContent = `ADD AT ${v}`;
      } else {
        const p = o.params.find(x => x.name === name); if (!p) return;
        T.selParams[name] = v; if (out) out.textContent = fmtParam(p, v);
      }
    });
    R.form.addEventListener('click', ev => {
      if (!ev.target.closest('.ap-go') || S.busy) return;
      const o = T.M.addable.find(x => x.key === T.sel); if (!o) return;
      const params = {}; for (const p of o.params) params[p.name] = num(T.selParams[p.name], p.def);
      if (send({ action: 'add', key: o.key, age: clamp(Math.round(num(T.selAge, o.min)), o.min, o.max), params })) {
        T.open = false; T.sel = null; T.selParams = {}; T.selAge = null; renderAddPanel(); setHeight();
      }
    });
    R.reset.addEventListener('click', () => { if (!R.reset.disabled && !S.busy) send({ action: 'reset' }); });

    if (typeof ResizeObserver !== 'undefined') {
      let lastW = 0;
      new ResizeObserver(() => { const w = R.scroll.clientWidth; if (Math.abs(w - lastW) > 1 && !T.drag) { lastW = w; layout(); } }).observe(R.scroll);
    }
    return {
      render, layout,
      busy(on) {
        if (!T.M) return;
        R.track.classList.toggle('busy', on);
        R.reset.disabled = on || !T.M.hasAlt;
        R.info.classList.toggle('busy', on);
        if (on) R.info.innerHTML = '🎲 <b>Your twin is recalculating …</b>';
      },
      _T: T,
    };
  })();

  /* ================================================================ (3) SUGGESTIONS */
  const SG = (() => {
    const R = { title: $('.sg-title'), intro: $('.sg-intro'), grid: $('.sg-grid') };
    let D = null;
    function render(data) {
      D = data;
      if (data.title) R.title.textContent = String(data.title);
      R.intro.textContent = data.intro !== undefined ? String(data.intro || '')
        : 'Tap “Try it” – your twin puts the change on your timeline and recalculates your net worth below.';
      const end = Math.round(num(data.end_age, 85)), vs = data.vs ? String(data.vs) : 'your path';
      const items = arr(data.items).filter(s => s && s.id !== undefined && s.id !== null);
      if (data.loading && !items.length) {
        R.grid.innerHTML = [0, 1, 2].map(() => '<div class="sg-skel"><span class="dice" aria-hidden="true">🎲</span>Your twin is thinking …</div>').join('');
        setHeight(); return;
      }
      if (!items.length) {
        R.grid.innerHTML = '<p class="sg-empty">No suggestions right now – move or add an event on your timeline yourself.</p>';
        setHeight(); return;
      }
      R.grid.innerHTML = items.map(s => {
        const imp = impactOf(s.impact) || 'flat', d = num(s.delta, NaN);
        const delta = isFinite(d) ? `${ARROW[imp][0]} ${chfSigned(d)}` : ARROW[imp][0];
        const words = ARROW[imp][1];
        const applied = !!s.applied;
        return `<article class="sg-card ${imp} ${applied ? 'applied' : ''}" data-id="${esc(s.id)}" aria-label="${esc(`${s.title || ''}: ${words}${isFinite(d) ? ', ' + chfSigned(d) + ' at ' + end : ''}`)}">` +
          `<div class="sg-top"><span class="sg-ic" aria-hidden="true">${esc(s.emoji || '💡')}</span><span class="sg-delta" title="${esc(words)}">${esc(delta)}</span></div>` +
          `<h3 class="sg-t">${esc(s.title || '')}</h3><p class="sg-x">${esc(s.text || '')}</p>` +
          `<div class="sg-foot"><span class="sg-at">${isFinite(d) ? esc(`at ${end} vs. ${vs}`) : ''}</span>` +
          `<button type="button" class="btn btn-sm ${imp === 'down' ? 'btn-pink' : 'btn-blue'} sg-go" data-id="${esc(s.id)}" ${applied ? 'disabled' : ''}>` +
          `${applied ? '✓ IN YOUR PATH' : 'TRY IT'}</button></div></article>`;
      }).join('') + (data.loading ? '<div class="sg-skel"><span class="dice" aria-hidden="true">🎲</span>More ideas …</div>' : '');
      busy(S.busy);
      setHeight();
    }
    function busy(on) {
      R.grid.querySelectorAll('.sg-go').forEach(b => {
        const card = b.closest('.sg-card');
        b.disabled = on || (card && card.classList.contains('applied'));
      });
      if (!on) R.grid.querySelectorAll('.sg-card.pending').forEach(c => c.classList.remove('pending'));
    }
    R.grid.addEventListener('click', ev => {
      const b = ev.target.closest('.sg-go'); if (!b || b.disabled || S.busy) return;
      const card = b.closest('.sg-card'); if (card) card.classList.add('pending');
      b.textContent = '…';
      send({ action: 'apply', id: b.dataset.id });
    });
    return { render, busy, get data() { return D; } };
  })();

  /* ================================================================ (4) CHART */
  const CH = (() => {
    const R = { title: $('.ch-title'), sub: $('.ch-sub'), band: $('.ch-band'), wrap: $('.ch-wrap'), cv: $('.ch-canvas'), tip: $('.ch-tip'),
                readout: $('#ch-readout'), legend: $('.ch-legend'), sum: $('.ch-sum') };
    const COL = { band: 'rgba(47,123,255,.20)', median: '#2f7bff', life: '#ff3d8b', alt: '#ff8a1f', altBand: 'rgba(255,138,31,.17)',
                  grid: '#ebe6fb', text: '#6b6394', ink: '#1d1446', played: '#7b4dff', altLife: 'rgba(255,138,31,.55)' };
    const C = { D: null, v: null, hover: null, plot: null, band: true };

    function niceTicks(lo, hi, count) {
      const raw = (hi - lo) / count, mag = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / mag;
      const step = (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * mag, out = [];
      for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Math.abs(v) < step / 1e6 ? 0 : v);
      return out;
    }
    /** markers: data.markers [{age, emoji, label, path: played|alt}] or derived from timeline items. */
    function markersOf(D, hasAlt) {
      if (Array.isArray(D.markers)) {
        return D.markers.filter(m => m && isNum(+m.age)).map(m => ({ age: +m.age, emoji: m.emoji ? String(m.emoji) : '', label: String(m.label || m.title || ''),
                                                                    path: m.path === 'alt' ? 'alt' : 'played' }));
      }
      const out = [];
      for (const t of arr(D.items)) {
        if (!t || !isNum(+t.age)) continue;
        const alt = t.alt_age === undefined || t.alt_age === null ? null : +t.alt_age;
        const base = { emoji: t.emoji ? String(t.emoji) : '', label: String(t.title || '') };
        if (t.kind !== 'added') out.push(Object.assign({ age: +t.age, path: 'played' }, base));
        if (hasAlt && !t.removed && (t.kind === 'added' || (alt !== null && Math.abs(alt - t.age) > 0.01))) {
          out.push(Object.assign({ age: t.kind === 'added' && alt === null ? +t.age : alt, path: 'alt' }, base));
        }
      }
      return out;
    }
    function view() {
      const D = C.D; if (!D) return null;
      const ages = arr(D.ages).map(a => num(a, NaN)).filter(isFinite), n = ages.length;
      if (n < 2) return { n, ages };
      const pl = D.played || {}, al = D.alt && typeof D.alt === 'object' ? D.alt : null;
      const v = { n, ages, a0: ages[0], aN: ages[n - 1],
                  p5: series(pl.p5, n), p50: series(pl.p50, n), p95: series(pl.p95, n), life: series(pl.life, n),
                  q5: al ? series(al.p5, n) : null, q50: al ? series(al.p50, n) : null, q95: al ? series(al.p95, n) : null,
                  qlife: al ? series(al.life, n) : null, label: D.label ? String(D.label) : '' };
      v.hasAlt = !!v.q50;
      v.markers = markersOf(D, v.hasAlt).filter(m => m.age >= v.a0 && m.age <= v.aN);
      return v;
    }
    const idxOfAge = (v, age) => clamp((age - v.a0) / (v.aN - v.a0) * (v.n - 1), 0, v.n - 1);
    const valAt = (a, fi) => {          // linear interpolation at a fractional index
      if (!a) return null;
      const i = Math.floor(fi), j = Math.min(a.length - 1, i + 1), f = fi - i;
      if (a[i] === null) return a[j]; if (a[j] === null) return a[i];
      return a[i] + (a[j] - a[i]) * f;
    };

    /** Series names: data.names {played, alt, life, played_events, alt_events} (the page's own plan uses other
     *  words than the played game). */
    function names() {
      const n = C.D && C.D.names && typeof C.D.names === 'object' ? C.D.names : {};
      const s = (k, d) => (n[k] ? String(n[k]) : d);
      return { played: s('played', 'Your path'), alt: s('alt', 'New path'), life: s('life', 'your life'),
               playedEv: s('played_events', 'Your events'), altEv: s('alt_events', 'Changed in the new path') };
    }
    function renderLegend(v) {
      const it = [], N = names();
      if (C.band) it.push(`<span><i class="bd" style="--c:${COL.band}"></i>Range p5–p95</span>`);
      it.push(`<span><i style="--c:${COL.median}"></i>${esc(N.played)} (median)</span>`);
      if (v.life) it.push(`<span><i style="--c:${COL.life}"></i>${esc(N.life)}</span>`);
      if (v.hasAlt) {
        it.push(`<span><i class="dash" style="--c:${COL.alt}"></i>${esc(v.label ? `${N.alt}: ${v.label}` : N.alt)} (median)</span>`);
        if (C.band && v.q5 && v.q95) it.push(`<span><i class="bd" style="--c:${COL.altBand}"></i>Range: ${esc(N.alt.toLowerCase())}</span>`);
      }
      if (v.markers.some(m => m.path === 'played')) it.push(`<span><i class="ev" style="--c:${COL.played}"></i>${esc(N.playedEv)}</span>`);
      if (v.markers.some(m => m.path === 'alt')) it.push(`<span><i class="ev" style="--c:${COL.alt}"></i>${esc(N.altEv)}</span>`);
      R.legend.innerHTML = it.join('');
    }
    function renderSummary(v) {
      const D = C.D, m = D.metrics && typeof D.metrics === 'object' ? D.metrics : {}, last = v.n - 1, end = Math.round(v.aN);
      const pe = isNum(m.played_end) ? m.played_end : at(v.p50, last);
      if (v.hasAlt) {
        const ae = isNum(m.alt_end) ? m.alt_end : at(v.q50, last);
        const d = isNum(m.delta_end) ? m.delta_end : (ae !== null && pe !== null ? ae - pe : null);
        if (d === null) { R.sum.innerHTML = ''; return; }
        const cls = d > 0.5 ? 'pos' : d < -0.5 ? 'neg' : '', N = names();
        R.sum.innerHTML = `<b class="${cls}">${esc(N.alt)}: ${esc(chfSigned(d))}</b> at ${end} vs. ${esc(N.played.toLowerCase())}` +
          (v.label ? ` <span>(“${esc(v.label)}”)</span>` : '') + '. ' +
          (pe !== null && ae !== null ? `Median at ${end}: ${esc(N.played.toLowerCase())} ${esc(chf(pe))} · ${esc(N.alt.toLowerCase())} ${esc(chf(ae))}.` : '');
      } else if (pe !== null) {
        const lo = at(v.p5, last), hi = at(v.p95, last);
        R.sum.innerHTML = `At ${end}, your expected (median) net worth is <b>${esc(chf(pe))}</b>` +
          (lo !== null && hi !== null ? ` – 90 % of the simulated lives end between ${esc(kfmt(lo))} and ${esc(kfmt(hi))}` : '') +
          '. Move or add events on your timeline to compare another path.';
      } else R.sum.innerHTML = '';
      // (D.summary is only the page's fallback text when this component is missing – the line above is complete)
    }

    function draw() {
      const cv = R.cv, v = C.v;
      const W = cv.clientWidth, H = cv.clientHeight; if (!W || !H) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      const g = cv.getContext && cv.getContext('2d'); if (!g) return;
      g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
      const F = (w, s) => `${w} ${s}px Nunito, system-ui, sans-serif`;
      g.font = F(800, 12); g.textBaseline = 'middle';
      const empty = msg => { g.fillStyle = COL.text; g.textAlign = 'center'; g.fillText(msg, W / 2, H / 2); C.plot = null; R.tip.hidden = true; };
      if (!v || v.n < 2) return empty('No data yet');
      const n = v.n, band = C.band;
      const all = [v.p50, v.life, v.q50, v.qlife].concat(band ? [v.p5, v.p95, v.q5, v.q95] : []).filter(Boolean);
      let lo = 0, hi = 0;
      for (const a of all) for (const x of a) if (x !== null) { if (x < lo) lo = x; if (x > hi) hi = x; }
      if (hi - lo < 1) hi = lo + 1;
      const pad = (hi - lo) * 0.06; if (lo < 0) lo -= pad; hi += pad;
      const ticks = niceTicks(lo, hi, H < 280 ? 4 : 5);
      lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
      const L = Math.max(44, Math.ceil(Math.max(...ticks.map(t => g.measureText(kfmt(t)).width))) + 16), Rr = 16, B = 30;
      const XA = age => L + (W - L - Rr) * (age - v.a0) / (v.aN - v.a0), X = i => XA(v.ages[i]);
      // marker label lanes at the top
      g.font = F(900, 11);
      const ends = [], placed = [];
      const groups = new Map();
      for (const m of v.markers) {
        const k = m.path + ':' + ageInt(m.age);
        if (!groups.has(k)) groups.set(k, { age: m.age, path: m.path, labels: [] });
        const lbl = `${m.emoji ? m.emoji + ' ' : ''}${m.label}`.trim();
        if (lbl && !groups.get(k).labels.includes(lbl)) groups.get(k).labels.push(lbl);
      }
      for (const e of [...groups.values()].sort((a, b) => a.age - b.age)) {
        let text = e.labels.join(' · ') || '•';
        const full = text, maxW = Math.max(70, W * 0.22);
        while (text.length > 4 && g.measureText(text).width > maxW) text = text.slice(0, -2);
        if (text !== full) text = text.replace(/\s+\S?$/, '') + '…';
        const w = g.measureText(text).width + 10, x = XA(e.age), x0 = x + w + 4 > W - 2 ? x - w : x;
        let lane = ends.findIndex(end => x0 >= end + 6);
        if (lane === -1) { lane = ends.length; ends.push(-1e9); }
        ends[lane] = x0 + w;
        placed.push({ e, text, x0, lane, flip: x0 !== x });
      }
      const laneN = Math.min(ends.length, 4), laneH = 16, T = 14 + laneN * laneH;
      const Y = x => T + (H - T - B) * (1 - (x - lo) / (hi - lo));
      C.plot = { L, Rr, W, n, X, Y, T, B, H };
      // grid + y labels
      g.font = F(800, 12); g.textAlign = 'right';
      for (const t of ticks) {
        const y = Y(t); if (y < T - 1 || y > H - B + 1) continue;
        g.strokeStyle = t === 0 ? 'rgba(29,20,70,.45)' : COL.grid; g.lineWidth = t === 0 ? 2 : 1; g.setLineDash([]);
        g.beginPath(); g.moveTo(L, y); g.lineTo(W - Rr, y); g.stroke();
        g.fillStyle = COL.text; g.fillText(kfmt(t), L - 8, y);
      }
      g.textAlign = 'left'; g.fillText('CHF', 2, T - 6 > 6 ? 6 : T - 4);
      // x labels every 5 years
      g.textAlign = 'center';
      const used = [];
      for (const a of ticks5(Math.round(v.a0), Math.round(v.aN))) {
        const x = XA(a); if (used.some(u => Math.abs(u - x) < 30)) continue; used.push(x);
        g.fillStyle = COL.text; g.fillText(String(a), clamp(x, L + 8, W - Rr - 8), H - B + 15);
      }
      g.textAlign = 'right'; g.fillText('Age', W - Rr, H - 5);
      // bands
      const fillBand = (a5, a95, fill) => {
        g.beginPath(); let started = false;
        for (let i = 0; i < n; i++) if (a95[i] !== null) { const x = X(i), y = Y(a95[i]); started ? g.lineTo(x, y) : g.moveTo(x, y); started = true; }
        for (let i = n - 1; i >= 0; i--) if (a5[i] !== null) g.lineTo(X(i), Y(a5[i]));
        if (started) { g.closePath(); g.fillStyle = fill; g.fill(); }
      };
      if (band && v.p5 && v.p95) fillBand(v.p5, v.p95, COL.band);
      if (band && v.hasAlt && v.q5 && v.q95) fillBand(v.q5, v.q95, COL.altBand);
      // markers: dashed vertical lines + labels at the top
      g.font = F(900, 11);
      for (const p of placed) {
        const x = XA(p.e.age), c = p.e.path === 'alt' ? COL.alt : COL.played;
        g.strokeStyle = p.e.path === 'alt' ? 'rgba(255,138,31,.55)' : 'rgba(123,77,255,.35)'; g.lineWidth = 1.2; g.setLineDash([3, 4]);
        g.beginPath(); g.moveTo(x, T - 2); g.lineTo(x, H - B); g.stroke(); g.setLineDash([]);
        if (p.lane < laneN) {
          const ly = 9 + p.lane * laneH;
          g.fillStyle = c; g.beginPath(); g.arc(x, ly, 3, 0, Math.PI * 2); g.fill();
          g.fillStyle = COL.ink; g.textAlign = 'left';
          g.fillText(p.text, p.flip ? p.x0 : x + 6, ly);
        }
      }
      // lines
      const line = (a, color, width, dash = [], outline = 0, alpha = 1) => {
        if (!a) return;
        const pts = []; for (let i = 0; i < n; i++) if (a[i] !== null) pts.push([X(i), Y(a[i])]);
        if (pts.length < 2) return;
        g.lineJoin = 'round'; g.lineCap = 'round'; g.globalAlpha = alpha;
        const stroke = (c, w) => { g.strokeStyle = c; g.lineWidth = w; g.setLineDash(dash); g.beginPath(); pts.forEach(([x, y], k) => (k ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke(); };
        if (outline) stroke(COL.ink, width + outline);
        stroke(color, width); g.setLineDash([]); g.globalAlpha = 1;
      };
      if (v.hasAlt && v.qlife) line(v.qlife, COL.altLife, 1.6, [], 0, 0.8);
      line(v.life, COL.life, 2.4, [], 2, 0.95);
      line(v.p50, COL.median, 3);
      if (v.hasAlt) line(v.q50, COL.alt, 3, [9, 6], 0);
      const dot = (x, y, fill, r) => { g.fillStyle = fill; g.strokeStyle = COL.ink; g.lineWidth = 2.2; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill(); g.stroke(); };
      for (const p of placed) {
        const fi = idxOfAge(v, p.e.age), a = p.e.path === 'alt' ? v.q50 : v.p50, val = valAt(a, fi);
        if (val !== null) dot(XA(p.e.age), Y(val), p.e.path === 'alt' ? COL.alt : COL.played, 4);
      }
      const last = n - 1;
      if (at(v.p50, last) !== null) dot(X(last), Y(v.p50[last]), COL.median, 5);
      if (v.hasAlt && at(v.q50, last) !== null) dot(X(last), Y(v.q50[last]), COL.alt, 5);
      // hover readout
      const h = C.hover;
      if (h === null || h > last) { R.tip.hidden = true; return; }
      g.strokeStyle = 'rgba(29,20,70,.6)'; g.lineWidth = 1.5; g.setLineDash([]);
      g.beginPath(); g.moveTo(X(h), T); g.lineTo(X(h), H - B); g.stroke();
      for (const [a, c] of [[v.q50, COL.alt], [v.life, COL.life], [v.p50, COL.median]]) if (at(a, h) !== null) dot(X(h), Y(a[h]), c, 5);
      const kids = [];
      const add = (tag, text, color, cls) => {
        const el = document.createElement(tag);
        if (color) { const i = document.createElement('i'); i.style.background = color; el.append(i); }
        el.append(text); if (cls) el.className = cls; kids.push(el);
      };
      add('strong', `At age ${Math.round(v.ages[h])}`);
      const med = at(v.p50, h), alt = at(v.q50, h), N = names();
      if (med !== null) add('span', `${N.played} (median) · ${chf(med)}`, COL.median);
      if (band && at(v.p5, h) !== null && at(v.p95, h) !== null) add('span', `Range p5–p95 · ${kfmt(v.p5[h])} – ${kfmt(v.p95[h])}`, 'rgba(47,123,255,.5)', 'd');
      if (at(v.life, h) !== null) add('span', `${N.life} · ${chf(v.life[h])}`, COL.life);
      if (alt !== null) {
        add('span', `${N.alt} (median) · ${chf(alt)}`, COL.alt);
        if (med !== null) add('span', `Difference · ${chfSigned(alt - med)}`, null, 'd');
      }
      const yr = Math.round(v.ages[h]);
      const evs = v.markers.filter(m => ageInt(m.age) === yr).map(m => `${m.path === 'alt' ? '→ ' : ''}${m.emoji ? m.emoji + ' ' : ''}${m.label}`);
      if (evs.length) add('em', [...new Set(evs)].join(' · '));
      R.tip.replaceChildren(...kids); R.tip.hidden = false;
      const x = X(h), tw = R.tip.offsetWidth, th = R.tip.offsetHeight;
      R.tip.style.left = Math.max(0, x + tw + 16 > W ? x - tw - 12 : x + 12) + 'px';
      const tops = [at(v.p95, h), at(v.life, h), at(v.q50, h), med].filter(z => z !== null).map(Y);
      R.tip.style.top = clamp(Math.min(...tops, H - B) - th - 8, 0, Math.max(0, H - B - th)) + 'px';
    }
    function setHover(i, announce) {
      C.hover = i; draw();
      if (announce) R.readout.textContent = R.tip.hidden ? '' : (R.tip.innerText || R.tip.textContent || '').replace(/\n+/g, ' · ');
    }
    function pointerIdx(ev) {
      const p = C.plot; if (!p) return null;
      const x = ev.clientX - R.cv.getBoundingClientRect().left;
      return clamp(Math.round((x - p.L) / (p.W - p.L - p.Rr) * (p.n - 1)), 0, p.n - 1);
    }
    R.cv.addEventListener('pointermove', ev => { if (ev.pointerType === 'touch') return; const i = pointerIdx(ev); if (i !== C.hover) setHover(i); });
    R.cv.addEventListener('pointerdown', ev => { const i = pointerIdx(ev); if (i !== null) setHover(i); });
    R.cv.addEventListener('pointerleave', () => { if (C.hover !== null) setHover(null); });
    R.cv.addEventListener('blur', () => { if (C.hover !== null) setHover(null); });
    R.cv.addEventListener('keydown', ev => {
      if (!C.plot) return;
      const n = C.plot.n, cur = C.hover === null ? -1 : C.hover, jump = ev.shiftKey ? 5 : 1;
      if (ev.key === 'Escape') { setHover(null); return; }
      const next = { ArrowLeft: cur < 0 ? 0 : cur - jump, ArrowRight: cur + jump, Home: 0, End: n - 1 }[ev.key];
      if (next === undefined) return;
      ev.preventDefault();
      setHover(clamp(next, 0, n - 1), true);
    });
    R.band.addEventListener('change', () => { C.band = R.band.checked; render(C.D); });
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => draw()).observe(R.wrap);

    function render(D) {
      if (!D) return;
      const first = C.D === null;
      C.D = D;
      if (D.title) R.title.textContent = String(D.title);
      if (D.subtitle) R.sub.textContent = String(D.subtitle);
      if (first && typeof D.show_band === 'boolean') C.band = D.show_band;
      R.band.checked = C.band;
      const ht = num(D.height, 0);
      if (ht > 0) R.cv.style.height = Math.max(200, Math.round(ht)) + 'px';
      C.v = view();
      if (C.hover !== null && (!C.v || C.hover >= C.v.n)) C.hover = null;
      if (C.v && C.v.n >= 2) { renderLegend(C.v); renderSummary(C.v); } else { R.legend.innerHTML = ''; R.sum.innerHTML = ''; }
      draw();
      setHeight();
    }
    return { render, draw, _C: C };
  })();

  /* ================================================================ data in */
  const VIEWS = { timeline: TL, suggestions: SG, chart: CH };
  let lastArgs = null;
  function show(view) {
    document.querySelectorAll('.view').forEach(s => { s.hidden = STANDALONE ? false : s.dataset.view !== view; });
  }
  function setData(view, data, height) {
    if (!VIEWS[view] || !data || typeof data !== 'object') return;
    const sig = JSON.stringify([view, data]);
    lastArgs = { view, data, height };
    if (sig === S.sig) return;
    S.sig = sig; S.view = view;
    S.minH = num(height, 0) > 0 ? Math.round(num(height)) : 0;
    show(view);
    if (S.busy) setBusy(false);
    VIEWS[view].render(data);
    setHeight();
  }
  function rerender() { if (lastArgs && VIEWS[lastArgs.view]) VIEWS[lastArgs.view].render(lastArgs.data); }

  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => setHeight()).observe(BODY);

  /* ================================================================ demo (outside Streamlit) */
  const DEMO = (() => {
    const start = 22, end = 85;
    const base = [
      { id: 'g1', kind: 'decision', key: 'bachelor', emoji: '🎓', title: 'Bachelor', cat: 'Education', age: 22, impact: 'up' },
      { id: 'g2', kind: 'decision', key: 'grad_job', emoji: '💼', title: 'Job after your degree', cat: 'Career', age: 25, impact: 'up' },
      { id: 'g3', kind: 'decision', key: 'wedding', emoji: '💍', title: 'Get married', cat: 'Family', age: 29, impact: 'down' },
      { id: 'g4', kind: 'decision', key: 'buy_house', emoji: '🏡', title: 'Buy a home', cat: 'Housing', age: 31, impact: 'down' },
      { id: 'g5', kind: 'decision', key: 'child', emoji: '👶', title: 'Have a child', cat: 'Family', age: 32, impact: 'down' },
      { id: 'g6', kind: 'decision', key: 'switch', emoji: '🚀', title: 'Job change', cat: 'Career', age: 36, impact: 'up' },
      { id: 'g7', kind: 'decision', key: 'gap_year', emoji: '🎒', title: 'Gap year', cat: 'Time off', age: 44, impact: 'flat' },
      { id: 'g8', kind: 'decision', key: 'retire', emoji: '🪑', title: 'Retire', cat: 'Career', age: 65, impact: 'flat' },
      { id: 'e1', kind: 'event', key: '', emoji: '🎓', title: 'Degree finished', age: 25, follows: 'g1', movable: false },
      { id: 'e2', kind: 'event', key: '', emoji: '🏠', title: 'Child moves out', age: 50, follows: 'g5', movable: false },
      { id: 'e3', kind: 'event', key: '', emoji: '🎒', title: 'Gap year ends', age: 45, follows: 'g7', movable: false },
    ];
    const addable = [
      { key: 'parttime', emoji: '⏳', title: 'Part-time 80 %', cat: 'Career', params: {}, min_age: 22, max_age: 64 },
      { key: 'buy_house', emoji: '🏡', title: 'Buy a home', cat: 'Housing', min_age: 25, max_age: 70,
        params: { price: { label: 'Price', min: 400000, max: 2000000, step: 50000, default: 850000, unit: 'CHF' } } },
      { key: 'costs', emoji: '🧾', title: 'Adjust monthly costs', cat: 'Housing', min_age: 22, max_age: 84,
        params: { delta: { label: 'Change per month', min: -2000, max: 2000, step: 100, default: -300, unit: 'CHF' } } },
      { key: 'child', emoji: '👶', title: 'Have a child', cat: 'Family', min_age: 22, max_age: 50,
        params: { cost: { label: 'Cost per month', min: 300, max: 3000, step: 100, default: 1100, unit: 'CHF' } } },
      { key: 'retire', emoji: '🪑', title: 'Retire', cat: 'Career', params: {}, min_age: 60, max_age: 70 },
    ];
    const SUGG = [
      { id: 's1', emoji: '🏡', title: 'Buy the home 4 years later', text: 'More savings first, a smaller mortgage and less interest.', impact: 'up', delta: 96000, edit: { moves: { g4: 35 } } },
      { id: 's2', emoji: '⏳', title: 'Work part-time from 40', text: 'More free time – but 20 % less salary and a smaller pension.', impact: 'down', delta: -184000, edit: { added: [{ key: 'parttime', age: 40, params: {} }] } },
      { id: 's3', emoji: '🧾', title: 'Spend CHF 300 less a month', text: 'Small change, invested every month for decades.', impact: 'up', delta: 211000, edit: { added: [{ key: 'costs', age: 30, params: { delta: -300 } }] } },
      { id: 's4', emoji: '🪑', title: 'Retire at 60', text: 'Five more years of freedom, five years less pension fund.', impact: 'down', delta: -152000, edit: { moves: { g8: 60 } } },
    ];
    let alt = { moves: {}, removed: [], added: [] }, aid = 0;
    const hasAlt = () => Object.keys(alt.moves).length > 0 || alt.removed.length > 0 || alt.added.length > 0;
    function items() {
      const out = base.map(t => {
        const owner = t.kind === 'event' ? t.follows : t.id, d = owner in alt.moves ? alt.moves[owner] - base.find(b => b.id === owner).age : 0;
        const removed = alt.removed.includes(owner);
        return Object.assign({ movable: true, follows: null }, t, { alt_age: d ? t.age + d : null, removed });
      });
      for (const a of alt.added) {
        const o = addable.find(x => x.key === a.key) || {};
        out.push({ id: a.id, kind: 'added', key: a.key, emoji: o.emoji, title: o.title, cat: o.cat, age: a.age, alt_age: a.age, removed: false, movable: true, impact: null });
      }
      return out;
    }
    function paths() {
      const ages = [], p50 = [], p5 = [], p95 = [], life = [], q50 = [], q5 = [], q95 = [];
      const shift = Object.entries(alt.moves).reduce((s, [, a]) => s + a, 0) % 7 - 3 + alt.added.length * 2 - alt.removed.length;
      for (let a = start; a <= end; a++) {
        const t = a - start, grow = t < 43 ? 9000 * t + 120 * t * t : 9000 * 43 + 120 * 43 * 43 - 14000 * (t - 43);
        const s = 5200 * Math.sqrt(t) * (1 + t / 30), m = grow - (a >= 31 ? 60000 : 0);
        ages.push(a); p50.push(m); p5.push(m - 1.5 * s); p95.push(m + 2.1 * s); life.push(m + 0.8 * s * Math.sin(t / 5));
        const k = m * (1 + shift * 0.025);
        q50.push(k); q5.push(k - 1.5 * s); q95.push(k + 2.1 * s);
      }
      const h = hasAlt();
      return { ages, played: { p5, p50, p95, life }, alt: h ? { p5: q5, p50: q50, p95: q95 } : null, label: h ? 'Your edited path' : null,
               metrics: { played_end: p50[p50.length - 1], alt_end: h ? q50[q50.length - 1] : null, delta_end: h ? q50[q50.length - 1] - p50[p50.length - 1] : null } };
    }
    function renderAll() {
      const it = items();
      TL.render({ start_age: start, end_age: end, items: it, addable, has_alt: hasAlt() });
      SG.render({ items: SUGG, end_age: end });
      CH.render(Object.assign(paths(), { items: it }));
      setHeight();
    }
    function apply(a) {
      const last = $('.demo-last'); if (last) last.textContent = 'Last action: ' + JSON.stringify(a);
      if (a.action === 'move') {
        const t = base.find(b => b.id === a.id);
        if (t) { if (t.age === a.age) delete alt.moves[a.id]; else alt.moves[a.id] = a.age; }
        const ad = alt.added.find(x => x.id === a.id); if (ad) ad.age = a.age;
      } else if (a.action === 'remove') {
        if (alt.added.some(x => x.id === a.id)) alt.added = alt.added.filter(x => x.id !== a.id);
        else if (!alt.removed.includes(a.id)) alt.removed.push(a.id);
      } else if (a.action === 'restore') alt.removed = alt.removed.filter(x => x !== a.id);
      else if (a.action === 'add') alt.added.push({ id: 'a' + (++aid), key: a.key, age: a.age, params: a.params || {} });
      else if (a.action === 'reset') alt = { moves: {}, removed: [], added: [] };
      else if (a.action === 'apply') {
        const s = SUGG.find(x => x.id === a.id), e = s && s.edit;
        if (e) {
          Object.assign(alt.moves, e.moves || {});
          for (const r of e.removed || []) if (!alt.removed.includes(r)) alt.removed.push(r);
          for (const ad of e.added || []) alt.added.push(Object.assign({ id: 'a' + (++aid) }, ad));
        }
      }
      setTimeout(renderAll, 250);            // pretend the page reran
    }
    function start_() {
      BODY.classList.add('demo');
      const note = $('.demo-note'); if (note) note.hidden = false;
      show(null);
      renderAll();
    }
    return { apply, start: start_, get alt() { return alt; } };
  })();

  /* ================================================================ boot */
  window.__lifereview = { S, TL, SG, CH, DEMO, setData, send, assignLanes, ticks5, fmt: { chf, chfSigned, kfmt, esc } };
  if (!STANDALONE) {
    window.addEventListener('message', ev => {
      const d = ev.data; if (!d || d.type !== 'streamlit:render') return;
      const a = d.args || {};
      setData(String(a.view || ''), a.data, a.height);
    });
    post('streamlit:componentReady', { apiVersion: 1 });
  } else {
    DEMO.start();
  }
})();
