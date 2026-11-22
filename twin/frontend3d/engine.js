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
const C = { cfg: { ...DEFAULT_CFG }, cat: 'gender', ch: null, car: null, rot: 0, drag: null, podium: null,
            pod: false, t: 0, waveUntil: 0 };   // pod = podium-only mode (analysis page: the twin as the agent)
function buildCreatorScene() {
  newView(); CREATOR.scene = scene; CREATOR.camera = camera; lights(6);
  C.podium = buildPodium(); scene.add(C.podium);
  const floor = add(scene, new THREE.CircleGeometry(12, 48), new THREE.ShadowMaterial({ opacity: .2 }), 0, -.6, 0); floor.rotation.x = -Math.PI / 2;
  camera.position.set(0, 1.7, 6.6); camera.lookAt(0, 1.15, 0);
}
function showCreator(cfg, cat) {
  if (!CREATOR.scene) buildCreatorScene();
  C.pod = false; activate('creator'); setCreator(cfg || C.cfg, cat || C.cat, false);
}
// Podium mode (component mode "podium"): only the character on its podium, slow idle turn + gentle bob.
// The figure is rebuilt only when the avatar changes; wave: true lets it wave for a moment (greeting / speaking).
function showPodium(cfg, { wave = false } = {}) {
  if (!CREATOR.scene) buildCreatorScene();
  const next = { ...DEFAULT_CFG, ...(cfg || {}) }, same = C.ch && !C.car && JSON.stringify(next) === JSON.stringify(C.cfg);
  C.pod = true; activate('creator');
  if (!same) setCreator(next, 'gender', !!C.ch);
  if (wave) waveNow();
}
function waveNow(sec = 2.6) { C.waveUntil = C.t + sec; }
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
  C.t += dt;
  if (C.pod) return updatePodium(dt);
  if (C.drag === null) C.rot += dt * .35;
  const t = C.car || C.ch; if (t) t.rotation.y = C.car ? C.rot - .6 : Math.sin(C.rot) * .5;
  if (C.ch) animateCharacter(C.ch, dt);
  const cam = C.car ? [0, 2.4, 7.2] : [0, 1.7, 6.6]; camera.position.lerp(new THREE.Vector3(...cam), .08); camera.lookAt(0, C.car ? .8 : 1.15, 0);
}

function updatePodium(dt) {
  const ch = C.ch; if (!ch) return;
  const waving = C.t < C.waveUntil;
  if (C.drag === null) C.rot += dt * .22;
  // idle: slow turn left/right; while waving it faces the viewer
  const want = waving ? 0 : Math.sin(C.rot) * .55;
  ch.rotation.y = C.drag === null ? lerp(ch.rotation.y, want, 1 - Math.exp(-dt * 3)) : Math.sin(C.rot) * .55;
  ch.position.y = (Math.sin(C.t * 2.1) + 1) * .03;                               // gentle bob
  const mode = waving ? 'wave' : 'idle'; if (ch.userData.mode !== mode && (ch.userData.mode === 'idle' || ch.userData.mode === 'wave')) ch.userData.mode = mode;
  animateCharacter(ch, dt);
  // keep the whole podium in view in a narrow column; leave room above the head for the speech bubble
  const aspect = Math.max(.35, E.W / Math.max(1, E.H)), dist = Math.max(6.9, 6.5 / aspect);
  camera.position.lerp(new THREE.Vector3(0, 1.75, dist), .12); camera.lookAt(0, 1.32, 0);
}

/* =================================================================== WORLD */
// Island geometry (1.6x the first version, so 40–70 one-year stations fit): ISL = usable grass radius,
// CURB = half width of the road incl. the white curb, GAP = free space between a building's edge and the curb.
const SCALE = 1.6, ISL = 27.5 * SCALE - 1, CURB = 1.95, GAP = 3;
function resetWorldState() {
  Object.assign(S, { K: 15, turn: 0, startAge: 20, seen: new Set(), queue: Promise.resolve(), life: {}, kids: 0, kidsLeft: 0, curve: null,
    samples: [], car: null, ch: null, focus: null, focusFace: null, stationMeshes: [], badgeSprites: [], cfg: null, u: 0,
    finaleDone: false, look: null, cam: null, introCtl: null, deco: { boats: [], clouds: [] }, labels: null, step: 1,
    rideTags: [], used: [], decor: [], figs: new Set(), sun: null, stationColor: -1, gen: (S.gen || 0) + 1 });
  const wasBusy = E.busy > 0; E.busy = 0; if (wasBusy && E.onBusy) E.onBusy(false);
  if (E.container) E.container.style.background = '';
}
const S = { K: 15, turn: 0, startAge: 20, seen: new Set(), queue: Promise.resolve(), life: {}, kids: 0, kidsLeft: 0,
            curve: null, samples: [], car: null, ch: null, focus: null, stationMeshes: [], badgeSprites: [], cfg: null, u: 0, busy: false,
            used: [], decor: [], figs: new Set() };
// Serpentine road: four gently waving rows (in phase, so the rows keep 18 units apart) joined by U-turns.
function buildRoadPts() {
  const pts = [], w = x => 1.6 * Math.sin(x * .21 + .4);
  const rows = [[27, -20, 21], [9, 21, -26], [-9, -26, 22], [-27, 22, -20]];
  rows.forEach(([z, x0, x1], i) => {
    const n = Math.max(2, Math.round(Math.abs(x1 - x0) / 6));
    for (let j = 0; j <= n; j++) { const x = lerp(x0, x1, j / n); pts.push([x, z + w(x)]); }
    const nx = rows[i + 1]; if (!nx) return;
    const cz = (z + nx[0]) / 2 + w(x1), R = Math.abs(z - nx[0]) / 2, dir = x1 > x0 ? 1 : -1;
    for (let j = 1; j < 6; j++) { const a = Math.PI / 2 - j / 6 * Math.PI; pts.push([x1 + dir * Math.cos(a) * R, cz + Math.sin(a) * R]); }
  });
  return pts;
}
const ROAD_PTS = buildRoadPts();
const clampU = u => Math.min(.999, Math.max(.001, u));
function initWorld(args) {
  resetWorldState(); newView(); const sun = lights(40); WORLD.scene = scene; WORLD.camera = camera;
  S.sun = sun; scene.add(sun.target); camera.far = 800; camera.updateProjectionMatrix();
  scene.fog = new THREE.Fog('#d9efff', 110, 330);
  S.K = args.K || 15; S.startAge = args.start_age || 20; S.cfg = { ...DEFAULT_CFG, ...(args.avatar || {}) };
  S.labels = Array.isArray(args.labels) ? args.labels : null; S.step = args.step || 1; S.rideTags = args.ride_tags || [];
  // lake + island (sand beach, grass with a slightly darker rim, foam ring on the water)
  const R = r => r * SCALE;
  const water = add(scene, new THREE.CircleGeometry(280, 72), M('#4fb6e8', .2), 0, -.8, 0); water.rotation.x = -Math.PI / 2; water.castShadow = false;
  const shallow = add(scene, new THREE.RingGeometry(R(30.2), R(36), 96), new THREE.MeshStandardMaterial({ color: '#8fdcf5', roughness: .3, transparent: true, opacity: .55 }), 0, -.78, 0);
  shallow.rotation.x = -Math.PI / 2; shallow.castShadow = false;
  const foam = add(scene, new THREE.TorusGeometry(R(30.6), .3, 8, 128), M('#ffffff', .5), 0, -.42, 0); foam.rotation.x = Math.PI / 2; foam.castShadow = false;
  add(scene, new THREE.CylinderGeometry(R(29), R(30.5), 1, 96), M('#f3dfa6', .95), 0, -.75, 0);
  add(scene, new THREE.CylinderGeometry(R(27.5), R(28.2), 1.2, 96), M('#7cc466', .95), 0, -.6, 0);
  add(scene, new THREE.CylinderGeometry(R(26.2), R(27.5), .02, 96), M('#8fd07a', .95), 0, .005, 0).receiveShadow = true;
  // road
  S.curve = new THREE.CatmullRomCurve3(ROAD_PTS.map(([x, z]) => new THREE.Vector3(x, 0, z)), false, 'catmullrom', .5);
  const N = 1400; S.samples = S.curve.getSpacedPoints(N);
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
  strip(CURB, .015, M('#f4f1e8', .8, { side: THREE.DoubleSide }));   // white curb
  strip(1.75, .02, M('#5f5b54', .9, { side: THREE.DoubleSide })); strip(1.5, .04, M('#7d7972', .85, { side: THREE.DoubleSide }));
  const ND = Math.round(S.curve.getLength() / 2.2);
  const dashes = new THREE.InstancedMesh(new THREE.BoxGeometry(.6, .02, .1), M('#fff6d6', .6), ND); const dm = new THREE.Object3D();
  for (let i = 0; i < ND; i++) { const u = (i + .5) / ND, p = S.curve.getPointAt(u), t = S.curve.getTangentAt(u);
    dm.position.set(p.x, .06, p.z); dm.rotation.set(0, Math.atan2(-t.z, t.x), 0); dm.updateMatrix(); dashes.setMatrixAt(i, dm.matrix); }
  scene.add(dashes);
  // scenery. Every decor item is registered in S.decor ({x, z, r, hard, refs}) so spot() keeps buildings off it:
  // little houses are hard obstacles, trees / bushes / rocks are soft (a building may replace them – they are hidden).
  const rnd = mulberry(7);
  const HC = ['#f6c7b6', '#bfe0f5', '#f8e2a8', '#d9c8f0', '#c9f0d6', '#ffd9b0', '#e3f0c0'];
  for (let i = 0, placed = 0; i < 500 && placed < 13; i++) {
    const a = rnd() * Math.PI * 2, rr = Math.sqrt(rnd()) * (ISL - 2), x = Math.cos(a) * rr, z = Math.sin(a) * rr;
    const nr = nearestRoad(x, z); if (nr.d < CURB + 2.4 + 1.15) continue;
    if (S.decor.some(q => Math.hypot(q.x - x, q.z - z) < q.r + 1.15 + 2.6)) continue;
    const h = buildHouse(HC[placed % HC.length], .55); h.position.set(x, 0, z); h.rotation.y = Math.atan2(nr.q.x - x, nr.q.z - z); scene.add(h);
    S.decor.push({ x, z, r: 1.15, hard: true }); placed++;
  }
  const trees = [];
  for (let i = 0; i < 1200 && trees.length < 200; i++) {
    const a = rnd() * Math.PI * 2, rr = Math.sqrt(rnd()) * (ISL - 1.5), x = Math.cos(a) * rr, z = Math.sin(a) * rr;
    if (minRoadDist(x, z) < 3.2) continue;
    if (S.decor.some(q => q.hard && Math.hypot(q.x - x, q.z - z) < q.r + 1)) continue;
    trees.push({ x, z, s: .6 + rnd() * .45, pine: rnd() < .5 });
  }
  const crowns = trees.filter(t => !t.pine), pines = trees.filter(t => t.pine);
  const mkInst = (geo, mat, n) => { const im = new THREE.InstancedMesh(geo, mat, Math.max(1, n)); im.castShadow = true; im.receiveShadow = true; im.count = n; scene.add(im); return im; };
  const trunkIM = mkInst(new THREE.CylinderGeometry(.12, .16, .8, 8), M('#8a5a36'), trees.length);
  const crownIM = mkInst(new THREE.SphereGeometry(.75, 14, 12), M('#4caf50', .8), crowns.length);
  const pineIM = mkInst(new THREE.ConeGeometry(.7, 1.8, 10), M('#2e7d4f', .8), pines.length);
  let ci = 0, pi = 0;
  trees.forEach((t, i) => {
    dm.rotation.set(0, 0, 0); dm.scale.setScalar(1); dm.position.set(t.x, .4, t.z); dm.updateMatrix(); trunkIM.setMatrixAt(i, dm.matrix);
    dm.scale.setScalar(t.s);
    let ref;
    if (t.pine) { dm.position.set(t.x, 1.4 * t.s, t.z); dm.updateMatrix(); pineIM.setMatrixAt(pi, dm.matrix); ref = [pineIM, pi++]; }
    else { dm.position.set(t.x, 1.3 * t.s, t.z); dm.updateMatrix(); crownIM.setMatrixAt(ci, dm.matrix); ref = [crownIM, ci++]; }
    S.decor.push({ x: t.x, z: t.z, r: .75 * t.s + .15, hard: false, refs: [[trunkIM, i], ref] });
  });
  dm.scale.setScalar(1);
  decorateWorld(rnd);
  // stations: disc with a rim; label = age (game) or month (film ride)
  const lblSize = S.K > 45 ? .9 : 1.1;
  for (let k = 0; k <= S.K; k++) {
    const p = S.curve.getPointAt(k / S.K);
    const disc = add(scene, new THREE.CylinderGeometry(.95, .95, .14, 32), M('#fffdf8', .5), p.x, .07, p.z);
    const rim = add(scene, new THREE.TorusGeometry(.97, .07, 8, 32), M('#ffffff', .4), p.x, .14, p.z); rim.rotation.x = Math.PI / 2;
    const text = S.labels && S.labels[k] !== undefined ? String(S.labels[k]) : String(S.startAge + k * S.step);
    let lbl;
    if (text.length <= 3) { lbl = sprite(text, lblSize, '#ffffff'); lbl.position.set(p.x, 1.05, p.z); }
    else {   // month labels (film ride): small, on the roadside, so the follow camera still sees the car
      const tg = S.curve.getTangentAt(clampU(k / S.K)), nn = new THREE.Vector3(-tg.z, 0, tg.x).normalize();
      lbl = tagSprite(text, .55, { bg: '#ffffff', fg: '#24365c' }); lbl.position.set(p.x + nn.x * 2.6, .7, p.z + nn.z * 2.6);
    }
    scene.add(lbl);
    S.stationMeshes.push(disc); S.badgeSprites.push(null);
  }
  // start and finish signs (float above the first and last station, always readable)
  const signAt = (k, text, color) => {
    const p = S.curve.getPointAt(clampU(k / S.K));
    const sp = tagSprite(text, 1.0, { bg: color, fg: '#ffffff' }); sp.position.set(p.x, 3.3, p.z); scene.add(sp);
  };
  if (S.labels && args.ride) { signAt(0, '🎬 TODAY', '#2a78d6'); signAt(S.K, '📍 NOW', '#eb6834'); }
  else { signAt(0, '🚦 START · AGE ' + S.startAge, '#2a78d6'); signAt(S.K, '🏁 AGE ' + (S.labels ? S.labels[S.K] : S.startAge + S.K * S.step), '#eb6834'); }
  // car + avatar
  S.car = buildCar(S.cfg.car); scene.add(S.car);
  S.life = { ...(args.life || {}) }; S.kids = S.life.kids || 0;
  if (S.life.retired || S.life.grey) Object.assign(S.life, { grey: true, cane: true });
  S.turn = args.turn ?? 0;
  const moving = args.prev_turn !== undefined && args.prev_turn !== args.turn;
  // children who already moved out: life.kids_home (if Python sends it) wins, else count the child_leaves anims seen
  if (Number.isFinite(S.life.kids_home)) S.kidsLeft = Math.max(0, S.kids - S.life.kids_home);
  else if (!moving) S.kidsLeft = (args.anims || []).filter(a => a.type === 'child_leaves').length;
  S.ch = buildCharacter(S.cfg, S.life); seatDriver(); refreshKids(); refreshPartner();
  placeCar(moving ? args.prev_turn / S.K : S.turn / S.K);
  if (!moving) (args.anims || []).forEach(a => S.seen.add(a.id));
  colorStations(moving ? args.prev_turn : S.turn); setBadges(args.badges || {});
  camera.position.set(S.car.position.x, 17, S.car.position.z + 19); camera.lookAt(S.car.position);
  if (args.intro && !moving) { S.cam = introStartCam(); enqueue(playIntro); }
  if (args.ride) { S.cam = introStartCam(); enqueue(playRide); }
  if (moving) update(args, true);
  else if (args.finale && !S.finaleDone) { S.finaleDone = true; enqueue(() => animRetirement(S.turn, null, true)); }
}
function mulberry(a) { return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
// closest road sample to (x, z): {d: distance to the road centre line, q: the sample point}
function nearestRoad(x, z) { let m = 1e9, q = null; for (const p of S.samples) { const d = (p.x - x) ** 2 + (p.z - z) ** 2; if (d < m) { m = d; q = p; } } return { d: Math.sqrt(m), q }; }
function minRoadDist(x, z) { return nearestRoad(x, z).d; }
function colorStations(cur) {
  if (cur === S.stationColor) return; S.stationColor = cur;
  S.stationMeshes.forEach((m, k) => { m.material = M(k < cur ? '#2a78d6' : k === cur ? '#ffd23f' : k === S.K ? '#eda100' : '#fffdf8', .5); });
}
function setBadges(b) {
  for (const [k, e] of Object.entries(b)) { const i = +k; if (S.badgeSprites[i] || !(i >= 0 && i <= S.K)) continue; const p = S.curve.getPointAt(i / S.K);
    const s = sprite(e, 1.3); s.position.set(p.x, 2.2, p.z); scene.add(s); S.badgeSprites[i] = s; }
}
function placeCar(u) {
  S.u = u; const p = S.curve.getPointAt(Math.min(1, Math.max(0, u))), t = S.curve.getTangentAt(clampU(u));
  S.car.position.set(p.x, 0, p.z); S.car.rotation.y = Math.atan2(-t.z, t.x);
}
// kids in the back seat: children still at home (born minus moved out), at most two are drawn
const kidCfg = i => ({ ...S.cfg, hat: 'keiner', hair: i % 2 ? 'dutt' : 'kurz', gender: i % 2 ? 'frau' : 'mann' });
function refreshKids() {
  (S.car.userData.kids || []).forEach(k => S.car.remove(k)); S.car.userData.kids = [];
  const home = Math.max(0, S.kids - S.kidsLeft);
  for (let j = 0; j < Math.min(home, 2); j++) { const i = S.kidsLeft + j, kid = buildCharacter(kidCfg(i));
    seat(kid, S.car, -.62, .33); kid.position.z = j ? -.22 : .22; S.car.userData.kids.push(kid); }
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
  let anims = (args.anims || []).filter(a => !S.seen.has(a.id)); anims.forEach(a => S.seen.add(a.id));
  const life = args.life || {}; const badges = args.badges || {};
  // skip: several years in one go – drive all stations in one smooth move, anims of the skipped years only briefly
  const skipped = +args.skipped || 0, brief = skipped >= 2;
  // the finale (end of life) already shows the rocking chair: a plain retirement anim in the same step only changes the state
  const finaleNow = args.finale && !S.finaleDone;
  if (finaleNow && anims.some(a => a.type === 'retirement')) {
    anims = anims.filter(a => a.type !== 'retirement'); enqueue(async () => { setRetired(); rebuildChar(); refreshPartner(); });
  }
  if (target !== S.turn || initial) {
    const from = initial ? args.prev_turn : S.turn; S.turn = target;
    if (brief) { const list = anims; anims = []; enqueue(() => driveSkip(from, target, list)); }
    else enqueue(() => drive(from, target));
  }
  for (const a of anims) enqueue(() => (a.brief || brief ? playBrief(a, target) : playAnim(a, target)));
  enqueue(async () => { setBadges(badges); colorStations(target);
    const suitChanged = !!life.suit !== !!S.life.suit; S.life = { ...S.life, ...life };
    if (life.retired && !S.life.grey) { setRetired(); rebuildChar(); }
    const partnerChanged = !!life.partner !== !!S.car.userData.partner;
    if (suitChanged) rebuildChar();
    const nk = life.kids || 0;
    if (Number.isFinite(life.kids_home)) S.kidsLeft = Math.max(0, nk - life.kids_home);
    else if (nk < S.kids) S.kidsLeft = Math.max(0, S.kidsLeft - (S.kids - nk));   // Python counts only children at home
    if (nk !== S.kids || (S.car.userData.kids || []).length !== Math.min(2, Math.max(0, nk - S.kidsLeft))) { S.kids = nk; refreshKids(); }
    if (partnerChanged) refreshPartner(); });
  if (finaleNow) { S.finaleDone = true; enqueue(() => animRetirement(target, null, true)); }
}

const spinWheels = () => (S.car.userData.wheels || []).forEach(w => { w.rotation.y += .3; });
async function drive(from, to, dur = null) {
  if (from === to || from === undefined || from === null) return;
  const u0 = from / S.K, u1 = to / S.K; dur = dur ?? 1.6 + .5 * Math.abs(to - from);
  await tween(dur, x => { const u = lerp(u0, u1, ease(x)); placeCar(u); spinWheels(); colorStations(Math.floor(u * S.K + 1e-6)); });
  colorStations(to);
}
// several years at once: one smooth drive, stopping briefly where an anim with a known station ("turn") happened
async function driveSkip(from, to, anims) {
  const n = Math.abs(to - from); toast(`⏩ +${n} year${n === 1 ? '' : 's'}`, 1500);
  const at = new Map();
  for (const a of anims) { const k = Number.isFinite(a.turn) && a.turn > Math.min(from, to) && a.turn <= Math.max(from, to) ? a.turn : to;
    if (!at.has(k)) at.set(k, []); at.get(k).push(a); }
  const stops = [...at.keys()].sort((a, b) => (to >= from ? a - b : b - a));
  let cur = from;
  for (const k of stops) {
    if (k !== cur) await drive(cur, k, Math.min(5, .9 + .22 * Math.abs(k - cur)));
    cur = k; for (const a of at.get(k)) await playBrief(a, k);
  }
  if (cur !== to) await drive(cur, to, Math.min(5, .9 + .22 * Math.abs(to - cur)));
}

/* ---------- world helpers for animations */
// Footprints of the buildings: radius r (world units, at scale 1) around a centre that sits `off` units from the
// building origin towards the road (the chapel's flower path points at the road).
const FOOT = { uni: { r: 2.55 }, office: { r: 1.8 }, house: { r: 2.0 }, flat: { r: 1.45 }, beach: { r: 2.95 }, chair: { r: .9 },
               bank: { r: 2.3 }, chapel: { r: 3.1, off: .65 }, signpost: { r: 1.3 } };
// A free building spot next to station k. Rules (checked for the footprint circle, not just the centre):
//  * the building edge keeps >= GAP units from the road incl. the curb (whole road, also the neighbouring rows),
//  * it stays on the island, * it does not overlap earlier buildings (S.used) or the little decor houses,
//  * trees / bushes / rocks are avoided if possible (a building that takes their place hides them).
// Search: positions along the road on both sides → rings around the station → only then a smaller building.
// farSide: prefer the side away from the default camera (tall buildings would hide the car); avoid: extra circles/points.
// Returns {B, face, side, P, c, r, scale}; pass the result to placeAt / claim.
function spot(k, { farSide = true, avoid = [], r = 2.2, off = 0 } = {}) {
  const u = clampU(k / S.K); const p = S.curve.getPointAt(u), t = S.curve.getTangentAt(u);
  const n = new THREE.Vector3(-t.z, 0, t.x).normalize();
  // the station's own stretch of road (± ~17 units): the building faces it, even where another row of the road is near
  const NS = S.samples.length - 1, i0 = Math.round(u * NS), W = Math.round(NS * 17 / S.curve.getLength());
  const localRoad = (x, z) => { let m = 1e9, q = null;
    for (let i = Math.max(0, i0 - W); i <= Math.min(NS, i0 + W); i++) { const r2 = S.samples[i], d = (r2.x - x) ** 2 + (r2.z - z) ** 2; if (d < m) { m = d; q = r2; } }
    return { d: Math.sqrt(m), q }; };
  const hard = [...S.used, ...S.decor.filter(d => d.hard),
    ...avoid.map(a => (a.r !== undefined ? a : { x: a.x, z: a.z, r: 2.2 }))];
  const test = (b, rr, relax = false) => {
    const nb = localRoad(b.x, b.z); if (nb.d < .5) return null;
    const c = b.clone().add(new THREE.Vector3(nb.q.x - b.x, 0, nb.q.z - b.z).setLength(off * rr / r));
    const road = nearestRoad(c.x, c.z).d - rr;
    if (road < CURB + GAP) return null;
    if (Math.hypot(c.x, c.z) + rr > ISL - .6) return null;
    let clash = 0; for (const q of hard) { const o = q.r + rr + .5 - Math.hypot(q.x - c.x, q.z - c.z); if (o > 0) { if (!relax) return null; clash += o; } }
    let soft = 0; for (const d of S.decor) if (!d.hard && !d.hidden && Math.hypot(d.x - c.x, d.z - c.z) < d.r + rr) soft++;
    const foreign = nearestRoad(b.x, b.z).d < nb.d - .5 ? 1 : 0;   // closer to another part of the road than to its station
    return { c, soft, foreign, clash };
  };
  const side = b => (farSide && b.z < p.z ? 2 : 0);
  let best = null;
  const consider = (b, rr, base, relax = false) => { const ok = test(b, rr, relax); if (!ok) return;
    const score = base + side(b) - ok.soft * .5 - ok.foreign * 4 - ok.clash * 10; if (!best || score > best.score) best = { b, c: ok.c, rr, score }; };
  for (const rr of [r, r * .85, r * .7, r * .55]) {
    const dmin = CURB + GAP + rr + off * rr / r + .2;
    for (const along of [0, 3, -3, 6, -6, 9, -9, 12, -12]) for (const s of [1, -1]) for (const dd of [0, .8, 1.8, 3]) {
      const b = p.clone().addScaledVector(t, along).addScaledVector(n, s * (dmin + dd));
      consider(b, rr, -Math.abs(along) * .25 - dd * .35);
    }
    if (!best) for (let R = 5; R <= 24 && !best; R += 1.5) for (let i = 0; i < 24; i++) {
      const a = i / 24 * Math.PI * 2 + R * .37, b = p.clone().add(new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R));
      consider(b, rr, -R * .4);
    }
    if (best) break;
  }
  if (!best) {   // very crowded map: a small building with the least overlap – but never on the road or in the water
    const rr = r * .55;
    for (let R = 5; R <= 30; R += 1.5) for (let i = 0; i < 24; i++) {
      const a = i / 24 * Math.PI * 2 + R * .37; consider(p.clone().add(new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R)), rr, -R * .4, true);
    }
  }
  if (!best) { const rr = r * .55, b = p.clone().addScaledVector(n, CURB + GAP + rr + 1); best = { b, c: b.clone(), rr, score: -99 }; }
  const B = best.b; const q = localRoad(B.x, B.z).q;
  const face = Math.atan2(q.x - B.x, q.z - B.z);
  const sideV = new THREE.Vector3(B.x - q.x, 0, B.z - q.z).normalize();
  return { B, face, side: sideV, P: p, c: best.c, r: best.rr, scale: best.rr / r };
}
// reserve a spot (S.used) and hide the trees / bushes / rocks under it
const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);
function claim(sp) {
  S.used.push({ x: sp.c.x, z: sp.c.z, r: sp.r });
  for (const d of S.decor) if (!d.hard && !d.hidden && Math.hypot(d.x - sp.c.x, d.z - sp.c.z) < d.r * .5 + sp.r) {
    d.hidden = true; for (const [im, i] of d.refs || []) { im.setMatrixAt(i, ZERO); im.instanceMatrix.needsUpdate = true; }
  }
}
const frontOf = (B, face, d) => new THREE.Vector3(B.x + Math.sin(face) * d, 0, B.z + Math.cos(face) * d);
const baseScale = obj => obj.userData.base || 1;
async function popIn(obj, dur = .6) { const s = baseScale(obj); obj.scale.setScalar(.01 * s); await tween(dur, x => obj.scale.setScalar(Math.max(.01, easeOutBack(x)) * s)); }
async function exitCar(side, ch = S.ch, along = 0) {
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  const t = S.curve.getTangentAt(clampU(S.u)); wp.addScaledVector(t, along);
  S.car.remove(ch); scene.add(ch); ch.scale.setScalar(1); ch.rotation.set(0, 0, 0);
  ch.userData.parts.legL.visible = ch.userData.parts.legR.visible = true; ch.userData.mode = 'idle'; unseat(ch);
  const out = wp.clone().addScaledVector(side, 1.6); ch.position.copy(wp).addScaledVector(side, .6);
  await walkTo(ch, out, 2.5); return ch;
}
// Figures avoid each other: every other figure standing in the world (S.figs + the avatar when it is out of the car)
// and the goal of a figure that is walking right now are obstacles; the path gets detour waypoints around them.
const FIG_R = .8;
function obstacles(self, ignore) {
  const out = [];
  const take = f => { if (!f || f === self || ignore.includes(f) || f.parent !== scene || !f.visible) return;
    out.push(new THREE.Vector3(f.position.x, 0, f.position.z)); if (f.userData.goal) out.push(f.userData.goal.clone()); };
  S.figs.forEach(take); take(S.ch);
  return out;
}
function planPath(from, to, self, ignore = []) {
  const obs = obstacles(self, ignore), pts = [new THREE.Vector3(from.x, 0, from.z), new THREE.Vector3(to.x, 0, to.z)];
  const clearance = w => obs.reduce((m, o) => Math.min(m, o.distanceTo(w)), 99);
  for (let iter = 0; iter < 14; iter++) {
    let changed = false;
    for (let i = 0; i < pts.length - 1 && !changed; i++) {
      const a = pts[i], b = pts[i + 1], ab = b.clone().sub(a), L2 = ab.lengthSq(); if (L2 < 1e-4) continue;
      for (const o of obs) {
        if (o.distanceTo(a) < FIG_R * .9 || o.distanceTo(b) < FIG_R * .9) continue;   // cannot avoid an obstacle at the end points
        const tt = Math.min(1, Math.max(0, o.clone().sub(a).dot(ab) / L2)), cp = a.clone().addScaledVector(ab, tt);
        if (cp.distanceTo(o) >= FIG_R) continue;
        // detour waypoint beside the obstacle: try both sides and growing offsets, keep the one with most room to all figures
        const perp = new THREE.Vector3(-ab.z, 0, ab.x).normalize(), pref = cp.clone().sub(o).dot(perp) >= 0 ? 1 : -1;
        let wp = null, room = -1;
        for (const k of [FIG_R + .3, FIG_R + 1, FIG_R + 1.8]) for (const sgn of [pref, -pref]) {
          const w = o.clone().addScaledVector(perp, sgn * k), c = clearance(w) - (sgn === pref ? 0 : .05) - k * .02;
          if (c > room) { room = c; wp = w; }
          if (room >= FIG_R + .2) break;
        }
        pts.splice(i + 1, 0, wp); changed = true; break;
      }
    }
    if (!changed) break;
  }
  return pts.slice(1);
}
async function walkSeg(ch, to, speed) {
  const from = ch.position.clone(); const d = to.clone().sub(from); d.y = 0; const L = d.length(); if (L < .01) return;
  if (L > 4) speed *= 1 + Math.min(.6, (L - 4) * .1);   // longer ways (bigger map) a bit faster
  ch.rotation.y = Math.atan2(d.x, d.z); ch.userData.mode = 'walk';
  await tween(L / speed, x => { ch.position.lerpVectors(from, to, x); ch.position.y = from.y; });
}
async function walkTo(ch, to, speed = 2.4, { ignore = [] } = {}) {
  const goal = new THREE.Vector3(to.x, 0, to.z); ch.userData.goal = goal;
  try { for (const wp of planPath(ch.position, goal, ch, ignore)) await walkSeg(ch, wp, speed); }
  finally { if (ch.userData.goal === goal) ch.userData.goal = null; ch.userData.mode = 'idle'; }
}
async function backToCar(side, along = 0) {
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp); wp.addScaledVector(S.curve.getTangentAt(clampU(S.u)), along);
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

/* ---------- map decoration: mountains across the lake, boats, clouds, flowers, rocks */
function decorateWorld(rnd) {
  // snowy mountain range on the far shore (lake view)
  for (let i = 0; i < 26; i++) {
    const a = Math.PI * (1.05 + i / 25 * .9) + (rnd() - .5) * .05, r = 128 + rnd() * 22, h = 20 + rnd() * 22, w = 13 + rnd() * 10;
    const g = new THREE.Group(); g.position.set(Math.cos(a) * r, -1, Math.sin(a) * r);
    add(g, new THREE.ConeGeometry(w, h, 7), M(rnd() < .5 ? '#8fa3b8' : '#7d93aa', .9), 0, h / 2, 0);
    add(g, new THREE.ConeGeometry(w * .38, h * .38, 7), M('#f7fbff', .7), 0, h - h * .19 + .02, 0);
    g.rotation.y = rnd() * 6; scene.add(g);
  }
  // sailboats bobbing on the lake
  for (let i = 0; i < 8; i++) {
    const a = rnd() * Math.PI * 2, r = 56 + rnd() * 28, g = new THREE.Group(); g.position.set(Math.cos(a) * r, -.75, Math.sin(a) * r);
    add(g, new THREE.BoxGeometry(2.2, .45, .8), M('#ffffff', .5), 0, .2, 0); add(g, new THREE.BoxGeometry(2.0, .12, .7), M('#c98b4b', .6), 0, .48, 0);
    add(g, new THREE.CylinderGeometry(.05, .05, 2.6), M('#8a5a36'), .1, 1.7, 0);
    const sh = new THREE.Shape(); sh.moveTo(0, 0); sh.lineTo(1.2, 0); sh.lineTo(0, 2.2); sh.lineTo(0, 0);
    const sail = add(g, new THREE.ShapeGeometry(sh), new THREE.MeshStandardMaterial({ color: ['#ffffff', '#ffd23f', '#e87ba4'][i % 3], side: THREE.DoubleSide }), .15, .6, 0);
    sail.castShadow = false; g.rotation.y = rnd() * 6; g.userData.ph = rnd() * 6; scene.add(g); S.deco.boats.push(g);
  }
  // puffy clouds
  for (let i = 0; i < 11; i++) {
    const g = new THREE.Group(); g.position.set(-100 + rnd() * 200, 28 + rnd() * 10, -75 + rnd() * 120);
    for (let j = 0; j < 4; j++) { const b = add(g, new THREE.SphereGeometry(2.2 + rnd() * 1.8, 14, 10), M('#ffffff', .95), j * 3 - 4.5, rnd() * 1.1, rnd() * 1.6); b.castShadow = false; }
    g.userData.v = .3 + rnd() * .4; scene.add(g); S.deco.clouds.push(g);
  }
  // flower patches, bushes and rocks away from the road (bushes and rocks are soft decor: buildings may replace them)
  const flowers = [], bushes = [], rocks = [];
  for (let i = 0; i < 2000 && flowers.length < 560; i++) {
    const a = rnd() * Math.PI * 2, rr = Math.sqrt(rnd()) * ISL, x = Math.cos(a) * rr, z = Math.sin(a) * rr;
    const d = minRoadDist(x, z); if (d < 2.4) continue;
    if (S.decor.some(q => q.hard && Math.hypot(q.x - x, q.z - z) < q.r + .3)) continue;
    if (rnd() < .82) flowers.push([x, z, rnd()]); else if (rnd() < .7) bushes.push([x, z, .5 + rnd() * .5]); else rocks.push([x, z, .3 + rnd() * .5]);
  }
  const dm = new THREE.Object3D(), FC = ['#ffffff', '#ffd23f', '#ff8fb1', '#b48cff', '#ff6b6b'];
  const fl = new THREE.InstancedMesh(new THREE.SphereGeometry(.09, 8, 6), M('#ffffff', .6), Math.max(1, flowers.length)); fl.count = flowers.length;
  flowers.forEach(([x, z, c], i) => { dm.position.set(x, .12, z); dm.scale.setScalar(1); dm.updateMatrix(); fl.setMatrixAt(i, dm.matrix); fl.setColorAt(i, new THREE.Color(FC[Math.floor(c * FC.length)])); });
  scene.add(fl);
  const bu = new THREE.InstancedMesh(new THREE.SphereGeometry(.55, 12, 10), M('#5fae4e', .85), Math.max(1, bushes.length)); bu.castShadow = true; bu.count = bushes.length;
  bushes.forEach(([x, z, k], i) => { dm.position.set(x, .25 * k, z); dm.scale.set(k, k * .75, k); dm.updateMatrix(); bu.setMatrixAt(i, dm.matrix);
    S.decor.push({ x, z, r: .55 * k, hard: false, refs: [[bu, i]] }); }); scene.add(bu);
  const ro = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(.6, 0), M('#a8a39a', .9), Math.max(1, rocks.length)); ro.castShadow = true; ro.count = rocks.length;
  rocks.forEach(([x, z, k], i) => { dm.position.set(x, .15 * k, z); dm.scale.set(k, k * .7, k); dm.rotation.y = x; dm.updateMatrix(); ro.setMatrixAt(i, dm.matrix);
    S.decor.push({ x, z, r: .6 * k, hard: false, refs: [[ro, i]] }); }); scene.add(ro);
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
  add(g, new THREE.BoxGeometry(1.1, .03, 2.3), M('#f2d9a6', .9), 0, .02, 2.3);   // short path: footprint FOOT.chapel
  const fc = ['#ff8fb1', '#ffffff', '#ffd23f'];
  for (let i = 0; i < 4; i++) for (const x of [-.78, .78]) add(g, new THREE.SphereGeometry(.16, 10, 8), M(fc[(i + (x > 0 ? 1 : 0)) % 3], .7), x, .14, 1.5 + i * .55);
  const ring = add(g, new THREE.TorusGeometry(1.05, .07, 8, 28, Math.PI), M('#5fa85a', .7), 0, 0, 3.4);
  for (let i = 0; i <= 8; i++) { const a = i / 8 * Math.PI; add(g, new THREE.SphereGeometry(.12, 10, 8), M(fc[i % 3], .6), Math.cos(a) * 1.05, Math.sin(a) * 1.05, 3.4); }
  ring.castShadow = true;
  const sign = sprite('💒', 1.1); sign.position.set(0, 7.3, .45); g.add(sign);
  g.userData.bell = bell; return g;
}

function buildSignpost() { // gap year: wooden signpost with far-away destinations, a suitcase and a globe
  const g = new THREE.Group();
  add(g, new THREE.CylinderGeometry(.08, .1, 3, 10), M('#8a5a36'), 0, 1.5, 0);
  [['BALI', '#eb6834', .5], ['PERU', '#1baf7a', -.6], ['OSLO', '#2a78d6', 2.2]].forEach(([t, c, rot], i) => {
    const arm = new THREE.Group(); arm.position.y = 2.65 - i * .55; arm.rotation.y = rot; g.add(arm);
    const b = new THREE.Mesh(new THREE.PlaneGeometry(1.3, .4), new THREE.MeshBasicMaterial({ map: textTexture(t, { bg: c, fg: '#ffffff', w: 330, h: 100, font: 62, radius: 12 }), side: THREE.DoubleSide }));
    b.position.x = .62; arm.add(b);
  });
  add(g, new THREE.BoxGeometry(.6, .45, .3), M('#e34948', .5), .6, .23, .45);
  add(g, new THREE.SphereGeometry(.32, 18, 14), M('#4fb6e8', .5), -.55, .32, .35);
  add(g, new THREE.TorusGeometry(.33, .025, 6, 24), M('#f2c14e', .4), -.55, .32, .35).rotation.y = .6;
  const sign = sprite('🌍', 1.0); sign.position.set(0, 3.7, 0); g.add(sign); return g;
}
// put a building on a spot from spot(): position, rotation, scale (the spot may ask for a smaller building), reserve it
function placeAt(obj, sp) {
  obj.position.copy(sp.B); obj.rotation.y = sp.face; obj.userData.base = baseScale(obj) * (sp.scale || 1);
  obj.scale.setScalar(obj.userData.base); scene.add(obj); claim(sp);
}

/* ---------- life-event animations */
// cam (optional): { dist, height, yaw } for a custom framing of the scene
async function withFocus(B, fn, face = null, cam = null) {
  S.focus = B; S.focusFace = face; S.focusCam = cam; try { await fn(); } finally { S.focus = null; S.focusCam = null; }
}
const bang = (label, dflt) => (label ? label.replace(/!*$/, '!') : dflt);
// graduation: the degree only – no office any more (a job is its own decision, anim "job")
async function animGraduation(k, label) {
  const sp = spot(k, FOOT.uni), { B, face, side } = sp; const uni = buildUni(); placeAt(uni, sp); toast('🎓 ' + bang(label, 'Graduation!'));
  await withFocus(B, async () => {
    await popIn(uni); const ch = await exitCar(side);
    await walkTo(ch, frontOf(B, face, 1.6 * sp.scale + 1)); await walkTo(ch, frontOf(B, face, 1.6 * sp.scale), 1.5); ch.visible = false; await wait(1.1);
    addProp(ch, 'gradcap'); addProp(ch, 'diploma'); ch.visible = true; await walkTo(ch, frontOf(B, face, 1.6 * sp.scale + 2.4), 1.8);
    faceCamera(ch); burst(ch.position); floatSprites(ch.position, '📜', 2, .7); await cheer(ch, 1.8);
    removeProp(ch, 'gradcap'); removeProp(ch, 'diploma'); await backToCar(side);
  }, face);
}
async function animJob(k, label) {
  const sp = spot(k, FOOT.office), { B, face, side } = sp; const off = buildOffice(); placeAt(off, sp); toast('💼 ' + (label || 'New job!'));
  await withFocus(B, async () => {
    await popIn(off); const ch = await exitCar(side);
    const door = 1.4 * sp.scale;
    await walkTo(ch, frontOf(B, face, door)); ch.visible = false; await wait(.9);
    S.life.suit = true; rebuildChar(); const c2 = S.ch; c2.visible = true; addProp(c2, 'briefcase');
    c2.position.copy(frontOf(B, face, door)); await walkTo(c2, frontOf(B, face, door + 1.6), 2);
    faceCamera(c2); floatSprites(c2.position, '🪙', 7); await cheer(c2, 1.4); removeProp(c2, 'briefcase'); await backToCar(side);
  }, face);
}
async function animVacation(k) {
  const sp = spot(k, FOOT.beach), { B, face, side } = sp; const beach = buildBeach(); placeAt(beach, sp); toast('🏝️ Time off!');
  await withFocus(B, async () => {
    await popIn(beach); const wasSuit = S.life.suit; if (wasSuit) { S.life.suit = false; rebuildChar(); }
    const ch = await exitCar(side); await walkTo(ch, B.clone().add(new THREE.Vector3(.4, 0, .3)));
    addProp(ch, 'strohhut'); addProp(ch, 'sunglasses'); faceCamera(ch); floatSprites(ch.position, '🌴', 3, 1);
    ch.userData.mode = 'sit'; await wait(2.2); ch.userData.mode = 'idle';
    removeProp(ch, 'strohhut'); removeProp(ch, 'sunglasses'); await backToCar(side);
    if (wasSuit) { S.life.suit = true; rebuildChar(); }
  }, face);
}
// gap year: backpack on, off to the signpost, a plane flies over, photos and maps float up – then back on the road
async function animGapYear(k, label) {
  const sp = spot(k, FOOT.signpost), { B, face, side } = sp; const post = buildSignpost(); placeAt(post, sp);
  toast('🎒 ' + (label || 'Gap year') + ' – 12 months off', 2800);
  await withFocus(B, async () => {
    await popIn(post); const wasSuit = S.life.suit; if (wasSuit) { S.life.suit = false; rebuildChar(); }
    const ch = await exitCar(side); addProp(ch, 'backpack'); addProp(ch, 'strohhut');
    await walkTo(ch, frontOf(B, face, 1.3), 2.2); faceCamera(ch);
    const right = new THREE.Vector3(Math.cos(face), 0, -Math.sin(face));
    const plane = sprite('✈️', 1.4); scene.add(plane);
    const p0 = B.clone().addScaledVector(right, -9).add(new THREE.Vector3(0, 5.5, 0)), p1 = B.clone().addScaledVector(right, 9).add(new THREE.Vector3(0, 7, 0));
    tween(2.6, x => { plane.position.lerpVectors(p0, p1, x); if (x >= 1) scene.remove(plane); });
    floatSprites(ch.position, '📸', 2, .7); await cheer(ch, 1.3);
    floatSprites(ch.position, '🗺️', 2, .7); floatSprites(ch.position, '🌍', 1, .8); ch.userData.mode = 'wave'; await wait(1.2); ch.userData.mode = 'idle';
    removeProp(ch, 'strohhut'); removeProp(ch, 'backpack'); await backToCar(side);
    if (wasSuit) { S.life.suit = true; rebuildChar(); }
  }, face);
}
async function animHouse(k) {
  // the mortgage comes from UBS: a UBS branch pops up next to the plot, the avatar signs, then the house lands
  const hs = spot(k, { ...FOOT.house, farSide: true }); claim(hs); const { B, face, side } = hs;
  const bs = spot(k, FOOT.bank); const bank = buildBank(); bank.userData.base = .8; placeAt(bank, bs);
  toast('🏦 Off to UBS for the mortgage …', 2600);
  const mid = B.clone().lerp(bs.B, .5);
  await withFocus(mid, async () => {
    await popIn(bank, .55);
    const door = 1.0 * baseScale(bank);
    const ch = await exitCar(bs.side); await walkTo(ch, frontOf(bs.B, bs.face, door + .7)); await walkTo(ch, frontOf(bs.B, bs.face, door), 1.4);
    ch.visible = false; await wait(1.0);
    addProp(ch, 'diploma'); ch.visible = true; await walkTo(ch, frontOf(bs.B, bs.face, door + 1.4), 1.8); faceCamera(ch);
    toast('✅ UBS mortgage approved – a home of your own!', 3000); floatSprites(ch.position, '✅', 2, .8);
    const h = buildHouse('#f6efe4'); const s = hs.scale; h.userData.base = s; h.position.copy(B); h.rotation.y = face; h.scale.setScalar(s); scene.add(h); h.position.y = 26;
    await tween(1.1, x => { h.position.y = 26 * (1 - x * x); });
    burst(B, 'dust', 22); await tween(.35, x => { const q = 1 + Math.sin(x * Math.PI) * .18; h.scale.set(s / q, s * (q * .85 + .15 * (1 - Math.sin(x * Math.PI))), s / q); });
    h.scale.setScalar(s); removeProp(ch, 'diploma');
    await walkTo(ch, frontOf(B, face, 1.1 * s + 1.5)); faceCamera(ch);
    floatSprites(ch.position, '🔑', 3, .9); await cheer(ch, 1.6); await backToCar(side);
  }, null);
}
async function animChild(k) {
  const { side } = spot(k, { r: 1 }); toast('👶 Welcome, baby!');
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  await withFocus(wp, async () => {
    const ch = await exitCar(side); faceCamera(ch); floatSprites(ch.position, '❤️', 8, .7);
    addProp(ch, 'baby'); await wait(2.4); removeProp(ch, 'baby'); await backToCar(side);
    S.kids += 1; refreshKids();
  });
}
// a child turns 18: gets out of the back seat with a backpack and suitcase, waves goodbye and walks to an own little flat
async function animChildLeaves(k, label) {
  toast('👋 ' + (label || 'Your child moves out'), 2800);
  const home = Math.max(0, S.kids - S.kidsLeft);
  if (!home) { S.kidsLeft += 1; return; }
  const sp = spot(k, FOOT.flat), { B, face, side } = sp;
  const idx = S.kidsLeft; S.kidsLeft += 1; refreshKids();
  const kid = buildCharacter(kidCfg(idx)); kid.userData.base = .82; scene.add(kid); S.figs.add(kid);
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  const t = S.curve.getTangentAt(clampU(S.u));
  kid.position.copy(wp).addScaledVector(t, -.6).addScaledVector(side, .6); kid.scale.setScalar(.82);
  await withFocus(wp.clone().lerp(B, .5), async () => {
    await walkTo(kid, wp.clone().addScaledVector(t, -.8).addScaledVector(side, 1.8), 2.2);
    addProp(kid, 'backpack'); addProp(kid, 'suitcase'); faceCamera(kid);
    kid.userData.mode = 'wave'; floatSprites(kid.position, '👋', 2, .7); await wait(1.6); kid.userData.mode = 'idle';
    const flat = buildHouse('#cfe8ff', .7); flat.userData.base = .7; placeAt(flat, sp); await popIn(flat, .5);
    await walkTo(kid, frontOf(B, face, 1.1 * baseScale(flat) + .5), 2.0);
    floatSprites(kid.position, '🏠', 1, .8); faceCamera(kid); kid.userData.mode = 'wave'; await wait(1.0);
    await tween(.4, x => kid.scale.setScalar(Math.max(.01, .82 * (1 - x))));
    scene.remove(kid); S.figs.delete(kid);
  });
}
function setRetired() { Object.assign(S.life, { grey: true, cane: true, suit: false, retired: true }); }
// Retirement mid-game (final = false): rocking chair, sunset glow for a moment, then back into the car – the road goes on.
// Finale at the end of life (final = true): the sunset stays, the partner joins, confetti.
async function animRetirement(k, label = null, final = false) {
  const sp = spot(k, FOOT.chair), { B, face, side } = sp;
  toast(final ? '🌅 What a life – time to enjoy' : '🪑 ' + bang(label, 'Retired!'), final ? 4000 : 3000);
  const chair = buildChair(); placeAt(chair, sp);
  const sky0 = new THREE.Color('#d9efff'), sky1 = new THREE.Color('#ffb38a');
  const tint = x => { scene.fog.color.copy(sky0).lerp(sky1, x); if (!E.container) return;
    E.container.style.background = x < .01 ? '' : `linear-gradient(180deg, ${'#' + sky0.clone().lerp(new THREE.Color('#ff9a6b'), x).getHexString()} 0%, #ffe2c4 100%)`; };
  await withFocus(B, async () => {
    await popIn(chair);
    tween(final ? 3 : 1.6, x => tint(final ? x : x * .8));
    setRetired(); rebuildChar(); refreshPartner();
    const ch = await exitCar(side); await walkTo(ch, chair.position.clone().add(new THREE.Vector3(Math.sin(face) * .2, 0, Math.cos(face) * .2)), 1.2);
    ch.rotation.y = face; ch.position.y = .15; removeProp(ch, 'cane'); ch.userData.mode = 'sit';
    const pt = S.car.userData.partner;
    if (final && pt) {   // the partner gets out and stands next to the chair
      S.car.remove(pt); scene.add(pt); pt.scale.setScalar(1); pt.rotation.set(0, 0, 0); pt.userData.parts.legL.visible = pt.userData.parts.legR.visible = true;
      unseat(pt); pt.userData.mode = 'idle'; S.figs.add(pt);
      const wp = new THREE.Vector3(); S.car.getWorldPosition(wp); pt.position.copy(wp).addScaledVector(side, .6);
      const right = new THREE.Vector3(Math.cos(face), 0, -Math.sin(face));
      walkTo(pt, B.clone().addScaledVector(right, 1.15), 1.4).then(() => { pt.rotation.y = face; });
    }
    await tween(final ? 5 : 3.2, x => { const r = Math.sin(x * Math.PI * (final ? 6 : 4)) * .12; chair.rotation.x = r; ch.rotation.x = r; });
    floatSprites(ch.position, final ? '🌅' : '☕', 2, .8);
    if (final) { burst(B, 'confetti', 60); return; }
    await wait(.5); chair.rotation.x = 0; ch.rotation.x = 0; ch.position.y = 0; ch.userData.mode = 'idle'; addProp(ch, 'cane');
    tween(1.6, x => tint((1 - x) * .8));
    await backToCar(side);
  }, face);
}
async function animWedding(k) {
  const sp = spot(k, { ...FOOT.chapel, farSide: true }), { B, face, side } = sp; const chapel = buildChapel(); placeAt(chapel, sp); toast('💍 Wedding day!', 3200);
  const fwd = new THREE.Vector3(Math.sin(face), 0, Math.cos(face)), right = new THREE.Vector3(Math.cos(face), 0, -Math.sin(face));
  const sc = sp.scale || 1;
  const at = (d, r = 0) => B.clone().addScaledVector(fwd, d * sc).addScaledVector(right, r * sc);
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
  // fixed, non-overlapping stand spots: guests in three rows on both sides of the aisle (>= 1 unit apart),
  // the couple walks in the aisle on two lanes (avatar right, partner left)
  const GUEST_AT = i => [1.5 + Math.floor(i / 2) * 1.0, (i % 2 ? 1 : -1) * (1.85 + Math.floor(i / 2) * .15)];
  const LANE = .5;
  const pcfg = partnerCfg(S.cfg);
  const role = c => (c.gender === 'frau' ? 'dress' : 'suit');
  const dressUp = (ch, r) => { addProp(ch, r === 'dress' ? 'veil' : 'tophat'); if (r === 'dress') addProp(ch, 'bouquet'); };
  await withFocus(at(2.2), async () => {
    await popIn(chapel, .7);
    const guests = GUESTS.map((cfg, i) => {
      const [d, r] = GUEST_AT(i), sgn = Math.sign(r), g = buildCharacter({ ...DEFAULT_CFG, ...cfg });
      g.position.copy(at(d, r));
      g.rotation.y = Math.atan2(-right.x * sgn, -right.z * sgn) + sgn * .35;   // towards the aisle, slightly to the front
      g.scale.setScalar(.85); scene.add(g); S.figs.add(g); return g;
    });
    // guests and the partner are in S.figs: updateWorld animates them every frame, walkTo walks around them
    await Promise.all(guests.map((g, i) => wait(i * .08).then(() => tween(.45, x => g.scale.setScalar(Math.max(.01, .85 * easeOutBack(x)))))));
    ring(3);
    // the avatar gets out and changes into the wedding outfit
    const ch = await exitCar(side); ch.visible = false; burst(ch.position, 'dust', 10); await wait(.35);
    const myRole = role(S.cfg); S.life.wedding = myRole; rebuildChar(); S.ch.visible = true; dressUp(S.ch, myRole);
    // the partner steps out of the chapel door
    const partner = buildCharacter(pcfg, { wedding: role(pcfg) }); dressUp(partner, role(pcfg));
    partner.position.copy(at(1.0, -LANE)); partner.rotation.y = face; scene.add(partner); S.figs.add(partner); await popIn(partner, .45);
    // both walk to the flower arch, meet in the middle and face the guests
    await Promise.all([walkTo(S.ch, at(4.2, LANE), 2.2), walkTo(partner, at(1.9, -LANE), 1.6)]);
    await walkTo(S.ch, at(2.0, LANE), 1.4);
    S.ch.rotation.y = partner.rotation.y = face;
    const rings = sprite('💍', 1.4); rings.position.copy(at(2.0)).add(new THREE.Vector3(0, 3.2, 0)); scene.add(rings);
    await tween(.45, x => rings.scale.setScalar(1.4 * easeOutBack(x)));
    floatSprites(at(2.0), '❤️', 10, .7); burst(at(2.4), 'confetti', 90); ring(4);
    guests.forEach(g => { g.userData.mode = 'cheer'; }); S.ch.userData.mode = partner.userData.mode = 'cheer';
    await wait(2.4);
    guests.forEach(g => { g.userData.mode = 'idle'; }); S.ch.userData.mode = partner.userData.mode = 'idle';
    await tween(.4, x => { rings.material.opacity = 1 - x; }); scene.remove(rings);
    // down the aisle together and side by side to the car (the partner aims for the passenger side, a bit ahead)
    await Promise.all([walkTo(S.ch, at(4.3, LANE), 2), walkTo(partner, at(4.3, -LANE), 2)]);
    for (const pr of ['veil', 'tophat', 'bouquet']) removeProp(S.ch, pr);
    S.life.wedding = null; rebuildChar();
    const wp = new THREE.Vector3(); S.car.getWorldPosition(wp); const t = S.curve.getTangentAt(clampU(S.u));
    const sgn = t.dot(right) > 0 ? -1 : 1;   // the partner stays on their own lane's side, so the two paths never cross
    await Promise.all([backToCar(side), walkTo(partner, wp.clone().addScaledVector(side, 1.6).addScaledVector(t, 1.2 * sgn), 2.2)]);
    scene.remove(partner); S.figs.delete(partner);
    S.life.partner = true; refreshPartner(); floatSprites(S.car.position, '💕', 4, .6);
    await Promise.all(guests.map(g => tween(.35, x => g.scale.setScalar(Math.max(.01, .85 * (1 - x)))).then(() => { scene.remove(g); S.figs.delete(g); })));
  }, face, { dist: 11, height: 10, yaw: .5 });
}
// skipped years: a short version of each event – the building pops up at its station, a banner, the new state
const EMO = { graduation: '🎓', job: '💼', startup: '🚀', vacation: '🏝️', gapyear: '🎒', house: '🏡', child: '👶', child_leaves: '👋',
              wedding: '💍', retirement: '🪑' };
const LABEL = { graduation: 'Graduation!', job: 'New job!', startup: 'Startup founded!', vacation: 'Time off!', gapyear: 'Gap year',
                house: 'A home of your own – UBS mortgage', child: 'Welcome, baby!', child_leaves: 'Your child moves out',
                wedding: 'Wedding day!', retirement: 'Retired!' };
async function playBrief(a, k) {
  const em = a.emoji || EMO[a.type] || '🃏';
  toast(`${em} ${a.label || LABEL[a.type] || 'Twist of fate'}`, 1500);
  const mk = { graduation: () => [buildUni(), FOOT.uni], job: () => [buildOffice(), FOOT.office], startup: () => [buildOffice(), FOOT.office],
               vacation: () => [buildBeach(), FOOT.beach], gapyear: () => [buildSignpost(), FOOT.signpost], house: () => [buildHouse('#f6efe4'), FOOT.house],
               wedding: () => [buildChapel(), FOOT.chapel], retirement: () => [buildChair(), FOOT.chair] }[a.type];
  if (mk) { const [obj, f] = mk(); const sp = spot(k, f); placeAt(obj, sp); popIn(obj, .4); }
  if (a.type === 'wedding') { S.life.partner = true; refreshPartner(); }
  else if (a.type === 'child') { S.kids += 1; refreshKids(); }
  else if (a.type === 'child_leaves') { S.kidsLeft += 1; refreshKids(); }
  else if (a.type === 'retirement') { setRetired(); rebuildChar(); refreshPartner(); }
  else if (a.type === 'job' || a.type === 'startup') { if (!S.life.suit) { S.life.suit = true; rebuildChar(); } }
  else if (a.type === 'crash') tween(.5, x => { S.car.position.y = Math.sin(x * Math.PI * 4) * .12; });
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp);
  const s = sprite(em, 1.6); s.position.copy(wp).add(new THREE.Vector3(0, 2.4, 0)); scene.add(s);
  await tween(.3, x => s.scale.setScalar(1.6 * easeOutBack(x)));
  await wait(.45);
  await tween(.35, x => { s.material.opacity = 1 - x; s.position.y += .04; }); scene.remove(s);
  S.car.position.y = 0;
}

/* ---------- intro: fly over the island, how to play, countdown (skippable) */
function introStartCam() { return { pos: new THREE.Vector3(-48, 66, 60), look: new THREE.Vector3(0, 0, 0) }; }
async function playIntro() {
  const gen = S.gen, ctl = S.introCtl = { skip: false };
  const ev = (step, data = {}) => { if (E.onIntro && gen === S.gen) E.onIntro(step, data); };
  const cam = S.cam = S.cam || introStartCam();
  ev('title', { from: S.startAge, to: S.labels ? S.labels[S.K] : S.startAge + S.K * S.step, stations: S.K, step: S.step });
  await tween(4.6, x => { const a = -.65 + ease(x) * 1.1, r = 72 - x * 10;
    cam.pos.set(Math.sin(a) * r, 64 - x * 12, Math.cos(a) * r); cam.look.set(0, 0, 0); }, ctl);
  // course preview: glide along the road from the last station (retirement) back to the start
  ev('howto');
  const p0 = cam.pos.clone(), l0 = cam.look.clone();
  await tween(Math.min(10, 6 + S.K * .05), x => {
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
  await tween(2.4, x => { const a = -.4 + x * .5; cam.pos.set(Math.sin(a) * 68, 56 - x * 9, Math.cos(a) * 68); cam.look.set(0, 0, 0); }, ctl);
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
  await tween(1.8, x => { cam.pos.copy(p0).lerp(new THREE.Vector3(12, 54, 64), ease(x)); cam.look.copy(l0).lerp(new THREE.Vector3(0, 0, 0), ease(x)); }, ctl);
  S.introCtl = null;
  ev('end');
}

async function animFate(a) {
  const wp = new THREE.Vector3(); S.car.getWorldPosition(wp); toast(`${a.emoji || '🃏'} ${a.label || 'Twist of fate'}`);
  const s = sprite(a.emoji || '🃏', 2.2); s.position.copy(wp).add(new THREE.Vector3(0, 2.6, 0)); scene.add(s);
  await tween(.4, x => s.scale.setScalar(2.2 * easeOutBack(x)));
  if (a.type === 'crash') { await tween(.6, x => { S.car.position.y = Math.sin(x * Math.PI * 4) * .15; }); S.car.position.y = 0; }
  await wait(1.1); await tween(.5, x => { s.material.opacity = 1 - x; s.position.y += .03; }); scene.remove(s);
}
async function playAnim(a, k) {
  switch (a.type) {
    case 'graduation': return animGraduation(k, a.label);
    case 'job': return animJob(k, a.label);
    case 'startup': return animJob(k, a.label || 'Startup founded!');
    case 'vacation': return animVacation(k);
    case 'gapyear': return animGapYear(k, a.label);
    case 'house': return animHouse(k);
    case 'child': return animChild(k);
    case 'child_leaves': return animChildLeaves(k, a.label);
    case 'wedding': return animWedding(k);
    case 'retirement': return animRetirement(k, a.label, false);   // mid-game: the road goes on afterwards
    default: return animFate(a);
  }
}
function updateWorld(dt) {
  animateCharacter(S.ch, dt); (S.car.userData.kids || []).forEach(c => animateCharacter(c, dt));
  if (S.car.userData.partner) animateCharacter(S.car.userData.partner, dt);
  S.figs.forEach(f => { if (f !== S.car.userData.partner && f.parent === scene) animateCharacter(f, dt); });   // guests, kid moving out …
  const tt = performance.now() / 1000;
  S.deco.boats.forEach(b => { b.position.y = -.75 + Math.sin(tt * 1.3 + b.userData.ph) * .08; b.rotation.z = Math.sin(tt + b.userData.ph) * .05; });
  S.deco.clouds.forEach(c => { c.position.x += c.userData.v * dt; if (c.position.x > 115) c.position.x = -115; });
  let look;
  if (S.cam) { camera.position.copy(S.cam.pos); camera.lookAt(S.cam.look); look = S.cam.look; }
  else {
    const target = S.focus ? S.focus.clone() : S.car.position.clone();
    const off = !S.focus ? new THREE.Vector3(0, 17, 19)
      : S.focusFace === null ? new THREE.Vector3(0, 7.5, 11)
      : S.focusCam ? new THREE.Vector3(Math.sin(S.focusFace + S.focusCam.yaw) * S.focusCam.dist, S.focusCam.height,
                                       Math.cos(S.focusFace + S.focusCam.yaw) * S.focusCam.dist)
      : new THREE.Vector3(Math.sin(S.focusFace) * 10.5, 7, Math.cos(S.focusFace) * 10.5);
    const want = target.clone().add(off); const k = 1 - Math.exp(-dt * 2.2);
    camera.position.lerp(want, k); S.look = (S.look || target.clone()).lerp(target, k); camera.lookAt(S.look.x, S.look.y + 1, S.look.z);
    look = S.look;
  }
  // the sun (and its shadow box) follows what the camera looks at – the island is too big for one fixed shadow map
  if (S.sun) { S.sun.position.set(look.x + 12, 22, look.z + 10); S.sun.target.position.set(look.x, 0, look.z); }
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

export { initEngine, showCreator, setCreator, showPodium, waveNow, showWorld, isBusy, setToastHandler, setBusyHandler, setIntroHandler, setRideHandler,
         skipIntro };
