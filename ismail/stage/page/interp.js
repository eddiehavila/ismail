// How a keyed object moves between its keys (clock.js), exactly, so the Blender render can do the same (the film
// assistant, 2026-10-05: the stage and the render were 74 cm apart between keys). Per object, anim.json "interp":
//   "stop"    (default) each segment eases in and out (smoothstep): the object stops at every key
//   "smooth"  it glides through the keys: location and scale follow a cubic Hermite curve per segment whose tangent at
//             key i is (p[i+1] - p[i-1]) / (t[i+1] - t[i-1]) (one-sided at the first and last key: the segment's slope),
//             evaluated at u = (t - t[i]) / (t[i+1] - t[i]); the turn slerps at u (no easing)
// The turn always takes the short way: a key's quaternion is negated when its dot with the previous one is negative.
// Pure numbers, no three.js: k(ks, t, mode) answers which segment and how far along it to slerp; vec() the values.

export const ease = (k) => k * k * (3 - 2 * k);

// the segment index i (keys i, i + 1) and u in 0..1 for time t; null outside the keys
export function segment(ks, t) {
  if (ks.length < 2 || t <= ks[0].t || t >= ks[ks.length - 1].t) return null;
  let i = 0;
  while (ks[i + 1].t < t) i++;
  return { i, u: (t - ks[i].t) / Math.max(1e-6, ks[i + 1].t - ks[i].t) };
}

// a location or scale (key field `f`) at time t
export function vec(ks, t, f, mode = 'stop') {
  if (t <= ks[0].t) return ks[0][f].slice();
  if (t >= ks[ks.length - 1].t) return ks[ks.length - 1][f].slice();
  const { i, u } = segment(ks, t), a = ks[i], b = ks[i + 1];
  if (mode !== 'smooth') {
    const k = ease(u);
    return a[f].map((x, j) => x + (b[f][j] - x) * k);
  }
  const h = b.t - a.t;
  const tan = (n) => {
    const p = ks[Math.max(0, n - 1)], q = ks[Math.min(ks.length - 1, n + 1)];
    return p[f].map((x, j) => (q[f][j] - x) / Math.max(1e-6, q.t - p.t));
  };
  const ma = tan(i), mb = tan(i + 1);
  const u2 = u * u, u3 = u2 * u;
  const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
  return a[f].map((x, j) => h00 * x + h10 * h * ma[j] + h01 * b[f][j] + h11 * h * mb[j]);
}

// how far to slerp between keys i and i + 1 at u
export const slerpK = (u, mode = 'stop') => (mode === 'smooth' ? u : ease(u));
