// 3D engine: one renderer, two views (creator podium + world island), life-event animations.
// Public API is exported at the bottom; see CONTRACT.md.
import { THREE, DEFAULT_CFG, M, add, lerp, ease, easeOutBack, sprite, tween, wait, runTasks } from './core.js';
import { buildCharacter, addProp, removeProp, animateCharacter, buildCar, seat, buildPodium } from './character.js';

/* =================================================================== renderer + views */
const E = { container: null, renderer: null, clock: null, W: 800, H: 600, view: null, busy: 0,
            onToast: null, onBusy: null };
let scene = null, camera = null;          // the ACTIVE view's scene/camera (world code builds into these)
const CREATOR = { scene: null, camera: null }, WORLD = { scene: null, camera: null, ready: false };

function initEngine(container) {
  if (E.renderer) return;
  E.container = container; E.W = container.clientWidth || window.innerWidth; E.H = container.clientHeight || window.innerHeight;
  const r = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  r.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); r.setSize(E.W, E.H);
  r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
  r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.05;
  r.domElement.style.display = 'block'; container.appendChild(r.domElement);
  E.renderer = r; E.clock = new THREE.Clock();
  new ResizeObserver(() => resize()).observe(container);
  r.domElement.addEventListener('pointerdown', e => { if (E.view === 'creator') C.drag = e.clientX; });
  window.addEventListener('pointerup', () => { C.drag = null; });
  window.addEventListener('pointermove', e => { if (C.drag !== null) { C.rot += (e.clientX - C.drag) * .012; C.drag = e.clientX; } });
  requestAnimationFrame(loop);
}
function resize() {
  E.W = E.container.clientWidth || E.W; E.H = E.container.clientHeight || E.H; E.renderer.setSize(E.W, E.H);
  for (const v of [CREATOR, WORLD]) if (v.camera) { v.camera.aspect = E.W / E.H; v.camera.updateProjectionMatrix(); }
}
function newView() {
  scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(38, E.W / E.H, .1, 500);
}
function activate(name) {
  E.view = name; const v = name === 'creator' ? CREATOR : WORLD; scene = v.scene; camera = v.camera;
}
function lights(shadowSize = 30) {
  scene.add(new THREE.HemisphereLight('#e6f4ff', '#8bbf6a', 1.1));
  const sun = new THREE.DirectionalLight('#fff1d6', 2.2); sun.position.set(12, 22, 10); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); const sc = sun.shadow.camera; sc.left = sc.bottom = -shadowSize; sc.right = sc.top = shadowSize; sc.far = 80;
  sun.shadow.bias = -.0005; scene.add(sun); return sun;
}
function toast(text, ms = 2600) { if (E.onToast) E.onToast(text, ms); }
function setBusy(d) { const was = E.busy > 0; E.busy = Math.max(0, E.busy + d); const now = E.busy > 0; if (was !== now && E.onBusy) E.onBusy(now); }

/* =================================================================== CREATOR (podium) */
const C = { cfg: { ...DEFAULT_CFG }, cat: 'gender', ch: null, car: null, rot: 0, drag: null, podium: null };
function buildCreatorScene() {
  newView(); CREATOR.scene = scene; CREATOR.camera = camera; lights(6);
  C.podium = buildPodium(); scene.add(C.podium);
  const floor = add(scene, new THREE.CircleGeometry(12, 48), new THREE.ShadowMaterial({ opacity: .2 }), 0, -.6, 0); floor.rotation.x = -Math.PI / 2;
  camera.position.set(0, 1.7, 6.6); camera.lookAt(0, 1.15, 0);
}
function showCreator(cfg, cat) {
  if (!CREATOR.scene) buildCreatorScene();
  activate('creator'); setCreator(cfg || C.cfg, cat || C.cat, false);
}
function setCreator(cfg, cat, pop = true) {
  if (!CREATOR.scene) buildCreatorScene();
  const prevScene = scene; scene = CREATOR.scene;
  C.cfg = { ...DEFAULT_CFG, ...cfg }; if (cat) C.cat = cat;
  if (C.ch) C.ch.parent.remove(C.ch); if (C.car) scene.remove(C.car); C.car = null;
  C.ch = buildCharacter(C.cfg);
  if (C.cat === 'car') { C.car = buildCar(C.cfg.car); scene.add(C.car); seat(C.ch, C.car); C.car.scale.setScalar(1.15); }
  else scene.add(C.ch);
  const target = C.car || C.ch;
  if (pop) { const s = target.scale.x; tween(.35, x => target.scale.setScalar(lerp(s * .88, s, easeOutBack(x)))); }
  scene = prevScene || scene;
}
function updateCreator(dt) {
  if (C.drag === null) C.rot += dt * .35;
  const t = C.car || C.ch; if (t) t.rotation.y = C.car ? C.rot - .6 : Math.sin(C.rot) * .5;
  if (C.ch) animateCharacter(C.ch, dt);
  const cam = C.car ? [0, 2.4, 7.2] : [0, 1.7, 6.6]; camera.position.lerp(new THREE.Vector3(...cam), .08); camera.lookAt(0, C.car ? .8 : 1.15, 0);
}

/* =================================================================== WORLD */
function resetWorldState() {
  Object.assign(S, { K: 15, turn: 0, startAge: 20, seen: new Set(), queue: Promise.resolve(), life: {}, kids: 0, curve: null,
    samples: [], car: null, ch: null, focus: null, focusFace: null, stationMeshes: [], badgeSprites: [], cfg: null, u: 0,
    finaleDone: false, look: null, gen: (S.gen || 0) + 1 });
  const wasBusy = E.busy > 0; E.busy = 0; if (wasBusy && E.onBusy) E.onBusy(false);
  if (E.container) E.container.style.background = '';
}
const S = { K: 15, turn: 0, startAge: 20, seen: new Set(), queue: Promise.resolve(), life: {}, kids: 0,
            curve: null, samples: [], car: null, ch: null, focus: null, stationMeshes: [], badgeSprites: [], cfg: null, u: 0, busy: false };
const ROAD_PTS = [[-20, 13], [-8, 14.5], [5, 12.5], [16, 13.5], [21.5, 7.5], [16, 1.2], [4, 0], [-8, 1], [-17, -.8],
                  [-21.5, -6.5], [-16, -12.5], [-4, -13.6], [8, -11.8], [20, -13.2]];
function initWorld(args) {
  resetWorldState(); newView(); const sun = lights(32); WORLD.scene = scene; WORLD.camera = camera;
  scene.fog = new THREE.Fog('#d9efff', 45, 110);
  S.K = args.K || 15; S.startAge = args.start_age || 20; S.cfg = { ...DEFAULT_CFG, ...(args.avatar || {}) };
  // water + island
  const water = add(scene, new THREE.CircleGeometry(160, 64), M('#5cc2f0', .25), 0, -.8, 0); water.rotation.x = -Math.PI / 2; water.castShadow = false;
  add(scene, new THREE.CylinderGeometry(29, 30.5, 1, 72), M('#f3dfa6', .95), 0, -.75, 0);
  add(scene, new THREE.CylinderGeometry(27.5, 28.2, 1.2, 72), M('#8fd07a', .95), 0, -.6, 0);
  // road
  S.curve = new THREE.CatmullRomCurve3(ROAD_PTS.map(([x, z]) => new THREE.Vector3(x, 0, z)), false, 'catmullrom', .5);
  const N = 700; S.samples = S.curve.getSpacedPoints(N);
  const strip = (w, y, mat) => {
    const pos = []; const idx = [];
    for (let i = 0; i <= N; i++) {
      const p = S.samples[i], t = S.curve.getTangentAt(i / N), n = new THREE.Vector3(-t.z, 0, t.x).normalize();
      pos.push(p.x + n.x * w, y, p.z + n.z * w, p.x - n.x * w, y, p.z - n.z * w);
      if (i < N) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    }
    const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.setIndex(idx); geo.computeVertexNormals();
    const m = new THREE.Mesh(geo, mat); m.receiveShadow = true; scene.add(m); return m;
  };
  strip(1.75, .02, M('#6e6a62', .9, { side: THREE.DoubleSide })); strip(1.45, .04, M('#8d8981', .85, { side: THREE.DoubleSide }));
  const dashes = new THREE.InstancedMesh(new THREE.BoxGeometry(.6, .02, .1), M('#fff6d6', .6), 140); const dm = new THREE.Object3D();
  for (let i = 0; i < 140; i++) { const u = (i + .5) / 140, p = S.curve.getPointAt(u), t = S.curve.getTangentAt(u);
    dm.position.set(p.x, .06, p.z); dm.rotation.set(0, Math.atan2(-t.z, t.x), 0); dm.updateMatrix(); dashes.setMatrixAt(i, dm.matrix); }
  scene.add(dashes);
  // scenery: trees + little houses away from the road
  const rnd = mulberry(7); const trunk = [], crown = [], pine = [];
  for (let i = 0; i < 260 && (crown.length + pine.length) < 85; i++) {
    const a = rnd() * Math.PI * 2, rr = Math.sqrt(rnd()) * 25.5, x = Math.cos(a) * rr, z = Math.sin(a) * rr;
    if (minRoadDist(x, z) < 3.2) continue;
    (rnd() < .5 ? crown : pine).push([x, z, .6 + rnd() * .45]); trunk.push([x, z]);
  }
  const inst = (geo, mat, list, f) => { const im = new THREE.InstancedMesh(geo, mat, list.length); im.castShadow = true; im.receiveShadow = true;
    list.forEach((it, i) => { f(dm, it); dm.updateMatrix(); im.setMatrixAt(i, dm.matrix); }); scene.add(im); };
  inst(new THREE.CylinderGeometry(.12, .16, .8, 8), M('#8a5a36'), trunk, (o, [x, z]) => { o.position.set(x, .4, z); o.rotation.set(0, 0, 0); o.scale.setScalar(1); });
  inst(new THREE.SphereGeometry(.75, 14, 12), M('#4caf50', .8), crown, (o, [x, z, s]) => { o.position.set(x, 1.3 * s, z); o.scale.setScalar(s); });
  inst(new THREE.ConeGeometry(.7, 1.8, 10), M('#2e7d4f', .8), pine, (o, [x, z, s]) => { o.position.set(x, 1.4 * s, z); o.scale.setScalar(s); });
  for (const [x, z, c] of [[-12, 7, '#f6c7b6'], [10, 6.5, '#bfe0f5'], [-4, -6.5, '#f8e2a8'], [13, -6.6, '#d9c8f0'], [-23, 4, '#c9f0d6']]) {
    if (minRoadDist(x, z) > 3) { const h = buildHouse(c, .55); h.position.set(x, 0, z); h.rotation.y = rnd() * 6; scene.add(h); }
  }
  // stations
  for (let k = 0; k <= S.K; k++) {
    const p = S.curve.getPointAt(k / S.K);
    const disc = add(scene, new THREE.CylinderGeometry(.95, .95, .14, 32), M('#fffdf8', .5), p.x, .07, p.z);
    const lbl = sprite(String(S.startAge + k), 1.1, '#ffffff'); lbl.position.set(p.x, 1.05, p.z); scene.add(lbl);
    S.stationMeshes.push(disc); S.badgeSprites.push(null);
  }
  // car + avatar
  S.car = buildCar(S.cfg.car); scene.add(S.car);
  S.life = args.life || {}; S.kids = S.life.kids || 0;
  S.ch = buildCharacter(S.cfg, S.life); seat(S.ch, S.car); refreshKids();
  S.turn = args.turn ?? 0;
  const moving = args.prev_turn !== undefined && args.prev_turn !== args.turn;
  placeCar(moving ? args.prev_turn / S.K : S.turn / S.K);
  if (!moving) (args.anims || []).forEach(a => S.seen.add(a.id));
  colorStations(moving ? args.prev_turn : S.turn); setBadges(args.badges || {});
  camera.position.set(S.car.position.x, 13, S.car.position.z + 15); camera.lookAt(S.car.position);
  if (moving) update(args, true);
  if (args.finale && !S.finaleDone) { S.finaleDone = true; enqueue(() => animRetirement(S.turn)); }
}
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function minRoadDist(x, z) { let m = 1e9; for (const p of S.samples) { const d = (p.x - x) ** 2 + (p.z - z) ** 2; if (d < m) m = d; } return Math.sqrt(m); }
function colorStations(cur) {
  S.stationMeshes.forEach((m, k) => { m.material = M(k < cur ? '#2a78d6' : k === cur ? '#ffd23f' : k === S.K ? '#eda100' : '#fffdf8', .5); });
}
function setBadges(b) {
  for (const [k, e] of Object.entries(b)) { const i = +k; if (S.badgeSprites[i]) continue; const p = S.curve.getPointAt(i / S.K);
    const s = sprite(e, 1.3); s.position.set(p.x, 2.2, p.z); scene.add(s); S.badgeSprites[i] = s; }
}
function placeCar(u) {
  S.u = u; const p = S.curve.getPointAt(Math.min(1, Math.max(0, u))), t = S.curve.getTangentAt(Math.min(.999, Math.max(.001, u)));
  S.car.position.set(p.x, 0, p.z); S.car.rotation.y = Math.atan2(-t.z, t.x);
}
function refreshKids() {
  (S.car.userData.kids || []).forEach(k => S.car.remove(k)); S.car.userData.kids = [];
  for (let i = 0; i < Math.min(S.kids, 2); i++) { const kid = buildCharacter({ ...S.cfg, hat: 'keiner', hair: i ? 'dutt' : 'kurz', gender: i ? 'frau' : 'mann' });
    seat(kid, S.car, -.62, .33); kid.position.z = i ? -.22 : .22; S.car.userData.kids.push(kid); }
}
function rebuildChar() {
  const parent = S.ch.parent, pos = S.ch.position.clone(), rot = S.ch.rotation.clone(), sc = S.ch.scale.clone(), mode = S.ch.userData.mode, props = Object.keys(S.ch.userData.props);
  parent.remove(S.ch); S.ch = buildCharacter(S.cfg, S.life); parent.add(S.ch); S.ch.position.copy(pos); S.ch.rotation.copy(rot); S.ch.scale.copy(sc);
  S.ch.userData.mode = mode; if (mode === 'seated') S.ch.userData.parts.legL.visible = S.ch.userData.parts.legR.visible = false;
  props.forEach(p => addProp(S.ch, p));
}
// queued tasks of a world that was reset since (restart) are skipped and must not touch the busy counter
const enqueue = fn => { const gen = S.gen; setBusy(+1);
  S.queue = S.queue.then(() => (gen === S.gen ? fn() : null)).catch(e => console.error(e)).finally(() => { if (gen === S.gen) setBusy(-1); });
  return S.queue; };

function update(args, initial = false) {
  if (!initial && args.avatar) S.cfg = { ...DEFAULT_CFG, ...args.avatar };
  const target = args.turn ?? S.turn;
  const anims = (args.anims || []).filter(a => !S.seen.has(a.id)); anims.forEach(a => S.seen.add(a.id));
  const life = args.life || {}; const badges = args.badges || {};
  if (target !== S.turn || initial) {
    const from = initial ? args.prev_turn : S.turn; S.turn = target;
    enqueue(() => drive(from, target));
  }
  for (const a of anims) enqueue(() => playAnim(a, target));
  enqueue(async () => { setBadges(badges); colorStations(target);
    const suitChanged = !!life.suit !== !!S.life.suit; S.life = { ...S.life, ...life };
    if (suitChanged) rebuildChar(); if ((life.kids || 0) !== S.kids) { S.kids = life.kids || 0; refreshKids(); } });
  if (args.finale && !S.finaleDone) { S.finaleDone = true; enqueue(() => animRetirement(target)); }
}

async function drive(from, to) {
  if (from === to) return;
  const u0 = from / S.K, u1 = to / S.K, dur = 1.6 + .5 * Math.abs(to - from);
  await tween(dur, x => { placeCar(lerp(u0, u1, ease(x))); (S.car.userData.wheels || []).forEach(w => w.rotation.y += .3); });
  colorStations(to);
}

/* ---------- world helpers for animations */
function spot(k) {
  const u = Math.min(.999, Math.max(.001, k / S.K)); const p = S.curve.getPointAt(u), t = S.curve.getTangentAt(u);
  const n = new THREE.Vector3(-t.z, 0, t.x).normalize(); let best = null;
  for (const s of [1, -1]) for (const d of [4.4, 5.4]) { const b = p.clone().addScaledVector(n, s * d);
    const score = Math.min(minRoadDist(b.x, b.z), 3.6) - (b.length() > 24 ? 10 : 0);
    if (!best || score > best.score) best = { b, s, score }; }
  const face = Math.atan2(p.x - best.b.x, p.z - best.b.z);
  return { B: best.b, face, side: n.clone().multiplyScalar(best.s), P: p };
}
const frontOf = (B, face, d) => new THREE.Vector3(B.x + Math.sin(face) * d, 0, B.z + Math.cos(face) * d);
async function popIn(obj, dur = .6) { obj.scale.setScalar(.01); await tween(dur, x => obj.scale.setScalar(Math.max(.01, easeOutBack(x)))); }
async function exitCar(side) {
  const ch = S.ch, wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  S.car.remove(ch); scene.add(ch); ch.scale.setScalar(1); ch.rotation.set(0, 0, 0);
  ch.userData.parts.legL.visible = ch.userData.parts.legR.visible = true; ch.userData.mode = 'idle';
  const out = wp.clone().addScaledVector(side, 1.6); ch.position.copy(wp).addScaledVector(side, .6);
  await walkTo(ch, out, 2.5); return ch;
}
async function walkTo(ch, to, speed = 2.4) {
  const from = ch.position.clone(); const d = to.clone().sub(from); const L = d.length(); if (L < .01) return;
  ch.rotation.y = Math.atan2(d.x, d.z); ch.userData.mode = 'walk';
  await tween(L / speed, x => ch.position.lerpVectors(from, to, x)); ch.userData.mode = 'idle';
}
async function backToCar(side) {
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  await walkTo(S.ch, wp.clone().addScaledVector(side, 1.6)); seat(S.ch, S.car);
}
async function cheer(ch, s) { ch.userData.mode = 'cheer'; await wait(s); ch.userData.mode = 'idle'; }
function faceCamera(ch) { const d = camera.position.clone().sub(ch.position); ch.rotation.y = Math.atan2(d.x, d.z); }
function burst(pos, kind = 'confetti', n = 70) {
  const cols = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#6250d6'];
  const parts = [];
  for (let i = 0; i < n; i++) {
    let m;
    if (kind === 'dust') m = add(scene, new THREE.SphereGeometry(.35, 10, 8), new THREE.MeshStandardMaterial({ color: '#e8e2d4', transparent: true, opacity: .8 }), pos.x, .3, pos.z);
    else { m = add(scene, new THREE.PlaneGeometry(.14, .22), new THREE.MeshStandardMaterial({ color: cols[i % 6], side: THREE.DoubleSide }), pos.x, 2, pos.z); }
    const a = Math.random() * Math.PI * 2, v = kind === 'dust' ? 2 + Math.random() * 2 : 2 + Math.random() * 3;
    m.userData.v = new THREE.Vector3(Math.cos(a) * v, kind === 'dust' ? .6 + Math.random() : 4 + Math.random() * 4, Math.sin(a) * v);
    parts.push(m);
  }
  tween(2.2, x => { const dt = 1 / 60; parts.forEach(m => { m.position.addScaledVector(m.userData.v, dt); m.userData.v.y -= (kind === 'dust' ? 1.5 : 9) * dt;
    if (kind === 'dust') { m.scale.setScalar(1 + x * 2.5); m.material.opacity = .8 * (1 - x); } else { m.rotation.x += .2; m.rotation.y += .15; if (m.position.y < .05) m.userData.v.set(0, 0, 0); } });
    if (x >= 1) parts.forEach(m => scene.remove(m)); });
}
function floatSprites(pos, emoji, n = 6, size = .8) {
  for (let i = 0; i < n; i++) { const s = sprite(emoji, size); const o = new THREE.Vector3((Math.random() - .5) * 1.6, 1.8 + Math.random(), (Math.random() - .5) * 1.6);
    s.position.copy(pos).add(o); scene.add(s); const y0 = s.position.y; const delay = i * .12;
    tween(2.2 + delay, x => { const xx = Math.max(0, (x * (2.2 + delay) - delay) / 2.2); s.position.y = y0 + xx * 2.2; s.material.opacity = 1 - xx; if (x >= 1) scene.remove(s); }); }
}

/* ---------- buildings */
function buildUni() {
  const g = new THREE.Group();
  add(g, new THREE.BoxGeometry(4, .3, 3), M('#e9e4d8'), 0, .15, 0);
  add(g, new THREE.BoxGeometry(3.6, 2.2, 2.4), M('#f3ead7'), 0, 1.4, -.2);
  for (const x of [-1.3, -.45, .45, 1.3]) add(g, new THREE.CylinderGeometry(.16, .18, 2.2, 14), M('#ffffff', .4), x, 1.4, 1.15);
  const sh = new THREE.Shape(); sh.moveTo(-2.05, 0); sh.lineTo(2.05, 0); sh.lineTo(0, 1.05); sh.lineTo(-2.05, 0);
  const ped = add(g, new THREE.ExtrudeGeometry(sh, { depth: 2.9, bevelEnabled: false }), M('#c9563c', .7), 0, 2.5, -1.55);
  add(g, new THREE.BoxGeometry(.8, 1.3, .1), M('#5a3826', .6), 0, .95, 1.0);
  add(g, new THREE.CylinderGeometry(.03, .03, 1.4), M('#888'), 0, 4.2, -.2);
  add(g, new THREE.BoxGeometry(.6, .35, .02), M('#2a78d6'), .3, 4.7, -.2);
  const sign = sprite('🎓', 1.1); sign.position.set(0, 3.0, 1.2); g.add(sign);
  return g;
}
function buildOffice() {
  const g = new THREE.Group();
  add(g, new THREE.BoxGeometry(2.4, 5.6, 2.2), M('#a8cde8', .15, { metalness: .2 }), 0, 2.8, 0);
  for (let y = .9; y < 5.4; y += .6) add(g, new THREE.BoxGeometry(2.45, .08, 2.25), M('#5c7c99', .4), 0, y, 0);
  add(g, new THREE.BoxGeometry(.9, 1.1, .1), M('#24365c', .3), 0, .55, 1.1);
  add(g, new THREE.BoxGeometry(1.6, .12, .5), M('#24365c'), 0, 1.25, 1.25);
  const sign = sprite('💼', 1.1); sign.position.set(0, 6.3, 0); g.add(sign); return g;
}
function buildHouse(color = '#f6efe4', s = 1) {
  const g = new THREE.Group();
  add(g, new THREE.BoxGeometry(2.6, 1.7, 2.2), M(color, .8), 0, .85, 0);
  const sh = new THREE.Shape(); sh.moveTo(-1.55, 0); sh.lineTo(1.55, 0); sh.lineTo(0, 1.25); sh.lineTo(-1.55, 0);
  add(g, new THREE.ExtrudeGeometry(sh, { depth: 2.5, bevelEnabled: false }), M('#c8553d', .7), 0, 1.7, -1.25);
  add(g, new THREE.BoxGeometry(.55, 1.0, .08), M('#7a4a2b', .6), 0, .5, 1.11);
  for (const x of [-.8, .8]) add(g, new THREE.BoxGeometry(.5, .45, .06), M('#cfeaff', .2), x, 1.0, 1.11);
  add(g, new THREE.BoxGeometry(.35, .8, .35), M('#9a6340'), .75, 2.6, -.3);
  g.scale.setScalar(s); return g;
}
function buildBeach() {
  const g = new THREE.Group();
  add(g, new THREE.CylinderGeometry(2.7, 2.9, .08, 40), M('#f3dfa6', .95), 0, .04, 0);
  add(g, new THREE.CylinderGeometry(.04, .04, 2.2), M('#ffffff'), -.9, 1.1, -.4);
  add(g, new THREE.ConeGeometry(1.4, .55, 10), M('#eb6834', .6), -.9, 2.2, -.4);
  add(g, new THREE.BoxGeometry(1.2, .03, .6), M('#e87ba4', .9), .4, .1, .5);
  const trunk = add(g, new THREE.CylinderGeometry(.12, .18, 2.6, 8), M('#a0703f'), 1.6, 1.3, -1.2); trunk.rotation.z = -.15;
  for (let i = 0; i < 6; i++) { const l = add(g, new THREE.ConeGeometry(.25, 1.6, 6), M('#3aa35b', .8), 1.8, 2.6, -1.2); l.rotation.set(Math.PI / 2.3, i / 6 * Math.PI * 2, 0, 'YXZ'); }
  const sun = sprite('☀️', 1.4); sun.position.set(0, 4.2, 0); g.add(sun); return g;
}
function buildChair() {
  const g = new THREE.Group(); const wood = M('#8a5a36', .6);
  add(g, new THREE.BoxGeometry(.9, .1, .8), wood, 0, .55, 0);
  add(g, new THREE.BoxGeometry(.9, 1.0, .1), wood, 0, 1.05, -.38).rotation.x = -.15;
  for (const x of [-.4, .4]) { const r = add(g, new THREE.TorusGeometry(.7, .04, 6, 20, Math.PI / 1.6), wood, x, .75, 0); r.rotation.set(0, Math.PI / 2, Math.PI + .5); }
  for (const x of [-.4, .4]) for (const z of [-.3, .3]) add(g, new THREE.CylinderGeometry(.04, .04, .5), wood, x, .3, z);
  return g;
}
function placeAt(obj, B, face) { obj.position.copy(B); obj.rotation.y = face; scene.add(obj); }

/* ---------- life-event animations */
async function withFocus(B, fn, face = null) { S.focus = B; S.focusFace = face; try { await fn(); } finally { S.focus = null; } }
async function animGraduation(k, label) {
  const { B, face, side } = spot(k); const uni = buildUni(); placeAt(uni, B, face); toast('🎓 ' + (label ? label.replace(/!*$/, '!') : 'Uniabschluss!'));
  await withFocus(B, async () => {
    await popIn(uni); const ch = await exitCar(side);
    await walkTo(ch, frontOf(B, face, 1.6)); await walkTo(ch, frontOf(B, face, .9), 1.5); ch.visible = false; await wait(1.1);
    addProp(ch, 'gradcap'); addProp(ch, 'diploma'); ch.visible = true; await walkTo(ch, frontOf(B, face, 3.2), 1.8);
    faceCamera(ch); burst(ch.position); await cheer(ch, 1.8);
    removeProp(ch, 'gradcap'); removeProp(ch, 'diploma'); await backToCar(side);
  }, face);
}
async function animJob(k, label) {
  const { B, face, side } = spot(k); const off = buildOffice(); placeAt(off, B, face); toast('💼 ' + (label || 'Neuer Job!'));
  await withFocus(B, async () => {
    await popIn(off); const ch = await exitCar(side);
    await walkTo(ch, frontOf(B, face, 1.4)); ch.visible = false; await wait(.9);
    S.life.suit = true; rebuildChar(); const c2 = S.ch; c2.visible = true; addProp(c2, 'briefcase');
    c2.position.copy(frontOf(B, face, 1.4)); await walkTo(c2, frontOf(B, face, 3.0), 2);
    faceCamera(c2); floatSprites(c2.position, '🪙', 7); await cheer(c2, 1.4); removeProp(c2, 'briefcase'); await backToCar(side);
  }, face);
}
async function animVacation(k) {
  const { B, face, side } = spot(k); const beach = buildBeach(); placeAt(beach, B, face); toast('🏝️ Auszeit!');
  await withFocus(B, async () => {
    await popIn(beach); const wasSuit = S.life.suit; if (wasSuit) { S.life.suit = false; rebuildChar(); }
    const ch = await exitCar(side); await walkTo(ch, B.clone().add(new THREE.Vector3(.4, 0, .3)));
    addProp(ch, 'strohhut'); addProp(ch, 'sunglasses'); faceCamera(ch); floatSprites(ch.position, '🌴', 3, 1);
    ch.userData.mode = 'sit'; await wait(2.2); ch.userData.mode = 'idle';
    removeProp(ch, 'strohhut'); removeProp(ch, 'sunglasses'); await backToCar(side);
    if (wasSuit) { S.life.suit = true; rebuildChar(); }
  }, face);
}
async function animHouse(k) {
  const { B, face, side } = spot(k); const h = buildHouse('#f6efe4'); placeAt(h, B, face); h.position.y = 26; toast('🏡 Eigenes Zuhause!');
  await withFocus(B, async () => {
    await tween(1.1, x => { h.position.y = 26 * (1 - x * x); });
    burst(B, 'dust', 22); await tween(.35, x => { const s = 1 + Math.sin(x * Math.PI) * .18; h.scale.set(1 / s, s * .85 + .15 * (1 - Math.sin(x * Math.PI)), 1 / s); });
    h.scale.setScalar(1);
    const ch = await exitCar(side); await walkTo(ch, frontOf(B, face, 2.6)); faceCamera(ch);
    floatSprites(ch.position, '🔑', 3, .9); await cheer(ch, 1.6); await backToCar(side);
  }, face);
}
async function animChild(k) {
  const { B, side } = spot(k); toast('👶 Willkommen, Baby!');
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  await withFocus(wp, async () => {
    const ch = await exitCar(side); faceCamera(ch); floatSprites(ch.position, '❤️', 8, .7);
    addProp(ch, 'baby'); await wait(2.4); removeProp(ch, 'baby'); await backToCar(side);
    S.kids += 1; refreshKids();
  });
}
async function animRetirement(k) {
  const { B, face, side } = spot(k); toast('🌅 Rente – Zeit zum Geniessen', 4000);
  const chair = buildChair(); placeAt(chair, B, face);
  await withFocus(B, async () => {
    await popIn(chair);
    const sky0 = new THREE.Color('#d9efff'), sky1 = new THREE.Color('#ffb38a');
    tween(3, x => { scene.fog.color.copy(sky0).lerp(sky1, x); E.container.style.background = `linear-gradient(180deg, ${'#' + sky0.clone().lerp(new THREE.Color('#ff9a6b'), x).getHexString()} 0%, #ffe2c4 100%)`; });
    S.life.grey = true; S.life.cane = true; S.life.suit = false; rebuildChar();
    const ch = await exitCar(side); await walkTo(ch, chair.position.clone().add(new THREE.Vector3(Math.sin(face) * .2, 0, Math.cos(face) * .2)), 1.2);
    ch.rotation.y = face; ch.position.y = .15; removeProp(ch, 'cane'); ch.userData.mode = 'sit';
    await tween(5, x => { const r = Math.sin(x * Math.PI * 6) * .12; chair.rotation.x = r; ch.rotation.x = r; });
    floatSprites(ch.position, '☕', 2, .8);
  }, face);
}
async function animFate(a) {
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp); toast(`${a.emoji || '🃏'} ${a.label || 'Schicksal'}`);
  const s = sprite(a.emoji || '🃏', 2.2); s.position.copy(wp).add(new THREE.Vector3(0, 2.6, 0)); scene.add(s);
  await tween(.4, x => s.scale.setScalar(2.2 * easeOutBack(x)));
  if (a.type === 'crash') { await tween(.6, x => { S.car.position.y = Math.sin(x * Math.PI * 4) * .15; }); }
  await wait(1.1); await tween(.5, x => { s.material.opacity = 1 - x; s.position.y += .03; }); scene.remove(s);
}
async function playAnim(a, k) {
  switch (a.type) {
    case 'graduation': return animGraduation(k, a.label);
    case 'job': return animJob(k, a.label);
    case 'startup': return animJob(k, a.label || 'Startup gegründet!');
    case 'vacation': return animVacation(k);
    case 'house': return animHouse(k);
    case 'child': return animChild(k);
    case 'retirement': return animRetirement(k);
    default: return animFate(a);
  }
}
function updateWorld(dt) {
  animateCharacter(S.ch, dt); (S.car.userData.kids || []).forEach(c => animateCharacter(c, dt));
  const target = S.focus ? S.focus.clone() : S.car.position.clone();
  const off = !S.focus ? new THREE.Vector3(0, 17, 19)
    : S.focusFace === null ? new THREE.Vector3(0, 7.5, 11)
    : new THREE.Vector3(Math.sin(S.focusFace) * 10.5, 7, Math.cos(S.focusFace) * 10.5);
  const want = target.clone().add(off); const k = 1 - Math.exp(-dt * 2.2);
  camera.position.lerp(want, k); S.look = (S.look || target.clone()).lerp(target, k); camera.lookAt(S.look.x, S.look.y + 1, S.look.z);
}


/* =================================================================== loop + API */
function loop() {
  const dt = Math.min(.05, E.clock.getDelta()); runTasks(dt);
  if (E.view === 'creator' && CREATOR.scene) updateCreator(dt);
  else if (E.view === 'world' && WORLD.ready) updateWorld(dt);
  if (scene && camera) E.renderer.render(scene, camera);
  requestAnimationFrame(loop);
}
function showWorld(args, { reset = false } = {}) {
  if (!WORLD.ready || reset) { initWorld(args); WORLD.ready = true; activate('world'); return; }
  activate('world'); update(args);
}
const isBusy = () => E.busy > 0;
const setToastHandler = fn => { E.onToast = fn; };
const setBusyHandler = fn => { E.onBusy = fn; };

export { initEngine, showCreator, setCreator, showWorld, isBusy, setToastHandler, setBusyHandler };
