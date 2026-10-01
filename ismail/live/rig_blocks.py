"""Live processors for the guitar rig (ismail/rig.py): fuzz, univibe, amp, cab, rotary, tape and wah, block by
block with their state kept, running the studio kernels themselves. They used to be baked into every rendered note,
which cost a worker ~1 s per second of guitar, stacked one amp's hiss per note, and reset the amp and the speaker
between notes. tests/test_live_parity.py holds each to its studio twin.

Automation of amp gain, cab mic and tape drive follows the block (the studio takes the mean over its window)."""
import numpy as np
from numba import njit
from scipy import signal

from .. import rig as R
from . import fx_blocks
from .fx_blocks import Proc, _Lag, _Sos

# ------------------------------------------------------------------ kernels


@njit(cache=True)
def up_s(x, h, os, hist):
    """Zero-stuffing upsampler + FIR h, computed polyphase (only the non-zero inputs): equal to lfilter(h) on the
    stuffed signal. x (c, n); hist (c, m) the last m inputs, m = ceil(len(h) / os), updated in place."""
    c, n = x.shape
    L = len(h)
    m = hist.shape[1]
    y = np.empty((c, n * os))
    for ch in range(c):
        buf = np.empty(m + n)
        buf[:m] = hist[ch]
        buf[m:] = x[ch]
        for q in range(n):
            for r in range(os):
                acc = 0.0
                i = 0
                while r + i * os < L:
                    acc += h[r + i * os] * buf[m + q - i]
                    i += 1
                y[ch, q * os + r] = acc
        hist[ch] = buf[n:]
    return y


@njit(cache=True)
def down_s(y, h, os, hist):
    """FIR h then keep every os-th sample, computing only the kept ones: equal to lfilter(h)[::os]. y (c, n * os);
    hist (c, len(h) - 1) the last inputs, updated in place."""
    c, N = y.shape
    L = len(h)
    m = L - 1
    n = N // os
    out = np.empty((c, n))
    for ch in range(c):
        buf = np.empty(m + N)
        buf[:m] = hist[ch]
        buf[m:] = y[ch]
        for k in range(n):
            acc = 0.0
            t = m + k * os
            for j in range(L):
                acc += h[j] * buf[t - j]
            out[ch, k] = acc
        hist[ch] = buf[N:]
    return out


@njit(cache=True)
def frac_delay_s(x, d, hist, pos0):
    """rig._frac_delay across blocks: hist holds the previous inputs, pos0 is the processor time of x[0]; before
    processor time 0 the input is silence (as at the start of a studio window)."""
    n = len(x)
    H = len(hist)
    y = np.empty(n)
    for i in range(n):
        p = i - d[i]
        if pos0 + p < 0:
            y[i] = 0.0
            continue
        j = int(np.floor(p))
        fr = p - j
        a = x[j] if j >= 0 else hist[H + j]
        jb = j + 1
        b = a if jb >= n else (x[jb] if jb >= 0 else hist[H + jb])
        y[i] = a + (b - a) * fr
    return y


def _push(hist, x):
    """The last len(hist) samples of hist followed by x."""
    H = len(hist)
    return np.concatenate([hist, x])[-H:] if H else hist


def _resampler(os):
    """The FIR scipy's resample_poly designs for a factor os (as fx_blocks._Distortion): up gain os, down gain 1.
    Run causally, up and down delay 10 base samples each."""
    half = 10 * os
    return signal.firwin(2 * half + 1, 1.0 / os, window=('kaiser', 5.0))


class _Fir:
    """Causal FIR over consecutive blocks of (c, n): what fftconvolve(x, h)[:n] gives over the whole window."""

    def __init__(self, h, channels):
        self.h = np.asarray(h, dtype=np.float64)
        self.hist = np.zeros((channels, len(self.h) - 1))
        self.H = {}                     # FFT size -> spectrum of h (blocks are mostly one size)

    def set(self, h):
        h = np.asarray(h, dtype=np.float64)
        m = len(h) - 1
        if m != self.hist.shape[1]:
            old = self.hist
            self.hist = np.zeros((old.shape[0], m))
            k = min(m, old.shape[1])
            if k:
                self.hist[:, m - k:] = old[:, old.shape[1] - k:]
        self.h = h
        self.H = {}

    def __call__(self, x):
        from scipy import fft
        m = self.hist.shape[1]
        buf = np.concatenate([self.hist, x], axis=1)
        self.hist = buf[:, buf.shape[1] - m:]
        if not m:
            return buf * self.h[0]
        L = buf.shape[1]
        nf = fft.next_fast_len(L, real=True)
        H = self.H.get(nf)
        if H is None:
            H = self.H[nf] = fft.rfft(self.h, nf)
        # overlap-save: outputs m.. of a circular convolution at least as long as the input are the linear ones
        return fft.irfft(fft.rfft(buf, nf, axis=1) * H, nf, axis=1)[:, m:L]


def _mean(v):
    return float(np.mean(v))


def _mix(dry, wet, m):
    return dry * (1 - m) + wet * m


# ------------------------------------------------------------------ processors


class _Fuzz(Proc):
    OS = 4

    def __init__(self, fx, env):
        super().__init__(fx, env)
        h = _resampler(self.OS)
        self.h_up, self.h_dn = h * self.OS, h
        self.up_h = np.zeros((2, -(-len(h) // self.OS)))
        self.dn_h = np.zeros((2, len(h) - 1))
        self.st = [np.zeros(2), np.zeros(2)]
        self.post = _Sos(np.vstack([signal.butter(1, 70, 'highpass', fs=self.sr, output='sos'),
                                    signal.butter(2, min(fx['tone_hz'], self.sr * 0.45), 'lowpass', fs=self.sr,
                                                  output='sos')]), 2)
        self.latency = 20
        self.dry_lag = _Lag(20, signal=True)
        self.mix_lag = _Lag(20)

    def process(self, x, blk):
        fx, n, os_ = self.fx, x.shape[1], self.OS
        g_in = 10 ** (np.asarray(blk.param('input_db', fx['input_db'])) / 20)
        drive = 1.0 + 60.0 * float(fx['fuzz']) ** 2
        xi = up_s(np.ascontiguousarray(x * g_in), self.h_up, os_, self.up_h)
        y = np.stack([R._fuzz_core(xi[c], drive, float(fx['bias']), bool(fx['silicon']), self.sr * os_, self.st[c])
                      for c in (0, 1)])
        y = down_s(y, self.h_dn, os_, self.dn_h)
        y = self.post(y) * 10 ** (fx['level_db'] / 20) * 0.5
        return _mix(self.dry_lag(x, n), y, self.mix_lag(blk.param('mix', fx['mix']), n))


class _Univibe(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.acc = 0.0
        self.lamp = np.zeros(1)
        self.caps = R.VIBE_CAPS * 48000.0 / self.sr
        self.z = [np.zeros(len(self.caps)), np.zeros(len(self.caps))]
        self.hp = _Sos(signal.butter(1, 25, 'highpass', fs=self.sr, output='sos'), 2)

    def process(self, x, blk):
        fx, n = self.fx, x.shape[1]
        rate = np.broadcast_to(np.asarray(blk.param('rate_hz', fx['rate_hz']), dtype=np.float64), (n,))
        inten = np.broadcast_to(np.asarray(blk.param('intensity', fx['intensity']), dtype=np.float64), (n,))
        c = self.acc + np.cumsum(rate)
        self.acc = float(c[-1]) if n else self.acc
        lamp = R._lamp(R.vibe_lamp_drive(c / self.sr, inten), self.sr, 0.006, 0.045, self.lamp)
        wet = np.stack([R._vibe_core(np.ascontiguousarray(x[k]), lamp, self.caps, 4.0e3, 2.0e5, 0.12,
                                     float(fx['drive']), self.z[k]) for k in (0, 1)])
        wet = self.hp(wet)
        out = wet if fx['mode'] == 'vibrato' else 0.5 * (x + wet)
        return _mix(x, out, blk.param('mix', fx['mix']))


class _Amp(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        os_ = R.AMP_OS
        self.srr = self.sr * os_
        h = _resampler(os_)
        self.h_up, self.h_dn = h * os_, h
        self.up_h = np.zeros((2, -(-len(h) // os_)))
        self.dn_h = np.zeros((2, len(h) - 1))
        hp, tone, pres, xfmr = R.amp_stage_sos(fx, self.srr)
        self.hp, self.tone, self.xfmr = _Sos(hp, 2), _Sos(tone, 2), _Sos(xfmr, 2)
        self.pres = _Sos(pres, 2) if pres is not None else None
        self.pw = [np.zeros(1), np.zeros(1)]
        self.gain = None
        self.pre = None
        self.noisy = fx['hiss_db'] > -119 or fx['hum_db'] > -119
        if self.noisy:
            self.noise = 0.5 * 10 ** (fx['out_db'] / 20) * np.hypot(0.98 * 10 ** (fx['hiss_db'] / 20),
                                                                    0.84 * 10 ** (fx['hum_db'] / 20))
        if self.noisy:
            self.rngs = R.noise_streams(fx['seed'])
            self.hiss_hp = _Sos(signal.butter(1, 800, 'highpass', fs=self.sr, output='sos'), 2)
            self.noise_lag = _Lag(20, signal=True)
        self.latency = 20

    def _set_gain(self, gain):
        sos = R.amp_pre_sos(self.fx, gain, self.sr)
        if self.pre is None or self.pre.sos.shape != sos.shape:
            self.pre = _Sos(sos, 2)
        else:
            self.pre.sos = np.ascontiguousarray(sos)
        self.gain = gain
        self.d1, self.d2, self.drive = R.amp_drives(self.fx, gain)

    def process(self, x, blk):
        fx, n, os_ = self.fx, x.shape[1], R.AMP_OS
        gain = _mean(blk.param('gain', fx['gain']))
        if gain != self.gain:
            self._set_gain(gain)
        y = up_s(np.ascontiguousarray(self.pre(x)), self.h_up, os_, self.up_h)
        y = np.stack([R._tube(ch, self.d1, 0.25) for ch in y])
        y = self.hp(y)
        y = np.stack([R._tube(ch, self.d2, 0.15) for ch in y]) * 0.5
        y = self.tone(y) * 3.0
        if self.pres is not None:
            y = self.pres(y)
        y = np.stack([R._power(y[c], self.drive, float(fx['sag']), self.srr, self.pw[c]) for c in (0, 1)])
        y = down_s(self.xfmr(y), self.h_dn, os_, self.dn_h)
        if self.noisy:
            # the amp's own noise, in studio time: the output runs `latency` behind it
            hiss = self.hiss_hp(np.stack([g.standard_normal(n) for g in self.rngs]))
            hum = R.amp_hum((blk.pos + np.arange(n)) / self.sr)
            y = y + self.noise_lag(10 ** (fx['hiss_db'] / 20) * hiss + 10 ** (fx['hum_db'] / 20) * hum[None, :], n)
        return y * 0.5 * 10 ** (fx['out_db'] / 20)


class _Cab(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.mic = None
        self.fir = None
        self.rooms = None

    def _set_mic(self, mic):
        h, rooms = R.cab_irs(self.fx, mic, self.sr)
        if self.fir is None:
            self.fir = _Fir(h, 2)
        else:
            self.fir.set(h)
        if rooms is None:
            self.rooms = None
        elif self.rooms is None:
            self.rooms = [_Fir(r, 1) for r in rooms]
        else:
            for f, r in zip(self.rooms, rooms):
                f.set(r)
        self.mic = mic

    def process(self, x, blk):
        mic = _mean(blk.param('mic', self.fx['mic']))
        if mic != self.mic:
            self._set_mic(mic)
        y = self.fir(x)
        if self.rooms is not None:
            y = np.concatenate([self.rooms[c](y[c:c + 1]) for c in (0, 1)])
        return y


class _Rotary(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.lo = _Sos(signal.butter(4, fx['crossover_hz'], 'lowpass', fs=self.sr, output='sos'))
        self.hi = _Sos(signal.butter(4, fx['crossover_hz'], 'highpass', fs=self.sr, output='sos'))
        self.sh, self.sd = np.zeros(2), np.zeros(2)
        self.ah, self.ad = 0.0, 0.0
        H = int(np.ceil((1.0 + abs(fx['doppler_ms'])) / 1000 * self.sr)) + 3
        self.hh, self.hl = np.zeros(H), np.zeros(H)

    def process(self, x, blk):
        p, n, sr = self.fx, x.shape[1], self.sr
        mono = x.mean(0)
        if p['drive'] > 0:
            g = 1 + 6 * p['drive']
            mono = np.tanh(mono * g) / np.tanh(g) * 0.8 + mono * 0.2
        lo, hi = self.lo(mono), self.hi(mono)
        spd = np.clip(np.broadcast_to(np.asarray(blk.param('speed', p['speed']), dtype=np.float64), (n,)), 0, 1)
        spd = np.ascontiguousarray(spd)
        h_rate = R._ramp_speed(spd, p['horn_slow'], p['horn_fast'], p['horn_ramp_s'], sr, self.sh)
        d_rate = R._ramp_speed(spd, p['drum_slow'], p['drum_fast'], p['drum_ramp_s'], sr, self.sd)
        ch_, cd = self.ah + np.cumsum(h_rate), self.ad + np.cumsum(d_rate)
        if n:
            self.ah, self.ad = float(ch_[-1]), float(cd[-1])
        h_ph, d_ph = ch_ / sr, cd / sr + 0.37
        out = []
        for ang in (-p['spread'] * 0.25, p['spread'] * 0.25):
            hc = np.cos(2 * np.pi * (h_ph + ang))
            dc = np.cos(2 * np.pi * (d_ph + ang))
            horn = frac_delay_s(hi, (1.0 + p['doppler_ms'] * hc) / 1000 * sr, self.hh, blk.pos) * \
                (1 - p['horn_am'] * 0.5 * (1 - hc))
            drum = frac_delay_s(lo, (1.0 + 0.3 * p['doppler_ms'] * dc) / 1000 * sr, self.hl, blk.pos) * \
                (1 - p['drum_am'] * 0.5 * (1 - dc))
            out.append(horn + drum)
        self.hh, self.hl = _push(self.hh, hi), _push(self.hl, lo)
        return _mix(x, np.stack(out), blk.param('mix', p['mix']))


class _Tape(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.sos = _Sos(R.tape_sos(fx, self.sr), 2)
        self.wow = fx['wow'] > 0 or fx['flutter'] > 0
        if self.wow:
            self.dev, self.off = R.tape_wow(fx, self.sr)
            self.acc = 0.0
            H = int(np.ceil(2 * self.off)) + 4
            self.hist = [np.zeros(H), np.zeros(H)]
        self.hiss = fx['hiss_db'] > -120
        if self.hiss:
            self.noise = 0.95 * 10 ** (fx['hiss_db'] / 20)
            self.rngs = R.noise_streams(int(fx['seed']) + 5)
            self.hiss_hp = _Sos(signal.butter(1, 2000, 'highpass', fs=self.sr, output='sos'), 2)

    def process(self, x, blk):
        p, n = self.fx, x.shape[1]
        y = self.sos(R.tape_saturate(x, _mean(blk.param('drive', p['drive']))))
        if self.wow:
            c = self.acc + np.cumsum(self.dev((blk.pos + np.arange(n)) / self.sr))
            if n:
                self.acc = float(c[-1])
            dly = c + self.off
            pre = y
            y = np.stack([frac_delay_s(np.ascontiguousarray(pre[k]), dly, self.hist[k], blk.pos) for k in (0, 1)])
            self.hist = [_push(self.hist[k], pre[k]) for k in (0, 1)]
        if self.hiss:
            y = y + self.hiss_hp(np.stack([g.standard_normal(n) for g in self.rngs]) * 10 ** (p['hiss_db'] / 20))
        return y


class _Wah(Proc):
    def __init__(self, fx, env):
        super().__init__(fx, env)
        self.e = np.zeros(1)
        self.pk = np.zeros(1)
        self.st = [np.zeros(2), np.zeros(2)]

    def process(self, x, blk):
        from .dsp_blocks import env_follow_s
        p, n = self.fx, x.shape[1]
        pos = np.array(np.broadcast_to(np.asarray(blk.param('pos', p['pos']), dtype=np.float64), (n,)))
        if p['auto'] > 0:
            e = env_follow_s(np.ascontiguousarray(np.abs(x).mean(0)), p['attack_ms'] / 1000, p['release_ms'] / 1000,
                             self.sr, self.e)
            pos = np.clip(pos + p['auto'] * R._peak_norm(e, self.sr, self.pk), 0, 1)
        fc = p['lo_hz'] * (p['hi_hz'] / p['lo_hz']) ** pos
        wet = np.stack([R._wah_core(np.ascontiguousarray(x[k]), fc, p['q'], self.sr, self.st[k]) for k in (0, 1)])
        return _mix(x, wet * 1.6, blk.param('mix', p['mix']))


PROCS = {'fuzz': _Fuzz, 'univibe': _Univibe, 'amp': _Amp, 'cab': _Cab, 'rotary': _Rotary, 'tape': _Tape,
         'wah': _Wah}
fx_blocks.PROCS.update(PROCS)
