"""Stateful DSP kernels for the live engine: each keeps its memory (filter states, delay lines, envelopes) between
calls, so a signal processed in blocks comes out the same as in one piece. Studio code (ismail/dsp.py) is the source
of truth for what each effect does; these are its block-by-block twins, held to it by tests/test_live_parity.py."""
import numpy as np
from numba import njit

from ..dsp import *  # noqa: F401,F403  (studio helpers and constants the kernels share)
from ..dsp import ALLPASSES, COMBS, FILTER_MODES, SR, as_curve  # noqa: F401


@njit(cache=True)
def svf_s(x, cutoff, res, mode, sr, st):
    """Zavalishin TPT state-variable filter, per-sample cutoff (Hz) and res (0..1).
    mode: 0 lp, 1 hp, 2 bp, 3 notch, 4 peak(allpass-ish). st: [ic1, ic2]."""
    n = len(x)
    y = np.empty(n)
    ic1 = st[0]
    ic2 = st[1]
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
    st[0] = ic1
    st[1] = ic2
    return y


@njit(cache=True)
def ladder_s(x, cutoff, res, drive, sr, st):
    """4-pole Moog-style ladder (Huovilainen-lite), per-sample cutoff/res. res 0..1 (1 ~ self-osc). st: [s0..s3]."""
    n = len(x)
    y = np.empty(n)
    s0 = st[0]
    s1 = st[1]
    s2 = st[2]
    s3 = st[3]
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
    st[0] = s0
    st[1] = s1
    st[2] = s2
    st[3] = s3
    return y


def filt_state():
    """State for filt_s (enough for every filter type)."""
    return np.zeros(4)


def filt_s(x, ftype, cutoff, res, sr, drive, st):
    """filt with its state carried in `st` (from filt_state())."""
    n = len(x)
    c = as_curve(cutoff, n)
    r = as_curve(res, n)
    if ftype == 'ladder':
        return ladder_s(x, c, r, float(drive), float(sr), st)
    base = ftype.rstrip('0123456789') or 'lp'
    if base not in FILTER_MODES:
        raise ValueError(f"unknown filter type {ftype!r}: use lp12 lp24 hp12 hp24 bp notch ladder")
    mode = FILTER_MODES[base]
    y = svf_s(x, c, r, mode, float(sr), st[0:2])
    if ftype.endswith('24'):
        # second stage at low resonance keeps the peak sane
        y = svf_s(y, c, r * 0.5, mode, float(sr), st[2:4])
    return y


@njit(cache=True)
def sos_s(x, sos, zi):
    """Cascaded biquads (second-order sections, a0 = 1) on x (channels, n), transposed direct form II like
    scipy.signal.sosfilt; zi (sections, channels, 2) is the state, updated in place."""
    c, n = x.shape
    k = sos.shape[0]
    y = np.empty((c, n))
    for ch in range(c):
        for i in range(n):
            v = x[ch, i]
            for s in range(k):
                o = sos[s, 0] * v + zi[s, ch, 0]
                zi[s, ch, 0] = sos[s, 1] * v - sos[s, 4] * o + zi[s, ch, 1]
                zi[s, ch, 1] = sos[s, 2] * v - sos[s, 5] * o
                v = o
            y[ch, i] = v
    return y


@njit(cache=True)
def lfilter_s(x, b, a, zi):
    """scipy.signal.lfilter along the last axis of x (channels, n) for a0 = 1 and len(a) == len(b) (pad with
    zeros); zi (channels, len(b) - 1) is the state, updated in place."""
    c, n = x.shape
    m = len(b) - 1
    y = np.empty((c, n))
    for ch in range(c):
        for i in range(n):
            v = x[ch, i]
            o = b[0] * v + (zi[ch, 0] if m > 0 else 0.0)
            for j in range(m - 1):
                zi[ch, j] = b[j + 1] * v - a[j + 1] * o + zi[ch, j + 1]
            if m > 0:
                zi[ch, m - 1] = b[m] * v - a[m] * o
            y[ch, i] = o
    return y


@njit(cache=True)
def env_follow_s(x, attack_s, release_s, sr, st):
    n = len(x)
    a = np.exp(-1.0 / max(attack_s * sr, 1.0))
    r = np.exp(-1.0 / max(release_s * sr, 1.0))
    e = st[0]
    out = np.empty(n)
    for i in range(n):
        v = abs(x[i])
        c = a if v > e else r
        e = c * e + (1.0 - c) * v
        out[i] = e
    st[0] = e
    return out


@njit(cache=True)
def smooth_gain_s(gr_db, attack_s, release_s, sr, st):
    """Smooth gain reduction (dB, <=0): attack when reducing more, release when recovering. st: [g]."""
    n = len(gr_db)
    a = np.exp(-1.0 / max(attack_s * sr, 1.0))
    r = np.exp(-1.0 / max(release_s * sr, 1.0))
    g = st[0]
    out = np.empty(n)
    for i in range(n):
        c = a if gr_db[i] < g else r
        g = c * g + (1 - c) * gr_db[i]
        out[i] = g
    st[0] = g
    return out


@njit(cache=True)
def mod_delay_s(x, delay_samps, feedback, mix, buf, st):
    """Delay line with per-sample fractional delay (samples). Used for chorus/flanger/vibrato.
    buf: circular buffer at least the largest delay + 2 long; st: [write index]."""
    n = len(x)
    size = len(buf)
    y = np.empty(n)
    w = int(st[0])
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
    st[0] = w
    return y


@njit(cache=True)
def feedback_delay_s(xl, xr, dsamp, fb, pingpong, lp_coef, bl, br, st):
    """bl, br: buffers of dsamp + 1; st: [write index, lowpass state L, lowpass state R]."""
    n = len(xl)
    size = dsamp + 1
    yl = np.empty(n)
    yr = np.empty(n)
    w = int(st[0])
    fl = st[1]
    fr = st[2]
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
    st[0] = w
    st[1] = fl
    st[2] = fr
    return yl, yr


@njit(cache=True)
def _comb_s(x, fb, damp, buf, st):
    """st: [index, damping store]."""
    n = len(x)
    d = len(buf)
    y = np.empty(n)
    idx = int(st[0])
    store = st[1]
    for i in range(n):
        o = buf[idx]
        store = o * (1 - damp) + store * damp
        buf[idx] = x[i] + store * fb
        y[i] = o
        idx = (idx + 1) % d
    st[0] = idx
    st[1] = store
    return y


@njit(cache=True)
def _allpass_s(x, fb, buf, st):
    n = len(x)
    d = len(buf)
    y = np.empty(n)
    idx = int(st[0])
    for i in range(n):
        b = buf[idx]
        y[i] = -x[i] + b
        buf[idx] = x[i] + b * fb
        idx = (idx + 1) % d
    st[0] = idx
    return y


class Freeverb:
    """Freeverb on a mono input -> (L, R) wet, keeping its state between calls."""

    def __init__(self, size=0.8, damp=0.4, sr=SR, spread=23):
        scale = sr / 44100
        self.fb = 0.7 + 0.28 * size
        self.damp = damp
        self.sides = []
        for sp in (0, spread):
            combs = [(np.zeros(int((c + sp) * scale)), np.zeros(2)) for c in COMBS]
            aps = [(np.zeros(int((a + sp) * scale)), np.zeros(1)) for a in ALLPASSES]
            self.sides.append((combs, aps))

    def process(self, x):
        outs = []
        for combs, aps in self.sides:
            acc = np.zeros(len(x))
            for buf, st in combs:
                acc += _comb_s(x, self.fb, self.damp, buf, st)
            for buf, st in aps:
                acc = _allpass_s(acc, 0.5, buf, st)
            outs.append(acc * 0.03)
        return outs[0], outs[1]


@njit(cache=True)
def allpass1_chain_s(x, coef, stages, feedback, z, st):
    """Phaser: chain of first-order allpasses with per-sample coefficient. z: (stages,), st: [last output]."""
    n = len(x)
    y = np.empty(n)
    last = st[0]
    for i in range(n):
        s = x[i] + last * feedback
        a = coef[i]
        for k in range(stages):
            o = a * s + z[k]
            z[k] = s - a * o
            s = o
        last = s
        y[i] = s
    st[0] = last
    return y
