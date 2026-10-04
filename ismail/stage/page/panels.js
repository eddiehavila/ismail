// Ephemeral panels: an agent shows the user something in VR (a render, a reference photo, a question) and gets their
// answer back as data. `live.py panel show <id> --image f --title t --text t --buttons "A,B"` opens one in front of
// the user, fixed in the world; the user answers by poking a button with a fingertip, pointing and pinching, or a
// RIGHT thumbs up / down held while the panel is in view. Events: panel_shown, panel_answer {id, answer, via},
// panel_closed {id, why}. The poke also works on any other registered surface (the colour panel in xr.js).
// anchor 'body' (the user, 2026-10-04: a message "needs to stick to me, just like my utility belt"): the panel rides
// with the user, just out of view to the right (side 'right', the default) or left of where their BODY faces
// (body.js), so turning the head finds it; ttl seconds or the X closes it; dragging it moves its place around them.
// A panel that tells about a place stays in the world (the default). No panel opens while the user is talking.
import * as THREE from 'three';
import { GIZMO } from './editor.js';

const CW = 1024;                         // canvas width; the height follows the content
const WIDTH = 0.56;                      // metres
const POKE_IN = 0.012, POKE_OUT = 0.03, HOVER = 0.08;   // fingertip to the surface, metres
const VERDICT_HOLD_MS = 450;
const BODY_WIDTH = 0.42, BODY_DEG = 72, BODY_DIST = 0.6, BODY_DROP = 0.12;   // a 0.42 m panel 72 degrees out sits just
                                                                            // past the Quest 3's view straight ahead

export function initPanels(ed, xrApi, hands, voice, live, body) {
  const { scene, camera, renderer } = ed;
  const panels = new Map();              // id -> panel
  const pokeables = [];                  // { mesh, w, h, press(uv, via), hover(uv|null) }

  // ---- drawing
  function layoutOf(p) {
    const pad = 28, titleH = p.title ? 64 : 0, imgH = p.img ? Math.round((CW - 2 * pad) * p.img.height / p.img.width) : 0;
    const textLines = p.text ? wrap(p.text, 52) : [], textH = textLines.length * 38 + (textLines.length ? 14 : 0);
    // up to four buttons in a row; more wrap into rows of three (the user, 2026-10-03: a person's menu had eight
    // buttons in one row and they were "getting scrunched")
    const n = p.buttons.length, per = n <= 4 ? Math.max(1, n) : 3, rows = n ? Math.ceil(n / per) : 0;
    const btnH = rows * 92;
    const H = pad + titleH + (imgH ? imgH + 14 : 0) + textH + btnH + pad;
    const bw = n ? (CW - 2 * pad - (per - 1) * 16) / per : 0;
    const by = H - pad - btnH + 8;
    p.rects = p.buttons.map((b, i) => ({ id: b, x: pad + (i % per) * (bw + 16), y: by + Math.floor(i / per) * 92, w: bw, h: 76 }));
    p.rects.push({ id: '__close', x: CW - pad - 48, y: pad + 4, w: 48, h: 48 });
    return { pad, titleH, imgH, textLines, H };
  }
  function wrap(t, n) {
    const out = [];
    for (const para of String(t).split('\n')) {
      let line = '';
      for (const w of para.split(' ')) { if ((line + w).length > n && line) { out.push(line); line = ''; } line += w + ' '; }
      out.push(line);
    }
    return out;
  }
  function draw(p) {
    const L = layoutOf(p), cv = p.cv;
    if (cv.height !== L.H) { cv.height = L.H; p.mesh.geometry.dispose(); p.mesh.geometry = new THREE.PlaneGeometry(p.width, p.width * L.H / CW); }
    const g = cv.getContext('2d');
    g.clearRect(0, 0, CW, L.H);
    g.fillStyle = 'rgba(16,18,22,0.94)'; g.beginPath(); g.roundRect(0, 0, CW, L.H, 26); g.fill();
    let y = L.pad;
    if (p.title) {
      g.fillStyle = '#f5f5f4'; g.font = 'bold 40px system-ui, sans-serif'; g.textBaseline = 'middle';
      g.fillText(p.title, L.pad, y + 28, CW - 2 * L.pad - 70);
      y += L.titleH;
    }
    const x = p.rects.find((r) => r.id === '__close');
    g.fillStyle = p.hover === '__close' ? '#b91c1c' : 'rgba(255,255,255,0.12)'; g.beginPath(); g.roundRect(x.x, x.y, x.w, x.h, 10); g.fill();
    g.strokeStyle = '#fff'; g.lineWidth = 5; g.beginPath(); g.moveTo(x.x + 14, x.y + 14); g.lineTo(x.x + 34, x.y + 34); g.moveTo(x.x + 34, x.y + 14); g.lineTo(x.x + 14, x.y + 34); g.stroke();
    if (p.img) { g.drawImage(p.img, L.pad, y, CW - 2 * L.pad, L.imgH); y += L.imgH + 14; }
    if (L.textLines.length) {
      g.fillStyle = '#d6d3d1'; g.font = '30px system-ui, sans-serif'; g.textBaseline = 'top';
      for (const ln of L.textLines) { g.fillText(ln, L.pad, y); y += 38; }
    }
    for (const r of p.rects) {
      if (r.id === '__close') continue;
      const on = p.hover === r.id, chosen = p.answer === r.id;
      g.fillStyle = chosen ? '#15803d' : on ? '#ca8a04' : 'rgba(255,255,255,0.14)';
      g.beginPath(); g.roundRect(r.x, r.y, r.w, r.h, 16); g.fill();
      g.fillStyle = '#fff'; g.font = 'bold 34px system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(r.id, r.x + r.w / 2, r.y + r.h / 2, r.w - 16); g.textAlign = 'left';
    }
    p.tex.needsUpdate = true;
  }
  const rectAt = (p, uv) => {
    const px = uv.x * CW, py = (1 - uv.y) * p.cv.height;
    return p.rects.find((r) => px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) || null;
  };

  // ---- one panel
  function placeInFront(obj, n) {
    const head = camera.getWorldPosition(new THREE.Vector3()), fwd = camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize();
    const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0));
    obj.position.copy(head).addScaledVector(fwd, 0.7).addScaledVector(right, (n % 3 - 1) * 0.3 * (n ? 1 : 0)).y -= 0.08;
    obj.lookAt(head.x, obj.position.y, head.z);
  }
  async function show(c) {
    const id = String(c.panel_id || 'panel_' + Date.now());   // (c.id is the server's command id)
    // never while the user is talking (the user, 2026-10-04: "your message interrupted me" and the thought was lost)
    if (renderer.xr.isPresenting && voice.talking()) {
      live.emit('panel_held', { id, why: 'the user is talking' });
      while (renderer.xr.isPresenting && voice.talking()) await new Promise((res) => setTimeout(res, 300));
    }
    if (panels.has(id)) close(id, 'replaced');
    const onBody = c.anchor === 'body' && !c.near;
    const width = c.width || (onBody ? BODY_WIDTH : WIDTH);
    const cv = document.createElement('canvas'); cv.width = CW; cv.height = 256;
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, width / 4),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, toneMapped: false, side: THREE.DoubleSide, depthTest: false, depthWrite: false }));   // drawn over the world, like Quest system panels (the user, 2026-10-03: a panel cut through a seated man)
    mesh.layers.set(GIZMO); mesh.renderOrder = 990;
    const p = { id, title: c.title || '', text: c.text || '', buttons: (c.buttons || []).map(String), img: null, cv, tex, mesh,
      width, hover: null, answer: null, resolve: null, timer: null, t0: performance.now(),
      body: onBody ? { deg: (c.side === 'left' ? -1 : 1) * (c.angle ?? BODY_DEG), dist: c.distance ?? BODY_DIST, dy: -BODY_DROP } : null };
    if (c.image) {
      p.img = await new Promise((res) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = c.image; });
      if (!p.img) p.text = (p.text ? p.text + '\n' : '') + '(could not load ' + c.image + ')';
    }
    draw(p);
    if (c.near) {                                               // beside a thing (actions.js), facing the user
      mesh.position.copy(c.near);
      const head = camera.getWorldPosition(new THREE.Vector3());
      mesh.lookAt(head.x, mesh.position.y, head.z);
    } else if (p.body) placeOnBody(p, 1);
    else placeInFront(mesh, panels.size);
    scene.add(mesh);
    panels.set(id, p);
    p.poke = { mesh, press: (uv, via) => pressAt(p, uv, via), hover: (uv) => { const r = uv && rectAt(p, uv); setHover(p, r ? r.id : null); },
      dragTo: (pos) => dragTo(p, pos), panel: p, isControl: (uv) => !!rectAt(p, uv) };
    pokeables.push(p.poke);
    mesh.userData.panelApi = p.poke;
    xrApi.addTarget(mesh);
    if (!c.quiet) voice.EAR.incoming();
    live.emit('panel_shown', { id, title: p.title, image: c.image || null, buttons: p.buttons, anchor: p.body ? 'body' : 'world',
      ...(p.body ? { side: p.body.deg < 0 ? 'left' : 'right' } : {}) });
    const ttl = c.ttl ?? c.seconds;
    const done = new Promise((resolve) => {
      p.resolve = resolve;
      if (ttl) p.timer = setTimeout(() => close(id, 'timeout'), ttl * 1000);
    });
    return c.wait === false ? { id, shown: true } : done;
  }
  function setHover(p, id) { if (p.hover !== id) { p.hover = id; draw(p); } }
  function pressAt(p, uv, via) {
    const r = rectAt(p, uv);
    if (!r) return false;                                       // the frame, the title, the image: not a control
    if (r.id === '__close') { close(p.id, 'closed by the user'); return true; }
    answer(p, r.id, via);
    return true;
  }
  // ---- moving a panel: pinch its frame (not a button) with the hand at it, or point and pinch from afar; it follows,
  // and turns to face the user when let go
  function faceUser(mesh) {
    const head = camera.getWorldPosition(new THREE.Vector3());
    mesh.lookAt(head.x, mesh.position.y, head.z);
  }
  function dragTo(p, pos) { p.mesh.position.copy(pos); faceUser(p.mesh); }
  // ---- riding with the user: each body panel has a place around the body (degrees right of its forward, metres out,
  // height from the eyes); panels on one side stack downward. k 1 jumps there, smaller eases (the body turns smoothly).
  const want = new THREE.Vector3();
  function placeOnBody(p, k) {
    let below = 0;
    for (const q of panels.values()) {
      if (q === p) break;
      if (q.body && Math.sign(q.body.deg) === Math.sign(p.body.deg)) below += q.mesh.geometry.parameters.height + 0.03;
    }
    body.around(p.body.deg, p.body.dist, want);
    want.y += p.body.dy - below;
    if (k >= 1) p.mesh.position.copy(want); else p.mesh.position.lerp(want, k);
    faceUser(p.mesh);
  }
  function rebase(p) {                                          // dropped where the user wanted it: that is its place now
    const b = body.bearing(p.mesh.getWorldPosition(new THREE.Vector3()));
    p.body = { deg: b.deg, dist: Math.max(0.3, b.dist), dy: b.dy };
  }
  function answer(p, a, via) {
    p.answer = a; draw(p);
    voice.EAR.sent();
    const res = { id: p.id, answer: a, via, seconds: +((performance.now() - p.t0) / 1000).toFixed(1) };
    live.emit('panel_answer', res);
    setTimeout(() => close(p.id, 'answered'), 600);        // a moment to see the choice light up
    if (p.resolve) { p.resolve(res); p.resolve = null; }
  }
  function close(id, why = 'closed') {
    const p = panels.get(id);
    if (!p) return { closed: false };
    panels.delete(id);
    clearTimeout(p.timer);
    scene.remove(p.mesh); xrApi.removeTarget(p.mesh);
    p.mesh.geometry.dispose(); p.mesh.material.dispose(); p.tex.dispose();
    const i = pokeables.indexOf(p.poke); if (i >= 0) pokeables.splice(i, 1);
    live.emit('panel_closed', { id, why });
    if (p.resolve) { p.resolve({ id, answer: null, why }); p.resolve = null; }
    return { closed: true };
  }

  // ---- finger poke on any registered surface: hover inside HOVER, press on crossing POKE_IN from the front
  const tipState = { left: { inside: null }, right: { inside: null } };
  const local = new THREE.Vector3();
  const headP = new THREE.Vector3(), gazeD = new THREE.Vector3(), toPk = new THREE.Vector3();
  function inView(pk) {                                         // presses only on what the user is looking at (a hand
    pk.mesh.getWorldPosition(toPk).sub(headP).normalize();     // tracked behind the head bumped a close button)
    return toPk.dot(gazeD) > 0.64;                              // within about 50 degrees of the gaze
  }
  function poke() {
    headP.setFromMatrixPosition(camera.matrixWorld);
    gazeD.set(0, 0, -1).transformDirection(camera.matrixWorld);
    const now = performance.now();
    for (const side of ['left', 'right']) {
      const h = hands.state[side], tip = h && h.f ? h.f.indexTip : null, st = tipState[side];
      let best = null;
      if (tip) {
        for (const pk of pokeables) {
          let shown = !!pk.mesh.parent;
          for (let o = pk.mesh; o && shown; o = o.parent) shown = o.visible;
          if (!shown) continue;
          if (pk.panel && (drag.left && drag.left.p === pk.panel || drag.right && drag.right.p === pk.panel)) continue;   // being carried: no pokes
          pk.mesh.updateMatrixWorld();
          local.copy(tip); pk.mesh.worldToLocal(local);
          const pg = pk.mesh.geometry.parameters, hw = pg.width / 2, hh = pg.height / 2;
          if (Math.abs(local.x) > hw || Math.abs(local.y) > hh || local.z > HOVER || local.z < -0.05) continue;
          if (!best || local.z < best.z) best = { pk, z: local.z, uv: new THREE.Vector2(local.x / pg.width + 0.5, local.y / pg.height + 0.5) };
        }
      }
      for (const pk of pokeables) if (pk.hover && (!best || best.pk !== pk) && pk.hoveredBy === side) { pk.hover(null); pk.hoveredBy = null; }
      if (!best) { st.inside = null; continue; }
      best.pk.hover(best.uv); best.pk.hoveredBy = side;
      if (best.z < POKE_IN && st.inside !== best.pk) {          // crossed the surface: one press per touch
        st.inside = best.pk;
        const settled = !best.pk.panel || now - (best.pk.panel.droppedAt || 0) > 800;   // not just let go of
        if (settled && inView(best.pk)) best.pk.press(best.uv, 'poke ' + side);
      } else if (best.z > POKE_OUT && st.inside === best.pk) st.inside = null;
    }
  }

  // ---- a right thumbs up / down held while a panel is in view answers it (if it has buttons, the first and the
  // last stand for yes and no; otherwise the answer is 'thumbs up' / 'thumbs down')
  let verdict = { g: null, since: 0 };
  function thumbs(now) {
    const r = hands.state.right, g = r && r.f && (r.g === 'thumbs_up' || r.g === 'thumbs_down') ? r.g : null;
    if (g !== verdict.g) verdict = { g, since: now };
    if (!g || now - verdict.since < VERDICT_HOLD_MS || !panels.size) return;
    const gaze = camera.getWorldDirection(new THREE.Vector3()), head = camera.getWorldPosition(new THREE.Vector3());
    let target = null, bestDot = Math.cos(THREE.MathUtils.degToRad(30));
    for (const p of panels.values()) {
      if (p.answer) continue;                                   // answered, fading out
      const d = p.mesh.getWorldPosition(new THREE.Vector3()).sub(head).normalize().dot(gaze);
      if (d > bestDot) { bestDot = d; target = p; }
    }
    if (!target || target.answer) return;
    verdict.since = Infinity;                                   // one verdict per gesture
    const a = target.buttons.length ? (g === 'thumbs_up' ? target.buttons[0] : target.buttons[target.buttons.length - 1]) : g.replace('_', ' ');
    answer(target, a, 'right ' + g.replace('_', ' '));
  }

  const drag = { left: null, right: null };
  function nearPanelAt(pt) {
    for (const p of panels.values()) {
      local.copy(pt); p.mesh.worldToLocal(local);
      const pg = p.mesh.geometry.parameters;
      if (Math.abs(local.x) <= pg.width / 2 + 0.03 && Math.abs(local.y) <= pg.height / 2 + 0.03 && Math.abs(local.z) < 0.06) {
        return { p, uv: new THREE.Vector2(local.x / pg.width + 0.5, local.y / pg.height + 0.5) };
      }
    }
    return null;
  }
  function nearDrag() {
    for (const side of ['left', 'right']) {
      const h = hands.state[side], f = h && h.f;
      if (!f) { drag[side] = null; continue; }
      const pt = f.p['thumb-tip'].clone().add(f.indexTip).multiplyScalar(0.5);
      const pinched = f.pinch < (drag[side] ? 0.035 : 0.02);
      if (drag[side]) {
        if (!pinched || !panels.has(drag[side].p.id)) {
          drag[side].p.droppedAt = performance.now();
          if (drag[side].p.body) rebase(drag[side].p);
          drag[side] = null; continue;
        }
        dragTo(drag[side].p, pt.add(drag[side].off));
      } else if (pinched && !drag[side + 'Was']) {
        const n = nearPanelAt(pt);
        if (n && !rectAt(n.p, n.uv)) drag[side] = { p: n.p, off: n.p.mesh.position.clone().sub(pt) };
      }
      drag[side + 'Was'] = pinched;
    }
  }
  // xr.js asks this before its own pinch: a hand at a panel's frame is moving it, not selecting through it
  function handAtPanel(side) {
    if (drag[side]) return true;
    const f = hands.state[side] && hands.state[side].f;
    if (!f) return false;
    const n = nearPanelAt(f.p['thumb-tip'].clone().add(f.indexTip).multiplyScalar(0.5));
    return !!n;
  }

  let lastT = 0;
  function update() {
    if (!renderer.xr.isPresenting) return;
    const now = performance.now(), k = 1 - Math.exp(-Math.min(0.1, (now - (lastT || now)) / 1000) * 6);
    lastT = now;
    for (const p of panels.values()) if (p.body && !(drag.left && drag.left.p === p) && !(drag.right && drag.right.p === p)) placeOnBody(p, k);
    nearDrag();
    poke();
    thumbs(performance.now());
  }
  renderer.xr.addEventListener('sessionend', () => { for (const id of [...panels.keys()]) close(id, 'left VR'); });

  function registerPokeable(mesh, press, hover) { const pk = { mesh, press, hover }; pokeables.push(pk); return pk; }
  xrApi.addNearCheck(handAtPanel);
  return { show, close, update, registerPokeable, panels };
}
