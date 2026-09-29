"""Grand piano voice calibrated from measured reference notes (piano_profile.json).

Per partial: amplitude, prompt/aftersound T60 and aftersound level interpolated between measured notes;
stiff-string inharmonicity and stretch tuning from smooth curves; 1-3 detuned strings by register;
a spaced-pair stereo image (per-partial inter-channel phase and level); hammer/soundboard knock; dampers.
"""
import os, json
import numpy as np
from numba import njit
from ismail import dsp

INFO = {
    "summary": "grand piano calibrated from measured notes: stiff-string partials, 1-3 detuned strings, stereo pair, "
               "hammer knock, dampers",
    "range": "A0-C8",
    "velocity": "hammer strength: louder and brighter",
    "functions": {"voice": "a struck note (dampers fall at note off, above G6 undamped)",
                  "voice_sym": "an undamped string ringing in sympathy: no hammer, slow swell (a halo layer)"},
    "tail": "4.0 s recommended (release rings)",
}

HERE = os.path.dirname(os.path.abspath(__file__))
_PROF = None

# log10 B and stretch (cents) vs MIDI, smoothed from the measurements and standard Railsback curves
B_CURVE = ([21, 36, 45, 48, 60, 72, 84, 96, 108], [-3.5, -4.19, -4.05, -3.89, -3.54, -3.15, -2.7, -2.3, -1.9])
STRETCH = ([21, 36, 48, 60, 72, 84, 96, 108], [-30, -8, -3, 0, 2, 8, 20, 32])
REF_VEL = 0.7
KNOCK = ([21, 48, 72, 96], [-52, -44, -38, -34])
PING = ([21, 76, 80, 84, 96], [0.0, 0.0, 0.5, 2.0, 2.8])
# measured loudness across the keyboard at equal velocity (dB, smoothed)
LOUD = ([21, 36, 48, 60, 72, 84, 96], [5.0, 2.5, 0.0, 0.5, -3.0, -6.0, -8.5])
ATTACK = ([21, 30, 36, 48, 60, 72], [0.04, 0.025, 0.014, 0.009, 0.005, 0.002])


def profile():
    global _PROF
    if _PROF is None:
        raw = json.load(open(os.path.join(HERE, 'grand_piano.json')))
        _PROF = {int(k): v for k, v in raw.items()}
    return _PROF


def _table(d, kmax):
    """Partial table of one measured note -> arrays indexed k=1..kmax (extrapolated past the last measured)."""
    amp = np.full(kmax, -99.0); t60e = np.zeros(kmax); t60l = np.zeros(kmax); late = np.zeros(kmax)
    parts = {p[0]: p for p in d['parts']}
    last = None
    ks = sorted(parts)
    slope = min(-2.0, (parts[ks[-1]][1] - parts[ks[-2]][1]) / (ks[-1] - ks[-2])) if len(ks) > 1 else -6.0
    for k in range(1, kmax + 1):
        if k in parts:
            last = parts[k]
            amp[k - 1], t60e[k - 1], t60l[k - 1], late[k - 1] = last[1], last[2], last[3], last[4]
        elif last is not None:
            gap = k - last[0]
            amp[k - 1] = last[1] + slope * gap
            t60e[k - 1] = last[2] / (1 + 0.15 * gap)
            t60l[k - 1] = last[3] / (1 + 0.15 * gap)
            late[k - 1] = last[4]
    return amp, t60e, t60l, late


def params(m, kmax):
    prof = profile()
    keys = sorted(prof)
    m = float(np.clip(m, keys[0], keys[-1]))
    hi = next(k for k in keys if k >= m)
    lo = max(k for k in keys if k <= m)
    w = 0.0 if hi == lo else (m - lo) / (hi - lo)
    a, b = _table(prof[lo], kmax), _table(prof[hi], kmax)
    amp = (1 - w) * a[0] + w * b[0]
    t60e = np.exp((1 - w) * np.log(np.maximum(a[1], .05)) + w * np.log(np.maximum(b[1], .05)))
    t60l = np.exp((1 - w) * np.log(np.maximum(a[2], .05)) + w * np.log(np.maximum(b[2], .05)))
    late = (1 - w) * a[3] + w * b[3]
    return amp, t60e, t60l, late


@njit(cache=True, fastmath=True)
def _bank(L, sr, f, tau, amp, gl, gr, ph, phr, out):
    for j in range(len(f)):
        w = 2.0 * np.pi * f[j] / sr
        r = np.exp(-1.0 / (tau[j] * sr))
        cw = np.cos(w) * r
        sw = np.sin(w) * r
        re = np.cos(ph[j]) * amp[j]
        im = np.sin(ph[j]) * amp[j]
        cr = np.cos(phr[j]) * gr[j]
        sr_ = np.sin(phr[j]) * gr[j]
        g = gl[j]
        n = L
        nd = int(tau[j] * sr * 9.2) + 1
        if nd < n:
            n = nd
        for i in range(n):
            out[0, i] += g * im
            out[1, i] += cr * im + sr_ * re
            re2 = re * cw - im * sw
            im = re * sw + im * cw
            re = re2


def voice(freq, t, vel, gate, sr, sympathetic=False):
    m = 69 + 12 * np.log2(freq / 440.0)
    rng = np.random.default_rng(int(freq * 1000) ^ int(vel * 9973) ^ int(gate * 7919))
    B = 10 ** np.interp(m, *B_CURVE)
    f0 = freq * 2 ** (np.interp(m, *STRETCH) / 1200)
    fmax = min(10000.0, sr * 0.45)
    kmax = max(1, min(60, int(fmax / f0)))
    amp_db, t60e, t60l, late_db = params(m, kmax)
    nstr = 1 if m < 29 else (2 if m < 41 else 3)
    ping = 0.0 if sympathetic else float(np.interp(m, *PING))
    damped = m < 89
    rel_tau = float(np.interp(m, [21, 45, 72, 89], [0.35, 0.18, 0.1, 0.08]))
    n_total = len(t)
    end = gate + rel_tau * 9.0 if damped else n_total / sr
    L = max(16, int(min(n_total, end * sr)))
    fs, ts, am, gl, gr, ph, phr = [], [], [], [], [], [], []
    for k in range(1, kmax + 1):
        fk = f0 * k * np.sqrt(1.0 + B * k * k)
        if fk > fmax:
            break
        # hammer: brighter when harder than the reference layer, darker when softer
        tilt = (vel - REF_VEL) * 12.0 * np.log2(1.0 + fk / 1000.0)
        a = 10 ** ((amp_db[k - 1] + tilt) / 20)
        if a < 3e-4:
            continue
        # higher partials never outlast the lowest ones (weak partials were measured into the noise floor)
        cap = 20.0 * 500.0 / max(fk, 500.0)
        e60 = min(t60e[k - 1], 1.2 * t60e[:3].max(), cap)
        l60 = min(t60l[k - 1], 1.1 * t60l[:3].max(), 1.5 * cap)
        te = e60 / 6.91
        tl = max(l60, e60) / 6.91
        wl = 1.0 if sympathetic else (0.0 if late_db[k - 1] <= -44 else 10 ** (late_db[k - 1] / 20))
        p = rng.uniform(0, 2 * np.pi)
        # spaced pair: a side signal in quadrature per partial; the mono sum keeps the measured spectrum
        beta = rng.uniform(0.3, 1.4) * rng.choice([-1.0, 1.0])
        th = np.arctan(beta)
        gL = gR = np.sqrt(1 + beta * beta)
        p += th
        dphi = -2 * th
        for s in range(0 if sympathetic else nstr):
            d = (s - (nstr - 1) / 2) * rng.uniform(0.3, 1.2) / 1731.0
            fs.append(fk * (1 + d)); ts.append(te); am.append(a * (1 - wl) / nstr)
            gl.append(gL); gr.append(gR); ph.append(p); phr.append(dphi)
        fs.append(fk * (1 + rng.uniform(-0.4, 0.4) / 1731.0)); ts.append(tl); am.append(a * wl)
        gl.append(gL); gr.append(gR); ph.append(p + rng.uniform(0, 1)); phr.append(-dphi)
        if ping > 0:
            # treble 'ping': energy that leaves the string within the first tens of ms
            fs.append(fk); ts.append(0.012); am.append(a * ping)
            gl.append(gL); gr.append(gR); ph.append(p); phr.append(dphi)
    fs = np.array(fs); ts = np.array(ts); am = np.array(am)
    am /= np.sqrt(np.sum(am ** 2) - np.sum((am * (ts < 0.02)) ** 2)) + 1e-12
    y = np.zeros((2, L))
    _bank(L, float(sr), fs, ts, am, np.array(gl), np.array(gr), np.array(ph), np.array(phr), y)
    # hammer felt noise + keybed thump
    tt = t[:L]
    if not sympathetic:
        na = min(L, int(0.06 * sr))
        knock_db = float(np.interp(m, KNOCK[0], KNOCK[1]))
        kn = rng.standard_normal((2, na)) * np.exp(-tt[:na] / 0.008)
        kn = np.stack([dsp.filt(dsp.filt(c, 'lp12', 1500 + 4000 * vel, 0.0, sr), 'hp12', 90.0, 0.0, sr) for c in kn])
        thump = np.sin(2 * np.pi * 110 * tt[:na]) * np.exp(-tt[:na] / 0.02) * float(np.interp(m, [21, 60, 72], [1.0, 0.4, 0.0]))
        y[:, :na] += (kn + 0.5 * thump) * 10 ** (knock_db / 20) * (0.4 + 0.6 * vel)
    atk = min(L, int((0.06 if sympathetic else float(np.interp(m, ATTACK[0], ATTACK[1]))) * sr))
    y[:, :atk] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, atk))
    if damped:
        k0 = int(gate * sr)
        if k0 < L:
            y[:, k0:] *= np.exp(-(np.arange(L - k0) / sr) / rel_tau)
    pan = float(np.clip((m - 60) / 40, -0.35, 0.35))
    y[0] *= np.sqrt(1 - pan); y[1] *= np.sqrt(1 + pan)
    return y * (0.015 + 0.985 * vel ** 2.0) * 0.25 * 10 ** (float(np.interp(m, *LOUD)) / 20)


def voice_sym(freq, t, vel, gate, sr):
    """An undamped string ringing in sympathy: no hammer, no prompt sound, a slow swell into the aftersound."""
    return voice(freq, t, vel, gate, sr, sympathetic=True)
