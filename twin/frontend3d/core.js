// Shared helpers: palettes, materials, sprites, tweens.
import * as THREE from 'three';
export { THREE };

/* =================================================================== palettes & options */
const SKINS = { hell: '#f6d3b8', rosig: '#f2c2a2', oliv: '#d9a77c', mittel: '#c68a5c', braun: '#9a6340', dunkel: '#6b4129' };
const HAIRC = { schwarz: '#2b2523', dunkelbraun: '#5a3826', braun: '#8a5a36', blond: '#e5bd62', rot: '#c4502b',
                pink: '#ef7fb0', blau: '#4c7be0', grau: '#c9c6c0' };
const COLORS = { blau: '#2a78d6', orange: '#eb6834', tuerkis: '#1baf7a', gelb: '#eda100', pink: '#e87ba4',
                 gruen: '#2f9e44', violett: '#6250d6', rot: '#e34948', weiss: '#f4f2ee', navy: '#24365c' };
const OPTIONS = {
  gender: ['frau', 'mann', 'divers'],
  skin: Object.keys(SKINS),
  hair: ['kurz', 'lang', 'dutt', 'locken', 'pferdeschwanz', 'afro', 'iro', 'glatze'],
  hairColor: Object.keys(HAIRC),
  hat: ['keiner', 'cap', 'beanie', 'strohhut', 'partyhut', 'kopfhoerer'],
  outfit: ['hoodie', 'tshirt', 'hemd', 'kleid', 'sport'],
  color: Object.keys(COLORS),
  car: Object.keys(COLORS),
};
const CAT_LABEL = { gender: 'Gender', skin: 'Skin tone', hair: 'Hairstyle', hairColor: 'Hair colour', hat: 'Hat',
                    outfit: 'Outfit', color: 'Colour', car: 'Car' };
// display names for the (internal, German) option keys
const NICE = { frau: 'woman', mann: 'man', divers: 'non-binary',
               hell: 'light', rosig: 'rosy', oliv: 'olive', mittel: 'medium', braun: 'brown', dunkel: 'dark',
               kurz: 'short', lang: 'long', dutt: 'bun', locken: 'curls', pferdeschwanz: 'ponytail', afro: 'afro',
               iro: 'mohawk', glatze: 'bald',
               schwarz: 'black', dunkelbraun: 'dark brown', blond: 'blond', rot: 'red', pink: 'pink', blau: 'blue', grau: 'grey',
               keiner: 'no hat', cap: 'cap', beanie: 'beanie', strohhut: 'straw hat', partyhut: 'party hat', kopfhoerer: 'headphones',
               hoodie: 'hoodie', tshirt: 'T-shirt', hemd: 'shirt', kleid: 'dress', sport: 'sportswear',
               orange: 'orange', tuerkis: 'turquoise', gelb: 'yellow', gruen: 'green', violett: 'violet', weiss: 'white', navy: 'navy' };
const DEFAULT_CFG = { name: 'Alex', gender: 'frau', skin: 'rosig', hair: 'lang', hairColor: 'braun', hat: 'keiner',
                      outfit: 'hoodie', color: 'violett', car: 'tuerkis' };

/* =================================================================== helpers */
const mats = new Map();
function M(c, r = .6, extra = {}) {
  const k = c + r + JSON.stringify(extra);
  if (!mats.has(k)) mats.set(k, new THREE.MeshStandardMaterial({ color: c, roughness: r, metalness: 0, ...extra }));
  return mats.get(k);
}
function add(parent, geo, mat, x = 0, y = 0, z = 0, sx = 1, sy = 1, sz = 1) {
  const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.scale.set(sx, sy, sz);
  m.castShadow = true; m.receiveShadow = true; parent.add(m); return m;
}
const shade = (hex, f) => { const c = new THREE.Color(hex); c.offsetHSL(0, 0, f); return '#' + c.getHexString(); };
const lerp = (a, b, t) => a + (b - a) * t;
const ease = x => x < .5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
const easeOutBack = x => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };

function sprite(text, size = 1, bg = null) {
  const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
  if (bg) { g.fillStyle = bg; g.beginPath(); g.arc(128, 128, 110, 0, Math.PI * 2); g.fill(); }
  g.font = (bg ? '700 110px' : '180px') + ' system-ui, "Apple Color Emoji", "Segoe UI Emoji", sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = bg ? '#24365c' : '#000';
  g.fillText(text, 128, bg ? 136 : 140);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  s.scale.set(size, size, 1); return s;
}

/* =================================================================== tweens */
const tasks = [];
const tween = (dur, fn) => new Promise(res => tasks.push({ t: 0, dur, fn, res }));
const wait = s => tween(s, () => {});
function runTasks(dt) {
  for (let i = tasks.length - 1; i >= 0; i--) {
    const k = tasks[i]; k.t += dt; const x = Math.min(1, k.t / k.dur); k.fn(x);
    if (x >= 1) { tasks.splice(i, 1); k.res(); }
  }
}


export { SKINS, HAIRC, COLORS, OPTIONS, CAT_LABEL, NICE, DEFAULT_CFG, M, add, shade, lerp, ease, easeOutBack, sprite,
         tween, wait, runTasks };
