"""Close the loop of a recorded take, so a person can dance it on repeat without a jump (the user, 2026-10-04: "close
the loops of movement since we have that animation data").

    python loop_take.py <scene> <take_id> [--min 4] [--max 12] [--blend 0.5]

Finds the window [a, b) whose end pose and motion best match its start (head turn, the hands and the body relative
to the hips, their speeds), plays the frames after b into the first `blend` seconds (a crossfade from the natural
continuation into the start), and takes out the drift over the window (where the hips travelled and how far the head
turned), so the dancer stays on their spot. Writes a new take <take_id>_loop next to the original (never touches it),
without the audio (it would not loop). Prints the window and the seam error before and after.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent


def load(take_dir):
    fr = [json.loads(l) for l in open(take_dir / 'frames.jsonl', encoding='utf-8')]
    return [f for f in fr if f.get('head')]


def hips(f):
    b = f.get('body') or {}
    return np.array(b['hips'][:3]) if 'hips' in b else np.array(f['head'][:3]) - [0, 0.65, 0]


def yaw(q):                                  # three: y up; heading of a quaternion (x, y, z, w)
    x, y, z, w = q
    return math.atan2(2 * (w * y + x * z), 1 - 2 * (y * y + x * x))


def feature(f):
    """Pose in the hips' own frame (position and heading taken out), so a loop matches shape, not place."""
    h, a = hips(f), yaw(f['head'][3:7])
    c, s = math.cos(-a), math.sin(-a)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    pts = [f['head'][:3]]
    for side in ('left', 'right'):
        j = (f.get(side) or {}).get('j')
        pts += [j[0][:3], j[9][:3]] if j and j[0] and len(j) > 9 and j[9] else [f['head'][:3], f['head'][:3]]
    b = f.get('body') or {}
    for k in ('spine-upper', 'left-arm-lower', 'right-arm-lower', 'left-upper-leg', 'right-upper-leg',
              'left-lower-leg', 'right-lower-leg', 'left-foot-ankle', 'right-foot-ankle'):
        pts.append(b[k][:3] if k in b else f['head'][:3])
    return np.concatenate([R @ (np.array(p) - h) for p in pts])


def best_window(F, hz, lo, hi, blend_n):
    n = len(F)
    V = np.vstack([F[1:] - F[:-1], F[-1:] - F[-2:-1]]) * hz
    st = np.linalg.norm(F[1:] - F[:-1], axis=1)       # tracking glitches (a hand lost and found) stay out of a loop
    bad = np.concatenate([[0], np.cumsum(st > 3 * np.percentile(st, 95))])
    best = None
    for a in range(0, n):
        for b in range(a + int(lo * hz), min(n - blend_n, a + int(hi * hz)) + 1):
            if bad[min(b + blend_n, n - 1)] - bad[a]:
                continue
            e = np.linalg.norm(F[b] - F[a]) + 0.08 * np.linalg.norm(V[b] - V[a])
            e += 0.002 * (b - a) / hz * -1               # a little preference for longer loops
            if best is None or e < best[0]:
                best = (e, a, b)
    return best


def lerp_q(q0, q1, w):
    q0, q1 = np.array(q0), np.array(q1)
    if np.dot(q0, q1) < 0:
        q1 = -q1
    q = q0 * (1 - w) + q1 * w
    return list(q / (np.linalg.norm(q) or 1))


def mix(f0, f1, w):
    """f0 -> f1 by w: positions lerped, quaternions nlerped; every [x,y,z,qx,qy,qz,qw(,r)] row alike."""
    def row(r0, r1):
        if not r0 or not r1:
            return r0 or r1
        out = [r0[i] * (1 - w) + r1[i] * w for i in range(3)] + lerp_q(r0[3:7], r1[3:7], w)
        return out + list(r0[7:])
    g = dict(f0)
    g['head'] = row(f0['head'], f1['head'])
    for side in ('left', 'right'):
        if f0.get(side) and f1.get(side) and f0[side].get('j') and f1[side].get('j'):
            g[side] = dict(f0[side], j=[row(x, y) for x, y in zip(f0[side]['j'], f1[side]['j'])])
    if f0.get('body') and f1.get('body'):
        g['body'] = {k: row(v, f1['body'].get(k)) for k, v in f0['body'].items()}
    return g


def transform(f, dpos, dyaw, pivot):
    """Move a frame by -dpos and turn it by -dyaw about the pivot (three y up)."""
    c, s = math.cos(-dyaw), math.sin(-dyaw)
    qy = [0, math.sin(-dyaw / 2), 0, math.cos(-dyaw / 2)]

    def qmul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]

    def row(r):
        if not r:
            return r
        x, y, z = r[0] - dpos[0] - pivot[0], r[1], r[2] - dpos[2] - pivot[2]
        return [c * x + s * z + pivot[0], y, -s * x + c * z + pivot[2]] + qmul(qy, r[3:7]) + list(r[7:])
    g = dict(f)
    g['head'] = row(f['head'])
    for side in ('left', 'right'):
        if f.get(side) and f[side].get('j'):
            g[side] = dict(f[side], j=[row(x) for x in f[side]['j']])
    if f.get('body'):
        g['body'] = {k: row(v) for k, v in f['body'].items()}
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scene')
    ap.add_argument('take')
    ap.add_argument('--min', type=float, default=4.0)
    ap.add_argument('--max', type=float, default=12.0)
    ap.add_argument('--blend', type=float, default=0.5)
    a_ = ap.parse_args()
    src = HERE / 'scenes' / a_.scene / 'takes' / a_.take
    meta = json.loads((src / 'meta.json').read_text(encoding='utf-8'))
    hz = meta.get('hz', 30)
    fr = load(src)
    F = np.array([feature(f) for f in fr])
    bn = max(1, int(a_.blend * hz))
    e, a, b = best_window(F, hz, a_.min, min(a_.max, len(fr) / hz - a_.blend), bn)
    L = b - a
    raw_seam = float(np.linalg.norm(F[b - 1] - F[a]))
    h0, h1 = hips(fr[a]), hips(fr[b])
    drift = (h1 - h0) * [1, 0, 1]
    turn = yaw(fr[b]['head'][3:7]) - yaw(fr[a]['head'][3:7])
    turn = (turn + math.pi) % (2 * math.pi) - math.pi
    out = []
    for i in range(L):
        f = fr[a + i]
        if i < bn:                                   # the continuation after b (brought back to the start's place
            f = mix(transform(fr[b + i], drift, turn, h0), fr[a + i], i / bn)   # and heading) fades into the start
        out.append(f)
    for i in range(L):                               # spread the drift and the turn over the loop, so it closes
        k = i / L
        out[i] = transform(out[i], drift * k, turn * k, h0)
        out[i]['t'] = round(i / hz, 4)
    G = np.array([feature(f) for f in out])
    seam = float(np.linalg.norm(G[-1] - G[0]))
    step = float(np.median(np.linalg.norm(G[1:] - G[:-1], axis=1)))
    dst = src.parent / (a_.take + '_loop')
    dst.mkdir(exist_ok=True)
    with open(dst / 'frames.jsonl', 'w', encoding='utf-8') as fo:
        for f in out:
            fo.write(json.dumps(f) + '\n')
    m = dict(meta, id=dst.name, name=meta.get('name', '') + ' (loop)', seconds=round(L / hz, 2), frames=L,
             loop_of=a_.take, window_s=[round(a / hz, 2), round(b / hz, 2)], blend_s=a_.blend,
             drift_m=[round(float(x), 3) for x in drift], turn_deg=round(math.degrees(turn), 1), kept=True)
    (dst / 'meta.json').write_text(json.dumps(m, indent=1), encoding='utf-8')
    print(f'{a_.take}: loop {a / hz:.2f}-{b / hz:.2f} s ({L / hz:.2f} s), drift {np.round(drift, 2)} m, '
          f'turn {math.degrees(turn):.0f} deg; seam {raw_seam:.3f} -> {seam:.3f} (a normal frame step is {step:.3f})')


if __name__ == '__main__':
    main()
