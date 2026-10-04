// Paced reveal: everything that enters the scene comes in a little at a time, never all in one frame. The user,
// 2026-10-03, in the headset: "I have to close my eyes from the lag when you reload ... making loading actually
// staggered in time so that each thing or set of things loads in one by one ... like the construct in the Matrix,
// the gun racks come in by themselves". One frame that uploads a whole room (geometry, textures, shader compiles)
// stalls the Quest for a second or more, and a stalled XR frame tears and swims.
//
//   ed.stage(root, opts) -> Promise   root: an Object3D not yet in the scene (or already in it, hidden)
//     parent    where root goes (default ed.scene; null: it is already placed)
//     minS      the shortest the reveal may take, seconds (the user likes to see the room assemble)
//     replace   a Map key -> old Mesh: a hot reload; each new piece hides its old twin as it appears, so the room
//               never blinks; the old lights hand over to the new in the last frame (same count: no recompile)
//     pop       small things grow in over a fifth of a second (no material change: free on the GPU)
//     order     'near' (structure first, then nearest first) | 'none'
//   Before the first piece shows, every shader the root needs is compiled off the frame (compileAsync, parallel
//   compile on the Quest), and textures go up to the GPU one per frame. Then at most a few meshes and a capped
//   vertex count are revealed per frame, never faster than minS allows.
import * as THREE from 'three';

const QUEST = /OculusBrowser|Quest/i.test(navigator.userAgent);
const BUDGET = QUEST ? { perFrame: 2, verts: 24000, texPerFrame: 1 } : { perFrame: 12, verts: 400000, texPerFrame: 4 };

export const meshKey = (o) => {                // stable across re-exports: the owning item's name and the mesh's own
  let p = o, item = '';
  while (p) { if (p.userData && p.userData.item) { item = p.userData.item.name; break; } p = p.parent; }
  return item + '/' + o.name;
};

export function initReveal(ed) {
  const jobs = [];
  const pops = [];
  const v = new THREE.Vector3(), head = new THREE.Vector3(), box = new THREE.Box3();

  function texturesOf(root) {
    const out = new Set();
    root.traverse((o) => {
      if (!o.isMesh) return;
      for (const m of [o.material].flat()) if (m) for (const val of Object.values(m)) if (val && val.isTexture) out.add(val);
    });
    return [...out];
  }

  function step() {
    const now = performance.now();
    for (let i = pops.length - 1; i >= 0; i--) {                // small things grow in (easeOutBack, 0.85 -> 1)
      const p = pops[i], k = Math.min(1, (now - p.t0) / 200), s = 0.85 + 0.15 * (1 + 2.2 * (k - 1) ** 3 + 1.2 * (k - 1) ** 2);
      p.o.scale.copy(p.s).multiplyScalar(k >= 1 ? 1 : s);
      if (k >= 1) pops.splice(i, 1);
    }
    const job = jobs[0];
    if (!job) return;
    if (job.tex.length) {                                        // textures first, a few per frame
      for (let n = 0; n < BUDGET.texPerFrame && job.tex.length; n++) {
        const t = job.tex.shift();
        try { ed.renderer.initTexture(t); } catch (_) { /* a texture without an image yet: it uploads on first draw */ }
      }
      return;
    }
    if (!job.started) {
      job.started = now;
      if (job.parent) job.parent.add(job.root);
      ed.camera.getWorldPosition(head);
      if (job.order === 'near') {
        for (const p of job.queue) {
          box.setFromObject(p.o).getCenter(v);
          p.d = (p.big ? 0 : 1000) + v.distanceTo(head);
        }
        job.queue.sort((a, b) => a.d - b.d);
      }
    }
    // never faster than minS, never more than the frame budget
    const allowed = Math.ceil(((now - job.started) / 1000) * (job.total / Math.max(0.1, job.minS))) - job.done;
    let n = 0, verts = 0;
    while (job.queue.length && n < Math.min(BUDGET.perFrame, Math.max(0, allowed))) {
      const p = job.queue.shift();
      const cnt = p.o.geometry && p.o.geometry.attributes.position ? p.o.geometry.attributes.position.count : 0;
      if (n > 0 && verts + cnt > BUDGET.verts) { job.queue.unshift(p); break; }
      p.o.visible = true;
      if (job.replace) { const old = job.replace.get(p.key); if (old) { old.visible = false; job.replace.delete(p.key); } }
      if (job.pop && !p.big) {
        pops.push({ o: p.o, s: p.o.scale.clone(), t0: now });
        p.o.scale.multiplyScalar(0.85);
      }
      n++; verts += cnt; job.done++;
    }
    if (n && (job.done % 12 < n || !job.queue.length)) ed.dispatchEvent({ type: 'reveal_progress', done: job.done, total: job.total });
    if (!job.queue.length) {
      if (job.replace) {
        for (const old of job.replace.values()) old.visible = false;   // pieces with no twin in the new export
        for (const l of job.oldLights) l.visible = false;
        for (const l of job.newLights) l.visible = true;               // one frame: same light count, no recompile
      }
      jobs.shift();
      job.resolve({ meshes: job.total, seconds: +((now - job.t0) / 1000).toFixed(1) });
    }
  }
  ed.preRender.push(step);

  ed.stage = async (root, opts = {}) => {
    const parent = opts.parent === undefined ? ed.scene : opts.parent;
    const queue = [];
    root.updateMatrixWorld(true);
    root.traverse((o) => {
      if (!o.isMesh && !o.isPoints && !o.isLine) return;
      if (!o.visible) return;                                      // hidden in the export: stays hidden
      let it = null; for (let p = o; p && !it; p = p.parent) it = p.userData && p.userData.item;
      queue.push({ o, key: meshKey(o), big: !!(it && it.big) });
      o.visible = false;
    });
    const newLights = [], oldLights = [];
    if (opts.replace) {                                            // the new lights wait for the hand-over
      root.traverse((o) => { if (o.isLight && o.visible) { newLights.push(o); o.visible = false; } });
      (opts.oldRoot || { traverse() {} }).traverse((o) => { if (o.isLight && o.visible) oldLights.push(o); });
    }
    // every program this root needs, compiled before any of it is drawn (lights as they will be during the reveal)
    try { await ed.renderer.compileAsync(root, ed.camera, ed.scene); } catch (e) { console.warn('[reveal] compile', e); }
    return new Promise((resolve) => {
      jobs.push({ root, parent, queue, total: queue.length, done: 0, tex: texturesOf(root), minS: opts.minS ?? (QUEST ? 6 : 1.5),
        replace: opts.replace || null, newLights, oldLights, pop: opts.pop !== false && !opts.replace,
        order: opts.order || 'near', resolve, t0: performance.now(), started: 0 });
    });
  };
  ed.staging = () => jobs.length > 0;
}
