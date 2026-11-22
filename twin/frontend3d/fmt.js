// Small shared formatters for the client modules (chat.js, dashboard.js). Plain functions, no DOM.
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const num = (v, d = 0) => (v === null || v === undefined || v === '' || !Number.isFinite(+v)) ? d : +v;
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const arr = v => Array.isArray(v) ? v : [];
export const grp = n => String(Math.round(Math.abs(num(n)))).replace(/\B(?=(\d{3})+(?!\d))/g, "'");
export const chf = v => (num(v) < -0.5 ? 'CHF −' : 'CHF ') + grp(v);
export const chfSigned = v => (num(v) < -0.5 ? '−' : num(v) > 0.5 ? '+' : '±') + 'CHF ' + grp(v);
export function kfmt(v) {
  const n = num(v), a = Math.abs(n), s = n < -0.5 ? '−' : '';
  if (a >= 1e6) return s + (a / 1e6).toFixed(a >= 1e7 ? 0 : 1) + ' Mio.';
  if (a >= 1e4) return s + Math.round(a / 1e3) + 'k';
  return s + grp(a);
}
export const safeColor = (c, d = '#7b4dff') => (typeof c === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : d;
/** finite numbers or null, padded/truncated to length n */
export const series = (a, n) => Array.from({ length: n }, (_, i) => {
  const v = arr(a)[i]; return (v === null || v === undefined || !Number.isFinite(+v)) ? null : +v;
});
