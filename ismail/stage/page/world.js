// The scene's world (scenes/<name>/world.json, served with defaults by GET world?scene=): what belongs to the scene,
// not to the runtime. Who plays whom (actors: person -> actor glb), which way a person faces (facings: person ->
// Blender [x, y]), who faces whom (partners: person -> person), the floor height people stand on, and keep-out boxes
// (Blender [x0, x1, y0, y1, z0, z1]) that grown trees never draw inside. Loaded before the scene and again after a
// scene switch; modules read world() when they need it, never a copy.
const EMPTY = () => ({ actors: {}, facings: {}, partners: {}, floor: 0, keep_out: [] });
const W = EMPTY();

export const world = () => W;

export async function loadWorld(name) {
  let w = {};
  try {
    const r = await fetch(`world?scene=${encodeURIComponent(name)}`, { cache: 'no-store' });
    if (r.ok) w = await r.json();
  } catch (_) { /* an older server, or offline: an empty world (no actors, floor 0) */ }
  for (const k of Object.keys(W)) delete W[k];
  Object.assign(W, EMPTY(), w);
  return W;
}
