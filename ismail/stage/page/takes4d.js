// A take seen in 4D (the user, 2026-10-02: "show me 4d snapshots of my takes in front of me"): the paths of the head
// and both wrists over the whole take, and N ghost poses (the head, both hands' skeletons) at moments spread through
// it, coloured from blue (start) to orange (end). Where they happened ('in place'), or as a filmstrip in front of the
// user ('strip': each pose moved along their right, 40 cm apart, the first one a metre ahead). Data: GET
// scenes/<scene>/takes/<id>/frames.jsonl ({t, head: [x,y,z,qx,qy,qz,qw], left/right: {j: [[x,y,z,qx,qy,qz,qw,r] x 25]}},
// three.js world space). Live: {"type": "take_view", "id": ..., "n": 8, "layout": "strip"|"place"}, {"type": "take_view_clear"}.
import * as THREE from 'three';
import { GIZMO } from './editor.js';

// finger chains over the 25 WebXR joints (0 wrist, then 4 thumb, 5 index, 5 middle, 5 ring, 5 pinky)
const CHAINS = [[0, 1, 2, 3, 4], [0, 5, 6, 7, 8, 9], [0, 10, 11, 12, 13, 14], [0, 15, 16, 17, 18, 19], [0, 20, 21, 22, 23, 24]];

export function initTakes4D(ed, live) {
  const { scene, camera } = ed;
  const scn = () => ed.sceneName;                      // live: scenes.js can switch it
  const root = new THREE.Group();
  root.name = 'take_view';
  scene.add(root);
  const colorAt = (k) => new THREE.Color().setHSL(0.6 - 0.52 * k, 0.85, 0.6);

  function clear() {
    root.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    root.clear();
    return { cleared: true };
  }
  function line(pts, color, opacity = 0.9) {
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const l = new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity, toneMapped: false, depthWrite: false }));
    l.layers.set(GIZMO); l.frustumCulled = false;
    root.add(l);
    return l;
  }
  function pathOf(frames, get, shift) {
    const pts = [];
    frames.forEach((f, i) => { const p = get(f); if (p) pts.push(new THREE.Vector3(p[0], p[1], p[2]).add(shift(i / Math.max(1, frames.length - 1)))); });
    return pts;
  }

  async function show(c) {
    clear();
    const id = c.take || c.id;                           // over the live link the server owns `id` (the command number)
    const txt = await fetch(`scenes/${encodeURIComponent(scn())}/takes/${encodeURIComponent(id)}/frames.jsonl`, { cache: 'no-store' })
      .then((r) => { if (!r.ok) throw new Error('no take ' + id); return r.text(); });
    const frames = txt.split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((f) => f.head);
    if (!frames.length) throw new Error('take ' + id + ' has no frames');
    const n = Math.max(2, Math.min(24, c.n || 8));
    const strip = (c.layout || 'strip') === 'strip';
    // the strip: the first pose a metre in front of the user, the rest along their right
    const head = camera.getWorldPosition(new THREE.Vector3());
    const fwd = camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize();
    const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
    const h0 = new THREE.Vector3(...frames[0].head.slice(0, 3));
    const base = strip ? head.clone().addScaledVector(fwd, 1.0).addScaledVector(right, -0.4 * (n - 1) / 2).sub(h0).setY(head.y - h0.y - 0.1) : new THREE.Vector3();
    const shift = (k) => (strip ? base.clone().addScaledVector(right, 0.4 * (n - 1) * k) : base);
    // the paths, over the whole take
    line(pathOf(frames, (f) => f.head, shift), 0x93c5fd, 0.5);
    for (const side of ['left', 'right']) line(pathOf(frames, (f) => f[side] && f[side].j && f[side].j[0], shift), side === 'left' ? 0xfca5a5 : 0x86efac, 0.6);
    // the ghosts
    const dot = new THREE.SphereGeometry(1, 8, 6);
    for (let i = 0; i < n; i++) {
      const k = i / (n - 1), f = frames[Math.round(k * (frames.length - 1))], col = colorAt(k), off = shift(k);
      const hm = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.16, 12).rotateX(-Math.PI / 2),
        new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.55, toneMapped: false }));
      hm.position.set(...f.head.slice(0, 3)).add(off);
      hm.quaternion.set(...f.head.slice(3, 7));
      hm.layers.set(GIZMO);
      root.add(hm);
      for (const side of ['left', 'right']) {
        const J = f[side] && f[side].j;
        if (!J || J.length < 25) continue;
        const P = J.map((q) => new THREE.Vector3(q[0], q[1], q[2]).add(off));
        for (const ch of CHAINS) line(ch.map((a) => P[a]), col.getHex(), 0.95);
        for (const a of [0, 4, 9, 14, 19, 24]) {
          const s = new THREE.Mesh(dot, new THREE.MeshBasicMaterial({ color: col, toneMapped: false }));
          s.scale.setScalar(a ? 0.006 : 0.012);
          s.position.copy(P[a]); s.layers.set(GIZMO);
          root.add(s);
        }
      }
    }
    const secs = frames[frames.length - 1].t - frames[0].t;
    live.emit('take_view', { id, poses: n, layout: strip ? 'strip' : 'place', seconds: +secs.toFixed(1), frames: frames.length });
    return { id, poses: n, seconds: +secs.toFixed(1), frames: frames.length };
  }
  return { show, clear };
}
