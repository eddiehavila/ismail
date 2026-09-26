"""Low-level DSP kernels (numba). Everything is float64 mono unless noted; stereo = shape (2, n)."""
import numpy as np
from numba import njit

SR = 44100


def as_curve(x, n):
    """Scalar or array -> float64 array of length n."""
    if np.isscalar(x):
        return np.full(n, float(x))
    a = np.asarray(x, dtype=np.float64)
    if len(a) >= n:
        return a[:n]
    return np.concatenate([a, np.full(n - len(a), a[-1] if len(a) else 0.0)])


# ---------------------------------------------------------------- oscillators

def poly_blep(t, dt):
    """Vectorised polyBLEP residual. t = phase in [0,1), dt = phase increment."""
    dt = np.maximum(dt, 1e-9)
    r = np.zeros_like(t)
    a = t < dt
    x = t[a] / dt[a]
    r[a] = x + x - x * x - 1.0
    b = t > 1.0 - dt
    x = (t[b] - 1.0) / dt[b]
    r[b] = x * x + x + x + 1.0
    return r


def osc(wave, phase, dt, pw=0.5):
    """phase: cumulative phase in cycles (float array). dt: per-sample increment (cycles). Returns [-1,1]."""
    t = np.mod(phase, 1.0)
    if wave == 'sine':
        return np.sin(2 * np.pi * t)
    if wave == 'saw':
        return 2.0 * t - 1.0 - poly_blep(t, dt)
    if wave == 'square' or wave == 'pulse':
        pwv = np.clip(as_curve(pw, len(t)), 0.02, 0.98)
        t2 = np.mod(t + (1 - pwv), 1.0)
        s1 = 2.0 * t - 1.0 - poly_blep(t, dt)
        s2 = 2.0 * t2 - 1.0 - poly_blep(t2, dt)
        y = s1 - s2
        return y - np.mean(y) if len(y) else y
    if wave == 'triangle':
        return 4.0 * np.abs(t - 0.5) - 1.0
    raise ValueError(f"unknown wave {wave!r}")


def additive(phase, dt, partials):
    """Sum of sine partials; partials = [amp_h1, amp_h2, ...]. Skips partials above Nyquist."""
    y = np.zeros_like(phase)
    maxdt = float(np.max(dt)) if len(dt) else 0.0
    for k, a in enumerate(partials, 1):
        if a == 0 or k * maxdt >= 0.5:
            continue
        y += a * np.sin(2 * np.pi * k * phase)
    return y


def table_osc(phase, table):
    """Single-cycle wavetable lookup with linear interpolation."""
    tbl = np.asarray(table, dtype=np.float64)
    n = len(tbl)
    idx = np.mod(phase, 1.0) * n
    i0 = idx.astype(np.int64) % n
    frac = idx - np.floor(idx)
    return tbl[i0] * (1 - frac) + tbl[(i0 + 1) % n] * frac


@njit(cache=True)
def pink_noise(n, seed):
    np.random.seed(seed)
    b0 = b1 = b2 = b3 = b4 = b5 = b6 = 0.0
    out = np.empty(n)
    for i in range(n):
        w = np.random.randn()
        b0 = 0.99886 * b0 + w * 0.0555179
        b1 = 0.99332 * b1 + w * 0.0750759
        b2 = 0.96900 * b2 + w * 0.1538520
        b3 = 0.86650 * b3 + w * 0.3104856
        b4 = 0.55000 * b4 + w * 0.5329522
        b5 = -0.7616 * b5 - w * 0.0168980
        out[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11
        b6 = w * 0.115926
    return out


# ---------------------------------------------------------------- filters

@njit(cache=True)
def svf(x, cutoff, res, mode, sr):
    """Zavalishin TPT state-variable filter, per-sample cutoff (Hz) and res (0..1).
    mode: 0 lp, 1 hp, 2 bp, 3 notch, 4 peak(allpass-ish)."""
    n = len(x)
    y = np.empty(n)
    ic1 = 0.0
    ic2 = 0.0
    for i in range(n):
        fc = min(max(cutoff[i], 10.0), sr * 0.49)
        g = np.tan(np.pi * fc / sr)
        k = 2.0 - 2.0 * min(max(res[i], 0.0), 0.995)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        v3 = x[i] - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        if mode == 0:
            y[i] = v2
        elif mode == 1:
            y[i] = x[i] - k * v1 - v2
        elif mode == 2:
            y[i] = v1
        elif mode == 3:
            y[i] = x[i] - k * v1
        else:
            y[i] = x[i] - 2.0 * k * v1
    return y


@njit(cache=True)
def ladder(x, cutoff, res, drive, sr):
    """4-pole Moog-style ladder (Huovilainen-lite), per-sample cutoff/res. res 0..1 (1 ~ self-osc)."""
    n = len(x)
    y = np.empty(n)
    s0 = s1 = s2 = s3 = 0.0
    for i in range(n):
        fc = min(max(cutoff[i], 10.0), sr * 0.45)
        g = np.tan(np.pi * fc / sr)
        G = g / (1.0 + g)
        k = 4.0 * min(max(res[i], 0.0), 1.0)
        inp = np.tanh(drive * (x[i] - k * s3))
        v = (inp - s0) * G
        l0 = v + s0
        s0 = l0 + v
        v = (l0 - s1) * G
        l1 = v + s1
        s1 = l1 + v
        v = (l1 - s2) * G
        l2 = v + s2
        s2 = l2 + v
        v = (l2 - s3) * G
        l3 = v + s3
        s3 = l3 + v
        y[i] = l3
    return y


FILTER_MODES = {'lp': 0, 'hp': 1, 'bp': 2, 'notch': 3, 'peak': 4}


def filt(x, ftype, cutoff, res, sr=SR, drive=1.0):
    """ftype: lp12 lp24 hp12 hp24 bp notch ladder. cutoff/res scalar or per-sample arrays."""
    n = len(x)
    c = as_curve(cutoff, n)
    r = as_curve(res, n)
    if ftype == 'ladder':
        return ladder(x, c, r, float(drive), float(sr))
    base = ftype.rstrip('0123456789') or 'lp'
    if base not in FILTER_MODES:
        raise ValueError(f"unknown filter type {ftype!r}: use lp12 lp24 hp12 hp24 bp notch ladder")
    mode = FILTER_MODES[base]
    y = svf(x, c, r, mode, float(sr))
    if ftype.endswith('24'):
        # second stage at low resonance keeps the peak sane
        y = svf(y, c, r * 0.5, mode, float(sr))
    return y


# ---------------------------------------------------------------- dynamics

@njit(cache=True)
def env_follow(x, attack_s, release_s, sr):
    n = len(x)
    a = np.exp(-1.0 / max(attack_s * sr, 1.0))
    r = np.exp(-1.0 / max(release_s * sr, 1.0))
    e = 0.0
    out = np.empty(n)
    for i in range(n):
        v = abs(x[i])
        c = a if v > e else r
        e = c * e + (1.0 - c) * v
        out[i] = e
    return out


@njit(cache=True)
def gain_computer(level_db, thresh, ratio, knee):
    n = len(level_db)
    gr = np.empty(n)
    for i in range(n):
        over = level_db[i] - thresh
        if knee > 0 and abs(over) <= knee / 2:
            gr[i] = (1.0 / ratio - 1.0) * (over + knee / 2) ** 2 / (2 * knee)
        elif over > knee / 2:
            gr[i] = (1.0 / ratio - 1.0) * over
        else:
            gr[i] = 0.0
    return gr


@njit(cache=True)
def smooth_gain(gr_db, attack_s, release_s, sr):
    """Smooth gain reduction (dB, <=0): attack when reducing more, release when recovering."""
    n = len(gr_db)
    a = np.exp(-1.0 / max(attack_s * sr, 1.0))
    r = np.exp(-1.0 / max(release_s * sr, 1.0))
    g = 0.0
    out = np.empty(n)
    for i in range(n):
        c = a if gr_db[i] < g else r
        g = c * g + (1 - c) * gr_db[i]
        out[i] = g
    return out


# ---------------------------------------------------------------- delay-based

@njit(cache=True)
def mod_delay(x, delay_samps, feedback, mix):
    """Delay line with per-sample fractional delay (samples). Used for chorus/flanger/vibrato."""
    n = len(x)
    size = int(np.max(delay_samps)) + 4
    buf = np.zeros(size)
    y = np.empty(n)
    w = 0
    for i in range(n):
        d = delay_samps[i]
        rpos = w - d
        while rpos < 0:
            rpos += size
        i0 = int(rpos)
        frac = rpos - i0
        i1 = (i0 + 1) % size
        wet = buf[i0 % size] * (1 - frac) + buf[i1] * frac
        buf[w] = x[i] + wet * feedback
        y[i] = x[i] * (1 - mix) + wet * mix
        w = (w + 1) % size
    return y


@njit(cache=True)
def feedback_delay(xl, xr, dsamp, fb, pingpong, lp_coef):
    n = len(xl)
    size = dsamp + 1
    bl = np.zeros(size)
    br = np.zeros(size)
    yl = np.empty(n)
    yr = np.empty(n)
    w = 0
    fl = 0.0
    fr = 0.0
    for i in range(n):
        r = (w - dsamp) % size
        ol = bl[r]
        orr = br[r]
        fl = fl + lp_coef * (ol - fl)
        fr = fr + lp_coef * (orr - fr)
        if pingpong:
            bl[w] = 0.5 * (xl[i] + xr[i]) + fr * fb
            br[w] = fl * fb
        else:
            bl[w] = xl[i] + fl * fb
            br[w] = xr[i] + fr * fb
        yl[i] = ol
        yr[i] = orr
        w = (w + 1) % size
    return yl, yr


@njit(cache=True)
def _comb(x, d, fb, damp):
    n = len(x)
    buf = np.zeros(d)
    y = np.empty(n)
    idx = 0
    store = 0.0
    for i in range(n):
        o = buf[idx]
        store = o * (1 - damp) + store * damp
        buf[idx] = x[i] + store * fb
        y[i] = o
        idx = (idx + 1) % d
    return y


@njit(cache=True)
def _allpass(x, d, fb):
    n = len(x)
    buf = np.zeros(d)
    y = np.empty(n)
    idx = 0
    for i in range(n):
        b = buf[idx]
        y[i] = -x[i] + b
        buf[idx] = x[i] + b * fb
        idx = (idx + 1) % d
    return y


COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
ALLPASSES = (556, 441, 341, 225)


def freeverb(x, size=0.8, damp=0.4, sr=SR, spread=23):
    """Freeverb on a mono input -> (L, R) wet."""
    scale = sr / 44100
    fb = 0.7 + 0.28 * size
    outs = []
    for sp in (0, spread):
        acc = np.zeros(len(x))
        for c in COMBS:
            acc += _comb(x, int((c + sp) * scale), fb, damp)
        for a in ALLPASSES:
            acc = _allpass(acc, int((a + sp) * scale), 0.5)
        outs.append(acc * 0.03)
    return outs[0], outs[1]


@njit(cache=True)
def allpass1_chain(x, coef, stages, feedback):
    """Phaser: chain of first-order allpasses with per-sample coefficient."""
    n = len(x)
    z = np.zeros(stages)
    y = np.empty(n)
    last = 0.0
    for i in range(n):
        s = x[i] + last * feedback
        a = coef[i]
        for k in range(stages):
            o = a * s + z[k]
            z[k] = s - a * o
            s = o
        last = s
        y[i] = s
    return y


# ---------------------------------------------------------------- helpers

def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-12))


def undb(d):
    return 10 ** (np.asarray(d) / 20.0)


def pan_gains(pan):
    """Equal-power pan, pan in [-1,1] (scalar or array) -> (gl, gr)."""
    p = (np.clip(pan, -1, 1) + 1) * np.pi / 4
    return np.cos(p) * np.sqrt(2), np.sin(p) * np.sqrt(2)


def lfo_wave(shape, phase):
    t = np.mod(phase, 1.0)
    if shape == 'sine':
        return np.sin(2 * np.pi * t)
    if shape == 'triangle':
        return 1 - 4 * np.abs(t - 0.5)
    if shape == 'saw':
        return 2 * t - 1
    if shape == 'ramp_down':
        return 1 - 2 * t
    if shape == 'square':
        return np.where(t < 0.5, 1.0, -1.0)
    if shape == 'sh':  # sample & hold
        rng = np.random.default_rng(7)
        vals = rng.uniform(-1, 1, int(np.max(phase)) + 2)
        return vals[np.floor(phase).astype(int)]
    raise ValueError(f"unknown lfo shape {shape!r}: sine triangle saw ramp_down square sh")
