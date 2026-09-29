"""Additive piano voice: stiff-string partials, three detuned strings, two-stage decay, dampers."""
import numpy as np
from numba import njit
from ismail import dsp

INFO = {
    "summary": "additive piano: stiff-string partials, three detuned strings, two-stage decay, dampers (no data file)",
    "range": "A0-C8",
    "velocity": "louder and brighter",
    "tail": "3.0 s recommended",
}


@njit(cache=True, fastmath=True)
def _bank(L, sr, f, tau, amp, gl, gr, ph, out):
    for j in range(len(f)):
        w = 2.0 * np.pi * f[j] / sr
        r = np.exp(-1.0 / (tau[j] * sr))
        cw = np.cos(w) * r
        sw = np.sin(w) * r
        re = np.cos(ph[j]) * amp[j]
        im = np.sin(ph[j]) * amp[j]
        n = L
        # samples until the partial falls 80 dB
        nd = int(tau[j] * sr * 9.2) + 1
        if nd < n:
            n = nd
        for i in range(n):
            out[0, i] += gl[j] * im
            out[1, i] += gr[j] * im
            re2 = re * cw - im * sw
            im = re * sw + im * cw
            re = re2


def voice(freq, t, vel, gate, sr):
    rng = np.random.default_rng(int(freq * 1000) ^ int(vel * 9973) ^ int(gate * 7919))
    lf = np.log2(freq / 261.63)
    B = float(np.clip(0.00011 * 2 ** (lf * 0.9), 0.00003, 0.003))
    T60 = float(np.clip(14.0 * 2 ** (-lf * 0.8), 0.8, 30.0))
    tau1 = T60 / 6.91
    damped = freq < 1400.0
    rel_tau = 0.07 + 0.05 * max(0.0, -lf)
    fc = (1100.0 + 6000.0 * vel ** 1.5) * (1.0 + 0.25 * max(lf, 0.0))
    strike = 1.0 / 7.3
    n_total = len(t)
    end = gate + rel_tau * 9.0 if damped else n_total / sr
    L = max(16, int(min(n_total, end * sr)))
    fs, ts, am, gl, gr, ph = [], [], [], [], [], []
    for k in range(1, 90):
        fk = k * freq * np.sqrt(1.0 + B * k * k)
        if fk > min(12000.0, sr * 0.45):
            break
        a = k ** -0.85 * abs(np.sin(np.pi * k * strike)) / (1.0 + (fk / fc) ** 2.0)
        if freq < 140.0 and k == 1:
            a *= 0.45
        if a < 1e-4:
            continue
        tk = tau1 / (1.0 + (fk / 2600.0) ** 1.2)
        d = rng.uniform(0.15, 1.1) / 1731.0
        p = rng.uniform(0, 2 * np.pi)
        # string A: prompt sound; B, C: aftersound, slightly detuned so they beat
        for ff, tt_, aa, l, r_ in ((fk, tk * 0.35, 0.5, 0.62, 0.38),
                                   (fk * (1 + d), tk, 0.35, 0.38, 0.62),
                                   (fk * (1 - 0.6 * d), tk * 0.8, 0.15, 0.5, 0.5)):
            fs.append(ff); ts.append(tt_); am.append(a * aa); gl.append(l); gr.append(r_); ph.append(p)
    y = np.zeros((2, L))
    _bank(L, float(sr), np.array(fs), np.array(ts), np.array(am), np.array(gl), np.array(gr), np.array(ph), y)
    if damped:
        k0 = int(gate * sr)
        if k0 < L:
            y[:, k0:] *= np.exp(-(np.arange(L - k0) / sr) / rel_tau)
    tt = t[:L]
    na = min(L, int(0.05 * sr))
    nz = rng.standard_normal(na) * np.exp(-tt[:na] / 0.005)
    nz = dsp.filt(nz, 'lp12', min(fc * 1.5, 9000.0), 0.0, sr)
    y[:, :na] += nz * 0.03 * vel
    atk = min(L, int(0.0015 * sr))
    y[:, :atk] *= np.linspace(0, 1, atk)
    pan = float(np.clip(lf * 0.15, -0.45, 0.45))
    y[0] *= np.sqrt(0.5 - pan * 0.5) * 1.414
    y[1] *= np.sqrt(0.5 + pan * 0.5) * 1.414
    tilt = 2 ** (0.4 * float(np.clip(lf, -3.0, 2.5)))
    return y * (0.02 + 0.98 * vel ** 2.2) * 0.4 * tilt
