# Dubstep bass engine (Poppycock, Luigi Manson): ismail `code` instrument source. Velocity picks the articulation:
# code = round(vel * 127); art = code // 10, variant = code % 10.
import numpy as np
from scipy.signal import lfilter

from ismail import dsp

INFO = {
    "summary": "dubstep bass engine: one voice, velocity picks the articulation",
    "range": "C0-C4 (roots around A0-A2)",
    "velocity": "the note velocity is a code: articulation = velocity // 10, variant = velocity % 10 (velocity 21 = wub variant 1): 1x yoi/yow vowel sweep, "
                "2x wub (rates 1/4, 1/3, 1/6, 1/2, accel, decel, 1/5 ...), 3x screech, 4x metal, 5x dive/rise, 6x zap, "
                "7x grind, 8x chop (32nds, sextuplets, quintuplets ...), 9x talk words (90, 91, 92; add more in WORDS), "
                "11x robot, 12x howl",
    "params": {"bpm": "passed automatically: wub, chop, grind and robot rates follow the song tempo"},
    "tail": "0.04 s (the engine shapes its own release)",
}

BPM = 150.0
BEAT = 60.0 / BPM  # set from the song tempo on every call
VOW = {'i': (280, 2250, 2900), 'e': (400, 2000, 2600), 'E': (550, 1770, 2500), 'a': (750, 1250, 2600),
       'A': (650, 1050, 2500), 'o': (450, 850, 2400), 'u': (320, 800, 2300), '@': (500, 1450, 2500)}


def _phase(f, sr):
    return np.cumsum(np.broadcast_to(f, f.shape) / sr)


def _osc(wave, ph):
    dt = np.abs(np.diff(ph, prepend=2 * ph[0] - ph[1] if len(ph) > 1 else 0.0))
    return dsp.osc(wave, ph, np.maximum(dt, 1e-9))


def _vowels(path, x):
    pos = np.array([p for p, _ in path])
    return [np.exp(np.interp(x, pos, np.log([VOW[v][k] for _, v in path]))) for k in range(3)]


def _formant(s, F, sr, res=0.9, gains=(1.0, 0.75, 0.35)):
    y = np.zeros_like(s)
    for f, g in zip(F, gains):
        y += dsp.filt(s, 'bp', f, res, sr) * g
    return y


def _fmsaw(f, sr, ratio, idx, fold):
    ph = _phase(f, sr)
    mod = np.sin(2 * np.pi * ratio * ph) * idx * 0.25
    s = _osc('saw', ph + mod) + 0.6 * _osc('square', 0.5 * ph + 0.13)
    return np.sin(fold * s)


def _ramp(mask, sr, ms=4.0):
    k = max(int(ms * sr / 1000), 1)
    return np.convolve(mask.astype(float), np.ones(k) / k, mode='same')


def yoi(f, t, g, sr, v):
    n = len(t)
    x = np.clip(t / g, 0, 1)
    paths = [[(0, 'u'), (0.35, 'o'), (1, 'a')], [(0, 'o'), (0.4, 'a'), (1, 'i')],
             [(0, 'i'), (0.3, 'o'), (0.7, 'a'), (1, 'u')], [(0, 'a'), (0.5, 'E'), (1, 'o')]]
    if v >= 8:
        x = 1 - np.abs(1 - 2 * np.mod(x * 2, 1.0))
    elif v >= 4:
        x = x ** 0.45
    idx = 0.8 + 2.6 * np.sin(np.pi * np.clip(x, 0, 1))
    s = _fmsaw(np.full(n, f), sr, 2.0, idx, 2.2)
    y = _formant(s, _vowels(paths[v % 4], x), sr) + 1.2 * dsp.filt(s, 'lp12', 320, 0.2, sr)
    return y


def wub(f, t, g, sr, v):
    n = len(t)
    per = [0.25, 1 / 3, 1 / 6, 0.5, None, None, 0.2, 0.375, 0.125, 2 / 3][v]
    x = np.clip(t / g, 0, 1)
    if per is None:
        p = 0.5 * 2 ** (-2 * x) if v == 4 else 0.125 * 2 ** (2 * x)
    else:
        p = np.full(n, per)
    lph = np.cumsum(1.0 / (p * BEAT) / sr)
    lfo = 0.5 - 0.5 * np.cos(2 * np.pi * lph)
    ph = _phase(np.full(n, f), sr)
    s = _osc('saw', ph) + _osc('saw', ph * 1.007 + 0.3) + 0.8 * _osc('square', ph * 0.5)
    s = np.tanh(1.8 * s)
    cut = 90 * 2 ** (5.4 * lfo)
    y = dsp.filt(s, 'ladder', cut, 0.62, sr, 1.5)
    y = np.tanh(2.2 * y)
    return dsp.filt(y, 'lp12', 6000, 0.0, sr)


def screech(f, t, g, sr, v):
    n = len(t)
    x = np.clip(t / g, 0, 1)
    ph = _phase(np.full(n, 2 * f), sr)
    m = v % 3
    if m == 0:
        r = 1.2 + 6.5 * x ** 0.7
    elif m == 1:
        r = 7.5 - 6.0 * x
    else:
        r = 3.2 + 2.4 * np.sin(2 * np.pi * t / (BEAT / 3))
    slave = np.mod(np.mod(ph, 1.0) * r, 1.0) * 2 - 1
    s = np.tanh(3.0 * (slave + 0.35 * _osc('square', ph)))
    y = dsp.filt(s, 'hp12', 280, 0.0, sr)
    y = dsp.filt(y, 'lp12', 7000, 0.1, sr)
    return 0.8 * y


def metal(f, t, g, sr, v):
    n = len(t)
    rr = [1.41, 2.76, 3.5, 0.5, 1.5][v % 5]
    ph = _phase(np.full(n, f), sr)
    idx = 3.0 * np.exp(-t / 0.12) + 1.0
    s = np.sin(2 * np.pi * ph + idx * np.sin(2 * np.pi * rr * ph)) * 0.8 + 0.5 * _osc('saw', ph)
    D = max(int(round(sr / (2 * f))), 2)
    a = np.zeros(D + 1)
    a[0], a[-1] = 1.0, -0.86
    y = lfilter([1.0], a, s)
    return np.tanh(0.6 * y)


def dive(f, t, g, sr, v):
    n = len(t)
    x = np.clip(t / g, 0, 1)
    depth = [1.0, 2.0, 3.0, 1.5, 2.5][v % 5]
    semis = -depth * 12 * (1 - x) ** 1.5 if v >= 5 else -depth * 12 * x ** 1.4
    fc = f * 2 ** (semis / 12)
    s = _fmsaw(fc, sr, 1.0, 1.5 + 1.5 * (1 - x), 2.4)
    y = dsp.filt(s, 'lp24', np.clip(fc * 8, 200, 12000), 0.35, sr)
    return y


def zap(f, t, g, sr, v):
    fc = f * 2 ** (3.5 * np.exp(-t / 0.025)) if v % 2 == 0 else f * 2 ** (3.0 * (1 - np.exp(-t / 0.04)))
    ph = _phase(fc, sr)
    s = _osc('square', ph) * 0.7 + np.sin(2 * np.pi * ph)
    return np.tanh(2.0 * s) * np.exp(-t / 0.09)


def grind(f, t, g, sr, v):
    n = len(t)
    fold = 1.5 + 0.35 * v
    chans = []
    for dets in ((-18, 7), (-6, 17)):
        s = sum(_osc('saw', _phase(np.full(n, f * 2 ** (d / 1200)), sr) + 0.17 * i) for i, d in enumerate(dets))
        s = s + 0.7 * _osc('square', _phase(np.full(n, f * 0.5), sr))
        s = np.sin(fold * 0.6 * s)
        sweep = 250 * 2 ** (3.2 * (0.5 - 0.5 * np.cos(2 * np.pi * t / (2 * BEAT))))
        s = dsp.filt(s, 'notch', sweep, 0.45, sr)
        s = dsp.filt(s, 'notch', sweep * 2.3, 0.45, sr)
        chans.append(dsp.filt(s, 'lp12', 5500, 0.1, sr))
    return np.stack(chans)


def chop(f, t, g, sr, v):
    n = len(t)
    p = [1 / 8, 1 / 6, 1 / 5, 1 / 4, 1 / 3, 1 / 7, 1 / 12][v % 7] * BEAT
    k = np.floor(t / p).astype(int)
    frac = np.mod(t, p) / p
    amp = _ramp(frac < 0.6, sr, 3.0)
    s = _fmsaw(np.full(n, f), sr, 2.0, 2.2 + np.mod(k, 3) * 0.8, 2.4)
    seq = 'aioeuA'
    F = [np.array([VOW[seq[kk % len(seq)]][j] for kk in range(k.max() + 1)])[k] for j in range(3)]
    F = [dsp.filt(fj.astype(float), 'lp12', 300.0, 0.0, sr) for fj in F]
    y = (_formant(s, F, sr) + 0.9 * dsp.filt(s, 'lp12', 300, 0.2, sr)) * amp
    side = np.where(k % 2 == 0, -0.55, 0.55)
    return np.stack([y * (1 - side) * 0.8, y * (1 + side) * 0.8])


WORDS = {
    # (pitch knots, vowel path, voiced spans, plosive bursts (pos, hp))
    0: ([(0, 1.0), (0.3, 1.0), (0.38, 1.335), (0.55, 1.335), (0.63, 0.95), (0.93, 0.84), (1, 0.84)],
        [(0, 'A'), (0.3, 'A'), (0.37, 'i'), (0.55, 'i'), (0.62, 'A'), (0.8, 'A'), (0.93, 'o'), (1, 'o')],
        [(0.04, 0.30), (0.38, 0.55), (0.63, 0.93)], [(0.04, 900), (0.38, 900), (0.62, 1800), (0.97, 1800)]),
    1: ([(0, 1.0), (0.35, 1.0), (0.45, 0.9), (0.62, 0.95), (0.8, 1.12), (1, 1.26)],          # "ma-ri-o?"
        [(0, 'u'), (0.07, 'a'), (0.33, 'a'), (0.42, 'i'), (0.6, 'i'), (0.7, 'o'), (1, 'u')],
        [(0.0, 0.36), (0.40, 1.0)], []),
    2: ([(0, 1.0), (0.3, 1.0), (0.4, 1.19), (0.55, 1.19), (0.65, 1.0), (1, 0.89)],           # "lu-i-gi"
        [(0, 'o'), (0.08, 'u'), (0.3, 'u'), (0.4, 'i'), (0.55, 'i'), (0.62, 'i'), (1, 'i')],
        [(0.03, 0.55), (0.63, 1.0)], [(0.6, 700)]),
}


def talk(f, t, g, sr, v):
    n = len(t)
    x = np.clip(t / g, 0, 1)
    pk, path, spans, bursts = WORDS.get(v, WORDS[0])
    fc = f * np.interp(x, [a for a, _ in pk], [b for _, b in pk])
    fc = dsp.filt(fc, 'lp12', 30.0, 0.0, sr)
    s = _fmsaw(fc, sr, 2.0, 2.0, 2.3)
    on = np.zeros(n, bool)
    for a, b in spans:
        on |= (x > a) & (x < b)
    y = (_formant(s, _vowels(path, x), sr, res=0.93) + 0.8 * dsp.filt(s, 'lp12', 300, 0.2, sr)) * _ramp(on, sr, 5.0)
    rng = np.random.default_rng(int(f * 10) + v)
    nz = rng.standard_normal(n)
    for pos, hp in bursts:
        tt = t - pos * g
        burst = np.where(tt >= 0, np.exp(-np.maximum(tt, 0) / 0.012), 0.0)
        y += dsp.filt(dsp.filt(nz, 'hp12', hp, 0.0, sr), 'lp12', 4500, 0.0, sr) * burst * 0.4
    return y


def howl(f, t, g, sr, v):
    """ghost siren: FM sine sliding up, vowel u -> o -> a, slow wide vibrato"""
    x = np.clip(t / g, 0, 1)
    semis = 12 * x ** 1.5 * (1 if v % 2 == 0 else -1) + 0.5 * np.sin(2 * np.pi * 5.5 * t) * np.clip(t / 0.3, 0, 1)
    fc = f * 2 ** (semis / 12)
    ph = _phase(fc, sr)
    s = np.sin(2 * np.pi * ph + (1.2 + 1.5 * x) * np.sin(2 * np.pi * 2 * ph)) + 0.4 * _osc('saw', ph)
    y = _formant(s, _vowels([(0, 'u'), (0.5, 'o'), (1, 'a')], x), sr, res=0.9) + 0.6 * s
    return y


def robot(f, t, g, sr, v):
    n = len(t)
    step = BEAT / 8
    k = np.floor(t / step).astype(int)
    rng = np.random.default_rng(int(f) * 7 + v)
    scale = np.array([0, 3, 5, 7, 10, 12, -5, 15, 1, 6])
    semis = scale[rng.integers(0, len(scale), k.max() + 1)][k]
    fc = f * 2 ** (semis / 12)
    s = _osc('square', _phase(fc, sr)) + 0.5 * _osc('saw', _phase(fc * 1.5, sr))
    hold = max(int(sr / 5500), 1)
    s = np.repeat(s[::hold], hold)[:n]
    s = np.round(s * 6) / 6
    F = [np.where(k % 2 == 0, VOW['e'][j], VOW['o'][j]).astype(float) for j in range(3)]
    y = _formant(s, F, sr, res=0.85) + 0.5 * dsp.filt(s, 'lp12', 400, 0.1, sr)
    return y * _ramp(np.mod(t, step) / step < 0.8, sr, 2.0)


ARTS = {1: yoi, 2: wub, 3: screech, 4: metal, 5: dive, 6: zap, 7: grind, 8: chop, 9: talk, 11: robot, 12: howl}
GAIN = {3: 0.75, 6: 0.6, 5: 0.95, 11: 0.8}
FIZZ = {3: 0.15, 6: 0.1, 5: 0.3}
DRIVE = {1: 1.6, 2: 1.2, 3: 1.4, 4: 1.8, 5: 1.6, 6: 1.2, 7: 1.5, 8: 1.6, 9: 1.7, 11: 1.4}


def voice(freq, t, vel, gate, sr, bpm=BPM):
    global BEAT
    BEAT = 60.0 / bpm
    code = int(round(vel * 127))
    art, var = code // 10, code % 10
    fn = ARTS.get(art, yoi)
    y = np.asarray(fn(freq, t, max(gate, 1e-3), sr, var), dtype=np.float64)
    if y.ndim == 1:
        y = np.stack([y, y])
    gn = max(int(gate * sr), 1)
    ref = np.percentile(np.abs(y[:, :gn]), 99.5) + 1e-9
    y = np.tanh(y / ref * DRIVE.get(art, 1.5)) * 0.55 * GAIN.get(art, 1.0)
    fz = np.stack([dsp.filt(np.clip(c * 3.0, -0.5, 0.5), 'hp12', 2500.0, 0.2, sr) for c in y])
    y = y + FIZZ.get(art, 0.45) * fz
    y = np.stack([dsp.filt(c, 'hp12', 60.0, 0.0, sr) for c in y])
    n = y.shape[1]
    e = np.ones(n)
    na = max(int(0.0015 * sr), 1)
    e[:na] = np.linspace(0, 1, na)
    tt = np.arange(n) - gn
    e *= np.where(tt > 0, np.exp(-np.maximum(tt, 0) / (0.012 * sr)), 1.0)
    return y * e
