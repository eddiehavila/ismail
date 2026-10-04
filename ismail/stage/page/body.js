// Which way the user's body faces, which is not where their head looks (the user, 2026-10-04: "where my head is facing
// is not where I'm actually facing"). The body keeps its heading while the head looks around; a head turn held past
// TURN_DEG for HOLD_MS turns the body after it, and the hands held out in front of the chest pull it toward them.
// Panels that ride with the user (panels.js, anchor 'body') sit just out of view of this heading, so looking left or
// right finds them and looking ahead does not.
import * as THREE from 'three';

const TURN_DEG = 35;            // a head turn past this, held, is the body turning
const HOLD_MS = 900;
const FOLLOW_S = 0.45;          // how fast the body catches up once it turns
const HANDS_S = 1.5;            // how fast hands held out in front pull the heading
const HANDS_MIN = 0.18;         // metres in front of the head (flat) before the hands count

const yawOf = (v) => Math.atan2(-v.x, -v.z);                       // 0 looks down -z, like the camera
const wrapA = (a) => Math.atan2(Math.sin(a), Math.cos(a));

export function initBody(ed, hands) {
  const { camera } = ed;
  const st = { yaw: null, offSince: 0, turning: false, last: 0, via: 'head' };
  // looking at something that rides with the body is the head turning, not the body (the user, 2026-10-04: turning
  // to a card "they dart out of my vision"); panels.js says when (holds)
  const holds = [];
  const head = new THREE.Vector3(), fwd = new THREE.Vector3(), mid = new THREE.Vector3();

  function headYaw() {
    camera.getWorldDirection(fwd);
    if (fwd.x * fwd.x + fwd.z * fwd.z < 1e-4) fwd.set(0, 1, 0).applyQuaternion(camera.quaternion);   // looking straight down
    return yawOf(fwd.setY(0));
  }
  function handsYaw() {
    const l = hands.state.left, r = hands.state.right;
    if (!(l && l.f && r && r.f) || l.resting || r.resting) return null;
    mid.copy(l.f.wrist).add(r.f.wrist).multiplyScalar(0.5).sub(head).setY(0);
    return mid.length() >= HANDS_MIN ? yawOf(mid) : null;
  }

  function update() {
    const now = performance.now(), dt = st.last ? Math.min(0.1, (now - st.last) / 1000) : 0;
    st.last = now;
    camera.getWorldPosition(head);
    const hy = headYaw();
    if (st.yaw === null) { st.yaw = hy; return; }
    const diff = wrapA(hy - st.yaw);
    st.headRel = THREE.MathUtils.radToDeg(-diff);                     // degrees the head looks right of the body
    const held = holds.some((fn) => fn());
    if (held) { st.offSince = 0; st.turning = false; return; }            // the hands do not pull it either
    if (Math.abs(diff) > THREE.MathUtils.degToRad(TURN_DEG)) {
      if (!st.offSince) st.offSince = now;
      if (now - st.offSince > HOLD_MS) st.turning = true;
    } else st.offSince = 0;
    if (st.turning) {
      st.yaw = wrapA(st.yaw + diff * (1 - Math.exp(-dt / FOLLOW_S)));
      if (Math.abs(diff) < THREE.MathUtils.degToRad(5)) st.turning = false;
    }
    const hd = handsYaw();
    st.via = hd === null ? 'head' : 'hands';
    if (hd !== null) st.yaw = wrapA(st.yaw + wrapA(hd - st.yaw) * (1 - Math.exp(-dt / HANDS_S)));
  }

  // the body's forward and the place `deg` to its right (negative: left), `dist` metres out at the head's height
  function forward(out = new THREE.Vector3()) { const y = st.yaw ?? headYaw(); return out.set(-Math.sin(y), 0, -Math.cos(y)); }
  function around(deg, dist, out = new THREE.Vector3()) {
    const y = (st.yaw ?? headYaw()) - THREE.MathUtils.degToRad(deg);
    camera.getWorldPosition(out);
    return out.add(new THREE.Vector3(-Math.sin(y) * dist, 0, -Math.cos(y) * dist));
  }
  // a world point as degrees right of the body's forward and metres away (flat)
  function bearing(p) {
    camera.getWorldPosition(head);
    const v = p.clone().sub(head).setY(0);
    return { deg: THREE.MathUtils.radToDeg(wrapA((st.yaw ?? headYaw()) - yawOf(v))), dist: v.length(), dy: p.y - head.y };
  }
  ed.renderer.xr.addEventListener('sessionstart', () => { st.yaw = null; st.turning = false; st.offSince = 0; });
  return { update, forward, around, bearing, state: st, holdWhile: (fn) => holds.push(fn), get yaw() { return st.yaw; } };
}
