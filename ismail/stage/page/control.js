// The control map (the user, 2026-10-04): which part of the user drives which part of an actor, changeable at any
// moment, during a Follow too, from the actor's saved defaults. The built-in human puppet map (actors.js pose) stays
// the base; a drive takes one part of the actor over, after it:
//   hold      the part keeps the pose it had when the drive was set (relative to its parent: it rides with the body)
//   effector  the part reaches (two-bone IK, arms and legs) for a target that moves as one of the user's joints moves,
//             relative to where both were when it bound: "his hands act out the man's feet". touch: two placeholders
//             appear in front of the user and the drive binds when the hand reaches its own
//   pin       the part reaches for a fixed point (an object, Blender xyz, or where its end is now) and stays there
//   mimic     the part copies the turn of a user joint since it bound, spread down the chain (a fingertip into a tail),
//             or 1:1 with a list of joints, one per bone
//   default   back to the built-in map
// An anchor partitions control (the user: "not cut in half, a partition"): each part has its own source and solver.
// A hand that drives something else no longer drives its own arm: that arm and its fingers hold unless they have a
// drive of their own. Live: control_set {person, part, mode, joint, at, scale, touch}, control_map {person, preset,
// drives, clear}. Events: control_set, control_bound, control_map.
import * as THREE from 'three';

const TOUCH_M = 0.06;                               // a hand this close to its placeholder binds the drive
const ORDER = ['spine', 'head', 'arm_l', 'arm_r', 'leg_l', 'leg_r'];
const I = new THREE.Quaternion();

export function initControl(ed, live, A) {
  const maps = new Map();                           // person -> Map(part -> drive)
  const autos = new Map();                          // "person/part" -> the hold of an arm whose hand drives something else
  const marks = new Map();                          // "person/part" -> placeholder mesh

  const srcPose = (f, joint, J) => {                // a user joint in a frame: [x, y, z, qx, qy, qz, qw] or null
    if (joint === 'head') return f.head;
    const [h, jn] = joint.split(':');
    const hd = f[h === 'hand_l' ? 'left' : 'right'];
    if (!hd || !hd.j) return null;
    return hd.j[jn ? J[jn] : 0] || null;
  };
  const qOf = (a) => new THREE.Quaternion(a[3], a[4], a[5], a[6]);
  const pOf = (a) => new THREE.Vector3(a[0], a[1], a[2]);
  const usedHands = (m) => new Set([...m.values()].filter((d) => d.mode === 'effector' || d.mode === 'mimic')
    .flatMap((d) => [d.joint].flat()).map((j) => String(j).split(':')[0]).filter((j) => j !== 'head'));

  async function set(c) {
    const person = c.person, rig = await A.rigOf(person);
    const parts = rig.profile.parts;
    if (!parts[c.part]) throw new Error(`no part ${c.part} on ${rig.who} (${rig.profile.rig}); parts: ${Object.keys(parts).join(', ')}`);
    const mode = c.mode || 'default';
    if ((mode === 'effector' || mode === 'pin') && !rig.profile.effectors.includes(c.part)) throw new Error(`${mode} needs a part that reaches: ${rig.profile.effectors.join(', ')}`);
    if ((mode === 'effector' || mode === 'mimic') && !c.joint) throw new Error(`${mode} needs joint= head, hand_l, hand_r or hand_r:<webxr joint>`);
    const m = maps.get(person) || new Map();
    unmark(person, c.part);
    if (mode === 'default') m.delete(c.part);
    else m.set(c.part, { part: c.part, mode, joint: c.joint || null, at: c.at ?? null, scale: c.scale || 1, touch: !!c.touch,
      bones: parts[c.part], bound: null });
    if (m.size) maps.set(person, m); else maps.delete(person);
    const r = { person, part: c.part, mode, joint: c.joint || null, waiting: !!c.touch && mode === 'effector' };
    live.emit('control_set', r);
    return { ...r, drives: state(person) };
  }

  function state(person) {
    const m = maps.get(person);
    return m ? [...m.values()].map((d) => ({ part: d.part, mode: d.mode, joint: d.joint, ...(d.at != null ? { at: d.at } : {}),
      ...(d.scale !== 1 ? { scale: d.scale } : {}), ...(d.touch ? { touch: true } : {}), bound: !!d.bound })) : [];
  }
  const summary = (person) => state(person).map((d) => (d.mode === 'hold' ? `${d.part} held` : d.mode === 'pin' ? `${d.part} pinned`
    : `${d.part} by ${[d.joint].flat().join('+')}${d.mode === 'mimic' ? ' (turn)' : ''}${d.touch && !d.bound ? ': touch the ball' : ''}`)).join(', ');

  async function setMap(c) {
    const person = c.person;
    if (c.clear) { for (const p of [...(maps.get(person) || new Map()).keys()]) unmark(person, p); maps.delete(person); }
    let preset = null;
    if (c.preset) {
      const rig = await A.readProfile(await A.rigOf(person));
      preset = rig.profile.maps[c.preset];
      if (!preset) throw new Error(`${rig.who} has no map ${c.preset}; saved: ${Object.keys(rig.profile.maps).join(', ') || 'none'}`);
      for (const [joint, to] of Object.entries(preset.pins || {})) A.anchor({ person, joint, to });
    }
    for (const d of [...((preset && preset.drives) || []), ...(c.drives || [])]) await set({ ...d, person });
    const rig = await A.rigOf(person);
    const r = { person, drives: state(person), presets: Object.keys(rig.profile.maps), pins: A.pinsOf(person) };
    live.emit('control_map', { person, preset: c.preset || null, drives: r.drives.length });
    return r;
  }

  // a Follow starts: drives bind again on its first frame (its own clock and place); the actor's saved "default"
  // map applies when nothing was set for this person in this session
  async function onFollow(person) {
    const m = maps.get(person);
    for (const k of [...autos.keys()]) if (k.startsWith(person + '/')) autos.delete(k);
    if (m) { for (const d of m.values()) d.bound = null; return; }
    const rig = await A.rigOf(person).then((r) => A.readProfile(r)).catch(() => null);
    if (rig && rig.profile.maps.default) await setMap({ person, preset: 'default' }).catch((e) =>
      live.emit('voice_error', { where: 'control map', error: String(e.message || e) }));
  }

  function mark(person, d, at) {
    const k = person + '/' + d.part;
    if (marks.has(k)) return marks.get(k);
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.035, 20, 12), new THREE.MeshBasicMaterial({ color: d.joint.startsWith('hand_l') ? 0x60a5fa : 0xf59e0b, transparent: true, opacity: 0.75 }));
    m.position.copy(at); m.renderOrder = 998;
    ed.scene.add(m); marks.set(k, m);
    return m;
  }
  function unmark(person, part) {
    const k = person + '/' + part, m = marks.get(k);
    if (m) { ed.scene.remove(m); m.geometry.dispose(); m.material.dispose(); marks.delete(k); }
  }

  // ---- each frame, after the base pose (actors.js pose): f is the frame as posed (turned, mirrored), raw as recorded
  function apply(st, f, raw) {
    const m = maps.get(st.person);
    if (!m || !m.size) return;
    const { rig } = st;
    const P = (a) => (st.to || st.anchor).clone().add(pOf(a).sub(st.anchor).multiplyScalar(st.s));
    const hands = usedHands(m);
    const drives = [...m.values()];
    for (const sd of ['l', 'r']) {                  // a hand that drives something else lets go of its own arm
      for (const p of ['arm_' + sd, 'fingers_' + sd]) {
        const k = st.person + '/' + p;
        if (!hands.has('hand_' + sd) || m.has(p) || !rig.profile.parts[p]) { autos.delete(k); continue; }
        if (!autos.has(k)) autos.set(k, { part: p, mode: 'hold', bones: rig.profile.parts[p], bound: null });
        drives.push(autos.get(k));
      }
    }
    drives.sort((a, b) => (ORDER.indexOf(a.part) + 1 || 99) - (ORDER.indexOf(b.part) + 1 || 99));
    for (const d of drives) {
      const bones = d.bones.map((n) => rig.bones[n]).filter(Boolean);
      if (!bones.length) continue;
      if (!d.bound) bind(st, d, f, raw, bones, P);
      if (!d.bound) continue;
      const B = d.bound;
      if (d.mode === 'hold') { holdLocal(bones, B.local); continue; }
      if (d.mode === 'mimic') {
        // held first, then each bone turned by the source's turn since binding: the whole turn on its own bone (1:1),
        // or spread down the chain, a growing share per bone (absolute, so shares never compound)
        holdLocal(bones, B.local);
        const held = bones.map((b) => b.getWorldQuaternion(new THREE.Quaternion()));
        const js = [d.joint].flat();
        bones.forEach((b, i) => {
          const one = js.length > 1, a = srcPose(f, one ? js[i] : js[0], st.J);
          if (!a) return;
          const delta = qOf(a).multiply(B.srcQ[one ? i : 0].clone().invert());
          A.setWorldQ(b, new THREE.Quaternion().slerpQuaternions(I, delta, one ? 1 : (i + 1) / bones.length).multiply(held[i]));
        });
        continue;
      }
      // effector / pin: the chain reaches for its target; its end turns with the source (effector) or keeps its turn
      let target = B.target, endQ = B.effQ;
      if (d.mode === 'effector') {
        const a = srcPose(f, d.joint, st.J);
        if (!a) { holdLocal(bones, B.local); continue; }
        target = B.effP.clone().add(P(a).sub(B.srcP).multiplyScalar(d.scale));
        endQ = qOf(a).multiply(B.srcQ[0].clone().invert()).multiply(B.effQ);
      }
      const [a0, b0, c0] = d.bones;
      const leg = d.part.startsWith('leg'), fw = rig.fwd.clone().applyQuaternion(st.pinYaw || st.lastYaw || I);
      const root = rig.bones[a0].getWorldPosition(new THREE.Vector3());
      const pole = leg ? root.clone().addScaledVector(fw, 1.0).add(new THREE.Vector3(0, 0.4, 0))
        : root.clone().add(new THREE.Vector3(0, -1, 0)).addScaledVector(fw, -0.4);
      A.twoBone(rig, a0, b0, c0, target, pole);
      A.setWorldQ(rig.bones[c0], endQ);
    }
  }
  function holdLocal(bones, local) {
    bones.forEach((b, i) => { b.quaternion.copy(local[i]); b.updateMatrixWorld(true); });
  }
  function bind(st, d, f, raw, bones, P) {
    const local = bones.map((b) => b.quaternion.clone());
    const end = bones[bones.length - 1];
    const effP = end.getWorldPosition(new THREE.Vector3()), effQ = end.getWorldQuaternion(new THREE.Quaternion());
    if (d.mode === 'hold') { d.bound = { local }; return; }
    if (d.mode === 'pin') {
      d.bound = { local, effQ, target: d.at === 'here' || d.at == null ? effP : A.pinPoint(d.at, d.part) };
      live.emit('control_bound', { person: st.person, part: d.part, mode: 'pin' });
      return;
    }
    const js = [d.joint].flat(), srcs = js.map((j) => srcPose(f, j, st.J));
    if (srcs.some((a) => !a)) return;                // the joint is not tracked this frame: bind on a later one
    if (d.mode === 'effector' && d.touch) {           // wait for the user's hand at its placeholder (raw, world space)
      const sd = d.joint.startsWith('hand_l') ? -1 : 1;
      // in front of the user's tracked head (the frame's, so a played or test source works as the headset does)
      const head = pOf(raw.head), fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(qOf(raw.head)).setY(0);
      if (fwd.lengthSq() < 1e-6) fwd.set(0, 0, -1);
      fwd.normalize();
      const lat = new THREE.Vector3(-fwd.z, 0, fwd.x);
      const ball = mark(st.person, d, head.clone().addScaledVector(fwd, 0.35).addScaledVector(lat, 0.12 * sd).add(new THREE.Vector3(0, -0.25, 0)));
      const r = srcPose(raw, d.joint, st.J);
      if (!d.wait) d.wait = { local };
      if (!r || pOf(r).distanceTo(ball.position) > TOUCH_M) { d.bound = null; holdLocal(bones, d.wait.local); return; }
      unmark(st.person, d.part);
      d.wait = null;
    }
    d.bound = { local, effP, effQ, srcP: P(srcs[0]), srcQ: srcs.map(qOf) };
    live.emit('control_bound', { person: st.person, part: d.part, mode: d.mode, joint: d.joint });
  }

  live.handlers.control_set = (c) => set(c);
  live.handlers.control_map = (c) => setMap(c);
  return { set, setMap, state, summary, apply, onFollow, maps };
}
