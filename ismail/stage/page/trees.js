// The grown trees (grow_tree.py's VR export, the tree session, 2026-10-03): scenes/<scene>/trees/tree_<k>.glb with
// tree_<k>.json beside it. Each tree's bark and foliage go under the scene's tree_<k> item (its old stand-in meshes are
// hidden), so a grab moves the tree and the user's edits place it; their growth attributes (_born, _axis, _from, _rad
// on the wood, _born, _pivot on the cards) let clock.js grow them from the stage clock. Event trees_loaded.
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export function initTrees(ed, live, clock) {
  const scn = () => ed.sceneName;                      // live: scenes.js can switch it
  const baseOf = () => `scenes/${encodeURIComponent(scn())}/trees/`;
  const loader = new GLTFLoader();
  let busy = null;
  const added = [];                                           // what the last load put in, taken out by the next

  // the trees share their bark and card images (6 trees, 5 distinct images): one GPU copy each, not one per tree
  // (132 MB down to ~37 MB on the Quest, 2026-10-03)
  let shared = new Map();
  function share(root) {
    root.traverse((o) => {
      if (!o.isMesh) return;
      for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
        for (const [slot, tex] of Object.entries(m)) {
          if (!tex || !tex.isTexture || !tex.name) continue;
          const key = `${tex.name}|${tex.colorSpace}|${tex.channel}`;
          const have = shared.get(key);
          if (!have) { shared.set(key, tex); continue; }
          if (have !== tex) { m[slot] = have; tex.dispose(); m.needsUpdate = true; }
        }
      }
    });
  }
  async function loadAll() {
    const done = [], base = baseOf();
    shared = new Map();                                       // a reload brings new images
    for (const n of added.splice(0)) n.removeFromParent();
    for (let k = 1; k <= 24; k++) {
      const meta = await fetch(`${base}tree_${k}.json`, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (!meta) { if (k > 6) break; continue; }
      const it = ed.byName.get(meta.name || `tree_${k}`);
      let g;
      console.log(`[vr] trees: loading tree_${k}`);
      try { g = await loader.loadAsync(`${base}tree_${k}.glb?v=${Date.now()}`); } catch (e) { live.emit('voice_error', { where: 'tree ' + k, error: String(e.message || e) }); continue; }
      share(g.scene);
      if (it) it.obj.traverse((o) => { if (o.isMesh && !o.userData.grown) o.visible = false; });   // the old stand-in
      for (const node of [...g.scene.children]) {
        if (it) node.position.set(0, 0, 0);                    // the item stands at the trunk
        node.traverse((o) => { o.userData.grown = true; if (o.isMesh) o.castShadow = true; });
        await ed.stage(node, { parent: it ? it.obj : ed.scene, minS: 0.8, pop: false });   // paced, like the room
        added.push(node);
      }
      done.push(meta.name || `tree_${k}`);
    }
    const growers = clock ? clock.patchGrowth() : [];
    if (done.length) live.emit('trees_loaded', { trees: done, growers });
    return { trees: done, growers };
  }
  const go = () => busy || (busy = loadAll().finally(() => { busy = null; }));
  // after the room has finished coming in (reveal.js): never two big loads at once
  if (ed.loaded && !ed.staging()) go(); else ed.addEventListener('revealed', function first() { ed.removeEventListener('revealed', first); go(); });
  ed.addEventListener('reloaded', go);
  live.handlers.trees_reload = () => go();
  return { load: go };
}
