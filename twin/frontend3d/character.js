// Character + car models. API (keep stable): buildCharacter(cfg, life), addProp(ch, name), removeProp(ch, name),
// animateCharacter(ch, dt), buildCar(color), seat(ch, car, x?, scale?), buildPodium().
// Hair is built from sculpted pieces (teardrop locks, puffs, shells) that are merged into one mesh per colour layer
// and cached per (style, hat fit), so rebuilding a character on every creator click stays cheap.
import { THREE, SKINS, HAIRC, COLORS, DEFAULT_CFG, M, add, shade, lerp } from './core.js';

/* =================================================================== shared geometry */
const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const GEO = {
  sph: new THREE.SphereGeometry(1, 18, 12),
  torus: new THREE.TorusGeometry(1, .38, 8, 22),
  drop: (() => { // teardrop: round end at y = -1, soft tip at y = +1, max radius 1
    const pts = []; let mx = 0; const n = 14;
    for (let i = 0; i <= n; i++) {
      const th = Math.PI * (1 - i / n), x = Math.max(0, Math.sin(th) * Math.pow(Math.sin(th / 2), .75));
      mx = Math.max(mx, x); pts.push([x, Math.cos(th)]);
    }
    return new THREE.LatheGeometry(pts.map(p => new THREE.Vector2(p[0] / mx, p[1])), 14);
  })(),
};
const capCache = new Map();
const capGeo = T => { const k = Math.round(T * 100) / 100; if (!capCache.has(k)) capCache.set(k, new THREE.SphereGeometry(1, 30, 14, 0, Math.PI * 2, 0, k)); return capCache.get(k); };

function mergeParts(parts) { // [{geo, m: Matrix4}] -> one indexed BufferGeometry (position, normal, uv)
  let nv = 0, ni = 0;
  for (const p of parts) { nv += p.geo.attributes.position.count; ni += p.geo.index.count; }
  const pos = new Float32Array(nv * 3), nor = new Float32Array(nv * 3), uv = new Float32Array(nv * 2);
  const idx = nv > 65535 ? new Uint32Array(ni) : new Uint16Array(ni);
  const v = V3(), nm = new THREE.Matrix3(); let ov = 0, oi = 0;
  for (const { geo, m } of parts) {
    const P = geo.attributes.position, N = geo.attributes.normal, U = geo.attributes.uv, I = geo.index; nm.getNormalMatrix(m);
    for (let i = 0; i < P.count; i++) {
      v.fromBufferAttribute(P, i).applyMatrix4(m); pos.set([v.x, v.y, v.z], (ov + i) * 3);
      v.fromBufferAttribute(N, i).applyMatrix3(nm).normalize(); nor.set([v.x, v.y, v.z], (ov + i) * 3);
      uv[(ov + i) * 2] = U.getX(i); uv[(ov + i) * 2 + 1] = U.getY(i);
    }
    for (let i = 0; i < I.count; i++) idx[oi + i] = I.getX(i) + ov;
    ov += P.count; oi += I.count;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2)); g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeBoundingSphere(); return g;
}

/* =================================================================== hair */
// Head space: head group origin = head centre, skull = sphere r .55 scaled (1, .95, .95); eyes at y .03 / z .48,
// brows at y .19, ears at x ±.53. Fringe locks stay above y ≈ .22 so the eyes (and brows) remain visible.
const HR = [.55, .5225, .5225];
function HS(yaw, el, out = 0) { // point on the skull + outward normal n + upward meridian tangent t
  const n = V3(Math.cos(el) * Math.sin(yaw), Math.sin(el), Math.cos(el) * Math.cos(yaw));
  const t = V3(-Math.sin(el) * Math.sin(yaw), Math.cos(el), -Math.sin(el) * Math.cos(yaw));
  return { p: V3((HR[0] + out) * n.x, (HR[1] + out) * n.y, (HR[2] + out) * n.z), n, t };
}
function basis(p, Y, Z, s, tw = 0) { // local Y = long axis (drop tip), local Z = outward; s = [width, half-length, thickness]
  Z = Z.clone().normalize(); Y = Y.clone().addScaledVector(Z, -Y.dot(Z)).normalize();
  let X = V3().crossVectors(Y, Z);
  if (tw) { Y = Y.clone().multiplyScalar(Math.cos(tw)).addScaledVector(X, Math.sin(tw)); X = V3().crossVectors(Y, Z); }
  const m = new THREE.Matrix4().makeBasis(X, Y, Z); m.scale(V3(...s)); m.setPosition(p); return m;
}
const raw = (p, s, r = [0, 0, 0]) => new THREE.Matrix4().compose(V3(...p), new THREE.Quaternion().setFromEuler(new THREE.Euler(...r)), V3(...s));

// hat fit: crown = the hat covers the top of the head, peak = something sits on the very top (party hat),
// fringe: full | low (squashed under a brim) | none (hidden under cap / beanie)
const HEAD_COVER = ['gradcap', 'strohhut', 'tophat', 'veil'];
function hatFit(hat) {
  return {
    crown: ['cap', 'beanie', 'strohhut', 'gradcap', 'tophat'].includes(hat), peak: hat === 'partyhut',
    fringe: hat === 'cap' || hat === 'beanie' ? 'none' : ['strohhut', 'gradcap', 'tophat'].includes(hat) ? 'low' : 'full',
  };
}

function hairPieces(style, fit, grey) {
  const out = [], pony = []; let anchor = null;
  const put = (L, geo, m, tag) => out.push({ L, geo, m, tag });
  const surf = (L, geo, yaw, el, o, s, opt = {}) => { const h = HS(yaw, el, o);
    let Y = opt.down ? h.t.clone().negate() : h.t.clone(); if (opt.lean) Y.addScaledVector(h.n, opt.lean);
    put(L, geo, basis(h.p, Y, h.n, s, opt.tw || 0), opt.tag); };
  const hang = (L, yaw, y, rad, s, opt = {}) => { const Z = V3(Math.sin(yaw), 0, Math.cos(yaw));
    put(L, GEO.drop, basis(V3(rad * Z.x, y, rad * Z.z), V3(0, -1, 0).addScaledVector(Z, opt.tilt || 0), Z, s, opt.tw || 0), opt.tag); };
  const ball = (L, p, s, tag) => put(L, GEO.sph, raw(p, s), tag);
  const shell = (L, R, frontY, backY, cy = .03, cz = -.03) => {
    const f = Math.acos(Math.max(-1, Math.min(1, (frontY - cy) / R))), b = Math.acos(Math.max(-1, Math.min(1, (backY - cy) / R)));
    const T = (f + b) / 2, a = (b - f) / 2; put(L, capGeo(T), raw([0, cy, cz], [R, R, R], [-a, 0, 0]));
  };
  const lock = (yaw, el, s, tw, L = 'base') => surf(L, GEO.drop, yaw, el, .055, s, { down: true, tw, tag: 'fringe' });
  const wantFringe = fit.fringe !== 'none';
  const shine = (yaw = -.3, el = 1.0, s = [.17, .08, .03], o = .08) => { if (!fit.crown) surf('light', GEO.sph, yaw, el, o, s); };
  const wisp = s => surf('base', GEO.drop, s * 1.38, .22, .03, [.08, .12, .05], { down: true, tw: -s * .2 });

  switch (style) {
    case 'kurz': {
      shell('base', fit.crown ? .565 : .6, .30, -.22);
      ball('dark', [0, -.12, -.36], [.4, .26, .22]);
      for (const s of [-1, 1]) surf('base', GEO.drop, s * 1.42, .3, .035, [.1, .13, .06], { down: true, tw: -s * .3 });
      for (const y of [Math.PI - .55, Math.PI, Math.PI + .55]) surf('dark', GEO.drop, y, .02, .035, [.17, .14, .07], { down: true });
      if (wantFringe) [[-.52, .63], [-.18, .71], [.18, .71], [.52, .63]].forEach(([y, e]) => lock(y, e, [.18, .15, .11], .38));
      if (!fit.crown) {
        surf('base', GEO.drop, 0, 1.22, .07, [.14, .17, .1], { lean: .5 });
        for (const s of [-1, 1]) surf('base', GEO.drop, s * .6, 1.08, .07, [.13, .15, .09], { lean: .5, tw: s * .3 });
        surf('dark', GEO.drop, Math.PI - .25, 1.15, .07, [.12, .14, .08], { lean: .6 });
        shine();
      }
      break;
    }
    case 'lang': {
      shell('base', fit.crown ? .565 : .61, .30, -.25);
      ball('dark', [0, -.12, -.2], [.56, .5, .42]);
      for (const s of [-1, 1]) ball('dark', [s * .47, -.22, -.1], [.15, .36, .3]);
      if (wantFringe) { [-.42, -.05, .33].forEach(y => lock(y, .7, [.21, .16, .12], .42)); lock(.8, .5, [.17, .22, .1], .2); }
      for (const s of [-1, 1]) {
        hang('base', s * 1.1, -.04, .53, [.17, .44, .13], { tilt: .16, tw: s * .06 });
        hang('base', s * 1.48, -.06, .55, [.21, .5, .14], { tilt: .2 });
        hang('base', s * 2.0, -.1, .5, [.25, .52, .15], { tilt: .22 });
        hang('dark', Math.PI + s * .5, -.16, .44, [.27, .52, .15], { tilt: .2 });
      }
      hang('dark', Math.PI, -.17, .44, [.28, .52, .15], { tilt: .2 });
      shine(-.3, 1.0, [.2, .09, .03]);
      break;
    }
    case 'dutt': {
      shell('base', fit.crown ? .565 : .59, .31, -.18);
      ball('dark', [0, -.08, -.34], [.38, .22, .2]);
      if (wantFringe) [[-.35, .5], [.05, .4], [.42, -.3]].forEach(([y, tw]) => lock(y, .73, [.19, .15, .1], tw));
      for (const s of [-1, 1]) wisp(s);
      const high = !fit.crown && !fit.peak;
      const c = high ? V3(0, .6, -.22) : V3(0, .14, -.64), ax = c.clone().normalize();
      put('base', GEO.sph, raw([c.x, c.y, c.z], high ? [.28, .26, .28] : [.24, .23, .22]));
      put('dark', GEO.torus, basis(c.clone().addScaledVector(ax, -.02), V3(1, 0, 0), ax, high ? [.25, .25, .3] : [.21, .21, .26], .6));
      put('tie', GEO.torus, basis(c.clone().addScaledVector(ax, high ? -.17 : -.14), V3(1, 0, 0), ax, high ? [.17, .17, .2] : [.14, .14, .18]));
      put('light', GEO.sph, raw([c.x - .07, c.y + .12, c.z + (high ? .08 : .1)], [.08, .05, .05]));
      break;
    }
    case 'locken': {
      shell('dark', fit.crown ? .565 : .6, .32, -.25);
      const curl = (yaw, el, r, L = 'base', tag) => { const h = HS(yaw, el, .05); put(L, GEO.sph, raw([h.p.x, h.p.y, h.p.z], [r, r, r]), tag); };
      [1.15, 1.6, 2.05, 2.5, 2.95].forEach((y, i) => { for (const s of [-1, 1]) curl(s * y, .1, i % 2 ? .15 : .17); });
      [2.3, 2.85].forEach((y, i) => { for (const s of [-1, 1]) curl(s * y, -.28, i ? .15 : .16, 'dark'); });
      curl(Math.PI, -.3, .16, 'dark');
      if (!fit.crown) {
        [.95, 1.5, 2.1, 2.7].forEach((y, i) => { for (const s of [-1, 1]) curl(s * y, .55, i % 2 ? .17 : .16); });
        [.5, 1.6, 2.7].forEach(y => { for (const s of [-1, 1]) curl(s * y, 1.02, .17); });
        if (!fit.peak) curl(0, 1.5, .18);
        for (const [y, e] of [[-.5, 1.12], [.6, .66], [-1.5, .62]]) surf('light', GEO.sph, y, e, .19, [.05, .04, .02]);
      }
      if (wantFringe) [-.55, -.19, .19, .55].forEach((y, i) => curl(y, .74 - (i % 3 ? 0 : .04), .13, 'base', 'fringe'));
      break;
    }
    case 'pferdeschwanz': {
      shell('base', fit.crown ? .565 : .59, .31, -.12);
      ball('dark', [0, -.02, -.38], [.36, .22, .18]);
      if (wantFringe) [-.4, -.05, .3].forEach(y => lock(y, .72, [.19, .15, .11], .45));
      for (const s of [-1, 1]) wisp(s);
      shine(-.28, 1.02, [.05, .15, .02], .07); shine(.2, 1.08, [.04, .12, .02], .07);
      anchor = fit.crown ? V3(0, .1, -.57) : V3(0, .3, -.53);
      const back = V3(0, .3, -1).normalize();
      put('base', GEO.sph, raw([anchor.x, anchor.y, anchor.z - .03], [.14, .14, .12]));
      put('tie', GEO.torus, basis(anchor.clone().addScaledVector(back, .07), V3(1, 0, 0), back, [.11, .11, .14]));
      const P = (L, geo, p, Y, s) => pony.push({ L, geo, m: basis(V3(...p), V3(...Y), V3(0, 0, -1), s) });
      P('base', GEO.drop, [0, -.14, -.2], [0, -1, -.55], [.17, .26, .15]);
      P('dark', GEO.sph, [0, -.25, -.22], [0, 1, 0], [.14, .2, .13]);
      P('base', GEO.drop, [0, -.44, -.3], [0, -1, -.1], [.15, .24, .13]);
      P('base', GEO.drop, [0, -.66, -.27], [0, -1, .3], [.09, .14, .08]);
      break;
    }
    case 'afro': {
      if (fit.crown) shell('dark', .565, .3, -.2);
      else ball('dark', [0, .16, -.14], [.6, .56, .56]);
      const N = 30, ga = Math.PI * (3 - Math.sqrt(5)), c = fit.crown ? [0, .06, -.1] : [0, .2, -.12], k = fit.crown ? [.6, .4, .56] : [.56, .52, .52];
      for (let i = 0; i < N; i++) {
        const y = 1 - (i + .5) / N * 2, r = Math.sqrt(1 - y * y), d = V3(Math.cos(i * ga) * r, y, Math.sin(i * ga) * r);
        if ((d.z > .3 && d.y < .45) || d.y < -.55) continue;
        if (fit.crown && d.y > .1) continue;
        if (fit.peak && d.y > .75) continue;
        const rr = fit.crown ? .24 : (i % 2 ? .28 : .31);
        put(d.y < -.05 ? 'dark' : 'base', GEO.sph, raw([c[0] + d.x * k[0], c[1] + d.y * k[1], c[2] + d.z * k[2]], [rr, rr, rr]));
      }
      if (wantFringe) [-.6, -.3, 0, .3, .6].forEach((y, i) => { const h = HS(y, .8 - (i % 2) * .04, .04); put('base', GEO.sph, raw([h.p.x, h.p.y, h.p.z], [.15, .14, .14]), 'fringe'); });
      if (!fit.crown) for (const [y, e] of [[-.4, .95], [.5, 1.2]]) surf('light', GEO.sph, y, e, .3, [.07, .05, .02]);
      break;
    }
    case 'iro': {
      shell('dark', .565, .3, -.2);
      if (!fit.crown) {
        const ph = [1.0, 1.24, 1.48, 1.72, 1.96, 2.2, 2.44], len = [.16, .22, .25, .25, .23, .2, .15];
        ph.forEach((f, i) => {
          if (fit.peak && f > 1.15 && f < 2.0) return;
          const n = V3(0, Math.sin(f), Math.cos(f)), bk = V3(0, Math.cos(f), -Math.sin(f));
          const base = V3(0, HR[1] * n.y, HR[2] * n.z);
          put('base', GEO.drop, basis(base.clone().addScaledVector(n, len[i] * .7), n.clone().addScaledVector(bk, .7), V3(1, 0, 0), [.17, len[i], .09]));
          put('base', GEO.sph, raw([0, base.y + n.y * .04, base.z + n.z * .04], [.075, .1, .1]));
        });
        surf('light', GEO.sph, 0, 1.25, .09, [.05, .14, .03]);
      }
      break;
    }
    case 'glatze': default: {
      if (!fit.crown) {
        surf('gloss', GEO.sph, -.35, .95, .004, [.14, .08, .02]);
        surf('gloss', GEO.sph, -.12, 1.12, .004, [.045, .03, .015]);
      }
      if (grey) for (const y of [1.5, 2.05, 2.6, -1.5, -2.05, -2.6, Math.PI])
        surf('base', GEO.drop, y, .06, .045, [.15, .1, .07], { down: true, tw: y > 0 ? .3 : -.3 });
      break;
    }
  }
  if (fit.fringe === 'low') { // squash the fringe under a brim (brim plane at y ≈ .36)
    const sq = new THREE.Matrix4().makeTranslation(0, .225, .02).multiply(new THREE.Matrix4().makeScale(1, .55, 1)).multiply(new THREE.Matrix4().makeTranslation(0, -.225, 0));
    for (const p of out) if (p.tag === 'fringe') p.m.premultiply(sq);
  }
  return { out, pony, anchor };
}

const hairCache = new Map();
function hairModel(style, hat, grey) {
  const fit = hatFit(hat);
  const key = [style, +fit.crown, +fit.peak, fit.fringe, style === 'glatze' && grey ? 1 : 0].join('|');
  if (hairCache.has(key)) return hairCache.get(key);
  const { out, pony, anchor } = hairPieces(style, fit, grey);
  const byLayer = {}; for (const p of out) (byLayer[p.L] = byLayer[p.L] || []).push(p);
  const layers = {}; for (const L in byLayer) layers[L] = mergeParts(byLayer[L]);
  const ponyLayers = {}; const pl = {}; for (const p of pony) (pl[p.L] = pl[p.L] || []).push(p);
  for (const L in pl) ponyLayers[L] = mergeParts(pl[L]);
  // measurements so hats can sit on the hair instead of inside it
  let topC = .5, topZ0 = .52, sideX = .5; const v = V3();
  for (const L in layers) { if (L === 'gloss') continue; const P = layers[L].attributes.position;
    for (let i = 0; i < P.count; i++) { v.fromBufferAttribute(P, i);
      if (v.x * v.x + v.z * v.z < .09) topC = Math.max(topC, v.y);
      if (Math.abs(v.z) < .12) topZ0 = Math.max(topZ0, v.y);
      if (Math.abs(v.y) < .2 && Math.abs(v.z) < .2) sideX = Math.max(sideX, Math.abs(v.x)); } }
  const model = { layers, ponyLayers, anchor, topC, topZ0, sideX };
  hairCache.set(key, model); return model;
}

function hairMats(cfg, life) {
  const c = life.grey ? '#d8d5cf' : (HAIRC[cfg.hairColor] || '#8a5a36');
  return { base: M(c, .5), dark: M(shade(c, -.06), .6), light: M(shade(c, .12), .3), tie: M(COLORS[cfg.color] || '#e34948', .4),
           gloss: M('#ffffff', .15, { transparent: true, opacity: .32, depthWrite: false }) };
}

function fitHair(ch) { // (re)builds the hair for the currently effective hat (worn hat or a head-covering prop)
  const u = ch.userData, P = u.parts, props = u.props;
  const hat = props.gradcap ? 'gradcap' : props.strohhut ? 'strohhut' : props.tophat ? 'tophat' : props.veil ? 'veil' : u.cfg.hat;
  if (u.hatG) u.hatG.visible = hat === u.cfg.hat;
  if (P.hair && u.hairHat === hat) return u.hairModel;
  if (P.hair) P.head.remove(P.hair);
  const model = hairModel(u.cfg.hair, hat, !!u.life.grey), mats = hairMats(u.cfg, u.life);
  const g = new THREE.Group(); g.name = 'hair';
  for (const L in model.layers) { const m = new THREE.Mesh(model.layers[L], mats[L]); m.castShadow = L !== 'gloss'; m.receiveShadow = L !== 'gloss'; g.add(m); }
  P.pony = null;
  if (model.anchor && Object.keys(model.ponyLayers).length) {
    const piv = new THREE.Group(); piv.position.copy(model.anchor); g.add(piv); P.pony = piv;
    for (const L in model.ponyLayers) { const m = new THREE.Mesh(model.ponyLayers[L], mats[L]); m.castShadow = m.receiveShadow = true; piv.add(m); }
  }
  P.head.add(g); P.hair = g; u.hairHat = hat; u.hairModel = model; return model;
}

function strawHat(grp) {
  add(grp, new THREE.CylinderGeometry(.42, .48, .32, 28), M('#e8c66a', .9), 0, .5, 0);
  add(grp, new THREE.CylinderGeometry(1.0, 1.0, .04, 40), M('#efd07a', .9), 0, .36, 0);
  add(grp, new THREE.TorusGeometry(.47, .045, 8, 28), M('#e34948'), 0, .42, 0).rotation.x = Math.PI / 2;
}

/* =================================================================== character */
function buildCharacter(cfg, life = {}) {
  cfg = { ...DEFAULT_CFG, ...cfg };
  const g = new THREE.Group(); const P = {}; g.userData = { parts: P, t: Math.random() * 10, mode: 'idle', props: {}, cfg, life };
  const skin = M(SKINS[cfg.skin] || SKINS.rosig, .75);
  // life.wedding: 'dress' (white wedding dress) | 'suit' (wedding suit) – worn only during the wedding scene
  const outfit = life.wedding === 'dress' ? 'kleid' : (life.suit || life.wedding === 'suit') ? 'anzug' : cfg.outfit;
  const main = life.wedding === 'dress' ? M('#fbfaf6', .45) : M(COLORS[cfg.color] || COLORS.blau, .6);
  const navy = M('#1f2740', .5), white = M('#f7f5f0', .6);
  // women: A-line dress like the restroom pictogram (trapezoid from the shoulders down, legs below).
  // The chosen outfit only adds details to the dress (hood, collar, stripes); a job means a navy dress.
  const wc = cfg.gender === 'frau';
  if (wc) return buildDressed(g, P, cfg, life, outfit, skin, main, navy, white);
  const pantsMat = outfit === 'anzug' ? navy : outfit === 'kleid' ? skin : outfit === 'sport' ? M('#e9e6df') : M('#3b4256');
  const topMat = outfit === 'anzug' ? navy : outfit === 'hemd' ? white : main;
  const bare = ['tshirt', 'kleid', 'sport'].includes(outfit);
  const armMat = bare ? skin : topMat;
  const r = cfg.gender === 'mann' ? .42 : .39;

  const body = new THREE.Group(); g.add(body); P.body = body;
  for (const s of [-1, 1]) {
    const hip = new THREE.Group(); hip.position.set(s * .17, .72, 0); body.add(hip);
    add(hip, new THREE.CapsuleGeometry(.13, .36, 6, 12), pantsMat, 0, -.3, 0);
    add(hip, new THREE.SphereGeometry(.16, 16, 12), M(outfit === 'sport' ? '#ffffff' : '#2b2b30', .5), 0, -.62, .07, 1, .6, 1.45);
    P[s < 0 ? 'legL' : 'legR'] = hip;
  }
  if (outfit === 'kleid') add(body, new THREE.CylinderGeometry(.33, .62, .62, 28), main, 0, .82, 0);
  if (outfit === 'sport') add(body, new THREE.CylinderGeometry(r * .95, r, .28, 24), M('#e9e6df'), 0, .72, 0);
  add(body, new THREE.CapsuleGeometry(r, .32, 8, 18), topMat, 0, 1.08, 0, 1, 1, .82);
  const front = r * .82;
  if (outfit === 'hoodie') {
    const hood = add(body, new THREE.TorusGeometry(.27, .09, 10, 24), M(shade(COLORS[cfg.color] || '#2a78d6', -.06)), 0, 1.42, -.12);
    hood.rotation.x = Math.PI / 2.3;
    add(body, new THREE.BoxGeometry(.42, .16, .06), M(shade(COLORS[cfg.color] || '#2a78d6', -.08)), 0, .94, front - .02);
    for (const s of [-1, 1]) add(body, new THREE.CylinderGeometry(.015, .015, .22), white, s * .08, 1.28, front + .02);
  }
  if (outfit === 'hemd' || outfit === 'anzug') {
    const v = add(body, new THREE.ConeGeometry(.15, .36, 3), white, 0, 1.3, front - .01); v.rotation.x = Math.PI;
    if (life.wedding === 'suit') { // bow tie + boutonniere
      for (const s of [-1, 1]) add(body, new THREE.ConeGeometry(.07, .12, 4), M('#1d1d24', .4), s * .06, 1.36, front + .03).rotation.z = s * Math.PI / 2;
      add(body, new THREE.SphereGeometry(.05, 10, 8), M('#ff8fb1', .6), r * .55, 1.3, front - .02);
    } else add(body, new THREE.BoxGeometry(.075, .32, .03), M(outfit === 'anzug' ? '#c0392b' : (COLORS[cfg.color] || '#24365c')), 0, 1.12, front + .03);
  }
  if (outfit === 'sport') for (const s of [-1, 1]) add(body, new THREE.BoxGeometry(.05, .55, .02), white, s * .2, 1.1, front);
  if (outfit === 'tshirt') add(body, new THREE.TorusGeometry(.17, .03, 8, 20), M(shade(COLORS[cfg.color] || '#2a78d6', -.12)), 0, 1.38, .1).rotation.x = Math.PI / 2.2;

  for (const s of [-1, 1]) {
    const sh = new THREE.Group(); sh.position.set(s * (r + .1), 1.32, 0); body.add(sh);
    add(sh, new THREE.CapsuleGeometry(.11, .34, 6, 12), armMat, 0, -.25, 0);
    if (bare && outfit !== 'kleid') add(sh, new THREE.SphereGeometry(.145, 12, 10), topMat, 0, -.03, 0, 1, .85, 1);
    const hand = new THREE.Group(); hand.position.set(0, -.52, 0); sh.add(hand);
    add(hand, new THREE.SphereGeometry(.12, 12, 10), skin);
    sh.rotation.z = s * .12;
    P[s < 0 ? 'armL' : 'armR'] = sh; P[s < 0 ? 'handL' : 'handR'] = hand;
  }
  return finishCharacter(g, P, body, cfg, life, skin);
}

// the A-line dress body (women) – same skeleton (legL/legR, armL/armR, handL/handR, body) as the default body
function buildDressed(g, P, cfg, life, outfit, skin, main, navy, white) {
  const wedding = life.wedding === 'dress';
  const dressMat = wedding ? main : outfit === 'anzug' ? navy : main;
  const accent = M(shade(wedding ? '#f3efe4' : outfit === 'anzug' ? '#1f2740' : (COLORS[cfg.color] || '#2a78d6'), -.1), .6);
  const sleeves = wedding ? false : ['hoodie', 'hemd', 'anzug'].includes(outfit);
  const body = new THREE.Group(); g.add(body); P.body = body; g.userData.restZ = .3;   // arms rest outside the dress
  for (const s of [-1, 1]) {
    const hip = new THREE.Group(); hip.position.set(s * .15, .72, 0); body.add(hip);
    add(hip, new THREE.CapsuleGeometry(.11, .38, 6, 12), skin, 0, -.3, 0);
    add(hip, new THREE.SphereGeometry(.15, 16, 12), M(outfit === 'sport' ? '#ffffff' : '#2b2b30', .5), 0, -.62, .07, 1, .6, 1.45);
    P[s < 0 ? 'legL' : 'legR'] = hip;
  }
  // the pictogram trapezoid: narrow at the shoulders, wide at the hem (above the knees)
  const dress = add(body, new THREE.CylinderGeometry(.25, .66, 1.02, 36), dressMat, 0, .97, 0); P.dress = dress;
  add(body, new THREE.SphereGeometry(.25, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), dressMat, 0, 1.47, 0, 1, .45, 1);
  add(body, new THREE.TorusGeometry(.655, .035, 8, 40), accent, 0, .48, 0).rotation.x = Math.PI / 2;   // hem
  if (outfit === 'hoodie' && !wedding) add(body, new THREE.TorusGeometry(.22, .08, 10, 24), accent, 0, 1.5, -.08).rotation.x = Math.PI / 2.3;
  if ((outfit === 'hemd' || outfit === 'anzug') && !wedding) {
    for (const s of [-1, 1]) { const c = add(body, new THREE.ConeGeometry(.08, .16, 3), white, s * .07, 1.46, .23); c.rotation.set(Math.PI, 0, s * .5); }
  }
  if (outfit === 'sport' && !wedding) for (const y of [.62, .72]) add(body, new THREE.TorusGeometry(.66 - (y - .48) * .4, .02, 6, 40), white, 0, y, 0).rotation.x = Math.PI / 2;
  if (outfit === 'kleid' || wedding) add(body, new THREE.TorusGeometry(.4, .04, 8, 32), accent, 0, 1.12, 0).rotation.x = Math.PI / 2;   // belt
  for (const s of [-1, 1]) {
    const sh = new THREE.Group(); sh.position.set(s * .35, 1.36, 0); body.add(sh);
    add(sh, new THREE.CapsuleGeometry(.1, .32, 6, 12), sleeves ? dressMat : skin, 0, -.24, 0);
    if (!sleeves) add(sh, new THREE.SphereGeometry(.13, 12, 10), dressMat, 0, -.02, 0, 1, .8, 1);
    const hand = new THREE.Group(); hand.position.set(0, -.5, 0); sh.add(hand);
    add(hand, new THREE.SphereGeometry(.115, 12, 10), skin);
    sh.rotation.z = s * .3;
    P[s < 0 ? 'armL' : 'armR'] = sh; P[s < 0 ? 'handL' : 'handR'] = hand;
  }
  return finishCharacter(g, P, body, cfg, life, skin);
}

// head, face, hair and hat – shared by both bodies
function finishCharacter(g, P, body, cfg, life, skin) {
  const head = new THREE.Group(); head.position.y = 1.84; body.add(head); P.head = head;
  add(head, new THREE.SphereGeometry(.55, 32, 24), skin, 0, 0, 0, 1, .95, .95);
  for (const s of [-1, 1]) add(head, new THREE.SphereGeometry(.1, 12, 10), skin, s * .53, -.02, 0);
  const eye = M('#231f1d', .3), hi = new THREE.MeshBasicMaterial({ color: '#ffffff' });
  for (const s of [-1, 1]) {
    add(head, new THREE.SphereGeometry(.075, 16, 12), eye, s * .19, .03, .48, 1, 1.25, .6);
    add(head, new THREE.SphereGeometry(.024, 8, 8), hi, s * .19 + .025, .075, .52);
    if (cfg.gender === 'frau') { const l = add(head, new THREE.BoxGeometry(.06, .022, .02), eye, s * .27, .12, .45); l.rotation.z = s * .55; }
    const ch = add(head, new THREE.CircleGeometry(.075, 18), new THREE.MeshBasicMaterial({ color: '#ff8f8f', transparent: true, opacity: .45 }), s * .31, -.1, .435);
    ch.rotation.y = s * .55; ch.castShadow = false;
    const brow = add(head, new THREE.BoxGeometry(.13, .03, .03), M(life.grey ? '#bdb9b2' : (HAIRC[cfg.hairColor] || '#5a3826'), .8), s * .19, .19, .47);
    brow.rotation.z = -s * .12;
  }
  const mouth = add(head, new THREE.TorusGeometry(.085, .022, 8, 18, Math.PI), M('#7a3b2e', .5), 0, -.16, .5);
  mouth.rotation.z = Math.PI;

  // ---------- hair (merged + cached per style/hat fit)
  const hair = fitHair(g);
  // ---------- hats (sized to the hair so nothing pokes through)
  const hc = COLORS[cfg.color] || '#eb6834';
  const hatG = new THREE.Group(); hatG.name = 'hat'; head.add(hatG); g.userData.hatG = hatG;
  switch (cfg.hat) {
    case 'cap': { const d = add(hatG, new THREE.SphereGeometry(.6, 32, 16, 0, Math.PI * 2, 0, Math.PI * .45), M(hc), 0, .05, -.02); d.rotation.x = -.15;
      const b = add(hatG, new THREE.CylinderGeometry(.42, .42, .04, 28), M(shade(hc, -.08)), 0, .22, .45, 1, 1, 1.1); b.rotation.x = .12;
      add(hatG, new THREE.SphereGeometry(.05, 10, 8), M(shade(hc, -.1)), 0, .64, -.05); break; }
    case 'beanie': add(hatG, new THREE.SphereGeometry(.61, 32, 16, 0, Math.PI * 2, 0, Math.PI * .5), M(hc, .9), 0, .12, 0);
      add(hatG, new THREE.TorusGeometry(.585, .085, 12, 32), M(shade(hc, -.08), .9), 0, .17, 0).rotation.x = Math.PI / 2;
      add(hatG, new THREE.SphereGeometry(.15, 14, 12), M('#ffffff', .95), 0, .77, 0); break;
    case 'strohhut': strawHat(hatG); break;
    case 'partyhut': { const lift = Math.max(0, hair.topC - .55);
      add(hatG, new THREE.ConeGeometry(.26, .62, 28), M(hc), 0, .78 + lift, 0);
      add(hatG, new THREE.SphereGeometry(.09, 10, 8), M('#ffffff'), 0, 1.1 + lift, 0); break; }
    case 'kopfhoerer': { const cx = Math.max(.6, hair.sideX + .06), top = Math.max(.6, hair.topZ0 + .05);
      add(hatG, new THREE.TorusGeometry(1, .07, 10, 32, Math.PI), M('#3a3a42', .4), 0, .02, 0, cx, top - .02, 1);
      for (const s of [-1, 1]) {
        add(hatG, new THREE.CylinderGeometry(.17, .17, .13, 20), M(hc, .4), s * cx, 0, 0).rotation.z = Math.PI / 2;
        add(hatG, new THREE.CylinderGeometry(.12, .12, .02, 18), M('#3a3a42', .5), s * (cx + .07), 0, 0).rotation.z = Math.PI / 2;
      }
      break; }
    default: break;
  }
  if (life.cane) addProp(g, 'cane');
  return g;
}

function addProp(ch, name) {
  const P = ch.userData.parts; if (ch.userData.props[name]) return;
  const grp = new THREE.Group(); let parent = P.head;
  switch (name) {
    case 'gradcap': add(grp, new THREE.CylinderGeometry(.42, .44, .22, 24), M('#1d1d24', .5), 0, .5, 0);
      add(grp, new THREE.BoxGeometry(1.05, .05, 1.05), M('#1d1d24', .5), 0, .63, 0).rotation.y = Math.PI / 4;
      add(grp, new THREE.CylinderGeometry(.015, .015, .4), M('#f2c14e', .4), .42, .45, .42);
      add(grp, new THREE.SphereGeometry(.05, 8, 8), M('#f2c14e', .4), .42, .25, .42); break;
    case 'strohhut': strawHat(grp); break;
    case 'sunglasses': for (const s of [-1, 1]) add(grp, new THREE.BoxGeometry(.24, .14, .04), M('#15151b', .2), s * .19, .04, .53);
      add(grp, new THREE.BoxGeometry(.16, .03, .03), M('#15151b', .2), 0, .07, .54); break;
    case 'diploma': parent = P.handR; add(grp, new THREE.CylinderGeometry(.07, .07, .55, 16), M('#fbf6e9', .7), 0, 0, .1).rotation.z = Math.PI / 2;
      add(grp, new THREE.TorusGeometry(.075, .02, 8, 16), M('#c0392b'), 0, 0, .1).rotation.y = Math.PI / 2; break;
    case 'briefcase': parent = P.handR; add(grp, new THREE.BoxGeometry(.44, .32, .13), M('#7a4a2b', .5), 0, -.22, 0);
      add(grp, new THREE.TorusGeometry(.07, .02, 8, 16, Math.PI), M('#4a2c18'), 0, -.05, 0); break;
    case 'cane': parent = P.handR; add(grp, new THREE.CylinderGeometry(.03, .03, .95, 10), M('#7a4a2b', .5), 0, -.45, .05);
      add(grp, new THREE.TorusGeometry(.08, .03, 8, 16, Math.PI), M('#7a4a2b', .5), .08, 0, .05); break;
    case 'tophat': add(grp, new THREE.CylinderGeometry(.34, .36, .52, 28), M('#1d1d24', .45), 0, .78, 0);
      add(grp, new THREE.CylinderGeometry(.56, .56, .04, 32), M('#1d1d24', .45), 0, .52, 0);
      add(grp, new THREE.CylinderGeometry(.365, .365, .1, 28), M('#c9a227', .4), 0, .6, 0); break;
    case 'veil': { // flower crown + translucent veil falling down the back
      const ring = add(grp, new THREE.TorusGeometry(.5, .045, 8, 32), M('#5fa85a', .7), 0, .4, -.02); ring.rotation.x = Math.PI / 2 - .25;
      const fc = ['#ffffff', '#ffd23f', '#ff8fb1'];
      for (let i = 0; i < 9; i++) { const a = i / 9 * Math.PI * 2;
        add(grp, new THREE.SphereGeometry(.075, 10, 8), M(fc[i % 3], .6), Math.cos(a) * .5, .4 + Math.sin(a) * .12, Math.sin(a) * .5 - .02); }
      const veil = add(grp, new THREE.CylinderGeometry(.5, .85, 1.5, 28, 1, true, Math.PI * .55, Math.PI * .9),
        new THREE.MeshStandardMaterial({ color: '#ffffff', transparent: true, opacity: .55, roughness: .4, side: THREE.DoubleSide, depthWrite: false }), 0, -.3, -.12);
      veil.castShadow = false; break; }
    case 'bouquet': { parent = P.handR; const b = new THREE.Group(); b.position.set(0, .05, .12); grp.add(b);
      add(b, new THREE.ConeGeometry(.13, .32, 12), M('#f3efe4', .7), 0, -.12, 0).rotation.x = Math.PI;
      const fc = ['#ff8fb1', '#ffffff', '#ffd23f', '#e34948', '#ff8fb1'];
      fc.forEach((c, i) => { const a = i / fc.length * Math.PI * 2; add(b, new THREE.SphereGeometry(.08, 10, 8), M(c, .6), Math.cos(a) * .09, .08, Math.sin(a) * .09); });
      add(b, new THREE.SphereGeometry(.08, 10, 8), M('#ffffff', .6), 0, .13, 0); break; }
    case 'baby': { parent = P.body; const b = new THREE.Group(); b.position.set(0, 1.08, .5); grp.add(b);
      add(b, new THREE.CapsuleGeometry(.17, .22, 6, 12), M('#9fd3f5', .9), 0, 0, 0).rotation.z = Math.PI / 2;
      add(b, new THREE.SphereGeometry(.15, 16, 12), M(SKINS[ch.userData.cfg.skin] || '#f2c2a2', .75), .27, .08, .02);
      P.armL.rotation.set(-1.15, 0, -.5); P.armR.rotation.set(-1.15, 0, .5); ch.userData.hold = true; break; }
    default: return;
  }
  parent.add(grp); ch.userData.props[name] = grp;
  if (HEAD_COVER.includes(name)) fitHair(ch);
}
function removeProp(ch, name) {
  const p = ch.userData.props[name]; if (!p) return; p.parent.remove(p); delete ch.userData.props[name];
  if (name === 'baby') { ch.userData.hold = false; }
  if (HEAD_COVER.includes(name)) fitHair(ch);
}

function animateCharacter(ch, dt) {
  const u = ch.userData, P = u.parts; u.t += dt;
  if (u.mode === 'walk') {
    const s = Math.sin(u.t * 10);
    P.legL.rotation.x = s * .6; P.legR.rotation.x = -s * .6;
    if (!u.hold) { P.armL.rotation.x = -s * .5; P.armR.rotation.x = s * .5; }
    P.body.position.y = Math.abs(Math.cos(u.t * 10)) * .06;
  } else if (u.mode === 'cheer') {
    P.legL.rotation.x = P.legR.rotation.x = 0;
    if (!u.hold) { P.armL.rotation.set(0, 0, -2.6 + Math.sin(u.t * 12) * .25); P.armR.rotation.set(0, 0, 2.6 - Math.sin(u.t * 12) * .25); }
    P.body.position.y = Math.abs(Math.sin(u.t * 7)) * .25;
  } else if (u.mode === 'sit') {
    P.legL.rotation.x = P.legR.rotation.x = -1.45; P.body.position.y = -.42;
  } else if (u.mode === 'seated') {
    P.body.position.y = 0;
  } else {
    P.legL.rotation.x *= .85; P.legR.rotation.x *= .85;
    if (!u.hold) { P.armL.rotation.x *= .85; P.armR.rotation.x *= .85; const rz = u.restZ || .12; P.armL.rotation.z = lerp(P.armL.rotation.z, -rz, .15); P.armR.rotation.z = lerp(P.armR.rotation.z, rz, .15); }
    P.body.position.y = Math.sin(u.t * 2.2) * .02;
  }
  P.head.rotation.z = Math.sin(u.t * 1.3) * .03;
  if (P.pony) { // swinging ponytail
    const lively = u.mode === 'walk' || u.mode === 'cheer', f = lively ? 9 : 2.2, a = lively ? .3 : .1;
    P.pony.rotation.z = Math.sin(u.t * f) * a * .7;
    P.pony.rotation.x = .05 + Math.abs(Math.sin(u.t * f)) * a * .5;
  }
}

/* =================================================================== car */
function buildCar(color) {
  const g = new THREE.Group(); const c = COLORS[color] || '#e34948'; const body = M(c, .35);
  const shell = add(g, new THREE.CapsuleGeometry(.5, 1.3, 8, 18), body, 0, .62, 0, .66, 1, .9); shell.rotation.z = Math.PI / 2;
  add(g, new THREE.BoxGeometry(.9, .14, .7), M('#3a3a40', .8), -.15, .95, 0);
  const ws = add(g, new THREE.BoxGeometry(.05, .36, .78), new THREE.MeshStandardMaterial({ color: '#cfeaff', transparent: true, opacity: .55, roughness: .1 }), .42, 1.12, 0);
  ws.rotation.z = -.35;
  for (const x of [-.72, .72]) for (const z of [-.46, .46]) {
    const w = add(g, new THREE.CylinderGeometry(.3, .3, .22, 22), M('#26262b', .7), x, .3, z); w.rotation.x = Math.PI / 2;
    add(w, new THREE.CylinderGeometry(.13, .13, .24, 14), M('#d9d9de', .3), 0, 0, 0); g.userData.wheels = (g.userData.wheels || []).concat(w);
  }
  for (const z of [-.28, .28]) {
    add(g, new THREE.SphereGeometry(.09, 10, 8), new THREE.MeshStandardMaterial({ color: '#fff3b0', emissive: '#ffe680', emissiveIntensity: .6 }), 1.13, .66, z);
    add(g, new THREE.SphereGeometry(.07, 10, 8), M('#ff6b6b', .4), -1.13, .66, z);
  }
  return g;
}
function seat(ch, car, x = -.12, scale = .5) {
  car.add(ch); ch.position.set(x, .28, 0); ch.rotation.set(0, Math.PI / 2, 0); ch.scale.setScalar(scale);
  ch.userData.parts.legL.visible = ch.userData.parts.legR.visible = false; ch.userData.mode = 'seated';
  if (ch.userData.parts.dress) ch.userData.parts.dress.scale.set(.62, 1, .62);   // tuck the dress into the seat
}
function unseat(ch) { if (ch.userData.parts.dress) ch.userData.parts.dress.scale.set(1, 1, 1); }

/* =================================================================== podium */
const tierCache = new Map();
function roundedTier(rTop, rBot, h, b) { // lathe profile with rounded top and bottom edges, centred on y = 0
  const k = [rTop, rBot, h, b].join(); if (tierCache.has(k)) return tierCache.get(k);
  const pts = [new THREE.Vector2(0, -h / 2)];
  for (let i = 0; i <= 5; i++) { const a = -Math.PI / 2 + i / 5 * Math.PI / 2; pts.push(new THREE.Vector2(rBot - b + Math.cos(a) * b, -h / 2 + b + Math.sin(a) * b)); }
  for (let i = 0; i <= 5; i++) { const a = i / 5 * Math.PI / 2; pts.push(new THREE.Vector2(rTop - b + Math.cos(a) * b, h / 2 - b + Math.sin(a) * b)); }
  pts.push(new THREE.Vector2(0, h / 2));
  const geo = new THREE.LatheGeometry(pts, 72); tierCache.set(k, geo); return geo;
}
function buildPodium() { // top surface at y = 0 (the character stands on it), floor at y ≈ -.6
  const g = new THREE.Group();
  add(g, roundedTier(1.78, 1.9, .28, .07), M('#26307e', .45), 0, -.46, 0);
  const glow = new THREE.MeshStandardMaterial({ color: '#ffe36b', emissive: '#ffc21a', emissiveIntensity: 1.0, roughness: .35 });
  add(g, roundedTier(1.74, 1.74, .08, .03), glow, 0, -.29, 0);
  add(g, roundedTier(1.64, 1.7, .2, .06), M('#2f72e6', .35), 0, -.15, 0);
  add(g, roundedTier(1.56, 1.58, .07, .03), new THREE.MeshStandardMaterial({ color: '#f6f2ff', roughness: .16, metalness: .05 }), 0, -.035, 0);
  const rim = add(g, new THREE.TorusGeometry(1.6, .045, 10, 80), M('#ff86bd', .3), 0, -.045, 0); rim.rotation.x = Math.PI / 2;
  const ring = add(g, new THREE.RingGeometry(1.2, 1.28, 72), new THREE.MeshStandardMaterial({ color: '#d7cdff', roughness: .3, polygonOffset: true, polygonOffsetFactor: -2 }), 0, .002, 0);
  ring.rotation.x = -Math.PI / 2; ring.castShadow = false;
  const bulbs = new THREE.InstancedMesh(new THREE.SphereGeometry(.055, 10, 8),
    new THREE.MeshStandardMaterial({ color: '#fff7d6', emissive: '#ffe08a', emissiveIntensity: .9, roughness: .3 }), 18);
  const m = new THREE.Matrix4();
  for (let i = 0; i < 18; i++) { const a = i / 18 * Math.PI * 2; m.makeTranslation(Math.cos(a) * 1.845, -.46, Math.sin(a) * 1.845); bulbs.setMatrixAt(i, m); }
  bulbs.instanceMatrix.needsUpdate = true; g.add(bulbs);
  return g;
}

export { buildCharacter, addProp, removeProp, animateCharacter, buildCar, seat, unseat, buildPodium };
