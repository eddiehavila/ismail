"""Takes and the music: measure how a take keeps time, cut whole-bar loops out of it, and put its hits on the beat.
Ported from the film session's tools (songs/crossroads/video/sync_measure.py, loop_cut.py, beat_warp.py), with the
parameters tuned live with the user in bluefront on 2026-10-05 and 06 (ledger:M145). Small numpy over a few thousand
samples: no scene, no page, no render.

An animation here is {name, hz, channels: {name: array (n, 3)}}: a take's head and both wrists (three.js metres, Y
up). What is read off one:
- pulse: the period of its main repeating motion (autocorrelation of its movement, 0.25 to 3 s) and how clear it is
  (0 none, 1 a perfect repeat);
- seam: how far and how fast it jumps when it wraps (last sample to first), against its typical step;
- against a song (bpm): the playback rate that puts the pulse on 1/2, 1, 2 or 4 beats, the length in bars at that
  rate, and where its low points ("the down of a bounce") fall;
- between two takes: the lag of one behind the other in beats (cross-correlation of their movement).
New takes (a loop cut, a beat warp) are written beside the source, silent: the copy drops the performance link (a
borrowed take carries the performer's voice) and the trim.
"""
import json
import math
import re
import time
from pathlib import Path

import numpy as np

NAME_RE = re.compile(r'[A-Za-z0-9_\-]{1,48}')
DROP = ('performance', 'perf_scene', 'perf_shift', 'trim', 'kept', 'label', 'notes')


# ---- reading
def frames(d):
    """A take's frames (those with a head), in order."""
    out = [json.loads(ln) for ln in open(Path(d) / 'frames.jsonl', encoding='utf-8') if ln.strip()]
    return [f for f in out if f.get('head')]


def meta(d):
    f = Path(d) / 'meta.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.is_file() else {}


def read_take(d, trim=True):
    """The head and both wrists as position channels; a wrist missing in a frame keeps its last place (the head's at
    first). trim=True: only the take's saved trim (meta.trim, what plays)."""
    m, fr = meta(d), frames(d)
    if len(fr) < 3:
        raise ValueError(f'{Path(d).name} has {len(fr)} frames')
    head, lw, rw = [], [], []
    last = {'left': None, 'right': None}
    for f in fr:
        head.append(f['head'][:3])
        for side, out in (('left', lw), ('right', rw)):
            h = f.get(side)
            p = h['j'][0][:3] if h and h.get('j') else last[side]
            last[side] = p
            out.append(p if p is not None else f['head'][:3])
    ts = np.array([f['t'] for f in fr], float)
    ts -= ts[0]
    hz = float((len(ts) - 1) / ts[-1]) if ts[-1] > 0 else float(m.get('hz') or 30)
    ch = {'head': np.array(head, float), 'wrist_l': np.array(lw, float), 'wrist_r': np.array(rw, float)}
    t0 = 0.0
    if trim and m.get('trim'):
        a, b = int(m['trim'][0] * hz), int(m['trim'][1] * hz)
        ch = {k: v[a:b] for k, v in ch.items()}
        t0 = a / hz
    return {'name': m.get('name') or Path(d).name, 'hz': hz, 'channels': ch, 't0': t0}


# ---- the movement signal: how much it moves per sample, all channels, each normalised
def movement(anim):
    hz, sig = anim['hz'], None
    for k, v in anim['channels'].items():
        sp = np.linalg.norm(np.diff(v, axis=0), axis=1) * hz
        if k == 'head':                                              # a bounce: the head's height carries the beat
            y = v[1:, 1] - np.convolve(v[:, 1], np.ones(15) / 15, mode='same')[1:]
            sp = sp + 4.0 * np.abs(np.gradient(y) * hz)
        sp = (sp - sp.mean()) / (sp.std() + 1e-9)
        sig = sp if sig is None else sig + sp
    return sig / max(1, len(anim['channels']))


def pulse(sig, hz, lo=0.25, hi=3.0):
    """The main repeat period (s) and its clarity (autocorrelation peak, 0 to 1)."""
    s = sig - sig.mean()
    n = len(s)
    ac = np.correlate(s, s, mode='full')[n - 1:]
    ac = ac / (ac[0] + 1e-9)
    a, b = int(lo * hz), min(int(hi * hz), n - 2)
    if b <= a + 2:
        return None, 0.0
    seg = ac[a:b]
    peaks = [i for i in range(1, len(seg) - 1) if seg[i] > seg[i - 1] and seg[i] >= seg[i + 1] and seg[i] > 0.1]
    if not peaks:
        return None, 0.0
    i = max(peaks, key=lambda i: seg[i] - 0.15 * (i / len(seg)))     # strongest, a little bias to the shorter one
    j = i + a
    d = 0.0
    if 1 <= j < len(ac) - 1:                                          # parabolic refinement of the lag
        y0, y1, y2 = ac[j - 1], ac[j], ac[j + 1]
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)
    return (j + d) / hz, float(seg[i])


def seam(anim):
    """The jump when it wraps: position and speed change last -> first, against the median step, per channel."""
    out = {}
    for k, v in anim['channels'].items():
        step = np.median(np.linalg.norm(np.diff(v, axis=0), axis=1)) + 1e-9
        jump = np.linalg.norm(v[0] - v[-1])
        out[k] = {'jump_cm': round(100 * float(jump), 1), 'x_step': round(float(jump / step), 1),
                  'speed_jump_cm_s': round(100 * float(np.linalg.norm((v[1] - v[0]) - (v[-1] - v[-2]))) * float(anim['hz']), 1)}
    return out


def lows(sig, hz, period):
    """Times (s) of the movement's low points, one per period: the down of each step."""
    w = max(3, int(period * hz * 0.5))
    sm = np.convolve(sig, np.ones(5) / 5, mode='same')
    return [i / hz for i in range(w, len(sm) - w) if sm[i] == sm[i - w:i + w + 1].min()]


def against_song(anim, sig, bpm, rate_range=(0.7, 1.4)):
    hz = anim['hz']
    length = (len(sig) + 1) / hz
    per, clar = pulse(sig, hz)
    beat = 60.0 / bpm
    res = {'seconds': round(length, 3), 'pulse_s': per and round(per, 3), 'pulse_clarity': round(clar, 2)}
    if not per:
        return res
    res['own_bpm'] = round(60 / per, 1)
    best = None                                                      # the rate nearest 1 that puts the pulse on k beats
    for k in (0.5, 1, 2, 4):
        r = per / (k * beat)
        if rate_range[0] <= r <= rate_range[1] and (best is None or abs(math.log(r)) < abs(math.log(best[1]))):
            best = (k, r)
    if best:
        k, r = best
        bars = length / r / (4 * beat)
        off = (bars * 4) % k
        res.update({'pulse_beats': k, 'rate': round(r, 3), 'loop_bars_at_rate': round(bars, 2),
                    'loop_seam_off_grid_beats': round(off if off < k / 2 else off - k, 2)})
        lo = lows(sig, hz, per)
        if lo:
            res['first_low_s'] = round(lo[0], 3)
            res['start_offset_beats'] = round((lo[0] / r) / beat % k, 2)
    return res


def lag(sig_a, ra, sig_b, rb, hz, bpm):
    """The lag of b behind a (beats) at their playback rates, and how well their movement matches (0 to 1)."""
    t = np.arange(0, min(len(sig_a) / ra, len(sig_b) / rb) / hz, 1 / hz)
    a = np.interp(t * ra * hz, np.arange(len(sig_a)), sig_a)
    b = np.interp(t * rb * hz, np.arange(len(sig_b)), sig_b)
    a, b = a - a.mean(), b - b.mean()
    cc = np.correlate(b, a, mode='full')
    k = int(np.argmax(cc)) - (len(a) - 1)
    return round(k / hz / (60 / bpm), 2), round(float(cc.max() / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)), 2)


def measure(dirs, bpm):
    """Each take against the song, its seam, and every pair's lag."""
    rows, sigs = [], []
    for d in dirs:
        an = read_take(d)
        sig = movement(an)
        rows.append({'take': Path(d).name, **against_song(an, sig, bpm), 'seam': seam(an)})
        sigs.append((sig, rows[-1].get('rate', 1.0), an['hz']))
    pairs = []
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            (sa, ra, hz), (sb, rb, _) = sigs[i], sigs[j]
            lb, c = lag(sa, ra, sb, rb, hz, bpm)
            pairs.append({'a': rows[i]['take'], 'b': rows[j]['take'], 'lag_beats': lb, 'match': c})
    return {'bpm': bpm, 'takes': rows, 'pairs': pairs}


def best_loops(d, bpm, bars=(2, 3, 4), top=4, step_s=0.25, seam_w=0.25, drift_w=1.5):
    """Whole-bar windows of a long take (at rate 1, so they stay on the song's grid), scored by a clear pulse on 1/2,
    1 or 2 beats, a small seam, enough movement and (drift_w) little travel on the floor (the user, 2026-10-06: Earl's
    loop "moves forward"). Returns the best distinct windows, times in the take's own seconds."""
    an = read_take(d)
    hz, beat = an['hz'], 60.0 / bpm
    n = len(an['channels']['head'])
    out = []
    for nb in bars:
        w = int(round(nb * 4 * beat * hz))
        for s in range(0, n - w, max(1, int(step_s * hz))):
            sub = {'hz': hz, 'channels': {k: v[s:s + w] for k, v in an['channels'].items()}}
            per, clar = pulse(movement(sub), hz)
            if not per:
                continue
            k = min((0.5, 1, 2), key=lambda k: abs(math.log(per / (k * beat))))
            off = abs(math.log(per / (k * beat)))
            jump = float(np.mean([v['x_step'] for v in seam(sub).values()]))
            energy = float(np.mean([np.linalg.norm(np.diff(v, axis=0), axis=1).mean() * hz for v in sub['channels'].values()]))
            hd = sub['channels']['head']
            drift = float(np.hypot(*(hd[-1, [0, 2]] - hd[0, [0, 2]])))
            wander = float(np.ptp(hd[:, 0]) + np.ptp(hd[:, 2]))
            score = clar - 2.0 * off - seam_w * jump + 0.2 * min(energy, 1.0) - drift_w * (drift + 0.5 * wander)
            t0 = an['t0']
            out.append({'start': round(float(t0 + s / hz), 2), 'end': round(float(t0 + (s + w) / hz), 2), 'bars': nb, 'score': round(score, 3),
                        'pulse_beats': k, 'pulse_off_pct': round(100 * (math.exp(off) - 1), 1), 'clarity': round(clar, 2),
                        'seam_x_step': round(jump, 1), 'energy_m_s': round(energy, 2), 'drift_m': round(drift, 2)})
    out.sort(key=lambda r: -r['score'])
    picked = []
    for r in out:                                                    # distinct: no two overlapping by half
        ln = r['end'] - r['start']
        if all(min(r['end'], p['end']) - max(r['start'], p['start']) < 0.5 * ln for p in picked):
            picked.append(r)
        if len(picked) >= top:
            break
    return picked


# ---- writing new takes
def mix(x, y, w):
    """x toward y by w: pose arrays [x, y, z, qx, qy, qz, qw, (r)] lerp and nlerp the short way; lists and dicts field
    by field; anything else the nearer one."""
    if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        if len(x) in (7, 8) and all(isinstance(v, (int, float)) for v in x + y):
            qa, qb = x[3:7], y[3:7]
            if sum(a * b for a, b in zip(qa, qb)) < 0:
                qb = [-v for v in qb]
            q = [qa[i] + (qb[i] - qa[i]) * w for i in range(4)]
            n = math.sqrt(sum(v * v for v in q)) or 1.0
            out = [x[i] + (y[i] - x[i]) * w for i in range(3)] + [v / n for v in q]
            if len(x) == 8:
                out.append(x[7] + (y[7] - x[7]) * w)
            return out
        return [mix(a, b, w) for a, b in zip(x, y)]
    if isinstance(x, dict) and isinstance(y, dict):
        return {k: (mix(x[k], y[k], w) if k in y else x[k]) for k in x}
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
        return x + (y - x) * w
    return y if w >= 0.5 else x


def _write(src, name, out, extra):
    if not NAME_RE.fullmatch(name or ''):
        raise ValueError(f'name {name!r}: letters, digits, _ and -, up to 48')
    tid = time.strftime('%Y%m%d_%H%M%S') + '_' + name
    d = Path(src).parent / tid
    if d.exists():
        raise ValueError(f'{tid} exists already')
    d.mkdir()
    with open(d / 'frames.jsonl', 'w', encoding='utf-8') as fh:
        for f in out:
            fh.write(json.dumps(f) + '\n')
    m = {k: v for k, v in meta(src).items() if k not in DROP}
    m.update({'id': tid, 'name': name, 'frames': len(out), 'seconds': out[-1]['t'], 'from_take': Path(src).name, **extra})
    (d / 'meta.json').write_text(json.dumps(m, indent=1), encoding='utf-8')
    return tid, m


def cut(src, name, a, b, blend=0.4, by='stage_take_loop'):
    """The window [a, b) (the take's seconds) as a new take. blend > 0 makes it a loop: the last `blend` seconds
    cross-fade (smooth 0 -> 1) into the frames just before a, so the frame after the last is the take's own frame
    before the first: the wrap is continuous in position and speed."""
    fr = frames(src)
    t0 = fr[0]['t']
    ts = [f['t'] - t0 for f in fr]
    if not 0 <= a < b:
        raise ValueError(f'the window [{a}, {b}] must have 0 <= start < end')
    ia = next((i for i, t in enumerate(ts) if t >= a), None)
    ib = next((i for i, t in enumerate(ts) if t >= b), len(fr))
    if ia is None or ib - ia < 4:
        raise ValueError(f'the window [{a}, {b}] holds {0 if ia is None else ib - ia} frames (the take is {ts[-1]:.2f} s)')
    out = [dict(f) for f in fr[ia:ib]]
    k = 0
    if blend > 0:
        hz = (len(fr) - 1) / (ts[-1] or 1)
        k = min(max(2, int(round(blend * hz))), ia, len(out) // 3)
        for j in range(k):
            w = 0.5 - 0.5 * math.cos(math.pi * (j + 1) / k)
            tail, pre = out[len(out) - k + j], fr[ia - k + j]
            for key in ('head', 'left', 'right', 'body'):
                if tail.get(key) is not None and pre.get(key) is not None:
                    tail[key] = mix(tail[key], pre[key], w)
    s = out[0]['t']
    for f in out:
        f['t'] = round(f['t'] - s, 4)
    tid, m = _write(src, name, out, {'from_window': [a, b], 'loop_blend_s': round(k / ((len(fr) - 1) / (ts[-1] or 1)), 3) if k else 0,
                                      'cut_by': by})
    return tid, m, seam(read_take(Path(src).parent / tid, trim=False))


def hits(anim, beat, min_gap_beats=0.6):
    """Accents: peaks of acceleration magnitude summed over the channels (each normalised to median..p90), over 0.8 a
    channel, at least min_gap_beats apart (the stronger kept). Seconds from the start, and the summed signal."""
    hz, acc = anim['hz'], None
    for v in anim['channels'].values():
        a = np.linalg.norm(np.gradient(np.gradient(v, axis=0), axis=0), axis=1) * hz * hz
        a = np.convolve(a, np.ones(3) / 3, mode='same')
        a = (a - np.median(a)) / (np.percentile(a, 90) - np.median(a) + 1e-9)
        acc = a if acc is None else acc + a
    gap = max(1, int(min_gap_beats * beat * hz))
    out = []
    for i in range(1, len(acc) - 1):
        if acc[i] >= acc[i - 1] and acc[i] > acc[i + 1] and acc[i] > 0.8 * len(anim['channels']):
            if out and i - out[-1] < gap:
                if acc[i] > acc[out[-1]]:
                    out[-1] = i
                continue
            out.append(i)
    return [i / hz for i in out], acc


def warp_map(hit_t, length, target_len, beat, sub=1.0, lo=0.75, hi=1.33):
    """Source -> target time knots: the take scaled to target_len, then each hit moved to the nearest grid point (sub
    beats), skipping a hit whose segment would run under lo or over hi times the scaled speed."""
    s = target_len / length
    grid = beat * sub
    src, dst = [0.0], [0.0]
    for h in hit_t:
        g = round(h * s / grid) * grid
        if g <= dst[-1] + 1e-6 or g >= target_len - 1e-6:
            continue
        if lo <= (h - src[-1]) / (g - dst[-1]) * s <= hi:
            src.append(h)
            dst.append(g)
    src.append(length)
    dst.append(target_len)
    return np.array(src), np.array(dst)


def warp(src, name, bpm, bars=2, sub=1.0, hz=30.0, by='stage_take_warp'):
    """The take as a loop of exactly `bars` bars at bpm, its time warped piecewise-linearly so each hit lands on the
    nearest beat (sub=0.5: half beat), resampled at hz with the frames between samples mixed."""
    beat = 60.0 / bpm
    an = read_take(src, trim=False)
    fr = frames(src)
    t0 = fr[0]['t']
    ts = np.array([f['t'] - t0 for f in fr])
    length, target = float(ts[-1]), bars * 4 * beat
    if not 0.5 <= target / length <= 2.0:
        raise ValueError(f'{bars} bars at {bpm} BPM is {target:.2f} s, the take {length:.2f} s: more than 2x apart '
                         '(cut a window of about that length first, stage_take_loop)')
    ht, _ = hits(an, beat)
    ks, kd = warp_map(ht, length, target, beat, sub)
    out = []
    for j in range(int(round(target * hz))):
        tt = j / hz
        s_ = float(np.interp(tt, kd, ks))
        i = max(0, min(int(np.searchsorted(ts, s_, side='right') - 1), len(fr) - 2))
        w = min(1.0, max(0.0, (s_ - ts[i]) / max(1e-6, ts[i + 1] - ts[i])))
        f = {'t': round(tt, 4)}
        for key in ('head', 'left', 'right', 'body'):
            a_, b_ = fr[i].get(key), fr[i + 1].get(key)
            if a_ is not None or b_ is not None:
                f[key] = mix(a_, b_, w) if (a_ is not None and b_ is not None) else (a_ if a_ is not None else b_)
        for key in fr[i]:
            f.setdefault(key, fr[i][key])
        out.append(f)
    on_grid = [round(float(np.interp(h, ks, kd)) / (beat * sub), 2) for h in ht]
    bw = {'bpm': bpm, 'bars': bars, 'sub': sub, 'hits_src_s': [round(h, 3) for h in ht],
          'knots_src': [round(float(x), 3) for x in ks], 'knots_dst': [round(float(x), 3) for x in kd], 'hits_on_grid_units': on_grid}
    tid, m = _write(src, name, out, {'hz': hz, 'seconds': round(target, 4), 'beat_warp': bw, 'cut_by': by})
    return tid, m, bw
