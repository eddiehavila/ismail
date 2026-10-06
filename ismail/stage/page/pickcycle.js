// Pinch again at the same point: the next thing under it. A person's box covers what they hold and what stands near
// them, so a pinch there always gave the person (the user, 2026-10-05, at the bartender: "pinching again at the same
// point should cycle through every object under that point"). One cycle for the ray and the fingers, for selecting
// and for moving.
const SAME_M = 0.06;        // metres: this close to the last pinch is the same point (further on a long ray)
const SAME_MS = 6000;       // and within this long of it

let last = null, emit = null;
export const setPickEmit = (fn) => { emit = fn; };

// items: what is under the point, the usual pick first (unique, in order); dist: how far the point is from the hand
export function cyclePick(pt, items, how, dist = 0) {
  if (!items || !items.length) return null;
  const now = performance.now(), tol = Math.max(SAME_M, 0.04 * dist);
  let i = 0;
  if (last && now - last.t < SAME_MS && pt.distanceTo(last.pt) < tol) {
    const k = items.indexOf(last.item);
    if (k >= 0) i = (k + 1) % items.length;
  }
  last = { pt: pt.clone(), item: items[i], t: now };
  if (items.length > 1 && emit) emit('pick_cycle', { how, item: items[i].name, n: i + 1, of: items.map((x) => x.name) });
  return items[i];
}
