// 3D engine: one renderer, two views (creator podium + world island), life-event animations.
// Public API is exported at the bottom; see CONTRACT.md.
import { THREE, DEFAULT_CFG, SKINS, HAIRC, COLORS, M, add, lerp, ease, easeOutBack, sprite, tween, wait, runTasks } from './core.js';
import { buildCharacter, addProp, removeProp, animateCharacter, buildCar, seat, unseat, buildPodium } from './character.js';

/* =================================================================== renderer + views */
const E = { container: null, renderer: null, clock: null, W: 800, H: 600, view: null, busy: 0,
            onToast: null, onBusy: null, onIntro: null, onRide: null };
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
    finaleDone: false, look: null, cam: null, introCtl: null, deco: { boats: [], clouds: [] }, labels: null, step: 1,
    rideTags: [], used: [], gen: (S.gen || 0) + 1 });
  const wasBusy = E.busy > 0; E.busy = 0; if (wasBusy && E.onBusy) E.onBusy(false);
  if (E.container) E.container.style.background = '';
}
const S = { K: 15, turn: 0, startAge: 20, seen: new Set(), queue: Promise.resolve(), life: {}, kids: 0,
            curve: null, samples: [], car: null, ch: null, focus: null, stationMeshes: [], badgeSprites: [], cfg: null, u: 0, busy: false };
const ROAD_PTS = [[-20, 13], [-8, 14.5], [5, 12.5], [16, 13.5], [21.5, 7.5], [16, 1.2], [4, 0], [-8, 1], [-17, -.8],
                  [-21.5, -6.5], [-16, -12.5], [-4, -13.6], [8, -11.8], [20, -13.2]];
function initWorld(args) {
  resetWorldState(); newView(); const sun = lights(32); WORLD.scene = scene; WORLD.camera = camera;
  scene.fog = new THREE.Fog('#d9efff', 60, 175);
  S.K = args.K || 15; S.startAge = args.start_age || 20; S.cfg = { ...DEFAULT_CFG, ...(args.avatar || {}) };
  S.labels = Array.isArray(args.labels) ? args.labels : null; S.step = args.step || 1; S.rideTags = args.ride_tags || [];
  // lake + island (sand beach, grass with a slightly darker rim, foam ring on the water)
  const water = add(scene, new THREE.CircleGeometry(160, 64), M('#4fb6e8', .2), 0, -.8, 0); water.rotation.x = -Math.PI / 2; water.castShadow = false;
  const shallow = add(scene, new THREE.RingGeometry(30.2, 36, 72), new THREE.MeshStandardMaterial({ color: '#8fdcf5', roughness: .3, transparent: true, opacity: .55 }), 0, -.78, 0);
  shallow.rotation.x = -Math.PI / 2; shallow.castShadow = false;
  const foam = add(scene, new THREE.TorusGeometry(30.6, .22, 8, 96), M('#ffffff', .5), 0, -.42, 0); foam.rotation.x = Math.PI / 2; foam.castShadow = false;
  add(scene, new THREE.CylinderGeometry(29, 30.5, 1, 72), M('#f3dfa6', .95), 0, -.75, 0);
  add(scene, new THREE.CylinderGeometry(27.5, 28.2, 1.2, 72), M('#7cc466', .95), 0, -.6, 0);
  add(scene, new THREE.CylinderGeometry(26.2, 27.5, .02, 72), M('#8fd07a', .95), 0, .005, 0).receiveShadow = true;
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
  strip(1.95, .015, M('#f4f1e8', .8, { side: THREE.DoubleSide }));   // white curb
  strip(1.75, .02, M('#5f5b54', .9, { side: THREE.DoubleSide })); strip(1.5, .04, M('#7d7972', .85, { side: THREE.DoubleSide }));
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
  decorateWorld(rnd);
  // stations: disc with a rim; label = age (game) or month (film ride)
  for (let k = 0; k <= S.K; k++) {
    const p = S.curve.getPointAt(k / S.K);
    const disc = add(scene, new THREE.CylinderGeometry(.95, .95, .14, 32), M('#fffdf8', .5), p.x, .07, p.z);
    const rim = add(scene, new THREE.TorusGeometry(.97, .07, 8, 32), M('#ffffff', .4), p.x, .14, p.z); rim.rotation.x = Math.PI / 2;
    const text = S.labels && S.labels[k] !== undefined ? String(S.labels[k]) : String(S.startAge + k * S.step);
    let lbl;
    if (text.length <= 3) { lbl = sprite(text, 1.1, '#ffffff'); lbl.position.set(p.x, 1.05, p.z); }
    else {   // month labels (film ride): small, on the roadside, so the follow camera still sees the car
      const tg = S.curve.getTangentAt(Math.min(.999, Math.max(.001, k / S.K))), nn = new THREE.Vector3(-tg.z, 0, tg.x).normalize();
      lbl = tagSprite(text, .55, { bg: '#ffffff', fg: '#24365c' }); lbl.position.set(p.x + nn.x * 2.6, .7, p.z + nn.z * 2.6);
    }
    scene.add(lbl);
    S.stationMeshes.push(disc); S.badgeSprites.push(null);
  }
  // start and finish signs (float above the first and last station, always readable)
  const signAt = (k, text, color) => {
    const p = S.curve.getPointAt(Math.min(.999, Math.max(.001, k / S.K)));
    const sp = tagSprite(text, 1.0, { bg: color, fg: '#ffffff' }); sp.position.set(p.x, 3.3, p.z); scene.add(sp);
  };
  if (S.labels && args.ride) { signAt(0, '🎬 TODAY', '#2a78d6'); signAt(S.K, '📍 NOW', '#eb6834'); }
  else { signAt(0, '🚦 START · AGE ' + S.startAge, '#2a78d6'); signAt(S.K, '🏁 RETIREMENT · ' + (S.labels ? S.labels[S.K] : S.startAge + S.K * S.step), '#eb6834'); }
  // car + avatar
  S.car = buildCar(S.cfg.car); scene.add(S.car);
  S.life = args.life || {}; S.kids = S.life.kids || 0;
  S.ch = buildCharacter(S.cfg, S.life); seatDriver(); refreshKids(); refreshPartner();
  S.turn = args.turn ?? 0;
  const moving = args.prev_turn !== undefined && args.prev_turn !== args.turn;
  placeCar(moving ? args.prev_turn / S.K : S.turn / S.K);
  if (!moving) (args.anims || []).forEach(a => S.seen.add(a.id));
  colorStations(moving ? args.prev_turn : S.turn); setBadges(args.badges || {});
  camera.position.set(S.car.position.x, 13, S.car.position.z + 15); camera.lookAt(S.car.position);
  if (args.intro && !moving) { S.cam = introStartCam(); enqueue(playIntro); }
  if (args.ride) { S.cam = introStartCam(); enqueue(playRide); }
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
// the partner (after the wedding) sits next to the driver; the driver moves over to make room
function seatDriver() { seat(S.ch, S.car); if (S.life.partner) S.ch.position.z = -.19; }
function partnerCfg(cfg) {
  let h = 7; for (const c of String(cfg.name || 'Alex')) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const pick = (arr, i) => arr[(h >>> (i * 3)) % arr.length];
  const gender = cfg.gender === 'frau' ? 'mann' : cfg.gender === 'mann' ? 'frau' : pick(['frau', 'mann'], 1);
  const hair = gender === 'mann' ? pick(['kurz', 'locken', 'afro', 'iro'], 2) : pick(['lang', 'dutt', 'pferdeschwanz', 'locken'], 2);
  const colors = Object.keys(COLORS).filter(c => c !== cfg.color && c !== 'weiss');
  return { ...DEFAULT_CFG, name: 'Partner', gender, hair, hat: 'keiner', skin: pick(Object.keys(SKINS), 3),
           hairColor: pick(Object.keys(HAIRC).filter(c => c !== 'grau'), 4), outfit: pick(['hemd', 'tshirt', 'hoodie', 'sport'], 5),
           color: pick(colors, 6) };
}
function refreshPartner() {
  const old = S.car.userData.partner; if (old) { S.car.remove(old); S.car.userData.partner = null; }
  if (S.life.partner) {
    const p = buildCharacter(partnerCfg(S.cfg), { grey: !!S.life.grey }); seat(p, S.car); p.position.z = .19; S.car.userData.partner = p;
  }
  if (S.ch && S.ch.parent === S.car) S.ch.position.z = S.life.partner ? -.19 : 0;
}
function rebuildChar() {
  const parent = S.ch.parent, pos = S.ch.position.clone(), rot = S.ch.rotation.clone(), sc = S.ch.scale.clone(), mode = S.ch.userData.mode, props = Object.keys(S.ch.userData.props);
  parent.remove(S.ch); S.ch = buildCharacter(S.cfg, S.life); parent.add(S.ch); S.ch.position.copy(pos); S.ch.rotation.copy(rot); S.ch.scale.copy(sc);
  S.ch.userData.mode = mode; if (mode === 'seated') { S.ch.userData.parts.legL.visible = S.ch.userData.parts.legR.visible = false;
    if (S.ch.userData.parts.dress) S.ch.userData.parts.dress.scale.set(.62, 1, .62); }
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
    const partnerChanged = !!life.partner !== !!S.car.userData.partner;
    if (suitChanged) rebuildChar(); if ((life.kids || 0) !== S.kids) { S.kids = life.kids || 0; refreshKids(); }
    if (partnerChanged) refreshPartner(); });
  if (args.finale && !S.finaleDone) { S.finaleDone = true; enqueue(() => animRetirement(target)); }
}

async function drive(from, to) {
  if (from === to) return;
  const u0 = from / S.K, u1 = to / S.K, dur = 1.6 + .5 * Math.abs(to - from);
  await tween(dur, x => { placeCar(lerp(u0, u1, ease(x))); (S.car.userData.wheels || []).forEach(w => w.rotation.y += .3); });
  colorStations(to);
}

/* ---------- world helpers for animations */
// A free building spot next to station k. farSide: prefer the side of the road away from the default camera (tall
// buildings would hide the car); avoid: extra points to keep away from. Spots of earlier buildings (S.used) are avoided,
// so e.g. the office of the first job never lands inside the university of the same station.
function spot(k, { farSide = true, avoid = [] } = {}) {
  const u = Math.min(.999, Math.max(.001, k / S.K)); const p = S.curve.getPointAt(u), t = S.curve.getTangentAt(u);
  const n = new THREE.Vector3(-t.z, 0, t.x).normalize(); let best = null;
  const taken = [...S.used, ...avoid];
  for (const along of [0, 3, -3, 6, -6]) for (const s of [1, -1]) for (const d of [4.4, 5.4]) {
    const b = p.clone().addScaledVector(t, along).addScaledVector(n, s * d);
    const clash = taken.reduce((m, q) => Math.min(m, Math.hypot(q.x - b.x, q.z - b.z)), 99);
    const score = Math.min(minRoadDist(b.x, b.z), 3.6) - (b.length() > 24 ? 10 : 0) + (farSide && b.z < p.z ? 2 : 0)
      - (clash < 5.5 ? 20 - clash : 0) - Math.abs(along) * .15;
    if (!best || score > best.score) best = { b, s, score };
  }
  // face the road point closest to the building
  let q = p, dmin = 1e9; for (const r of S.samples) { const dd = (r.x - best.b.x) ** 2 + (r.z - best.b.z) ** 2; if (dd < dmin) { dmin = dd; q = r; } }
  const face = Math.atan2(q.x - best.b.x, q.z - best.b.z);
  const side = new THREE.Vector3(best.b.x - q.x, 0, best.b.z - q.z).normalize();
  return { B: best.b, face, side, P: p };
}
const frontOf = (B, face, d) => new THREE.Vector3(B.x + Math.sin(face) * d, 0, B.z + Math.cos(face) * d);
async function popIn(obj, dur = .6) { obj.scale.setScalar(.01); await tween(dur, x => obj.scale.setScalar(Math.max(.01, easeOutBack(x)))); }
async function exitCar(side) {
  const ch = S.ch, wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  S.car.remove(ch); scene.add(ch); ch.scale.setScalar(1); ch.rotation.set(0, 0, 0);
  ch.userData.parts.legL.visible = ch.userData.parts.legR.visible = true; ch.userData.mode = 'idle'; unseat(ch);
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
  await walkTo(S.ch, wp.clone().addScaledVector(side, 1.6)); seatDriver();
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

/* ---------- text on canvas (signs, tags) */
function textTexture(text, { bg = '#ffffff', fg = '#24365c', w = 512, h = 160, font = 92, radius = null, border = null } = {}) {
  const c = document.createElement('canvas'); c.width = w; c.height = h; const g = c.getContext('2d');
  const r = radius ?? h / 2; g.fillStyle = bg; g.beginPath(); g.roundRect(4, 4, w - 8, h - 8, r); g.fill();
  if (border) { g.lineWidth = 8; g.strokeStyle = border; g.stroke(); }
  g.font = `800 ${font}px Nunito, system-ui, "Apple Color Emoji", "Segoe UI Emoji", sans-serif`;
  g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillStyle = fg; g.fillText(text, w / 2, h / 2 + font * .06);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; return tex;
}
function tagSprite(text, size = 1, opts = {}) {
  const w = Math.max(320, 70 * text.length + 120), h = 160;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: textTexture(text, { w, h, border: '#24365c', ...opts }), transparent: true, depthWrite: false }));
  s.scale.set(size * w / h, size, 1); return s;
}

/* ---------- map decoration: mountains across the lake, boats, clouds, flowers, rocks, a UBS branch */
function decorateWorld(rnd) {
  // snowy mountain range on the far shore (lake view)
  for (let i = 0; i < 22; i++) {
    const a = Math.PI * (1.05 + i / 21 * .9) + (rnd() - .5) * .05, r = 78 + rnd() * 14, h = 14 + rnd() * 16, w = 9 + rnd() * 7;
    const g = new THREE.Group(); g.position.set(Math.cos(a) * r, -1, Math.sin(a) * r);
    add(g, new THREE.ConeGeometry(w, h, 7), M(rnd() < .5 ? '#8fa3b8' : '#7d93aa', .9), 0, h / 2, 0);
    add(g, new THREE.ConeGeometry(w * .38, h * .38, 7), M('#f7fbff', .7), 0, h - h * .19 + .02, 0);
    g.rotation.y = rnd() * 6; scene.add(g);
  }
  // sailboats bobbing on the lake
  for (let i = 0; i < 5; i++) {
    const a = rnd() * Math.PI * 2, r = 36 + rnd() * 16, g = new THREE.Group(); g.position.set(Math.cos(a) * r, -.75, Math.sin(a) * r);
    add(g, new THREE.BoxGeometry(2.2, .45, .8), M('#ffffff', .5), 0, .2, 0); add(g, new THREE.BoxGeometry(2.0, .12, .7), M('#c98b4b', .6), 0, .48, 0);
    add(g, new THREE.CylinderGeometry(.05, .05, 2.6), M('#8a5a36'), .1, 1.7, 0);
    const sh = new THREE.Shape(); sh.moveTo(0, 0); sh.lineTo(1.2, 0); sh.lineTo(0, 2.2); sh.lineTo(0, 0);
    const sail = add(g, new THREE.ShapeGeometry(sh), new THREE.MeshStandardMaterial({ color: ['#ffffff', '#ffd23f', '#e87ba4'][i % 3], side: THREE.DoubleSide }), .15, .6, 0);
    sail.castShadow = false; g.rotation.y = rnd() * 6; g.userData.ph = rnd() * 6; scene.add(g); S.deco.boats.push(g);
  }
  // puffy clouds
  for (let i = 0; i < 7; i++) {
    const g = new THREE.Group(); g.position.set(-60 + rnd() * 120, 20 + rnd() * 6, -45 + rnd() * 70);
    for (let j = 0; j < 4; j++) { const b = add(g, new THREE.SphereGeometry(1.6 + rnd() * 1.3, 14, 10), M('#ffffff', .95), j * 2.2 - 3.3, rnd() * .8, rnd() * 1.2); b.castShadow = false; }
    g.userData.v = .25 + rnd() * .35; scene.add(g); S.deco.clouds.push(g);
  }
  // flower patches, bushes and rocks away from the road
  const flowers = [], bushes = [], rocks = [];
  for (let i = 0; i < 700 && flowers.length < 220; i++) {
    const a = rnd() * Math.PI * 2, rr = Math.sqrt(rnd()) * 26, x = Math.cos(a) * rr, z = Math.sin(a) * rr;
    const d = minRoadDist(x, z); if (d < 2.4) continue;
    if (rnd() < .82) flowers.push([x, z, rnd()]); else if (rnd() < .7) bushes.push([x, z, .5 + rnd() * .5]); else rocks.push([x, z, .3 + rnd() * .5]);
  }
  const dm = new THREE.Object3D(), FC = ['#ffffff', '#ffd23f', '#ff8fb1', '#b48cff', '#ff6b6b'];
  const fl = new THREE.InstancedMesh(new THREE.SphereGeometry(.09, 8, 6), M('#ffffff', .6), flowers.length);
  flowers.forEach(([x, z, c], i) => { dm.position.set(x, .12, z); dm.scale.setScalar(1); dm.updateMatrix(); fl.setMatrixAt(i, dm.matrix); fl.setColorAt(i, new THREE.Color(FC[Math.floor(c * FC.length)])); });
  scene.add(fl);
  const bu = new THREE.InstancedMesh(new THREE.SphereGeometry(.55, 12, 10), M('#5fae4e', .85), bushes.length); bu.castShadow = true;
  bushes.forEach(([x, z, k], i) => { dm.position.set(x, .25 * k, z); dm.scale.set(k, k * .75, k); dm.updateMatrix(); bu.setMatrixAt(i, dm.matrix); }); scene.add(bu);
  const ro = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(.6, 0), M('#a8a39a', .9), rocks.length); ro.castShadow = true;
  rocks.forEach(([x, z, k], i) => { dm.position.set(x, .15 * k, z); dm.scale.set(k, k * .7, k); dm.rotation.y = x; dm.updateMatrix(); ro.setMatrixAt(i, dm.matrix); }); scene.add(ro);
  dm.rotation.set(0, 0, 0);
}
function buildBank() { // modern branch: white stone, glass front, red-and-white sign with the bank name
  const g = new THREE.Group();
  add(g, new THREE.BoxGeometry(3.6, .2, 2.8), M('#d9d6cf'), 0, .1, 0);
  add(g, new THREE.BoxGeometry(3.4, 2.6, 2.4), M('#f4f2ee', .6), 0, 1.5, 0);
  add(g, new THREE.BoxGeometry(3.6, .2, 2.6), M('#c9c6bf', .6), 0, 2.9, 0);
  add(g, new THREE.BoxGeometry(2.8, 1.5, .06), M('#9fc8e6', .1, { metalness: .2 }), 0, 1.0, 1.21);
  for (const x of [-.95, 0, .95]) add(g, new THREE.BoxGeometry(.06, 1.5, .08), M('#3a3a42', .4), x, 1.0, 1.23);
  add(g, new THREE.BoxGeometry(2.8, .9, .06), M('#9fc8e6', .1, { metalness: .2 }), 0, 2.15, 1.21);
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(1.9, .62), new THREE.MeshBasicMaterial({ map: textTexture('UBS', { bg: '#e60000', fg: '#ffffff', w: 380, h: 124, font: 86, radius: 14 }) }));
  sign.position.set(0, 3.32, 1.0); g.add(sign);
  add(g, new THREE.BoxGeometry(2.0, .72, .08), M('#e60000', .5), 0, 3.32, .95);
  const pole = add(g, new THREE.CylinderGeometry(.05, .05, 2.4), M('#9aa0a6'), 1.9, 1.2, 1.4);
  const flag = new THREE.Mesh(new THREE.PlaneGeometry(.8, .5), new THREE.MeshBasicMaterial({ map: textTexture('UBS', { bg: '#e60000', fg: '#ffffff', w: 200, h: 124, font: 64, radius: 6 }), side: THREE.DoubleSide }));
  flag.position.set(2.32, 2.15, 1.4); g.add(flag); pole.castShadow = true;
  return g;
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
function buildChapel() { // white chapel with a bell tower; local +z = front (faces the road)
  const g = new THREE.Group(), white = M('#fdfbf6', .7), roofM = M('#8a72e0', .6), gold = M('#f2c14e', .3, { metalness: .3 });
  add(g, new THREE.BoxGeometry(3.3, .25, 3.6), M('#e9e4d8'), 0, .12, -.4);
  add(g, new THREE.BoxGeometry(2.6, 2.3, 3.0), white, 0, 1.4, -.45);
  const sh = new THREE.Shape(); sh.moveTo(-1.6, 0); sh.lineTo(1.6, 0); sh.lineTo(0, 1.35); sh.lineTo(-1.6, 0);
  add(g, new THREE.ExtrudeGeometry(sh, { depth: 3.3, bevelEnabled: false }), roofM, 0, 2.55, -2.1);
  // door (arched) + round window
  add(g, new THREE.BoxGeometry(.84, 1.1, .08), M('#c98b4b', .6), 0, .8, 1.07);
  const arch = add(g, new THREE.CylinderGeometry(.42, .42, .08, 24, 1, false, 0, Math.PI), M('#c98b4b', .6), 0, 1.35, 1.07); arch.rotation.set(Math.PI / 2, 0, Math.PI / 2);
  for (const x of [-.14, .14]) add(g, new THREE.TorusGeometry(.06, .015, 6, 14), gold, x, .85, 1.13);
  add(g, new THREE.CircleGeometry(.32, 24), M('#bfe6ff', .2), 0, 2.05, 1.06);
  add(g, new THREE.TorusGeometry(.34, .05, 8, 24), white, 0, 2.05, 1.07);
  for (const x of [-1.31, 1.31]) for (const z of [-1.3, .15]) add(g, new THREE.BoxGeometry(.06, .8, .45), M('#bfe6ff', .2), x, 1.55, z);
  // bell tower on the front gable: open belfry with a swinging golden bell, pointed roof
  add(g, new THREE.BoxGeometry(1.05, 1.1, 1.05), white, 0, 3.4, .45);
  for (const x of [-.45, .45]) for (const z of [0, .9]) add(g, new THREE.BoxGeometry(.14, .9, .14), white, x, 4.4, z);
  add(g, new THREE.BoxGeometry(1.15, .14, 1.15), white, 0, 4.9, .45);
  const steeple = add(g, new THREE.ConeGeometry(.82, 1.5, 4), roofM, 0, 5.72, .45); steeple.rotation.y = Math.PI / 4;
  add(g, new THREE.SphereGeometry(.1, 12, 10), gold, 0, 6.55, .45);
  const bell = new THREE.Group(); bell.position.set(0, 4.8, .45); g.add(bell);
  add(bell, new THREE.CylinderGeometry(.16, .3, .42, 20), gold, 0, -.3, 0); add(bell, new THREE.SphereGeometry(.07, 10, 8), gold, 0, -.55, 0);
  // flower-lined path and a flower arch towards the road
  add(g, new THREE.BoxGeometry(1.1, .03, 3.2), M('#f2d9a6', .9), 0, .02, 2.75);
  const fc = ['#ff8fb1', '#ffffff', '#ffd23f'];
  for (let i = 0; i < 5; i++) for (const x of [-.78, .78]) add(g, new THREE.SphereGeometry(.16, 10, 8), M(fc[(i + (x > 0 ? 1 : 0)) % 3], .7), x, .14, 1.5 + i * .6);
  const ring = add(g, new THREE.TorusGeometry(1.05, .07, 8, 28, Math.PI), M('#5fa85a', .7), 0, 0, 4.1);
  for (let i = 0; i <= 8; i++) { const a = i / 8 * Math.PI; add(g, new THREE.SphereGeometry(.12, 10, 8), M(fc[i % 3], .6), Math.cos(a) * 1.05, Math.sin(a) * 1.05, 4.1); }
  ring.castShadow = true;
  const sign = sprite('💒', 1.1); sign.position.set(0, 7.3, .45); g.add(sign);
  g.userData.bell = bell; return g;
}
function placeAt(obj, B, face) { obj.position.copy(B); obj.rotation.y = face; scene.add(obj); S.used.push(B.clone()); }

/* ---------- life-event animations */
// cam (optional): { dist, height, yaw } for a custom framing of the scene
async function withFocus(B, fn, face = null, cam = null) {
  S.focus = B; S.focusFace = face; S.focusCam = cam; try { await fn(); } finally { S.focus = null; S.focusCam = null; }
}
async function animGraduation(k, label) {
  const { B, face, side } = spot(k); const uni = buildUni(); placeAt(uni, B, face); toast('🎓 ' + (label ? label.replace(/!*$/, '!') : 'Graduation!'));
  await withFocus(B, async () => {
    await popIn(uni); const ch = await exitCar(side);
    await walkTo(ch, frontOf(B, face, 1.6)); await walkTo(ch, frontOf(B, face, .9), 1.5); ch.visible = false; await wait(1.1);
    addProp(ch, 'gradcap'); addProp(ch, 'diploma'); ch.visible = true; await walkTo(ch, frontOf(B, face, 3.2), 1.8);
    faceCamera(ch); burst(ch.position); await cheer(ch, 1.8);
    removeProp(ch, 'gradcap'); removeProp(ch, 'diploma'); await backToCar(side);
  }, face);
}
async function animJob(k, label) {
  const { B, face, side } = spot(k); const off = buildOffice(); placeAt(off, B, face); toast('💼 ' + (label || 'New job!'));
  await withFocus(B, async () => {
    await popIn(off); const ch = await exitCar(side);
    await walkTo(ch, frontOf(B, face, 1.4)); ch.visible = false; await wait(.9);
    S.life.suit = true; rebuildChar(); const c2 = S.ch; c2.visible = true; addProp(c2, 'briefcase');
    c2.position.copy(frontOf(B, face, 1.4)); await walkTo(c2, frontOf(B, face, 3.0), 2);
    faceCamera(c2); floatSprites(c2.position, '🪙', 7); await cheer(c2, 1.4); removeProp(c2, 'briefcase'); await backToCar(side);
  }, face);
}
async function animVacation(k) {
  const { B, face, side } = spot(k); const beach = buildBeach(); placeAt(beach, B, face); toast('🏝️ Time off!');
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
  // the mortgage comes from UBS: a UBS branch pops up next to the plot, the avatar signs, then the house lands
  const { B, face, side } = spot(k, { farSide: true });
  const bs = spot(k, { avoid: [B] }); const bank = buildBank(); bank.scale.setScalar(.8); placeAt(bank, bs.B, bs.face);
  toast('🏦 Off to UBS for the mortgage …', 2600);
  const mid = B.clone().lerp(bs.B, .5);
  await withFocus(mid, async () => {
    await popIn(bank, .55);
    const ch = await exitCar(bs.side); await walkTo(ch, frontOf(bs.B, bs.face, 1.7)); await walkTo(ch, frontOf(bs.B, bs.face, 1.0), 1.4);
    ch.visible = false; await wait(1.0);
    addProp(ch, 'diploma'); ch.visible = true; await walkTo(ch, frontOf(bs.B, bs.face, 2.4), 1.8); faceCamera(ch);
    toast('✅ UBS mortgage approved – a home of your own!', 3000); floatSprites(ch.position, '✅', 2, .8);
    const h = buildHouse('#f6efe4'); placeAt(h, B, face); h.position.y = 26;
    await tween(1.1, x => { h.position.y = 26 * (1 - x * x); });
    burst(B, 'dust', 22); await tween(.35, x => { const q = 1 + Math.sin(x * Math.PI) * .18; h.scale.set(1 / q, q * .85 + .15 * (1 - Math.sin(x * Math.PI)), 1 / q); });
    h.scale.setScalar(1); removeProp(ch, 'diploma');
    await walkTo(ch, frontOf(B, face, 2.6)); faceCamera(ch);
    floatSprites(ch.position, '🔑', 3, .9); await cheer(ch, 1.6); await backToCar(side);
  }, null);
}
async function animChild(k) {
  const { B, side } = spot(k); toast('👶 Welcome, baby!');
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  await withFocus(wp, async () => {
    const ch = await exitCar(side); faceCamera(ch); floatSprites(ch.position, '❤️', 8, .7);
    addProp(ch, 'baby'); await wait(2.4); removeProp(ch, 'baby'); await backToCar(side);
    S.kids += 1; refreshKids();
  });
}
async function animRetirement(k) {
  const { B, face, side } = spot(k); toast('🌅 Retirement – time to enjoy', 4000);
  const chair = buildChair(); placeAt(chair, B, face);
  await withFocus(B, async () => {
    await popIn(chair);
    const sky0 = new THREE.Color('#d9efff'), sky1 = new THREE.Color('#ffb38a');
    tween(3, x => { scene.fog.color.copy(sky0).lerp(sky1, x); E.container.style.background = `linear-gradient(180deg, ${'#' + sky0.clone().lerp(new THREE.Color('#ff9a6b'), x).getHexString()} 0%, #ffe2c4 100%)`; });
    S.life.grey = true; S.life.cane = true; S.life.suit = false; rebuildChar(); refreshPartner();
    const ch = await exitCar(side); await walkTo(ch, chair.position.clone().add(new THREE.Vector3(Math.sin(face) * .2, 0, Math.cos(face) * .2)), 1.2);
    ch.rotation.y = face; ch.position.y = .15; removeProp(ch, 'cane'); ch.userData.mode = 'sit';
    await tween(5, x => { const r = Math.sin(x * Math.PI * 6) * .12; chair.rotation.x = r; ch.rotation.x = r; });
    floatSprites(ch.position, '☕', 2, .8);
  }, face);
}
async function animWedding(k) {
  const { B, face, side } = spot(k, { farSide: true }); const chapel = buildChapel(); placeAt(chapel, B, face); toast('💍 Wedding day!', 3200);
  const fwd = new THREE.Vector3(Math.sin(face), 0, Math.cos(face)), right = new THREE.Vector3(Math.cos(face), 0, -Math.sin(face));
  const at = (d, r = 0) => B.clone().addScaledVector(fwd, d).addScaledVector(right, r);
  const ring = async (n = 3) => { const bell = chapel.userData.bell; const wp = new THREE.Vector3(); bell.getWorldPosition(wp);
    floatSprites(wp, '🔔', 2, .7); await tween(1.4, x => { bell.rotation.x = Math.sin(x * Math.PI * 2 * n) * .5 * (1 - x); }); };
  const GUESTS = [
    { gender: 'frau', hair: 'locken', hairColor: 'rot', color: 'pink', outfit: 'kleid', hat: 'keiner', skin: 'hell' },
    { gender: 'mann', hair: 'kurz', hairColor: 'schwarz', color: 'navy', outfit: 'hemd', hat: 'keiner', skin: 'braun' },
    { gender: 'divers', hair: 'iro', hairColor: 'blau', color: 'gelb', outfit: 'tshirt', hat: 'partyhut', skin: 'oliv' },
    { gender: 'frau', hair: 'dutt', hairColor: 'grau', color: 'violett', outfit: 'kleid', hat: 'keiner', skin: 'rosig' },
    { gender: 'mann', hair: 'afro', hairColor: 'dunkelbraun', color: 'gruen', outfit: 'hemd', hat: 'keiner', skin: 'dunkel' },
    { gender: 'frau', hair: 'pferdeschwanz', hairColor: 'blond', color: 'tuerkis', outfit: 'sport', hat: 'cap', skin: 'mittel' },
  ];
  const pcfg = partnerCfg(S.cfg);
  const role = c => (c.gender === 'frau' ? 'dress' : 'suit');
  const dressUp = (ch, r) => { addProp(ch, r === 'dress' ? 'veil' : 'tophat'); if (r === 'dress') addProp(ch, 'bouquet'); };
  await withFocus(at(2.2), async () => {
    await popIn(chapel, .7);
    const guests = GUESTS.map((cfg, i) => {
      const sgn = i % 2 ? 1 : -1, g = buildCharacter({ ...DEFAULT_CFG, ...cfg });
      g.position.copy(at(1.5 + Math.floor(i / 2) * .8, sgn * (1.75 + Math.floor(i / 2) * .2)));
      g.rotation.y = Math.atan2(-right.x * sgn, -right.z * sgn) + sgn * .35;   // towards the aisle, slightly to the front
      g.scale.setScalar(.85); scene.add(g); return g;
    });
    // guests (and later the partner) are animated every frame while the scene runs
    const crowd = [...guests]; let alive = true;
    (async () => { while (alive) await tween(.25, () => crowd.forEach(c => animateCharacter(c, 1 / 60))); })();
    await Promise.all(guests.map((g, i) => wait(i * .08).then(() => tween(.45, x => g.scale.setScalar(Math.max(.01, .85 * easeOutBack(x)))))));
    ring(3);
    // the avatar gets out and changes into the wedding outfit
    const ch = await exitCar(side); ch.visible = false; burst(ch.position, 'dust', 10); await wait(.35);
    const myRole = role(S.cfg); S.life.wedding = myRole; rebuildChar(); S.ch.visible = true; dressUp(S.ch, myRole);
    // the partner steps out of the chapel door
    const partner = buildCharacter(pcfg, { wedding: role(pcfg) }); dressUp(partner, role(pcfg));
    partner.position.copy(at(1.0)); partner.rotation.y = face; scene.add(partner); crowd.push(partner); await popIn(partner, .45);
    // both walk to the flower arch, meet in the middle and face the guests
    await Promise.all([walkTo(S.ch, at(3.6, .45), 2.2), walkTo(partner, at(1.9, -.45), 1.6)]);
    await walkTo(S.ch, at(2.0, .45), 1.4);
    S.ch.rotation.y = partner.rotation.y = face;
    const rings = sprite('💍', 1.4); rings.position.copy(at(2.0)).add(new THREE.Vector3(0, 3.2, 0)); scene.add(rings);
    await tween(.45, x => rings.scale.setScalar(1.4 * easeOutBack(x)));
    floatSprites(at(2.0), '❤️', 10, .7); burst(at(2.4), 'confetti', 90); ring(4);
    guests.forEach(g => { g.userData.mode = 'cheer'; }); S.ch.userData.mode = partner.userData.mode = 'cheer';
    await wait(2.4);
    guests.forEach(g => { g.userData.mode = 'idle'; }); S.ch.userData.mode = partner.userData.mode = 'idle';
    await tween(.4, x => { rings.material.opacity = 1 - x; }); scene.remove(rings);
    // down the aisle together and into the car
    await Promise.all([walkTo(S.ch, at(3.9, .45), 2), walkTo(partner, at(3.9, -.45), 2)]);
    crowd.splice(crowd.indexOf(partner), 1); scene.remove(partner);
    for (const pr of ['veil', 'tophat', 'bouquet']) removeProp(S.ch, pr);
    S.life.wedding = null; rebuildChar();
    await backToCar(side);
    S.life.partner = true; refreshPartner(); floatSprites(S.car.position, '💕', 4, .6);
    await Promise.all(guests.map(g => tween(.35, x => g.scale.setScalar(Math.max(.01, .85 * (1 - x)))).then(() => scene.remove(g))));
    alive = false;
  }, face, { dist: 10, height: 9.5, yaw: .5 });
}

/* ---------- intro: fly over the island, how to play, countdown (skippable) */
function introStartCam() { return { pos: new THREE.Vector3(-30, 42, 38), look: new THREE.Vector3(0, 0, 0) }; }
async function playIntro() {
  const gen = S.gen, ctl = S.introCtl = { skip: false };
  const ev = (step, data = {}) => { if (E.onIntro && gen === S.gen) E.onIntro(step, data); };
  const cam = S.cam = S.cam || introStartCam();
  ev('title', { from: S.startAge, to: S.labels ? S.labels[S.K] : S.startAge + S.K * S.step, stations: S.K, step: S.step });
  await tween(4.2, x => { const a = -.65 + ease(x) * 1.1, r = 44 - x * 6;
    cam.pos.set(Math.sin(a) * r, 40 - x * 8, Math.cos(a) * r); cam.look.set(0, 0, 0); }, ctl);
  // course preview: glide along the road from the last station (retirement) back to the start
  ev('howto');
  const p0 = cam.pos.clone(), l0 = cam.look.clone();
  await tween(7, x => {
    const u = Math.min(.999, Math.max(.001, 1 - ease(x))), p = S.curve.getPointAt(u), t = S.curve.getTangentAt(u);
    const pos = p.clone().addScaledVector(t, 9).add(new THREE.Vector3(0, 7.5, 0)), look = p.clone().addScaledVector(t, -6);
    const blend = Math.min(1, x * 5);   // first 20 %: leave the overview smoothly
    cam.pos.copy(p0).lerp(pos, blend); cam.look.copy(l0).lerp(look, blend);
  }, ctl);
  // swoop down behind the car – then the game starts (no countdown)
  const p1 = cam.pos.clone(), l1 = cam.look.clone();
  const end = () => [S.car.position.clone().add(new THREE.Vector3(0, 17, 19)), S.car.position.clone()];
  await tween(1.6, x => { const [pe, le] = end(); cam.pos.copy(p1).lerp(pe, ease(x)); cam.look.copy(l1).lerp(le, ease(x)); }, ctl);
  if (gen !== S.gen) return;                       // world was rebuilt (restart) meanwhile
  const [pe, le] = end(); cam.pos.copy(pe); cam.look.copy(le);
  S.look = le.clone(); S.cam = null; S.introCtl = null;
  ev('end', { skipped: ctl.skip });
}
const skipIntro = () => { if (S.introCtl) S.introCtl.skip = true; };   // also skips the film ride

/* ---------- film ride: the car drives through the months of the player's real data */
async function playRide() {
  const gen = S.gen, ctl = S.introCtl = { skip: false };
  const ev = (step, data = {}) => { if (E.onRide && gen === S.gen) E.onRide(step, data); };
  const cam = S.cam = S.cam || introStartCam();
  const wantFor = () => {   // cinematic follow: behind and beside the car, low
    const u = Math.min(.999, Math.max(.001, S.u)), t = S.curve.getTangentAt(u), side = new THREE.Vector3(-t.z, 0, t.x).normalize();
    const c = S.car.position;
    return [c.clone().addScaledVector(t, -6.5).addScaledVector(side, 4.2).add(new THREE.Vector3(0, 3.6, 0)),
            c.clone().addScaledVector(t, 2.5).add(new THREE.Vector3(0, .8, 0))];
  };
  const follow = k => { const [p, l] = wantFor(); cam.pos.lerp(p, k); cam.look.lerp(l, k); };
  ev('start', { n: S.K });
  await tween(2.4, x => { const a = -.4 + x * .5; cam.pos.set(Math.sin(a) * 42, 36 - x * 6, Math.cos(a) * 42); cam.look.set(0, 0, 0); }, ctl);
  await tween(1.6, x => follow(.02 + .2 * ease(x)), ctl);
  for (let k = 1; k <= S.K; k++) {
    if (gen !== S.gen) return;
    const u0 = (k - 1) / S.K, u1 = k / S.K;
    await tween(1.5, x => { placeCar(lerp(u0, u1, ease(x))); (S.car.userData.wheels || []).forEach(w => w.rotation.y += .3); follow(.09); }, ctl);
    colorStations(k); ev('station', { i: k - 1 });
    const tag = S.rideTags[k - 1];
    if (tag) {
      const p = S.curve.getPointAt(Math.min(.999, u1)), tg = S.curve.getTangentAt(Math.min(.999, u1));
      const nn = new THREE.Vector3(-tg.z, 0, tg.x).normalize();
      const sp = tagSprite(tag.text, .6, { bg: tag.good ? '#2fd27a' : '#ff5a7a', fg: '#ffffff' });
      sp.position.set(p.x + nn.x * 2.6, 1.45, p.z + nn.z * 2.6); scene.add(sp); sp.scale.multiplyScalar(.01); const full = sp.scale.clone().multiplyScalar(100);
      tween(.45, x => sp.scale.copy(full).multiplyScalar(Math.max(.01, easeOutBack(x))));
      if (tag.note) floatSprites(new THREE.Vector3(p.x, 0, p.z), tag.good ? '🎉' : '⚠️', 2, .7);
    }
    await tween(1.5, () => follow(.09), ctl);
  }
  if (gen !== S.gen) return;
  const p0 = cam.pos.clone(), l0 = cam.look.clone();
  await tween(1.8, x => { cam.pos.copy(p0).lerp(new THREE.Vector3(8, 34, 40), ease(x)); cam.look.copy(l0).lerp(new THREE.Vector3(0, 0, 0), ease(x)); }, ctl);
  S.introCtl = null;
  ev('end');
}

async function animFate(a) {
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp); toast(`${a.emoji || '🃏'} ${a.label || 'Twist of fate'}`);
  const s = sprite(a.emoji || '🃏', 2.2); s.position.copy(wp).add(new THREE.Vector3(0, 2.6, 0)); scene.add(s);
  await tween(.4, x => s.scale.setScalar(2.2 * easeOutBack(x)));
  if (a.type === 'crash') { await tween(.6, x => { S.car.position.y = Math.sin(x * Math.PI * 4) * .15; }); }
  await wait(1.1); await tween(.5, x => { s.material.opacity = 1 - x; s.position.y += .03; }); scene.remove(s);
}
async function playAnim(a, k) {
  switch (a.type) {
    case 'graduation': return animGraduation(k, a.label);
    case 'job': return animJob(k, a.label);
    case 'startup': return animJob(k, a.label || 'Startup founded!');
    case 'vacation': return animVacation(k);
    case 'house': return animHouse(k);
    case 'child': return animChild(k);
    case 'wedding': return animWedding(k);
    case 'retirement': return animRetirement(k);
    default: return animFate(a);
  }
}
function updateWorld(dt) {
  animateCharacter(S.ch, dt); (S.car.userData.kids || []).forEach(c => animateCharacter(c, dt));
  if (S.car.userData.partner) animateCharacter(S.car.userData.partner, dt);
  const tt = performance.now() / 1000;
  S.deco.boats.forEach(b => { b.position.y = -.75 + Math.sin(tt * 1.3 + b.userData.ph) * .08; b.rotation.z = Math.sin(tt + b.userData.ph) * .05; });
  S.deco.clouds.forEach(c => { c.position.x += c.userData.v * dt; if (c.position.x > 70) c.position.x = -70; });
  if (S.cam) { camera.position.copy(S.cam.pos); camera.lookAt(S.cam.look); return; }
  const target = S.focus ? S.focus.clone() : S.car.position.clone();
  const off = !S.focus ? new THREE.Vector3(0, 17, 19)
    : S.focusFace === null ? new THREE.Vector3(0, 7.5, 11)
    : S.focusCam ? new THREE.Vector3(Math.sin(S.focusFace + S.focusCam.yaw) * S.focusCam.dist, S.focusCam.height,
                                     Math.cos(S.focusFace + S.focusCam.yaw) * S.focusCam.dist)
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
const setIntroHandler = fn => { E.onIntro = fn; };
const setRideHandler = fn => { E.onRide = fn; };

export { initEngine, showCreator, setCreator, showWorld, isBusy, setToastHandler, setBusyHandler, setIntroHandler, setRideHandler,
         skipIntro };
