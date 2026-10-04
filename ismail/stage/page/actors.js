// A take played on a person: their skinned MakeHuman body (scenes/<scene>/actors/<who>.glb, rooms/actor_export.py)
// stands in for the baked statue while the take plays, driven by the user's recorded head and hands through the human
// puppet map:
//   head      -> head and neck, the turn spread down the spine; the hips follow under the head
//   wrists    -> targets the arms reach for (two-bone IK, elbows down and out)
//   fingers   -> the 25 WebXR joints onto the three-bone fingers (orientation, world space)
//   legs      -> feet planted on the floor, stepping when the hips leave them (procedural; a leg pass comes later)
// The take is scaled to the actor's height about where it started. Live: {"type": "actor_play", "person":
// "person_couple_2_m", "take": "<id>", "loop": true}, {"type": "actor_stop", "person": ...}. Event actor_play / actor_stop.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { JOINTS } from './hands.js';
import { cutout } from './editor.js';
import { world } from './world.js';

// who plays whom, facings, partners and the floor are the scene's (world.json via world.js), not the runtime's
// where a person stands: the bottom of their stand-in (the band is up on the stage), the room's floor without one
// which way a person faces: a person keeps THEIR OWN facing while the user drives them, whichever way the user faces
// (the user, 2026-10-03, at the bar: "I want him to be facing the same direction that he's facing ... I can see what
// his hands are doing and I can see his face"). A couple faces the partner (person_couple_k_m <-> _f; the posed
// people's facing is in their meshes, not their objects); the people with a known spot face the way the room says
// (Blender xy: the bartender the room, Sam the bar, the band the floor); anyone else faces the user where they stand.
function facingOf(ed, person, at, user) {
  const pn = world().partners[person];
  const other = pn && ed.byName.get(pn);
  if (other) {
    const d = other.obj.getWorldPosition(new THREE.Vector3()).sub(at).setY(0);
    if (d.lengthSq() > 1e-4) return d.normalize();
  }
  const fb = world().facings[person];
  if (fb) return new THREE.Vector3(fb[0], 0, -fb[1]).normalize();            // Blender (x, y) -> three (x, -y)
  if (user) {
    const d = user.clone().sub(at).setY(0);
    if (d.lengthSq() > 1e-4) return d.normalize();
  }
  return null;
}
// the turn that carries the user's heading at the start onto the person's facing (the user, 2026-10-03: they had to go
// and stand facing the way he faced); null when the person has no facing of their own
function turnFor(headQ, facing) {
  if (!facing) return null;
  const f = new THREE.Vector3(0, 0, -1).applyQuaternion(headQ).setY(0);
  if (f.lengthSq() < 1e-6) return null;
  return new THREE.Quaternion().setFromUnitVectors(f.normalize(), facing);
}
const _v = new THREE.Vector3(), _q = new THREE.Quaternion();
function turnArr(a, st) {                     // [x, y, z, qx, qy, qz, qw]: turned about the anchor
  if (!a) return a;
  _v.set(a[0], a[1], a[2]).sub(st.anchor).applyQuaternion(st.turn).add(st.anchor);
  const out = [_v.x, _v.y, _v.z];
  if (a.length >= 7) { _q.set(a[3], a[4], a[5], a[6]).premultiply(st.turn); out.push(_q.x, _q.y, _q.z, _q.w); }
  return out;
}
function turnFrame(f, st) {
  const g = { ...f, head: turnArr(f.head, st) };
  for (const h of Object.keys(f)) if (f[h] && Array.isArray(f[h].j)) g[h] = { ...f[h], j: f[h].j.map((x) => turnArr(x, st)) };
  return g;
}
// Mirror (the user: "my right is his right ... or he mirrors me"): the frame reflected through the vertical plane of
// the person's facing, left and right swapped, so facing him you move like his reflection. A reflected joint frame is
// left-handed: its local x is flipped to make it a rotation again.
const _m = new THREE.Matrix4(), _cx = new THREE.Vector3(), _cy = new THREE.Vector3(), _cz = new THREE.Vector3(), _d = new THREE.Vector3();
function mirrorArr(a, st) {
  if (!a) return a;
  const n = st.mirrorN;
  _v.set(a[0], a[1], a[2]);
  _v.addScaledVector(n, -2 * _d.copy(_v).sub(st.anchor).dot(n));
  const out = [_v.x, _v.y, _v.z];
  if (a.length >= 7) {
    _m.makeRotationFromQuaternion(_q.set(a[3], a[4], a[5], a[6])).extractBasis(_cx, _cy, _cz);
    for (const c of [_cx, _cy, _cz]) c.addScaledVector(n, -2 * c.dot(n));
    _cx.negate();
    _q.setFromRotationMatrix(_m.makeBasis(_cx, _cy, _cz));
    out.push(_q.x, _q.y, _q.z, _q.w);
  }
  return out;
}
function mirrorFrame(f, st) {
  const g = { ...f, head: mirrorArr(f.head, st) };
  const mh = (h) => (f[h] && Array.isArray(f[h].j) ? { ...f[h], j: f[h].j.map((x) => mirrorArr(x, st)) } : f[h]);
  g.left = mh('right'); g.right = mh('left');
  return g;
}
const groundOf = (it) => {
  const FLOOR = world().floor || 0;
  if (!it) return FLOOR;
  const y = new THREE.Box3().setFromObject(it.obj).min.y;
  return Number.isFinite(y) && y > -0.5 && y < 3 ? Math.max(FLOOR, y) : FLOOR;
};
const FINGER_JOINTS = {
  thumb: ['thumb-metacarpal', 'thumb-phalanx-proximal', 'thumb-phalanx-distal'],
  index: ['index-finger-phalanx-proximal', 'index-finger-phalanx-intermediate', 'index-finger-phalanx-distal'],
  middle: ['middle-finger-phalanx-proximal', 'middle-finger-phalanx-intermediate', 'middle-finger-phalanx-distal'],
  ring: ['ring-finger-phalanx-proximal', 'ring-finger-phalanx-intermediate', 'ring-finger-phalanx-distal'],
  pinky: ['pinky-finger-phalanx-proximal', 'pinky-finger-phalanx-intermediate', 'pinky-finger-phalanx-distal'],
};
const SPINE = [['spine_01', 0.15], ['spine_02', 0.3], ['spine_03', 0.5], ['neck_01', 0.75], ['head', 1.0]];
const STEP_AT = 0.22, STEP_S = 0.28, LIFT = 0.07;
const Y = new THREE.Vector3(0, 1, 0);

export function initActors(ed, live) {
  const { scene } = ed;
  const scn = () => ed.sceneName;                      // live: scenes.js can switch it
  const loaded = new Map();               // who -> Promise<rig>
  let source = null;                      // hands.frameNow: the user's body right now (follow)
  const playing = new Map();              // person -> state

  // ---- an actor: its bones and their rest pose in world space
  function load(who, base) {
    if (!loaded.has(who)) {
      loaded.set(who, new GLTFLoader().loadAsync(`${base}actors/${who}.glb`).then((g) => {
        const root = g.scene;
        root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; [o.material].flat().forEach(cutout); } });
        const bones = {};
        root.traverse((o) => { if (o.isBone) bones[o.name] = o; });
        root.updateMatrixWorld(true);
        const rest = {};
        for (const [n, b] of Object.entries(bones)) rest[n] = { q: b.getWorldQuaternion(new THREE.Quaternion()), p: b.getWorldPosition(new THREE.Vector3()) };
        const fwd = rest.ball_l.p.clone().sub(rest.foot_l.p).setY(0).normalize();
        const left = rest.upperarm_l.p.clone().sub(rest.upperarm_r.p).setY(0).normalize();
        return { who, root, bones, rest, fwd, left, cal: handCalibration(bones, rest), local: Object.fromEntries(Object.entries(bones).map(([n, b]) => [n, b.quaternion.clone()])) };
      }));
    }
    return loaded.get(who);
  }

  // ---- hands: each WebXR joint straight onto its bone, no rest-pose guess. A WebXR joint has -Z along the bone toward
  // the tip and +Y out of the back of the hand (the nail). Per bone, cal = C^-1 where C carries those axes into the
  // bone's local frame; then bone world = joint world * cal. The hand and the four fingers take "back" from the rig's
  // own palm (the hand bone is rolled ~41 deg off it); the thumbs from the rig's nail axis (-Z local, the fingers'
  // convention measured on these MakeHuman rigs), since a thumb's nail does not face the back of the hand. (The user
  // on the first played take: "his thumbs are completely the wrong way"; the old map assumed every joint lay along
  // the arm at rest, and this rig rests in an A-pose.)
  function handCalibration(bones, rest) {
    const cal = {};
    const P_ = (n) => rest[n].p;
    const make = (n, alongW, backW) => {
      const qi = rest[n].q.clone().invert();
      const al = alongW.clone().applyQuaternion(qi).normalize();
      const bk = backW.clone().applyQuaternion(qi);
      bk.sub(al.clone().multiplyScalar(bk.dot(al))).normalize();
      const zx = al.clone().negate(), yx = bk, xx = new THREE.Vector3().crossVectors(yx, zx);
      cal[n] = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(xx, yx, zx)).invert();
    };
    for (const sd of ['l', 'r']) {
      if (!bones[`hand_${sd}`]) continue;
      const back = new THREE.Vector3().crossVectors(P_(`index_01_${sd}`).clone().sub(P_(`pinky_01_${sd}`)),
        P_(`middle_01_${sd}`).clone().sub(P_(`hand_${sd}`))).normalize();
      if (sd === 'r') back.negate();
      make(`hand_${sd}`, P_(`middle_01_${sd}`).clone().sub(P_(`hand_${sd}`)), back);
      for (const fg of ['index', 'middle', 'ring', 'pinky', 'thumb']) {
        for (let k = 1; k <= 3; k++) {
          const n = `${fg}_0${k}_${sd}`;
          if (!rest[n]) continue;
          const yW = new THREE.Vector3(0, 1, 0).applyQuaternion(rest[n].q);       // along the bone (+Y on these rigs)
          make(n, yW, fg === 'thumb' ? new THREE.Vector3(0, 0, -1).applyQuaternion(rest[n].q) : back);
        }
      }
    }
    return cal;
  }

  // ---- setting a bone's world rotation / aiming it, parents first
  const tq = new THREE.Quaternion(), tq2 = new THREE.Quaternion(), tv = new THREE.Vector3(), tv2 = new THREE.Vector3();
  function setWorldQ(b, qw) {
    b.parent.getWorldQuaternion(tq).invert();
    b.quaternion.copy(tq.multiply(qw));
    b.updateMatrixWorld(true);
  }
  function aim(b, child, target) {                          // turn b so its child lies toward target
    const p = b.getWorldPosition(tv), c = child.getWorldPosition(tv2);
    const cur = c.sub(p).normalize(), want = target.clone().sub(p).normalize();
    const d = new THREE.Quaternion().setFromUnitVectors(cur, want);
    setWorldQ(b, d.multiply(b.getWorldQuaternion(tq2)));
  }
  function twoBone(rig, a, bn, cn, target, pole) {         // a -> b -> c reaches target, bending toward pole
    const A = rig.bones[a], B = rig.bones[bn], C = rig.bones[cn];
    const S = A.getWorldPosition(new THREE.Vector3());
    const la = rig.rest[bn].p.distanceTo(rig.rest[a].p), lb = rig.rest[cn].p.distanceTo(rig.rest[bn].p);
    const d = Math.min(S.distanceTo(target), la + lb - 1e-4);
    const u = target.clone().sub(S).normalize();
    const v = pole.clone().sub(S); v.sub(u.clone().multiplyScalar(v.dot(u))).normalize();
    const ca = THREE.MathUtils.clamp((la * la + d * d - lb * lb) / (2 * la * d), -1, 1);
    const E = S.clone().addScaledVector(u, la * ca).addScaledVector(v, la * Math.sqrt(1 - ca * ca));
    aim(A, B, E);
    aim(B, C, S.clone().addScaledVector(u, d));
  }

  // ---- one frame of the take onto the rig
  function pose(st, f) {
    if (st.turn) f = turnFrame(f, st);
    if (st.mirror && st.mirrorN) f = mirrorFrame(f, st);
    const { rig, s, anchor, J } = st, to = st.to || anchor;
    const P = (a) => to.clone().add(new THREE.Vector3(a[0], a[1], a[2]).sub(anchor).multiplyScalar(s));
    for (const [n, q] of Object.entries(rig.local)) rig.bones[n].quaternion.copy(q);   // from rest each frame
    rig.root.updateMatrixWorld(true);
    // the head: the camera's turn relative to "looking along the actor's rest forward"
    const qc = new THREE.Quaternion(f.head[3], f.head[4], f.head[5], f.head[6]);
    const delta = qc.clone().multiply(st.alignInv);
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(qc).setY(0);
    const yaw = new THREE.Quaternion().setFromUnitVectors(rig.fwd, fwd.lengthSq() > 1e-6 ? fwd.normalize() : rig.fwd);
    const head = P(f.head);
    // the hips under the head, turned with it
    const pel = rig.bones.pelvis;
    const off = rig.rest.pelvis.p.clone().sub(rig.rest.head.p).applyQuaternion(yaw);
    const hipAt = head.clone().add(off);
    hipAt.y = Math.min(hipAt.y, st.floor + rig.rest.pelvis.p.y - rig.rest.foot_l.p.y + 0.08);   // never off the ground
    pel.parent.updateMatrixWorld(true);
    pel.position.copy(pel.parent.worldToLocal(hipAt.clone()));
    setWorldQ(pel, yaw.clone().multiply(rig.rest.pelvis.q));
    for (const [n, k] of SPINE) {
      const q = new THREE.Quaternion().slerpQuaternions(yaw, delta, k);
      setWorldQ(rig.bones[n], q.multiply(rig.rest[n].q));
    }
    // arms and hands, fingers
    const side = (sd, h) => {
      const hd = f[h];
      const sgn = sd === 'l' ? 1 : -1;
      if (!hd || !hd.j || !hd.j[0]) {                      // the hand out of tracking: the arm hangs at the side
        const sh0 = rig.bones[`upperarm_${sd}`].getWorldPosition(new THREE.Vector3());
        const lat = rig.left.clone().applyQuaternion(yaw).multiplyScalar(sgn * 0.12);
        twoBone(rig, `upperarm_${sd}`, `lowerarm_${sd}`, `hand_${sd}`, sh0.clone().add(lat).add(new THREE.Vector3(0, -0.6, 0)),
          sh0.clone().add(rig.fwd.clone().applyQuaternion(yaw).multiplyScalar(-1)));
        return;
      }
      const lateral = rig.left.clone().applyQuaternion(yaw).multiplyScalar(sgn);
      const back = rig.fwd.clone().applyQuaternion(yaw).multiplyScalar(-1);
      const sh = rig.bones[`upperarm_${sd}`].getWorldPosition(new THREE.Vector3());
      twoBone(rig, `upperarm_${sd}`, `lowerarm_${sd}`, `hand_${sd}`, P(hd.j[0]), sh.clone().add(new THREE.Vector3(0, -1, 0)).addScaledVector(lateral, 0.5).addScaledVector(back, 0.4));
      const jq = (i) => { const a = hd.j[i]; return a ? new THREE.Quaternion(a[3], a[4], a[5], a[6]) : null; };
      const w = jq(0);
      if (w && rig.cal[`hand_${sd}`]) setWorldQ(rig.bones[`hand_${sd}`], w.multiply(rig.cal[`hand_${sd}`]));
      for (const [fg, names] of Object.entries(FINGER_JOINTS)) {
        names.forEach((jn, k) => {
          const b = rig.bones[`${fg}_0${k + 1}_${sd}`], q = jq(J[jn]);
          if (b && q && rig.cal[b.name]) setWorldQ(b, q.multiply(rig.cal[b.name]));
        });
      }
    };
    side('l', 'left'); side('r', 'right');
    // legs: planted feet, a step when the hips leave them
    const now = f.t;
    for (const sd of ['l', 'r']) {
      const ft = st.feet[sd];
      const want = hipAt.clone().add(rig.rest[`foot_${sd}`].p.clone().sub(rig.rest.pelvis.p).applyQuaternion(yaw));
      want.y = st.floor + rig.rest[`foot_${sd}`].p.y;
      if (!ft.at) ft.at = want.clone();
      const other = st.feet[sd === 'l' ? 'r' : 'l'];
      if (!ft.step && !other.step && ft.at.distanceTo(want) > STEP_AT) ft.step = { from: ft.at.clone(), to: want.clone(), t0: now };
      let at = ft.at;
      if (ft.step) {
        const k = Math.min(1, (now - ft.step.t0) / STEP_S);
        at = ft.step.from.clone().lerp(ft.step.to, k); at.y += Math.sin(Math.PI * k) * LIFT;
        if (k >= 1) { ft.at = ft.step.to; ft.step = null; }
      }
      const knee = rig.bones[`thigh_${sd}`].getWorldPosition(new THREE.Vector3()).addScaledVector(rig.fwd.clone().applyQuaternion(yaw), 1.0);
      twoBone(rig, `thigh_${sd}`, `calf_${sd}`, `foot_${sd}`, at, knee);
      setWorldQ(rig.bones[`foot_${sd}`], yaw.clone().multiply(rig.rest[`foot_${sd}`].q));
    }
  }

  // ---- play / stop
  async function play(c) {
    const person = c.person, who = c.actor || world().actors[person];
    if (!who) throw new Error('no actor for ' + person + ' (world.json actors, or pass actor)');
    const base = `scenes/${encodeURIComponent(c.assets || scn())}/`;
    const tbase = `scenes/${encodeURIComponent(c.takes || scn())}/takes/${encodeURIComponent(c.take)}/`;
    const [rig0, meta, txt] = await Promise.all([load(who, base), fetch(tbase + 'meta.json', { cache: 'no-store' }).then((r) => r.json()),
      fetch(tbase + 'frames.jsonl', { cache: 'no-store' }).then((r) => { if (!r.ok) throw new Error('no take ' + c.take); return r.text(); })]);
    stop({ person });
    let frames = txt.split('\n').filter(Boolean).map((l) => JSON.parse(l)).filter((f) => f.head);
    if (!frames.length) throw new Error('take has no frames');
    // a trimmed take plays only its kept part (actions.js review: Start here / End here; saved in meta.trim)
    const trim = c.trim === null ? null : c.trim || meta.trim;
    if (Array.isArray(trim) && trim.length === 2) {
      const cut = frames.filter((f) => f.t >= trim[0] && f.t <= trim[1]);
      if (cut.length > 1) frames = cut;
    }
    const rig = playing.size && [...playing.values()].some((p) => p.rig.who === who) ? await cloneRig(rig0) : rig0;
    const J = Object.fromEntries((meta.joints || []).map((n, i) => [n, i]));
    // scale: the user's standing head height to the actor's
    const floor = world().floor || 0;                       // the user's floor while recording
    const heads = frames.map((f) => f.head[1]).sort((a, b) => a - b);
    // the median: a take can hold moments raised on the thumbstick, which a high percentile took for standing height
    const userH = heads[Math.floor(heads.length * 0.5)] - floor, actorH = rig.rest.head.p.y - rig.rest.foot_l.p.y + 0.08;
    const s = THREE.MathUtils.clamp(actorH / Math.max(0.5, userH), 0.6, 1.4);
    const anchor = new THREE.Vector3(frames[0].head[0], floor, frames[0].head[2]);
    const align = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, -1), rig.fwd);
    const it = ed.byName.get(person);
    // a take borrowed from someone else plays where this person stands (the user, 2026-10-03: "make the people that
    // are inside the place who can dance, dance"): its start moves onto them; their own take plays where it was made
    // and since live follow (the user, 2026-10-03: "they stand where they are, and they follow along with my
    // movements"), every take plays where its person stands, the way it looked while it was recorded; c.in_place
    // plays it where the user stood
    let to = null, ground = floor;
    if (it && !c.in_place) {
      const w = it.obj.getWorldPosition(new THREE.Vector3());
      ground = groundOf(it);
      to = new THREE.Vector3(w.x, ground, w.z);
    }
    if (it) it.obj.visible = false;
    scene.add(rig.root);
    const h0 = frames[0].head;
    const turn = to && h0.length >= 7 ? turnFor(new THREE.Quaternion(h0[3], h0[4], h0[5], h0[6]), facingOf(ed, person, to)) : null;
    const st = { person, rig, frames, J, s, anchor, to, floor: ground, alignInv: align.clone().invert(), feet: { l: {}, r: {} },
      t0: performance.now(), loop: c.loop !== false, it, take: c.take, i: 0, rate: c.rate || 1, turn };
    playing.set(person, st);
    live.emit('actor_play', { person, actor: who, take: c.take, seconds: +(frames[frames.length - 1].t - frames[0].t).toFixed(1), scale: +s.toFixed(2) });
    return { person, actor: who, frames: frames.length, scale: +s.toFixed(2) };
  }
  // ---- follow: the person moves with the user, live, from where they stand (no take needed; a take on a person
  // turns it on while recording). Same puppet map as a played take, fed the user's frame of this moment.
  async function follow(c) {
    const person = c.person, who = c.actor || world().actors[person];
    if (!who) throw new Error('no actor for ' + person + ' (world.json actors, or pass actor)');
    if (!source) throw new Error('no live body source');
    const rig0 = await load(who, `scenes/${encodeURIComponent(c.assets || scn())}/`);
    stop({ person });
    const rig = [...playing.values()].some((p) => p.rig.who === who) ? await cloneRig(rig0) : rig0;
    const f0 = source(), floor = world().floor || 0;
    const userH = Math.max(0.5, f0.head[1] - floor), actorH = rig.rest.head.p.y - rig.rest.foot_l.p.y + 0.08;
    const s = THREE.MathUtils.clamp(actorH / userH, 0.6, 1.4);
    const it = ed.byName.get(person);
    const w = it ? it.obj.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(f0.head[0], floor, f0.head[2]);
    const align = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, -1), rig.fwd);
    const ground = groundOf(it);
    if (it) it.obj.visible = false;
    scene.add(rig.root);
    const toW = new THREE.Vector3(w.x, ground, w.z);
    const facing = facingOf(ed, person, toW, new THREE.Vector3(f0.head[0], 0, f0.head[2]));
    const turn = turnFor(new THREE.Quaternion(f0.head[3], f0.head[4], f0.head[5], f0.head[6]), facing);
    const st = { person, rig, live: true, J: Object.fromEntries(JOINTS.map((n, i) => [n, i])), s, floor: ground,
      anchor: new THREE.Vector3(f0.head[0], floor, f0.head[2]), to: toW, turn, mode: c.mode || 'place', drift: new THREE.Vector3(),
      mirror: !!c.mirror, mirrorN: facing ? new THREE.Vector3(facing.z, 0, -facing.x) : null,
      last: new THREE.Vector3(f0.head[0], f0.head[1], f0.head[2]),
      alignInv: align.clone().invert(), feet: { l: {}, r: {} }, t0: performance.now(), it };
    playing.set(person, st);
    live.emit('actor_follow', { person, actor: who, scale: +s.toFixed(2) });
    return { person, actor: who, following: true, scale: +s.toFixed(2) };
  }
  async function cloneRig(r) {                              // a second person on the same actor (couple 3)
    const { clone } = await import('three/addons/utils/SkeletonUtils.js');
    const root = clone(r.root), bones = {};
    root.traverse((o) => { if (o.isBone) bones[o.name] = o; });
    return { ...r, root, bones };
  }
  function stop(c) {
    const st = playing.get(c.person);
    if (!st) return { stopped: false };
    playing.delete(c.person);
    scene.remove(st.rig.root);
    if (st.it) st.it.obj.visible = true;
    live.emit('actor_stop', { person: c.person, why: c.why || 'stopped', live: !!st.live });
    return { stopped: true };
  }
  const cur = new THREE.Vector3(), jump = new THREE.Vector3(), WALK_AWAY_M = 6;
  const shiftArr = (x, d) => (x ? [x[0] - d.x, x[1], x[2] - d.z, ...x.slice(3)] : x);
  function shifted(f, d) {                      // every position of a frame moved by -d (horizontal)
    const g = { ...f, head: shiftArr(f.head, d) };
    for (const h of Object.keys(f)) if (f[h] && Array.isArray(f[h].j)) g[h] = { ...f[h], j: f[h].j.map((x) => shiftArr(x, d)) };
    return g;
  }
  // the user's controls while someone follows (actions.js' follow panel)
  function turnBy(person, deg) {
    const st = playing.get(person);
    if (!st) return null;
    const r = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(deg));
    st.turn = st.turn ? r.multiply(st.turn) : r;
    if (st.mirrorN) st.mirrorN.applyQuaternion(r);
    return { person, turned: deg };
  }
  function setMode(person, mode) {
    const st = playing.get(person);
    if (!st || !st.live) return null;
    if (mode === 'walk' && st.mode === 'place') { st.anchor.add(st.drift); st.drift.set(0, 0, 0); }   // no jump when he starts walking
    st.mode = mode;
    return { person, mode };
  }
  function moveTo(person, at) {                // his spot moves (the stand-in too, as an undoable edit): never during a take
    const st = playing.get(person);
    if (!st) return null;
    const d = new THREE.Vector3(at.x - st.to.x, 0, at.z - st.to.z);
    st.to.add(d);
    if (st.it) {
      const o = st.it.obj, wp = o.getWorldPosition(new THREE.Vector3()).add(d);
      ed.beginEdit('move ' + person);
      o.position.copy(o.parent ? o.parent.worldToLocal(wp) : wp);
      ed.endEdit();
    }
    live.emit('actor_moved', { person, by: [+d.x.toFixed(2), +d.z.toFixed(2)] });
    return { person, moved: true };
  }
  function update() {
    for (const st of playing.values()) {
      if (st.live) {
        const f = source && source();
        if (!f) continue;
        // a teleport (the head jumps a metre in a frame) leaves the person where they are, still following (carrying them
        // along would break a take: the user, 2026-10-03; "Move him here" on the follow panel moves them on purpose)
        cur.set(f.head[0], f.head[1], f.head[2]);
        if (cur.distanceTo(st.last) > 0.8) st.anchor.add(jump.copy(cur).sub(st.last).setY(0));
        st.last.copy(cur);
        // "place": he dances on his spot while the user walks around him (the slow drift of the user's head is taken
        // out, the sway kept); "walk": he walks as the user walks. Far away ends it (and a take: actions.js).
        if (st.mode === 'place') st.drift.lerp(jump.copy(cur).sub(st.anchor).setY(0), 0.02);
        const far = st.mode === 'place' ? Math.hypot(cur.x - st.to.x, cur.z - st.to.z) : Math.hypot(cur.x - st.anchor.x, cur.z - st.anchor.z);
        if (far > WALK_AWAY_M) { stop({ person: st.person, why: 'walked_away' }); continue; }
        f.t = (performance.now() - st.t0) / 1000;
        pose(st, st.mode === 'place' ? shifted(f, st.drift) : f);
        continue;
      }
      const T = st.frames[st.frames.length - 1].t, t0 = st.frames[0].t;
      let t = t0 + (performance.now() - st.t0) / 1000 * st.rate;
      if (t > T) { if (!st.loop) { stop({ person: st.person }); continue; } st.t0 = performance.now(); t = t0; st.i = 0; st.feet = { l: {}, r: {} }; }
      while (st.i < st.frames.length - 1 && st.frames[st.i + 1].t <= t) st.i++;
      pose(st, st.frames[st.i]);
    }
  }
  ed.preRender.push(update);
  const canPlay = (person) => !!world().actors[person];
  const setSource = (fn) => { source = fn; };
  // where a playing take is now (its own clock, seconds) and its span
  const at = (person) => { const st = playing.get(person); return st && st.frames ? { t: st.frames[st.i].t, t0: st.frames[0].t, t1: st.frames[st.frames.length - 1].t } : null; };
  function setMirror(person, on) {
    const st = playing.get(person);
    if (!st) return null;
    st.mirror = !!on;
    live.emit('actor_mirror', { person, mirror: st.mirror });
    return { person, mirror: st.mirror };
  }
  return { play, stop, follow, setSource, playing, load, pose, canPlay, turnBy, setMode, moveTo, at, setMirror };
}
