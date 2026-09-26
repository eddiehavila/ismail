# Signature sound effects: ismail `code` instrument. code = round(vel*127): 10 gunshot, 20 reload, 30 shell casing, 40 bone crunch, 50 punch, 60 rip, 70 gong.
import numpy as np

from ismail import dsp

INFO = {
    "summary": "one-shot sound effects picked by velocity: gunshot, reload, shell casing, bone crunch, punch, rip, gong",
    "velocity": "the note velocity picks the effect (velocity // 10): 1 gunshot (vel 10), 2 reload (20), 3 shell casing (30), 4 bone crunch (40), "
                "5 punch (50), 6 rip (60), 7 gong (70)",
    "range": "pitch is ignored",
    "tail": "4.5 s (the gong rings)",
}


def _decay(t, tau, t0=0.0):
    tt = t - t0
    return np.where(tt >= 0, np.exp(-np.maximum(tt, 0) / tau), 0.0)


def shot(t, sr):
    rng = np.random.default_rng(11)
    n = len(t)
    nz = rng.standard_normal(n)
    crack = dsp.filt(nz, 'hp12', 1800.0, 0.1, sr) * _decay(t, 0.006) * 7.0
    atk = np.clip(t / 0.0003, 0, 1)
    blast = dsp.filt(dsp.filt(nz, 'lp12', 5000.0, 0.1, sr), 'hp12', 150.0, 0.0, sr) * _decay(t, 0.05) * atk * 3.2
    body = dsp.filt(nz, 'bp', 900.0, 0.4, sr) * _decay(t, 0.03) * atk * 4.0
    f = 38 + 130 * np.exp(-t / 0.018)
    thump = np.sin(2 * np.pi * np.cumsum(f) / sr) * _decay(t, 0.07) * atk * 0.9
    y = crack + blast + body + thump
    for dly, g in ((0.043, 0.45), (0.097, 0.3), (0.171, 0.22), (0.26, 0.12)):  # walls
        k = int(dly * sr)
        r = np.zeros(n)
        r[k:] = dsp.filt(blast[:n - k] + 0.5 * crack[:n - k], 'lp12', 3000.0, 0.0, sr)
        y += r * g
    room = dsp.filt(dsp.filt(nz, 'lp12', 900.0, 0.0, sr), 'hp12', 90.0, 0.0, sr)
    y += room * _decay(t, 0.55, 0.01) * np.clip((t - 0.01) / 0.03, 0, 1) * 0.5
    y = np.tanh(1.8 * y)
    # slight stereo from decorrelated reflections
    side = dsp.filt(rng.standard_normal(n), 'lp12', 1500.0, 0.0, sr) * _decay(t, 0.35, 0.03) * 0.25
    return np.stack([y + side, y - side]) * 0.7


def reload(t, sr):
    rng = np.random.default_rng(5)
    n = len(t)
    nz = rng.standard_normal(n)
    y = np.zeros(n)
    for t0, fc, g in ((0.0, 3200, 1.0), (0.012, 1400, 0.6), (0.21, 2600, 1.2), (0.225, 900, 0.8)):
        y += dsp.filt(nz, 'bp', fc, 0.8, sr) * _decay(t, 0.009, t0) * g
    for t0, fr in ((0.0, 2350), (0.21, 1870)):   # metal ring of the slide
        tt = np.maximum(t - t0, 0)
        y += np.sin(2 * np.pi * fr * tt) * _decay(t, 0.03, t0) * 0.25
    return np.tanh(2.0 * y) * 0.6


def casing(t, sr):
    y = np.zeros(len(t))
    for t0, g in ((0.0, 1.0), (0.14, 0.55), (0.24, 0.3), (0.3, 0.15)):
        tt = np.maximum(t - t0, 0)
        for fr, a in ((5230, 1.0), (7910, 0.6), (11020, 0.35)):
            y += np.sin(2 * np.pi * fr * tt) * a * g * _decay(t, 0.05, t0)
    return y * 0.18


def _clicks(t, sr, rng, n_clicks, span, lo=1500, hi=6000):
    """bone-crack crackle: many 1-2 ms band-passed clicks scattered over `span` s."""
    n = len(t)
    y = np.zeros(n)
    nz = rng.standard_normal(n)
    for _ in range(n_clicks):
        t0 = rng.uniform(0, span) ** 1.3 / span ** 0.3
        fc = rng.uniform(lo, hi)
        y += dsp.filt(nz, 'bp', fc, 0.6, sr) * _decay(t, rng.uniform(0.0008, 0.002), t0) * rng.uniform(0.4, 1.0) * np.exp(-t0 / 0.06)
    return y


def crunch(t, sr):
    rng = np.random.default_rng(23)
    n = len(t)
    nz = rng.standard_normal(n)
    y = _clicks(t, sr, rng, 60, 0.09) * 4.5
    f = 45 + 60 * np.exp(-t / 0.025)
    y += np.sin(2 * np.pi * np.cumsum(f) / sr) * _decay(t, 0.06) * 0.6                        # body thud
    sweep = 380 * 2 ** (1.8 * np.clip(t / 0.12, 0, 1))
    y += dsp.filt(dsp.filt(nz, 'lp12', 1500.0, 0.0, sr), 'bp', sweep, 0.75, sr) * _decay(t, 0.12, 0.01) * 1.6  # wet squelch
    return np.tanh(1.5 * y) * 0.7


def punch(t, sr):
    rng = np.random.default_rng(31)
    n = len(t)
    nz = rng.standard_normal(n)
    hit_t = 0.11
    swoosh = dsp.filt(nz, 'bp', 700 * 2 ** (2.2 * np.clip(t / hit_t, 0, 1)), 0.5, sr) * np.clip(t / hit_t, 0, 1) ** 2 * (t < hit_t)
    tt = np.maximum(t - hit_t, 0)
    f = 50 + 90 * np.exp(-tt / 0.02)
    thud = np.sin(2 * np.pi * np.cumsum(f * (t >= hit_t)) / sr) * _decay(t, 0.09, hit_t) * 1.8
    smack = dsp.filt(nz, 'bp', 1800.0, 0.3, sr) * _decay(t, 0.012, hit_t) * 2.5
    return np.tanh(1.4 * (0.5 * swoosh + thud + smack)) * 0.7


def rip(t, sr):
    rng = np.random.default_rng(47)
    n = len(t)
    nz = rng.standard_normal(n)
    x = np.clip(t / 0.45, 0, 1)
    fc = 3200 * 2 ** (-2.6 * x)
    am = 0.55 + 0.45 * np.sign(np.sin(2 * np.pi * np.cumsum(35 + 45 * rng.random(n)) / sr))  # jagged tearing
    y = dsp.filt(nz, 'bp', fc, 0.55, sr) * am * np.where(t < 0.45, 1.0, np.exp(-(t - 0.45) / 0.05)) * 1.8
    y += _clicks(t, sr, rng, 25, 0.4, 800, 4000) * 1.5
    return np.tanh(1.3 * y) * 0.6


def gong(t, sr):
    """the tournament gong: inharmonic partials, highs bloom late, beating pairs, 4 s decay."""
    y = np.zeros(len(t))
    f0 = 98.0
    for r, a, tau, bloom in ((1.0, 1.0, 3.8, 0.0), (1.52, 0.7, 3.2, 0.05), (2.03, 0.55, 2.6, 0.12), (2.74, 0.5, 2.2, 0.25),
                             (3.41, 0.4, 1.8, 0.35), (4.12, 0.3, 1.4, 0.45), (5.33, 0.25, 1.1, 0.6), (6.91, 0.18, 0.8, 0.7)):
        for d in (-0.6, 0.6):
            env = (1 - np.exp(-t / (0.01 + bloom * 0.25))) * np.exp(-t / tau)
            y += np.sin(2 * np.pi * (f0 * r + d) * t) * a * env
    rng = np.random.default_rng(3)
    for k in range(18):                           # upper inharmonic cloud
        r = 7.5 * 1.19 ** k * rng.uniform(0.97, 1.03)
        bloom = 0.15 + 0.05 * k
        env = (1 - np.exp(-t / bloom)) * np.exp(-t / (1.6 - 0.06 * k))
        y += np.sin(2 * np.pi * f0 * r * t + rng.uniform(0, 6.3)) * 0.22 * env
    strike = rng.standard_normal(len(t))
    y += dsp.filt(strike, 'lp12', 2500.0, 0.0, sr) * _decay(t, 0.03) * 0.9
    shimmer = dsp.filt(rng.standard_normal(len(t)), 'bp', 3500.0, 0.3, sr)
    y += shimmer * (1 - np.exp(-t / 0.35)) * np.exp(-t / 1.4) * 0.35
    return np.tanh(0.5 * y) * 0.8


def voice(freq, t, vel, gate, sr):
    code = int(round(vel * 127)) // 10
    return {1: shot, 2: reload, 3: casing, 4: crunch, 5: punch, 6: rip, 7: gong}.get(code, shot)(t, sr)
