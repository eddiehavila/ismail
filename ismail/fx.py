"""Effects. Each effect is a dict {"type": ..., params}, run by a processor that keeps state between blocks
(make(fx, env).process(block)); apply_fx(x, fx, ctx, idx) runs one over a whole offline window.

ctx.param(fx_index, name, default) returns a per-sample curve when the param is automated, else the scalar.
ctx.track_audio(name) returns another track's post-fx audio (for sidechain/vocoder).
ctx.track_onsets(name) returns note-on times (sec) of another track (for duck).
"""
import numpy as np
from scipy import signal

from . import dsp
from .notation import parse_steps

SR = dsp.SR

FX_DEFAULTS = {
    "gain": {"gain_db": 0.0, "pan": 0.0},
    "eq": {"bands": []},
    "filter": {"mode": "lp24", "cutoff": 20000.0, "res": 0.0, "mix": 1.0, "lfo_rate_beats": None, "lfo_depth_oct": 0.0,
               "lfo_shape": "sine"},
    "distortion": {"mode": "tanh", "drive_db": 12.0, "mix": 1.0, "out_db": 0.0, "bits": 8, "rate_hz": 11025.0,
                   "tone_hz": None, "oversample": 2},
    "compressor": {"threshold_db": -18.0, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 120.0, "knee_db": 6.0,
                   "makeup_db": 0.0, "sidechain": None, "sc_hpf_hz": None, "mix": 1.0},
    "duck": {"source": None, "every_beats": None, "depth_db": -12.0, "attack_ms": 2.0, "hold_ms": 0.0,
             "release_ms": 180.0, "curve": 2.0},
    "gate": {"pattern": "x.x.x.x.x.x.x.x.", "step": 0.25, "attack_ms": 2.0, "release_ms": 30.0, "depth": 1.0},
    "delay": {"time_beats": 0.75, "time_ms": None, "feedback": 0.35, "mix": 0.25, "pingpong": False,
              "lp_hz": 6000.0, "hp_hz": 150.0, "dry": None},
    "reverb": {"size": 0.75, "damp": 0.4, "mix": 0.25, "predelay_ms": 10.0, "width": 1.0, "hp_hz": 200.0,
               "lp_hz": 12000.0, "dry": None},
    "hall": {"rt60": 2.2, "low_mult": 1.3, "high_mult": 0.45, "predelay_ms": 20.0, "early": 0.5, "width": 1.0,
             "hp_hz": 80.0, "mix": 0.25, "dry": None, "seed": 1},
    "chorus": {"rate_hz": 0.8, "depth_ms": 3.0, "delay_ms": 12.0, "feedback": 0.0, "mix": 0.5},
    "flanger": {"rate_hz": 0.25, "rate_beats": None, "depth_ms": 2.0, "delay_ms": 1.0, "feedback": 0.6, "mix": 0.5},
    "phaser": {"rate_hz": 0.3, "rate_beats": None, "depth": 0.8, "center": 0.5, "stages": 6, "feedback": 0.5,
               "mix": 0.5},
    "tremolo": {"rate_beats": 0.5, "rate_hz": None, "depth": 0.5, "shape": "sine", "mode": "amp", "phase": 0.0},
    "width": {"width": 1.0, "mono_below_hz": None},
    "limiter": {"ceiling_db": -0.3, "gain_db": 0.0, "release_ms": 60.0, "lookahead_ms": 3.0},
    "vocoder": {"modulator": None, "bands": 20, "lo_hz": 90.0, "hi_hz": 9000.0, "q": 6.0, "release_ms": 25.0,
                "mix": 1.0, "unvoiced": 0.15},
    "bitcrush": {"bits": 8, "rate_hz": 11025.0, "mix": 1.0},
    "formant": {"vowel": "@", "f1": None, "f2": None, "f3": None, "q": 8.0, "gains_db": [0.0, -4.0, -10.0],
                "mix": 1.0, "shift": 1.0},
}
VOWEL_FORMANTS = {'i': (280, 2250, 2900), 'e': (400, 2000, 2600), 'E': (550, 1770, 2500), 'a': (750, 1250, 2600),
                  'A': (650, 1050, 2500), 'o': (450, 850, 2400), 'u': (320, 800, 2300), '@': (500, 1450, 2500)}
FX_TYPES = tuple(FX_DEFAULTS)
EQ_BAND_TYPES = ('peak', 'lowshelf', 'highshelf', 'lowcut', 'highcut', 'notch', 'bandpass')

# params that accept automation (per-sample curves)
AUTOMATABLE = {
    "gain": ("gain_db", "pan"), "filter": ("cutoff", "res", "mix"), "distortion": ("drive_db", "mix"),
    "delay": ("mix",), "reverb": ("mix",), "hall": ("mix",), "chorus": ("mix",), "flanger": ("mix", "feedback"),
    "phaser": ("mix",), "tremolo": ("depth",), "formant": ("mix",), "width": ("width",), "compressor": ("threshold_db",),
    "duck": ("depth_db",), "gate": ("depth",), "vocoder": ("mix",), "bitcrush": ("mix",),
}


class FxError(ValueError):
    pass


def normalize(fx):
    if not isinstance(fx, dict) or fx.get('type') not in FX_DEFAULTS:
        raise FxError(f"effect needs 'type' in {', '.join(FX_TYPES)}")
    unknown = set(fx) - set(FX_DEFAULTS[fx['type']]) - {'type', 'name', 'bypass'}
    if unknown:
        raise FxError(f"unknown {fx['type']} params {sorted(unknown)}; valid: {sorted(FX_DEFAULTS[fx['type']])}")
    full = dict(FX_DEFAULTS[fx['type']], **fx)
    if fx['type'] == 'eq':
        for b in full['bands']:
            if b.get('type', 'peak') not in EQ_BAND_TYPES:
                raise FxError(f"eq band type {b.get('type')!r}: use {', '.join(EQ_BAND_TYPES)}")
    return full


# ------------------------------------------------------------------ helpers

def _mix(dry, wet, m):
    return dry * (1 - m) + wet * m


def rbj_sos(btype, f, gain_db, q, sr):
    """RBJ cookbook biquad as an sos row."""
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * min(f, sr * 0.49) / sr
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2 * q)
    if btype == 'peak':
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif btype == 'lowshelf':
        s = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + s), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - s)]
        a = [(A + 1) + (A - 1) * cw + s, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - s]
    elif btype == 'highshelf':
        s = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + s), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - s)]
        a = [(A + 1) - (A - 1) * cw + s, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - s]
    elif btype == 'lowcut':
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif btype == 'highcut':
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif btype == 'notch':
        b = [1, -2 * cw, 1]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif btype == 'bandpass':
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise FxError(f"bad eq band {btype}")
    b = np.array(b) / a[0]
    a = np.array(a) / a[0]
    return np.concatenate([b, a])


def eq_sos(bands, sr):
    rows = []
    for bd in bands:
        t = bd.get('type', 'peak')
        q = bd.get('q', 0.707)
        rows.append(rbj_sos(t, bd['freq'], bd.get('gain_db', 0.0), q, sr))
        if t in ('lowcut', 'highcut') and bd.get('slope', 12) >= 24:
            rows.append(rbj_sos(t, bd['freq'], 0, q, sr))
    return np.array(rows)


def _lfo_phase(n, rate_hz, rate_beats, bpm, sr, start_sample):
    if rate_beats:
        rate_hz = bpm / 60 / rate_beats
    return (start_sample + np.arange(n)) * rate_hz / sr


def _shape_env(n, onsets_samp, attack, hold, release, curve):
    """Duck shape in [0,1]: rises to 1 at each onset (attack), holds, falls back to 0 (release)."""
    a, h, r = int(attack), int(hold), max(int(release), 1)
    i = np.arange(a + h + r + 1)
    shape = np.where(i < a, i / max(a, 1), np.where(i < a + h, 1.0, np.clip(1 - (i - a - h) / r, 0, 1) ** curve))
    out = np.zeros(n)
    for o in onsets_samp:
        o = int(o)
        if 0 <= o < n:
            m = min(len(shape), n - o)
            np.maximum(out[o:o + m], shape[:m], out=out[o:o + m])
    return out


# ------------------------------------------------------------------ main

def _dry(fx, ctx):
    """delay/reverb dry level: default 1 (insert), but 0 on a pure send-return bus (no track outputs into it):
    the dry signal already reaches the mix through the sending track."""
    if fx.get('dry') is not None:
        return float(fx['dry'])
    name = str(getattr(ctx, 'track', ''))
    if name.startswith('bus:'):
        tracks = getattr(getattr(ctx, 'r', None), 'project', {}).get('tracks', {})
        if not any(t.get('output') == name[4:] for t in tracks.values()):
            return 0.0
    return 1.0


# ------------------------------------------------------------------ processors
#
# Every effect is a processor: built once, then fed consecutive blocks; it keeps its own state (filter memories,
# delay lines, envelopes, reverb tails), so the output does not depend on how the signal is cut into blocks.
# Offline rendering feeds the whole window as one block (apply_fx); the live engine feeds ~12 ms blocks. A
# processor that needs to look ahead or buffer (limiter, oversampled distortion, hall) reports `latency` in
# samples: its output is its input delayed by that much. apply_fx compensates it, the live engine aligns tracks.

class Env:
    """What a processor is built with. offset_samples: processor-time sample of song beat 0 (grid effects)."""

    def __init__(self, sr=SR, bpm=120.0, dry=1.0, offset_samples=0):
        self.sr, self.bpm, self.dry, self.offset_samples = sr, float(bpm), float(dry), int(offset_samples)


class Block:
    """One block of processing. pos: processor-time sample of the block's first sample. The live engine and
    apply_fx subclass it; param() gives a scalar or an (n,) curve, key() another track's post-fx audio for this
    block, onsets() another track's note onsets (processor-time samples) in [lo, hi)."""
    pos = 0
    n = 0

    def param(self, name, default):
        return default

    def key(self, track):
        raise FxError(f"sidechain source {track!r} is not available here")

    def onsets(self, track, lo, hi):
        raise FxError(f"duck source {track!r} is not available here")

    def modulator(self, ref):
        raise FxError(f"vocoder modulator {ref!r} is not available here")

    def note_gr(self, gr_db):
        pass


class _Lag:
    """Delays a signal (history starts silent) or a param (history starts at its first value) by `L` samples
    across blocks, for latency alignment; scalar params become curves."""

    def __init__(self, L, signal=False):
        self.L = L
        self.signal = signal
        self.h = None

    def __call__(self, v, n):
        if self.L == 0:
            return v
        v = np.asarray(v, dtype=np.float64)
        if v.ndim == 0:
            v = np.full(n, float(v))
        elif v.shape[-1] < n:
            v = dsp.as_curve(v, n)
        if self.h is None:
            first = v[..., :1] * (0.0 if self.signal else 1.0)
            self.h = np.repeat(first, self.L, axis=-1)
        cat = np.concatenate([self.h, v], axis=-1)
        self.h = cat[..., -self.L:]
        return cat[..., :n]


class _Sos:
    """sosfilt that remembers its state (mono (n,) or stereo (2, n) input)."""

    def __init__(self, sos, channels=None):
        self.sos = np.ascontiguousarray(sos, dtype=np.float64)
        self.mono = channels is None
        self.zi = np.zeros((self.sos.shape[0], 1 if self.mono else channels, 2))

    def __call__(self, x):
        x = np.asarray(x, dtype=np.float64)
        if self.mono:
            return dsp.sos_s(np.ascontiguousarray(x[None, :]), self.sos, self.zi)[0]
        return dsp.sos_s(np.ascontiguousarray(x), self.sos, self.zi)


class _Lfilter:
    """lfilter(b, a) along the last axis of (2, n), remembering its state."""

    def __init__(self, b, a, channels=2):
        m = max(len(b), len(a))
        self.b = np.zeros(m)
        self.b[:len(b)] = b
        self.a = np.zeros(m)
        self.a[:len(a)] = a
        self.b /= self.a[0]
        self.a /= self.a[0]
        self.zi = np.zeros((channels, m - 1))

    def __call__(self, x):
        return dsp.lfilter_s(np.ascontiguousarray(x, dtype=np.float64), self.b, self.a, self.zi)


class Proc:
    latency = 0

    def __init__(self, fx, env):
        self.fx = fx
        self.env = env
        self.sr = env.sr

    def process(self, x, blk):
        raise NotImplementedError


class _Bypass(Proc):
    def process(self, x, blk):
        return x


class _Gain(Proc):
    def process(self, x, blk):
        g = dsp.undb(blk.param('gain_db', self.fx['gain_db']))
        gl, gr = dsp.pan_gains(blk.param('pan', self.fx['pan']))
        return np.stack([x[0] * g * gl, x[1] * g * gr])


class _Eq(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.f = _Sos(eq_sos(fx['bands'], self.sr), 2) if fx['bands'] else None

    def process(self, x, blk):
        return x if self.f is None else self.f(x)


class _Filter(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.st = [dsp.filt_state(), dsp.filt_state()]

    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        cut = dsp.as_curve(blk.param('cutoff', fx['cutoff']), n)
        if fx['lfo_rate_beats'] and fx['lfo_depth_oct']:
            ph = _lfo_phase(n, None, fx['lfo_rate_beats'], self.env.bpm, self.sr, blk.pos)
            cut = cut * 2 ** (fx['lfo_depth_oct'] * dsp.lfo_wave(fx['lfo_shape'], ph))
        res = blk.param('res', fx['res'])
        wet = np.stack([dsp.filt_s(np.ascontiguousarray(x[c]), fx['mode'], cut, res, self.sr, 1.0, self.st[c])
                        for c in (0, 1)])
        return _mix(x, wet, blk.param('mix', fx['mix']))


class _Crush:
    """Bit depth + sample-and-hold decimation, holds counted from processor time 0 (block-independent)."""

    def __init__(self, bits, rate_hz, sr):
        self.q = 2 ** (bits - 1)
        self.hold = max(1, int(round(sr / rate_hz)))
        self.last = np.zeros(2)

    def __call__(self, x, pos):
        y = np.round(x * self.q) / self.q
        if self.hold == 1:
            return y
        n = x.shape[1]
        src = ((pos + np.arange(n)) // self.hold) * self.hold - pos
        out = y[:, np.maximum(src, 0)]
        if src[0] < 0:
            out[:, src < 0] = self.last[:, None]
        tail = ((pos + n - 1) // self.hold) * self.hold - pos
        if tail >= 0:
            self.last = y[:, tail].copy()
        return out


OS_MODES = ('tanh', 'hard', 'fold', 'asym', 'rectify')


class _Distortion(Proc):
    """Oversampled waveshaper. The resampling filters are the ones scipy's resample_poly designs; run causally
    they delay by 10 base samples each way, so latency = 20."""

    def __init__(self, fx, env):
        super().__init__(fx, env)
        mode = fx['mode']
        if mode not in OS_MODES + ('bitcrush', 'downsample'):
            raise FxError(f"distortion mode {mode!r}: tanh hard fold asym rectify bitcrush downsample")
        self.os = int(fx['oversample']) if mode in OS_MODES else 1
        if self.os > 1:
            half = 10 * self.os
            h = signal.firwin(2 * half + 1, 1.0 / self.os, window=('kaiser', 5.0))
            self.up = _Lfilter(h * self.os, [1.0])
            self.down = _Lfilter(h, [1.0])
            self.latency = 20
            self.g_lag = _Lag(10)
        if mode == 'asym':      # DC from the asymmetric curve: a 10 Hz blocker at the oversampled rate
            R = 1 - 2 * np.pi * 10 / (self.sr * self.os)
            self.dc = _Lfilter([1.0, -1.0], [1.0, -R])
        if mode in ('bitcrush', 'downsample'):
            self.crush = _Crush(fx['bits'] if mode == 'bitcrush' else 24, fx['rate_hz'], self.sr)
        self.tone = _Sos(eq_sos([{"type": "highcut", "freq": fx['tone_hz']}], self.sr), 2) if fx['tone_hz'] else None
        self.dry_lag = _Lag(self.latency, signal=True)
        self.mix_lag = _Lag(self.latency)

    def process(self, x, blk):
        fx, n, os_ = self.fx, x.shape[1], self.os
        g = dsp.undb(blk.param('drive_db', fx['drive_db']))
        mode = fx['mode']
        if mode in ('bitcrush', 'downsample'):
            y = self.crush(x * g, blk.pos)
        else:
            if os_ > 1:
                z = np.zeros((2, n * os_))
                z[:, ::os_] = x
                xi = self.up(z)
                gl = self.g_lag(g, n) if not np.isscalar(g) else g
                gi = np.repeat(gl, os_) if not np.isscalar(gl) else gl
            else:
                xi, gi = x, g
            if mode == 'tanh':
                y = np.tanh(xi * gi)
            elif mode == 'hard':
                y = np.clip(xi * gi, -1, 1)
            elif mode == 'fold':
                y = np.sin(xi * gi * np.pi / 2)
            elif mode == 'asym':
                zz = xi * gi
                y = np.where(zz > 0, np.tanh(zz), np.tanh(zz * 0.5) * 1.2)
                y = self.dc(y)
            else:
                y = np.abs(np.tanh(xi * gi)) * 2 - 0.5
            if os_ > 1:
                y = self.down(y)[:, ::os_]
        if self.tone is not None:
            y = self.tone(y)
        y = y * dsp.undb(fx['out_db'])
        return _mix(self.dry_lag(x, n), y, self.mix_lag(blk.param('mix', fx['mix']), n))


class _Bitcrush(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.crush = _Crush(fx['bits'], fx['rate_hz'], self.sr)

    def process(self, x, blk):
        return _mix(x, self.crush(x, blk.pos), blk.param('mix', self.fx['mix']))


class _Compressor(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.hpf = _Sos(eq_sos([{"type": "lowcut", "freq": fx['sc_hpf_hz']}], self.sr)) if fx['sc_hpf_hz'] else None
        self.e = np.zeros(1)
        self.g = np.zeros(1)

    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        key = x if not fx['sidechain'] else blk.key(fx['sidechain'])
        key = key.mean(0) if key.ndim == 2 else key
        if self.hpf is not None:
            key = self.hpf(key)
        lvl = dsp.db(dsp.env_follow_s(np.ascontiguousarray(key, dtype=np.float64), 0.0005, 0.01, self.sr, self.e))
        thr = dsp.as_curve(blk.param('threshold_db', fx['threshold_db']), n)
        gr = dsp.gain_computer(lvl - thr, 0.0, float(fx['ratio']), float(fx['knee_db']))
        gr = dsp.smooth_gain_s(gr, fx['attack_ms'] / 1000, fx['release_ms'] / 1000, self.sr, self.g)
        y = x * dsp.undb(gr + fx['makeup_db'])
        blk.note_gr(float(np.min(gr)) if len(gr) else 0.0)
        return _mix(x, y, fx['mix'])


class _Duck(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        if not fx['source'] and not fx['every_beats']:
            raise FxError("duck needs 'source': '<track>' (duck on its notes) or 'every_beats': 1")
        ms = self.sr / 1000
        a, h, r = int(fx['attack_ms'] * ms), int(fx['hold_ms'] * ms), max(int(fx['release_ms'] * ms), 1)
        i = np.arange(a + h + r + 1)
        self.shape = np.where(i < a, i / max(a, 1), np.where(i < a + h, 1.0,
                                                             np.clip(1 - (i - a - h) / r, 0, 1) ** fx['curve']))

    def process(self, x, blk):
        fx, n, pos = self.fx, x.shape[1], blk.pos
        L = len(self.shape)
        if fx['source']:
            ons = blk.onsets(fx['source'], pos - L, pos + n)
        else:
            step = fx['every_beats'] * 60 / self.env.bpm * self.sr
            base = self.env.offset_samples % step
            k0 = max(0, int(np.ceil((pos - L - base) / step)))
            k1 = int(np.floor((pos + n - base) / step))
            ons = base + np.arange(k0, k1 + 1) * step
        out = np.zeros(n)
        for o in ons:
            oi = int(o) - pos
            a, b = max(0, -oi), min(L, n - oi)
            if b > a:
                np.maximum(out[oi + a:oi + b], self.shape[a:b], out=out[oi + a:oi + b])
        return x * dsp.undb(out * -np.abs(dsp.as_curve(blk.param('depth_db', fx['depth_db']), n)))


class _Gate(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.steps, self.total = parse_steps(fx['pattern'], fx['step'])
        self.e = np.zeros(1)

    def process(self, x, blk):
        fx, n, pos = self.fx, x.shape[1], blk.pos
        spb = 60 / self.env.bpm * self.sr
        off = self.env.offset_samples
        cycle = self.total * spb
        tgt = np.zeros(n)
        k0 = int(np.floor((pos - off) / cycle)) - 1
        k1 = int(np.floor((pos + n - off) / cycle)) + 1
        for k in range(k0, k1 + 1):
            for st, d, v in self.steps:
                a = int(off + (k * self.total + st) * spb)
                b = int(a + d * spb)
                lo, hi = max(a, pos), min(b, pos + n)
                if hi > lo:
                    tgt[lo - pos:hi - pos] = v / 127
        env = dsp.env_follow_s(tgt, fx['attack_ms'] / 1000, fx['release_ms'] / 1000, self.sr, self.e)
        depth = blk.param('depth', fx['depth'])
        return x * (1 - depth + depth * env)


class _Delay(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.ds = max(int((fx['time_ms'] / 1000 if fx['time_ms'] else fx['time_beats'] * 60 / env.bpm) * self.sr), 1)
        self.hp = _Sos(eq_sos([{"type": "lowcut", "freq": fx['hp_hz']}], self.sr), 2) if fx['hp_hz'] else None
        self.coef = 1 - np.exp(-2 * np.pi * fx['lp_hz'] / self.sr)
        self.bl, self.br, self.st = np.zeros(self.ds + 1), np.zeros(self.ds + 1), np.zeros(3)

    def process(self, x, blk):
        src = x if self.hp is None else self.hp(x)
        wl, wr = dsp.feedback_delay_s(src[0].copy(), src[1].copy(), self.ds, float(self.fx['feedback']),
                                      bool(self.fx['pingpong']), self.coef, self.bl, self.br, self.st)
        return x * self.env.dry + np.stack([wl, wr]) * blk.param('mix', self.fx['mix'])


class _Reverb(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        pre = int(fx['predelay_ms'] / 1000 * self.sr)
        self.pre = _Lag(pre, signal=True) if pre else None
        self.hp = _Sos(eq_sos([{"type": "lowcut", "freq": fx['hp_hz']}], self.sr)) if fx['hp_hz'] else None
        self.lp = _Sos(eq_sos([{"type": "highcut", "freq": fx['lp_hz']}], self.sr)) if fx['lp_hz'] else None
        self.verb = dsp.Freeverb(fx['size'], fx['damp'], self.sr)

    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        mono = x.mean(0)
        if self.hp is not None:
            mono = self.hp(mono)
        if self.lp is not None:
            mono = self.lp(mono)
        if self.pre is not None:
            mono = self.pre(mono, n)
        wl, wr = self.verb.process(np.ascontiguousarray(mono))
        mid, side = (wl + wr) / 2, (wl - wr) / 2 * fx['width']
        return x * self.env.dry + np.stack([mid + side, mid - side]) * blk.param('mix', fx['mix']) * 3.0


class PartConv:
    """Uniformly partitioned FFT convolution (overlap-save) of a mono input with k impulse responses.
    Output = the linear convolution delayed by P samples, whatever the block sizes. A first block of 16+
    partitions (offline: the whole window) is convolved in one FFT pass instead; the processor then refuses
    further blocks (offline runs never send any)."""

    def __init__(self, irs, P=1024):
        self.P = P
        self.irs = irs
        k, m = irs.shape
        self.nparts = max(1, int(np.ceil(m / P)))
        pad = np.zeros((k, self.nparts * P))
        pad[:, :m] = irs
        parts = pad.reshape(k, self.nparts, P)
        self.H = np.fft.rfft(np.concatenate([parts, np.zeros_like(parts)], axis=2), axis=2)
        self.fdl = np.zeros((self.nparts, P + 1), dtype=complex)
        self.inbuf = np.zeros(2 * P)
        self.pending = np.zeros(0)
        self.out = np.zeros((k, P))
        self.fed = 0
        self.oneshot = False

    def process(self, x):
        n = len(x)
        if self.oneshot:
            raise RuntimeError("PartConv used one-shot (offline); build a new one for block processing")
        if self.fed == 0 and n >= 16 * self.P:
            self.oneshot = True
            y = np.stack([signal.oaconvolve(x, ir)[:n] for ir in self.irs])
            return np.concatenate([np.zeros((len(self.irs), self.P)), y], axis=1)[:, :n]
        self.fed += n
        self.pending = np.concatenate([self.pending, x])
        outs = [self.out]
        P = self.P
        while len(self.pending) >= P:
            blk, self.pending = self.pending[:P], self.pending[P:]
            self.inbuf = np.concatenate([self.inbuf[P:], blk])
            self.fdl = np.roll(self.fdl, 1, axis=0)
            self.fdl[0] = np.fft.rfft(self.inbuf)
            Y = np.einsum('kpf,pf->kf', self.H, self.fdl)
            outs.append(np.fft.irfft(Y, 2 * P, axis=1)[:, P:])
        allout = np.concatenate(outs, axis=1)
        self.out = allout[:, n:]
        return allout[:, :n]


class _Hall(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        ir = hall_ir(fx['rt60'], fx['low_mult'], fx['high_mult'], fx['predelay_ms'], fx['early'], self.sr,
                     int(fx['seed']))
        self.conv = PartConv(ir, 1024)
        self.latency = self.conv.P
        self.hp = _Sos(eq_sos([{"type": "lowcut", "freq": fx['hp_hz']}], self.sr)) if fx['hp_hz'] else None
        self.dry_lag = _Lag(self.latency, signal=True)
        self.mix_lag = _Lag(self.latency)

    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        mono = x.mean(0)
        if self.hp is not None:
            mono = self.hp(mono)
        wl, wr = self.conv.process(mono)
        mid, side = (wl + wr) / 2, (wl - wr) / 2 * fx['width']
        return self.dry_lag(x, n) * self.env.dry + np.stack([mid + side, mid - side]) * \
            self.mix_lag(blk.param('mix', fx['mix']), n)


class _Chorus(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        size = int((fx['delay_ms'] + fx['depth_ms']) / 1000 * self.sr) + 4
        self.bufs = [np.zeros(size), np.zeros(size)]
        self.st = [np.zeros(1), np.zeros(1)]

    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        is_flanger = fx['type'] == 'flanger'
        rate = fx['rate_hz'] if not is_flanger or not fx.get('rate_beats') else self.env.bpm / 60 / fx['rate_beats']
        ph = (blk.pos + np.arange(n)) * rate / self.sr
        outs = []
        for ch, off in ((0, 0.0), (1, 0.25)):
            d = (fx['delay_ms'] + fx['depth_ms'] * (0.5 + 0.5 * np.sin(2 * np.pi * (ph + off)))) / 1000 * self.sr
            outs.append(dsp.mod_delay_s(np.ascontiguousarray(x[ch]), d, fx['feedback'], 1.0, self.bufs[ch], self.st[ch]))
        return _mix(x, np.stack(outs), blk.param('mix', fx['mix']))


class _Phaser(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.z = [np.zeros(int(fx['stages'])), np.zeros(int(fx['stages']))]
        self.st = [np.zeros(1), np.zeros(1)]

    def process(self, x, blk):
        fx, n, sr = self.fx, x.shape[1], self.sr
        ph = _lfo_phase(n, fx['rate_hz'], fx['rate_beats'], self.env.bpm, sr, blk.pos)
        outs = []
        for ch, off in ((0, 0.0), (1, 0.25)):
            m = fx['center'] + 0.5 * fx['depth'] * np.sin(2 * np.pi * (ph + off))
            fc = 200 * 2 ** (m * 6)  # 200 Hz .. 12.8 kHz
            wc = np.tan(np.pi * np.minimum(fc, sr * 0.45) / sr)
            coef = (wc - 1) / (wc + 1)
            outs.append(dsp.allpass1_chain_s(np.ascontiguousarray(x[ch]), coef, int(fx['stages']), fx['feedback'],
                                             self.z[ch], self.st[ch]))
        return _mix(x, (x + np.stack(outs)) / 2, blk.param('mix', fx['mix']))


class _Tremolo(Proc):
    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        ph = _lfo_phase(n, fx['rate_hz'], fx['rate_beats'], self.env.bpm, self.sr,
                        blk.pos - self.env.offset_samples) + fx['phase']
        w = dsp.lfo_wave(fx['shape'], ph)
        d = blk.param('depth', fx['depth'])
        if fx['mode'] == 'pan':
            gl, gr = dsp.pan_gains(w * d)
            return np.stack([x[0] * gl, x[1] * gr])
        return x * (1 - d * (0.5 - 0.5 * w))


class _Width(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.hp = _Sos(eq_sos([{"type": "lowcut", "freq": fx['mono_below_hz'], "slope": 24}], self.sr)) \
            if fx['mono_below_hz'] else None

    def process(self, x, blk):
        mid = (x[0] + x[1]) / 2
        side = (x[0] - x[1]) / 2
        if self.hp is not None:
            side = self.hp(side)
        side = side * blk.param('width', self.fx['width'])
        return np.stack([mid + side, mid - side])


class _Limiter(Proc):
    """Peak limiter: the gain at sample i is set by the peaks within +-lookahead of i, so the output is delayed
    by the lookahead (latency)."""

    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.la = int(fx['lookahead_ms'] / 1000 * self.sr)
        self.latency = self.la
        self.ceil = dsp.undb(fx['ceiling_db'])
        self.xh = np.zeros((2, self.la))
        self.ph = np.zeros(2 * self.la)
        self.g = np.zeros(1)

    def process(self, x, blk):
        from scipy.ndimage import maximum_filter1d
        fx, n, la = self.fx, x.shape[1], self.la
        xg = x * dsp.undb(fx['gain_db'])
        ext = np.concatenate([self.ph, np.max(np.abs(xg), axis=0)])
        self.ph = ext[len(ext) - 2 * la:] if la else self.ph
        pk = maximum_filter1d(ext, size=2 * la + 1)[la:la + n]
        xd = np.concatenate([self.xh, xg], axis=1)
        self.xh = xd[:, xd.shape[1] - la:] if la else self.xh
        xd = xd[:, :n]
        need = np.minimum(1.0, self.ceil / np.maximum(pk, 1e-9))
        gdb = dsp.smooth_gain_s(dsp.db(need), 0.0001, fx['release_ms'] / 1000, self.sr, self.g)
        gdb = np.minimum(gdb, dsp.db(need))
        blk.note_gr(float(np.min(gdb)) if n else 0.0)
        return np.clip(xd * dsp.undb(gdb), -self.ceil, self.ceil)


class _Formant(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        if fx['vowel'] not in VOWEL_FORMANTS and not (fx['f1'] and fx['f2']):
            raise FxError(f"formant vowel must be one of {list(VOWEL_FORMANTS)} or give f1/f2(/f3) in Hz")
        base = VOWEL_FORMANTS.get(fx['vowel'], (500, 1450, 2500))
        fs = [fx['f1'] or base[0], fx['f2'] or base[1], fx['f3'] or base[2]]
        self.bands = []
        for f, g in zip(fs, fx['gains_db']):
            f = min(f * fx['shift'], self.sr * 0.45)
            bw = f / fx['q']
            sos = signal.butter(2, [max(f - bw / 2, 20), f + bw / 2], btype='band', fs=self.sr, output='sos')
            self.bands.append((_Sos(sos, 2), dsp.undb(g)))

    def process(self, x, blk):
        wet = np.zeros_like(x)
        for f, g in self.bands:
            wet += f(x) * g
        return _mix(x, wet * 4.0, blk.param('mix', self.fx['mix']))


class _Vocoder(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        if not fx['modulator']:
            raise FxError("vocoder needs 'modulator': '<track name>' or 'sound:<name>' (the voice)")
        sr = self.sr
        edges = np.geomspace(fx['lo_hz'], fx['hi_hz'], int(fx['bands']) + 1)
        centers = np.sqrt(edges[:-1] * edges[1:])
        self.bands = []
        for fc in centers:
            sos = signal.butter(2, [fc / 2 ** (0.5 / fx['q'] * 3), min(fc * 2 ** (0.5 / fx['q'] * 3), sr * 0.45)],
                                btype='band', fs=sr, output='sos')
            self.bands.append((_Sos(sos), _Sos(sos, 2), np.zeros(1)))
        self.hp = _Sos(signal.butter(4, 5000, btype='high', fs=sr, output='sos'))

    def process(self, x, blk):
        fx = self.fx
        mod = blk.modulator(fx['modulator'])
        mod = mod.mean(0) if mod.ndim == 2 else mod
        rel = fx['release_ms'] / 1000
        wet = np.zeros_like(x)
        for fm, fc, e in self.bands:
            env = dsp.env_follow_s(np.ascontiguousarray(fm(mod)), 0.002, rel, self.sr, e)
            wet += fc(x) * env
        hp = self.hp(mod)
        if fx['unvoiced']:
            wet += hp * fx['unvoiced']
        return _mix(x, wet * 8.0, blk.param('mix', fx['mix']))


PROCS = {'gain': _Gain, 'eq': _Eq, 'filter': _Filter, 'distortion': _Distortion, 'bitcrush': _Bitcrush,
         'compressor': _Compressor, 'duck': _Duck, 'gate': _Gate, 'delay': _Delay, 'reverb': _Reverb, 'hall': _Hall,
         'chorus': _Chorus, 'flanger': _Chorus, 'phaser': _Phaser, 'tremolo': _Tremolo, 'width': _Width,
         'limiter': _Limiter, 'formant': _Formant, 'vocoder': _Vocoder}


def make(fx, env):
    """A processor for a normalized effect dict."""
    if fx.get('bypass'):
        return _Bypass(fx, env)
    return PROCS[fx['type']](fx, env)


class _OfflineBlock(Block):
    """The whole render window as one block, reading automation / sources from a render Ctx."""

    def __init__(self, ctx, idx, n, n0):
        self.ctx, self.idx, self.n, self.n0 = ctx, idx, n, n0

    def param(self, name, default):
        v = self.ctx.param(self.idx, name, default)
        return v if np.isscalar(v) else dsp.as_curve(v, self.n)

    def _pad(self, a):
        a = np.asarray(a, dtype=np.float64)
        if a.shape[-1] >= self.n:
            return a[..., :self.n]
        return np.concatenate([a, np.zeros(a.shape[:-1] + (self.n - a.shape[-1],))], axis=-1)

    def key(self, track):
        return self._pad(self.ctx.track_audio(track))

    def onsets(self, track, lo, hi):
        o = np.asarray(self.ctx.track_onsets(track), dtype=np.float64) * self.ctx.sr
        return o[(o >= lo) & (o < hi)]

    def modulator(self, ref):
        return self._pad(self.ctx.modulator_audio(ref, self.n0))

    def note_gr(self, gr_db):
        self.ctx.note_gr(self.idx, gr_db)


def apply_fx(x, fx, ctx, idx):
    """Offline: run effect `fx` over the whole window x (2, n) as one block, latency compensated."""
    if fx.get('bypass'):
        return x
    env = Env(ctx.sr, ctx.bpm, _dry(fx, ctx), getattr(ctx, 'offset_samples', 0))
    p = make(fx, env)
    n = x.shape[1]
    L = p.latency
    xin = x if L == 0 else np.concatenate([x, np.zeros((2, L))], axis=1)
    y = p.process(xin, _OfflineBlock(ctx, idx, n + L, n))
    return y[:, L:] if L else y


_IR_CACHE = {}


def hall_ir(rt60, low_mult, high_mult, predelay_ms, early, sr, seed=1):
    """Synthetic hall impulse response (2, n), unit energy: decorrelated noise tail whose decay time falls with
    frequency (octave bands, rt60 at 1 kHz, low_mult below ~250 Hz, high_mult above ~6 kHz), a density build-up
    over the first ~80 ms, and sparse early reflections."""
    key = (rt60, low_mult, high_mult, predelay_ms, early, sr, seed)
    if key in _IR_CACHE:
        return _IR_CACHE[key]
    rng = np.random.default_rng(seed)
    n = int((rt60 * max(low_mult, 1.0) * 1.1 + predelay_ms / 1000) * sr)
    t = np.arange(n) / sr
    pre = int(predelay_ms / 1000 * sr)
    noise = rng.standard_normal((2, n))
    tail = np.zeros((2, n))
    centers = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
    lc = np.log2(np.array(centers) / 1000.0)
    for fc, l in zip(centers, lc):
        mult = np.interp(l, [-4, -2, 0, 2.6, 4], [low_mult, low_mult, 1.0, high_mult, high_mult * 0.7])
        lo, hi = fc / np.sqrt(2), min(fc * np.sqrt(2), sr * 0.45)
        if lo >= hi:
            continue
        sos = signal.butter(2, [lo, hi], btype='band', fs=sr, output='sos')
        band = signal.sosfilt(sos, noise, axis=1)
        tail += band * np.exp(-6.91 * t / (rt60 * mult))
    build = 1 - np.exp(-np.maximum(t - 0.01, 0) / 0.04)
    tail *= build
    tail = np.concatenate([np.zeros((2, pre)), tail[:, :n - pre]], axis=1)
    er = np.zeros((2, n))
    for i in range(14):
        d = pre + int(rng.uniform(0.004, 0.075) * sr)
        g = early * rng.uniform(0.4, 1.0) * np.exp(-(d - pre) / sr / 0.05)
        er[i % 2, d] += g * 3.0
        er[(i + 1) % 2, min(n - 1, d + int(rng.uniform(0.0005, 0.003) * sr))] += g * 1.5
    ir = tail / np.sqrt(np.sum(tail ** 2) / 2) + er / max(1.0, np.sqrt(np.sum(er ** 2) / 2) / max(early, 1e-6))
    ir /= np.sqrt(np.sum(ir ** 2) / 2)
    _IR_CACHE[key] = ir
    return ir
