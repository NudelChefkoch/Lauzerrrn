// Twin chat (after Juli's coach.js): message thread with tool-trace chips, quick prompts, composer.
// The panel is ONE element that ui.js moves between the play side panel and the dashboard.
// Python answers every message (LLM router or offline rules); all numbers come from our SDE.
// Every piece of text from the payload is escaped.
import { esc, arr, safeColor } from './fmt.js';

const MAX = 400;

export function createChat({ onSend, onCompare } = {}) {
  const el = document.createElement('section');
  el.className = 'chat';
  el.setAttribute('aria-label', 'Twin chat');
  el.innerHTML = `
    <div class="chat-head">
      <span class="chat-av" aria-hidden="true">T</span>
      <div class="chat-ttl"><b class="chat-name">Twin chat</b><span class="chat-mode off">Offline calculator</span></div>
      <button type="button" class="chat-fold" aria-expanded="true" title="Show/hide chat">▾</button>
    </div>
    <div class="chat-body">
      <ol class="chat-thread" role="log" aria-live="polite" aria-label="Conversation with your twin"></ol>
      <div class="chat-prompts" aria-label="Suggested questions"></div>
      <form class="chat-form" autocomplete="off">
        <label class="vh" for="chat-msg">Your message to the twin</label>
        <textarea id="chat-msg" rows="2" maxlength="${MAX}" placeholder="Ask your twin … (Enter sends)"></textarea>
        <div class="chat-row"><span class="chat-count">0/${MAX}</span>
          <button type="submit" class="btn btn-sm btn-pink chat-send">SEND</button></div>
      </form>
    </div>`;
  const q = s => el.querySelector(s);
  const R = {
    av: q('.chat-av'), name: q('.chat-name'), mode: q('.chat-mode'), fold: q('.chat-fold'),
    thread: q('.chat-thread'), prompts: q('.chat-prompts'), form: q('.chat-form'), ta: q('textarea'),
    count: q('.chat-count'), send: q('.chat-send'),
  };
  let st = { locked: false, pending: null, sig: '', msgs: [] };

  function submit(text) {
    const t = String(text || '').trim().slice(0, MAX);
    if (!t || st.locked) return;
    if (onSend && onSend(t) !== false) { R.ta.value = ''; updateCount(); }
  }
  function updateCount() {
    const n = R.ta.value.length;
    R.count.textContent = `${n}/${MAX}`; R.count.classList.toggle('full', n >= MAX);
  }
  R.form.addEventListener('submit', ev => { ev.preventDefault(); submit(R.ta.value); });
  R.ta.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); submit(R.ta.value); }
    ev.stopPropagation();
  });
  R.ta.addEventListener('input', updateCount);
  R.fold.addEventListener('click', () => setFolded(!el.classList.contains('folded')));
  el.addEventListener('click', ev => {
    const p = ev.target.closest('[data-prompt]');
    if (p && el.contains(p) && !p.disabled) { submit(st.prompts[+p.dataset.prompt]); return; }
    const c = ev.target.closest('[data-compare]');
    if (c && el.contains(c) && !c.disabled) {
      const m = st.msgs[+c.dataset.compare];
      if (m && m.suggestion && onCompare) onCompare(m.suggestion);
    }
  });

  function setFolded(f) {
    el.classList.toggle('folded', f);
    R.fold.setAttribute('aria-expanded', String(!f));
    R.fold.textContent = f ? '▸' : '▾';
  }

  function bubble(m, i, initial, color) {
    const text = esc(m.text || '').replace(/\n/g, '<br>');
    if (m.role === 'user') {
      return `<li class="cmsg user"><div class="cb"><span class="cstage">You</span><p>${text}</p></div></li>`;
    }
    const tools = arr(m.tools).map(t => {
      const args = t && t.args !== undefined && t.args !== null ? (typeof t.args === 'string' ? t.args : JSON.stringify(t.args)) : '';
      return `<span class="ctool" title="Calculated with the simulation">🔧 ${esc(t && t.name)}(${esc(args)})${t && t.result !== undefined && t.result !== null && t.result !== '' ? ` → ${esc(t.result)}` : ''}</span>`;
    }).join('');
    const s = m.suggestion && typeof m.suggestion === 'object' && m.suggestion.key ? m.suggestion : null;
    const sugg = s ? `<div class="csugg"><span>💡 Suggestion: <b>${esc(s.title || s.key)}</b></span>
        <button type="button" class="btn btn-sm btn-blue" data-compare="${i}" data-chatlock>Compare in the dashboard</button></div>` : '';
    return `<li class="cmsg twin"><span class="cav" style="background:${color}" aria-hidden="true">${esc(initial)}</span>
      <div class="cb">${m.stage && !String(m.text || '').includes(String(m.stage)) ? `<span class="cstage">${esc(m.stage)}</span>` : ''}<p>${text}</p>
      ${tools ? `<div class="ctools">${tools}</div>` : ''}${sugg}</div></li>`;
  }

  /**
   * chat: payload chat block (may be null) · opts: {name, color, locked, pending (string|null)}
   */
  function render(chat, opts = {}) {
    const c = chat && typeof chat === 'object' ? chat : {};
    const name = String(opts.name || '').trim();
    const initial = (Array.from(name)[0] || 'T').toUpperCase();
    const color = safeColor(opts.color);
    R.av.textContent = initial; R.av.style.background = color;
    R.name.textContent = name ? `Chat with ${name}'s twin` : 'Twin chat';
    const llm = c.mode === 'llm';
    R.mode.textContent = llm ? `Qwen local${c.model ? ' · ' + c.model : ''}` : 'Offline calculator';
    R.mode.classList.toggle('off', !llm);
    R.mode.title = llm ? 'A local language model picks the matching calculation – every number comes from the simulation.'
      : 'Rule-based choice of the calculation – every number comes from the simulation.';

    st.msgs = arr(c.messages).filter(m => m && typeof m === 'object');
    st.prompts = arr(c.prompts).map(String).slice(0, 6);
    st.locked = !!opts.locked;
    const pending = opts.pending ? String(opts.pending) : null;
    const sig = JSON.stringify([st.msgs, pending, initial, color, st.locked]);
    if (sig !== st.sig) {
      const atEnd = R.thread.scrollHeight - R.thread.scrollTop - R.thread.clientHeight < 60;
      const grew = st.msgs.length !== st.lastLen || pending !== st.pending;
      st.sig = sig; st.lastLen = st.msgs.length; st.pending = pending;
      let html = st.msgs.map((m, i) => bubble(m, i, initial, color)).join('');
      if (!st.msgs.length && !pending) html = `<li class="cempty">Ask your twin what a decision means for your net worth. It checks every answer with the simulation.</li>`;
      if (pending) {
        html += bubble({ role: 'user', text: pending }, -1, initial, color);
        html += `<li class="cmsg twin typing"><span class="cav" style="background:${color}" aria-hidden="true">${esc(initial)}</span>
          <div class="cb"><span class="dots" aria-label="Your twin is calculating"><i></i><i></i><i></i></span></div></li>`;
      }
      R.thread.innerHTML = html;
      if (grew || atEnd) R.thread.scrollTop = R.thread.scrollHeight;
    }
    R.prompts.innerHTML = st.prompts.map((p, i) => `<button type="button" class="cprompt" data-prompt="${i}" data-chatlock>${esc(p)}</button>`).join('');
    el.querySelectorAll('[data-chatlock]').forEach(b => { b.disabled = st.locked; });
    R.send.disabled = st.locked;
    el.classList.toggle('busy', !!pending);
  }

  return {
    el, render, setFolded,
    focus() { setFolded(false); try { R.ta.focus({ preventScroll: true }); } catch (e) { R.ta.focus(); } },
    scrollEnd() { R.thread.scrollTop = R.thread.scrollHeight; },
    count(role = 'twin') { return st.msgs.filter(m => m.role === role).length; },
  };
}

export const chatTwinCount = chat => arr(chat && chat.messages).filter(m => m && m.role === 'twin').length;
