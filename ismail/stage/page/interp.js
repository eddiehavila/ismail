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

// ---- take playback between recorded samples (actors.js). The user, 2026-10-06 (voice note #20002): playback "looks
// low frame rate and steppy"; a take recorded while the headset ran at 20 to 30 fps has about 20 samples a second,
// and each one was held until the next. mixFrame(a, b, u, out) is the frame u (0..1) of the way from sample a to
// sample b: numbers lerp; a pose array [x, y, z, qx, qy, qz, qw, (radius)] lerps its position and radius and nlerps
// its quaternion the short way (unit quaternions only: other arrays of 7 or 8 numbers just lerp); objects and arrays
// mix field by field; anything else (a gesture name, a hand that is missing in one sample) is the nearer sample's.
// out: the previous result, written in place when its shape matches and mixFrame made it (never a recorded sample
// passed through), so playback makes no garbage per frame on the Quest.
const OWN = new WeakSet();                       // buffers mixFrame made: the only ones it writes into
const own = (o) => { OWN.add(o); return o; };
const isQ = (a) => { const n = a[3] * a[3] + a[4] * a[4] + a[5] * a[5] + a[6] * a[6]; return n > 0.81 && n < 1.21; };

export function mixFrame(a, b, u, out) {
  if (typeof a === 'number') return typeof b === 'number' ? a + (b - a) * u : (u < 0.5 ? a : b);
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || b.length !== a.length) return u < 0.5 ? a : b;
    const o = Array.isArray(out) && out.length === a.length && OWN.has(out) ? out : own(new Array(a.length));
    if (a.length && typeof a[0] === 'number') {
      for (let k = 0; k < a.length; k++) o[k] = a[k] + (b[k] - a[k]) * u;
      if ((a.length === 7 || a.length === 8) && isQ(a) && isQ(b)) {
        const s = a[3] * b[3] + a[4] * b[4] + a[5] * b[5] + a[6] * b[6] < 0 ? -1 : 1;
        let n = 0;
        for (let k = 3; k < 7; k++) { o[k] = a[k] + (s * b[k] - a[k]) * u; n += o[k] * o[k]; }
        n = Math.sqrt(n) || 1;
        for (let k = 3; k < 7; k++) o[k] /= n;
      }
      return o;
    }
    for (let k = 0; k < a.length; k++) o[k] = mixFrame(a[k], b[k], u, o[k]);
    return o;
  }
  if (a && typeof a === 'object') {
    if (!b || typeof b !== 'object' || Array.isArray(b)) return u < 0.5 ? a : b;
    const o = out && typeof out === 'object' && !Array.isArray(out) && OWN.has(out) ? out : own({});
    for (const k in a) o[k] = k in b ? mixFrame(a[k], b[k], u, o[k]) : a[k];
    return o;
  }
  return u < 0.5 ? a : b;
}

// a take frame for playback: only what posing reads (t, head, the hands) is mixed; the rest (the 83-joint body) is
// sample a's. A whole frame took 0.1 ms on the desktop, the body most of it.
const POSED = ['t', 'head', 'left', 'right'];
export function mixTake(a, b, u, out) {
  const o = out && OWN.has(out) ? out : own({});
  for (const k in a) if (!POSED.includes(k)) o[k] = a[k];
  for (const k of POSED) if (k in a) o[k] = k in b ? mixFrame(a[k], b[k], u, o[k]) : a[k];
  return o;
}
