"""Big Rusty Drums (Karoryfer Samples, CC0-1.0, v1.100) as a performer: the real multi-velocity, round-robin
recordings of a 1980s Polish kit, played hit by hit. Every hit picks its velocity layer from how hard it is struck
(with a little keyed spread, as a drummer never hits the same layer twice) and its round robin from where it sits
in the song (neighbouring hits never repeat a take), then mixes the kit's own mic positions (close, bottom,
overheads, bleed). Pitches as kit70: 36 kick, 37 snare ghost, 38 snare, 40 rimshot, 42 closed hat, 44 pedal hat,
46 open hat, 49 crash, 57 crash 2 (sizzle), 51 ride, 53 ride bell, 48 tom 14", 45 tom 15", 43 tom 18", 41 tom 22".
Samples: not in git; samples_fetch('big_rusty') downloads the pieces this voice plays (ismail.samples)."""
import glob
import os
import re

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
INFO = {
    "summary": "Big Rusty Drums (Karoryfer, CC0) multi-velocity round-robin kit with its mic positions, hit by hit",
    "range": "36 kick, 37 ghost, 38 snare, 40 rimshot, 42/44/46 hats, 49/57 crashes, 51 ride, 53 bell, 48/45/43/41 toms",
    "velocity": "picks the recorded velocity layer (+ keyed spread) and scales within it",
    "params": {"close_db / oh_db / btm_db / bleed_db": "mic levels, dB", "kick_tune / snare_tune / tom_tune": "semitones",
               "<piece>_db": "per-piece level (kick, snare, hat, crash, ride, tom)", "spread": "velocity-layer spread, layers",
               "humanize_ms": "timing jitter, ms", "cym_len": "cymbal sample length cap, s", "level": "output gain"},
    "source": "https://github.com/sfzinstruments/karoryfer.big-rusty-drums (CC0-1.0)",
    "measured": "sampled: the real kit's hits, played back (samples_fetch('big_rusty'))",
}

# pitch: (piece, folder under Samples, pan of the close mic, -1 = drummer's left)
MAP = {36: ('kick', 'kick_24/kick', 0.0), 37: ('snare', 'snare_14/center', -0.1), 38: ('snare', 'snare_14/center', -0.1),
       40: ('snare', 'snare_14/rimshot', -0.1), 42: ('hat', 'hihat_14/cl', -0.45), 44: ('hat', 'hihat_14/chik', -0.45),
       46: ('hat', 'hihat_14/open', -0.45), 49: ('crash', 'crash_17/cr', -0.55), 57: ('crash', 'crash_sizzle_17/cr', 0.6),
       51: ('ride', 'ride_22/rd', 0.5), 53: ('ride', 'ride_22/bl', 0.5), 48: ('tom', 'tom_14/center', -0.25),
       45: ('tom', 'tom_15/center', 0.05), 43: ('tom', 'tom_18/center', 0.35), 41: ('tom', 'tom_22/center', 0.5)}
CLOSE = {'kick', 'cl', 'top'}
_cache = {}


def _root():
    from ismail import samples
    return samples.need('big_rusty')


def _index(folder):
    """{mic: {layer: [files by rr]}} and the number of layers."""
    if folder in _cache:
        return _cache[folder]
    base = os.path.join(_root(), folder)
    out, nl = {}, 0
    if not os.path.isdir(base):                               # a partial copy without this piece: the hit is skipped
        _cache[folder] = (out, nl)
        return out, nl
    for mic in sorted(os.listdir(base)):
        d = {}
        for f in glob.glob(os.path.join(base, mic, '*.flac')):
            m = re.search(r'_vl(\d+)_rr(\d+)', os.path.basename(f))
            if m:
                d.setdefault(int(m.group(1)), {})[int(m.group(2))] = f
        if d:
            out[mic] = {k: [v[r] for r in sorted(v)] for k, v in d.items()}
            nl = max(nl, max(d))
    _cache[folder] = (out, nl)
    return out, nl


def _load(f, sr, semis, cap_s):
    key = (f, sr, round(semis, 3), cap_s)
    if key in _cache:
        return _cache[key]
    import soundfile as sf
    from scipy import signal
    y, fsr = sf.read(f, dtype='float64', always_2d=True)
    y = y.T                                                   # (channels, n)
    if cap_s:
        n = int(cap_s * fsr)
        if y.shape[1] > n:
            y = y[:, :n].copy()
            fade = int(0.3 * fsr)
            y[:, -fade:] *= np.linspace(1, 0, fade) ** 2
    ratio = fsr / sr * 2 ** (semis / 12.0)                    # tuning = playback speed, as a drum tuned up or down
    if abs(ratio - 1) > 1e-6:
        from fractions import Fraction
        fr = Fraction(ratio).limit_denominator(400)
        y = signal.resample_poly(y, fr.denominator, fr.numerator, axis=1)
    _cache[key] = y
    return y


def _rng(beat, m, salt):
    return np.random.default_rng([int(round(beat * 960)) % (2 ** 31), int(m), int(salt)])


def perform(notes, total_n, sr, bpm=120.0, lanes=None, beat0=0.0, close_db=0.0, oh_db=-6.0, btm_db=-9.0,
            bleed_db=-18.0, kick_tune=0.0, snare_tune=0.0, tom_tune=0.0, kick_db=0.0, snare_db=0.0, hat_db=0.0,
            crash_db=0.0, ride_db=0.0, tom_db=0.0, spread=0.6, humanize_ms=2.0, cym_len=6.0, level=1.0, **_):
    L = np.zeros(total_n)
    R = np.zeros(total_n)
    tune = {'kick': kick_tune, 'snare': snare_tune, 'tom': tom_tune}
    pdb = {'kick': kick_db, 'snare': snare_db, 'hat': hat_db, 'crash': crash_db, 'ride': ride_db, 'tom': tom_db}
    for st, m, d, v in notes:
        m = int(m)
        if m not in MAP:
            continue
        piece, folder, pan = MAP[m]
        idx, nl = _index(folder)
        if not idx:
            continue
        beat = beat0 + st * bpm / 60.0
        r = _rng(beat, m, 1)
        vv = (37 / 127 * v) if m == 37 else v                      # a ghost note is a soft snare hit
        layer = int(np.clip(round(vv / 127 * nl + r.normal(0, spread)), 1, nl))
        top = layer / nl * 127
        g = float(np.clip(vv / top, 0.6, 1.15)) * 10 ** (pdb[piece] / 20) * level
        t0 = st + r.normal(0, humanize_ms / 1000.0)
        i0 = max(0, int(round(t0 * sr)))
        if i0 >= total_n:
            continue
        cap = cym_len if piece in ('crash', 'ride') else None
        for mic, layers in idx.items():
            lay = layers.get(layer) or layers[min(layers, key=lambda k: abs(k - layer))]
            rr = (int(round(beat * 4)) + m) % len(lay)              # walks the takes: neighbours never repeat
            y = _load(lay[rr], sr, tune.get(piece, 0.0), cap)
            mg = close_db if mic in CLOSE else oh_db if mic == 'oh' else btm_db if mic == 'btm' else bleed_db
            a = g * 10 ** (mg / 20)
            n = min(y.shape[1], total_n - i0)
            if y.shape[0] == 1:
                gl, gr = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
                L[i0:i0 + n] += a * gl * y[0, :n]
                R[i0:i0 + n] += a * gr * y[0, :n]
            else:
                L[i0:i0 + n] += a * y[0, :n]
                R[i0:i0 + n] += a * y[1, :n]
    return np.stack([L, R]) * 0.7
