// Objects pinned to a hand joint for this session (the user, 2026-10-03: the guitar resting "on this part of my
// thumb", to play Cyrus with it). Never saved: editor.computeEdits writes an anchored object as it was before
// (userData.anchorHome), and a release puts it back; leaving VR or the scene releases everything.
//   live: anchor {object, hand?, joint?, at?} -> {anchored, hand, joint}
//           hand 'left' (default) | 'right'; joint an XR hand joint name, default 'thumb-metacarpal';
//           at 'keep' (default: hold the pose it has now, relative to the joint) | 'joint' (its origin onto the joint)
//         anchor_release {object?}  (every pinned object when none is named)
//   events: anchored, anchor_released
import * as THREE from 'three';

export function initAnchors(ed, xr, live) {
  const pins = new Map();                                    // name -> { it, side, joint, rel }
  const m = new THREE.Matrix4(), inv = new THREE.Matrix4();

  function jointOf(side, joint) {
    for (const s of xr.ctls) {
      if (!s.src || s.src.handedness !== side || !s.src.hand || !s.hand || !s.hand.joints) continue;
      const j = s.hand.joints[joint];
      if (j && j.visible !== false) { j.updateWorldMatrix(true, false); return j; }
    }
    return null;
  }

  function anchor(c) {
    const it = ed.byName.get(c.object);
    if (!it) throw new Error('no object named ' + c.object);
    const side = c.hand || 'left', joint = c.joint || 'thumb-metacarpal';
    const j = jointOf(side, joint);
    if (!j) throw new Error(`the ${side} hand is not tracked, or it has no joint ${joint}`);
    if (pins.has(it.name)) release({ object: it.name });
    const o = it.obj;
    o.userData.anchorHome = { changed: ed.changed(it), t: ed.blenderTransform(it),
      pos: o.position.clone(), quat: o.quaternion.clone(), scale: o.scale.clone() };
    o.updateWorldMatrix(true, false);
    const wm = o.matrixWorld.clone();
    if (c.at === 'joint') wm.setPosition(new THREE.Vector3().setFromMatrixPosition(j.matrixWorld));
    pins.set(it.name, { it, side, joint, rel: j.matrixWorld.clone().invert().multiply(wm) });
    live.emit('anchored', { object: it.name, hand: side, joint });
    return { anchored: it.name, hand: side, joint };
  }

  function release(c = {}) {
    const names = c.object ? [c.object] : [...pins.keys()];
    for (const n of names) {
      const p = pins.get(n);
      if (!p) continue;
      const o = p.it.obj, h = o.userData.anchorHome;
      if (h) { o.position.copy(h.pos); o.quaternion.copy(h.quat); o.scale.copy(h.scale); o.updateMatrixWorld(true); }
      delete o.userData.anchorHome;
      pins.delete(n);
      live.emit('anchor_released', { object: n });
    }
    return { released: names.filter((n) => !pins.has(n)) };
  }

  function update() {
    for (const p of pins.values()) {
      const j = jointOf(p.side, p.joint);
      if (!j) continue;                                      // tracking lost: it stays where it was
      const o = p.it.obj;
      m.multiplyMatrices(j.matrixWorld, p.rel);
      if (o.parent) { o.parent.updateWorldMatrix(true, false); m.premultiply(inv.copy(o.parent.matrixWorld).invert()); }
      m.decompose(o.position, o.quaternion, o.scale);
    }
  }

  live.handlers.anchor = anchor;
  live.handlers.anchor_release = release;
  ed.renderer.xr.addEventListener('sessionend', () => release());
  live.onEmit((type) => { if (type === 'scene_leaving') release(); });
  ed.preRender.push(function anchors() { if (pins.size) update(); });
  return { anchor, release, pins };
}
