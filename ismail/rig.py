"""Guitar rig effects: the 1960s/70s chain between a pickup and a tape machine.

fuzz     germanium/silicon two-transistor fuzz (Fuzz Face): asymmetric clipping whose bias shifts with the signal,
         so it sputters on decays and cleans up when the input is turned down
univibe  four-stage photocell phase shifter: staggered stage capacitors (uneven notch spacing), one lamp driving
         all four LDRs (fast on, slow off), stages that are not true all-passes, soft clipping per stage
amp      tube guitar amp with no master volume (Plexi-style): bright cap, two preamp stages, Marshall tone stack
         (Yeh & Smith 2006 analytic TMB), a push-pull power stage with supply sag and presence
cab      speaker cabinet + microphone as a minimum-phase FIR: cone resonance, presence rise, steep top roll-off,
         cone break-up ripples; mic='close'|'room'|a blend; the room mic adds a short stereo reflection pattern
rotary   rotating speaker (Leslie): 800 Hz crossover, horn and drum with their own speeds, Doppler + amplitude
         modulation, speed changes that ramp (horn fast, drum slow), two mics for stereo
tape     tape machine: soft asymmetric saturation, head bump, top-end loss, wow and flutter, hiss
wah      wah pedal: resonant band-pass swept by a pedal position (automatable) or by the input envelope

All of them take and return stereo (2, n) float64. Parameters and ranges are in DEFAULTS and DOCS.
Every one is causal and its kernels take their state as an argument, so the live engine runs the same code block
by block (ismail/live/rig_blocks.py; tests/test_live_parity.py holds the two together).
"""
import numpy as np
from numba import njit
from scipy import signal

DEFAULTS = {
    "fuzz": {"fuzz": 0.8, "input_db": 0.0, "bias": 0.5, "level_db": 0.0, "tone_hz": 7000.0, "mix": 1.0,
             "silicon": True},
    "univibe": {"rate_hz": 3.5, "intensity": 0.8, "mode": "chorus", "mix": 1.0, "drive": 0.3},
    "amp": {"gain": 5.0, "volume": 6.0, "bass": 5.0, "mid": 6.0, "treble": 6.0, "presence": 5.0, "bright": 0.5,
            "sag": 0.5, "out_db": 0.0, "hiss_db": -120.0, "hum_db": -120.0, "seed": 1},
    "cab": {"mic": 0.2, "low_hz": 75.0, "high_hz": 5000.0, "presence_db": 4.0, "breakup": 1.0, "room_ms": 7.0,
            "width": 0.6, "seed": 3},
    "rotary": {"speed": 0.0, "horn_slow": 0.83, "horn_fast": 6.7, "drum_slow": 0.67, "drum_fast": 5.7,
               "horn_ramp_s": 0.8, "drum_ramp_s": 3.5, "doppler_ms": 0.35, "horn_am": 0.5, "drum_am": 0.35,
               "crossover_hz": 800.0, "spread": 0.8, "drive": 0.2, "mix": 1.0},
    "tape": {"drive": 0.3, "bump_db": 2.0, "bump_hz": 70.0, "hf_hz": 15000.0, "wow": 0.05, "flutter": 0.03,
             "hiss_db": -72.0, "seed": 7},
    "wah": {"pos": 0.5, "auto": 0.0, "lo_hz": 380.0, "hi_hz": 2300.0, "q": 6.0, "mix": 1.0, "attack_ms": 8.0,
            "release_ms": 120.0},
}
AUTOMATABLE = {"fuzz": ("input_db", "mix"), "univibe": ("rate_hz", "intensity", "mix"), "amp": ("gain",),
               "cab": ("mic",), "rotary": ("speed", "mix"), "tape": ("drive",), "wah": ("pos", "mix")}
DOCS = {
    "fuzz": "fuzz 0-1 (Fuzz knob), input_db: guitar volume into the pedal (-12 cleans up), bias 0-1 (0.5 = sweet, "
            "low = gated sputter), silicon True (Hendrix 1970) / False (germanium, softer), tone_hz: top roll-off",
    "univibe": "rate_hz 0.5-10 (the speed pedal), intensity 0-1, mode chorus (dry+wet: throb) | vibrato (wet: "
               "pitch wobble), drive 0-1 (stage clipping)",
    "amp": "gain/volume 0-10 (no master: volume past 6 is power-amp saturation), bass/mid/treble/presence 0-10, "
           "bright 0-1 (bright cap: treble boost at low gain), sag 0-1 (supply droop: compression and bloom), "
           "hiss_db / hum_db: the amp's own noise floor re full scale (-75 / -82 is a live 1970 amp; -120 = off)",
    "cab": "mic 0 = close SM57, 1 = room; low_hz cone resonance (60-120), high_hz top roll-off (3500-7000), "
           "presence_db (0-8), breakup 0-2 (cone ripples above 1 kHz), room_ms, width 0-1 (room mic stereo)",
    "rotary": "speed 0 = chorale (slow), 1 = tremolo (fast); automate it and the rotors ramp; horn_am/drum_am "
              "amplitude depth, doppler_ms horn path swing, crossover_hz, spread (mic angle), drive (Leslie amp)",
    "tape": "drive 0-1 (saturation), bump_db/bump_hz head bump, hf_hz top loss, wow/flutter in % , hiss_db",
    "wah": "pos 0 heel (dark) .. 1 toe (bright), automatable; auto 0-1 lets the input envelope push the pedal",
}


def _curve(v, n):
    a = np.asarray(v, dtype=np.float64)
    return np.full(n, float(a)) if a.ndim == 0 else a[:n]


# ------------------------------------------------------------------ fuzz

@njit(cache=True)
def _fuzz_core(x, drive, bias, silicon, sr, st):
    # two-transistor feedback fuzz, reduced: a bias point that the signal's own envelope pulls down (the
    # coupling caps charge), so decaying notes cross the knee later and sputter, as the real pedal does
    n = len(x)
    y = np.empty(n)
    env = st[0]
    a_att = np.exp(-1.0 / (0.001 * sr))
    a_rel = np.exp(-1.0 / (0.040 * sr))
    dc = st[1]
    a_dc = np.exp(-1.0 / (0.02 * sr))
    knee_p = 0.55 if silicon else 0.75
    knee_n = 0.9 if silicon else 1.1
    for i in range(n):
        v = abs(x[i])
        env = a_att * env + (1 - a_att) * v if v > env else a_rel * env + (1 - a_rel) * v
        b = (bias - 0.5) * 0.6 - 0.35 * env
        z = x[i] * drive + b
        if z > 0:
            o = knee_p * np.tanh(z / knee_p)
        else:
            o = -knee_n * np.tanh(-z / knee_n) if silicon else -knee_n * (1 - np.exp(z / knee_n))
        dc = a_dc * dc + (1 - a_dc) * o
        y[i] = o - dc
    st[0] = env
    st[1] = dc
    return y


def fuzz(x, p, sr, P):
    n = x.shape[1]
    os_ = 4
    g_in = 10 ** (_curve(P('input_db'), n) / 20)
    drive = 1.0 + 60.0 * float(p['fuzz']) ** 2
    xi = signal.resample_poly(x * g_in, os_, 1, axis=1)
    y = np.stack([_fuzz_core(ch, drive, float(p['bias']), bool(p['silicon']), sr * os_, np.zeros(2))
                  for ch in xi])
    y = signal.resample_poly(y, 1, os_, axis=1)[:, :n]
    sos = np.vstack([signal.butter(1, 70, 'highpass', fs=sr, output='sos'),
                     signal.butter(2, min(p['tone_hz'], sr * 0.45), 'lowpass', fs=sr, output='sos')])
    y = signal.sosfilt(sos, y, axis=1) * 10 ** (p['level_db'] / 20) * 0.5
    m = _curve(P('mix'), n)
    return x * (1 - m) + y * m


# ------------------------------------------------------------------ univibe

@njit(cache=True)
def _vibe_core(x, lamp, caps, r_min, r_max, leak, drive, z):
    # lamp -> LDR resistance (log-law), each stage a 1st-order all-pass at 1/(2 pi R C) that leaks some dry
    # signal (unbalanced phase splitter) and clips softly
    n = len(x)
    ns = len(caps)
    y = np.empty(n)
    for i in range(n):
        r = r_max * (r_min / r_max) ** lamp[i]
        s = x[i]
        for k in range(ns):
            w = np.tan(np.pi * min(1.0 / (2 * np.pi * r * caps[k]), 20000.0) / 48000.0)
            c = (w - 1.0) / (w + 1.0)
            ap = c * s + z[k]
            z[k] = s - c * ap
            o = (1.0 - leak) * ap + leak * s
            if drive > 0:
                o = np.tanh(o * (1 + 3 * drive)) / (1 + 3 * drive)
            s = o
        y[i] = s
    return y


@njit(cache=True)
def _lamp(drive_wave, sr, on_s, off_s, st):
    n = len(drive_wave)
    out = np.empty(n)
    a_on = np.exp(-1.0 / (on_s * sr))
    a_off = np.exp(-1.0 / (off_s * sr))
    v = st[0]
    for i in range(n):
        d = drive_wave[i]
        a = a_on if d > v else a_off
        v = a * v + (1 - a) * d
        out[i] = v
    st[0] = v
    return out


def vibe_lamp_drive(ph, inten):
    """The phase-shift oscillator's skewed sine (fast rise, slow fall) as the lamp's drive, from the LFO phase in
    cycles (cumulative rate / sr)."""
    s = np.sin(2 * np.pi * ph)
    skew = 0.5 + 0.5 * np.sign(s) * np.abs(s) ** 0.7
    return skew * inten + (1 - inten) * 0.15


VIBE_CAPS = np.array([15e-9, 220e-9, 470e-12, 4.7e-9])


def univibe(x, p, sr, P):
    n = x.shape[1]
    rate = _curve(P('rate_hz'), n)
    inten = _curve(P('intensity'), n)
    ph = np.cumsum(rate) / sr
    lamp = _lamp(vibe_lamp_drive(ph, inten), sr, 0.006, 0.045, np.zeros(1))
    # the kernel's bilinear warp uses 48000; scale caps so corner frequencies are right at any sr
    caps = VIBE_CAPS * 48000.0 / sr
    wet = np.stack([_vibe_core(ch, lamp, caps, 4.0e3, 2.0e5, 0.12, float(p['drive']), np.zeros(len(caps)))
                    for ch in x])
    wet = signal.sosfilt(signal.butter(1, 25, 'highpass', fs=sr, output='sos'), wet, axis=1)
    if p['mode'] == 'vibrato':
        out = wet
    else:
        out = 0.5 * (x + wet)
    m = _curve(P('mix'), n)
    return x * (1 - m) + out * m


# ------------------------------------------------------------------ amp

def _tonestack(bass, mid, treble, sr):
    """Marshall tone stack (Yeh & Smith, DAFx 2006 analytic TMB model) -> sos. Knobs 0-10."""
    l, m, t = [min(max(k / 10.0, 0.0), 1.0) for k in (bass, mid, treble)]
    l = l ** 2  # log-taper bass pot
    C1, C2, C3 = 470e-12, 22e-9, 22e-9
    R1, R2, R3, R4 = 220e3, 1e6, 22e3, 33e3
    b1 = t * C1 * R1 + m * C3 * R3 + l * (C1 * R2 + C2 * R2) + (C1 * R3 + C2 * R3)
    b2 = (t * (C1 * C2 * R1 * R4 + C1 * C3 * R1 * R4) - m * m * (C1 * C3 * R3 ** 2 + C2 * C3 * R3 ** 2)
          + m * (C1 * C3 * R1 * R3 + C1 * C3 * R3 ** 2 + C2 * C3 * R3 ** 2)
          + l * (C1 * C2 * R1 * R2 + C1 * C2 * R2 * R4 + C1 * C3 * R2 * R4)
          + l * m * (C1 * C3 * R2 * R3 + C2 * C3 * R2 * R3)
          + (C1 * C2 * R1 * R3 + C1 * C2 * R3 * R4 + C1 * C3 * R3 * R4))
    b3 = (l * m * (C1 * C2 * C3 * R1 * R2 * R3 + C1 * C2 * C3 * R2 * R3 * R4)
          - m * m * (C1 * C2 * C3 * R1 * R3 ** 2 + C1 * C2 * C3 * R3 ** 2 * R4)
          + m * (C1 * C2 * C3 * R1 * R3 ** 2 + C1 * C2 * C3 * R3 ** 2 * R4)
          + t * C1 * C2 * C3 * R1 * R3 * R4 - t * m * C1 * C2 * C3 * R1 * R3 * R4
          + t * l * C1 * C2 * C3 * R1 * R2 * R4)
    a1 = (C1 * R1 + C1 * R3 + C2 * R3 + C2 * R4 + C3 * R4) + m * C3 * R3 + l * (C1 * R2 + C2 * R2)
    a2 = (m * (C1 * C3 * R1 * R3 - C2 * C3 * R3 * R4 + C1 * C3 * R3 ** 2 + C2 * C3 * R3 ** 2)
          + l * m * (C1 * C3 * R2 * R3 + C2 * C3 * R2 * R3) - m * m * (C1 * C3 * R3 ** 2 + C2 * C3 * R3 ** 2)
          + l * (C1 * C2 * R2 * R4 + C1 * C2 * R1 * R2 + C1 * C3 * R2 * R4 + C2 * C3 * R2 * R4)
          + (C1 * C2 * R1 * R4 + C1 * C3 * R1 * R4 + C1 * C2 * R3 * R4 + C1 * C2 * R1 * R3
             + C1 * C3 * R3 * R4 + C2 * C3 * R3 * R4))
    a3 = (l * m * (C1 * C2 * C3 * R1 * R2 * R3 + C1 * C2 * C3 * R2 * R3 * R4)
          - m * m * (C1 * C2 * C3 * R1 * R3 ** 2 + C1 * C2 * C3 * R3 ** 2 * R4)
          + m * (C1 * C2 * C3 * R3 ** 2 * R4 + C1 * C2 * C3 * R1 * R3 ** 2 - C1 * C2 * C3 * R1 * R3 * R4)
          + l * C1 * C2 * C3 * R1 * R2 * R4 + C1 * C2 * C3 * R1 * R3 * R4)
    b, a = signal.bilinear([b3, b2, b1, 0.0], [a3, a2, a1, 1.0], fs=sr)
    return signal.tf2sos(b, a)


@njit(cache=True)
def _tube(x, drive, bias):
    # 12AX7-ish triode stage: soft on the way up, harder grid-conduction knee on the way down, then DC removed
    n = len(x)
    y = np.empty(n)
    for i in range(n):
        z = x[i] * drive + bias
        if z >= 0:
            y[i] = np.tanh(z)
        else:
            y[i] = -1.4 * np.tanh(-z / 1.4) if z > -1.0 else -(1.4 * np.tanh(1 / 1.4) + 0.3 * np.tanh(-z - 1.0))
        y[i] -= np.tanh(bias)
    return y


@njit(cache=True)
def _power(x, drive, sag, sr, st):
    # push-pull pentodes: symmetric soft clip; supply sag pulls the gain down with the average current
    n = len(x)
    y = np.empty(n)
    env = st[0]
    a_att = np.exp(-1.0 / (0.012 * sr))
    a_rel = np.exp(-1.0 / (0.180 * sr))
    for i in range(n):
        g = drive / (1.0 + sag * 2.5 * env)
        z = x[i] * g
        o = z / (1 + z * z) ** 0.5 if abs(z) < 3 else np.sign(z) * (0.95 + 0.05 * np.tanh(abs(z) - 3))
        o = np.tanh(1.2 * o) / np.tanh(1.2)
        v = abs(o)
        env = a_att * env + (1 - a_att) * v if v > env else a_rel * env + (1 - a_rel) * v
        y[i] = o
    st[0] = env
    return y


AMP_OS = 2


def amp_pre_sos(p, gain, sr):
    """Input high-pass, plus the bright cap (treble passes the volume pot at low gain settings)."""
    bright = float(p['bright']) * max(0.0, 1.0 - gain / 10.0) * 9.0
    pre = [signal.butter(1, 30, 'highpass', fs=sr, output='sos')]
    if bright > 0.1:
        pre.append(_shelf(3000, bright, sr, high=True))
    return np.vstack(pre)


def amp_stage_sos(p, srr):
    """The filters inside the oversampled amp, in order: interstage high-pass, tone stack, presence (None when
    flat), output transformer."""
    pres = (float(p['presence']) - 5) * 1.2
    return (signal.butter(1, 80, 'highpass', fs=srr, output='sos'), _tonestack(p['bass'], p['mid'], p['treble'], srr),
            _shelf(3500, pres, srr, high=True) if abs(pres) > 0.1 else None,
            np.vstack([signal.butter(1, 60, 'highpass', fs=srr, output='sos'),
                       signal.butter(2, 11000, 'lowpass', fs=srr, output='sos')]))


def amp_drives(p, gain):
    """(first triode drive, second triode drive, power stage drive)."""
    g1 = 10 ** ((gain * 3.2 - 2) / 20)
    return 6.0 * g1, 1.0 + gain * 0.8, 10 ** ((float(p['volume']) * 2.8 - 14) / 20)


HUM = ((1, 1.0), (2, 0.5), (3, 0.35), (5, 0.15))


def amp_hum(t):
    return sum(a * np.sin(2 * np.pi * 60 * k * t + k) for k, a in HUM)


def noise_streams(seed):
    """One generator per channel: drawn in blocks, the noise is the same as drawn whole."""
    return [np.random.default_rng([int(seed), c]) for c in (0, 1)]


def amp(x, p, sr, P):
    n = x.shape[1]
    srr = sr * AMP_OS
    gain = float(np.mean(_curve(P('gain'), n)))
    d1, d2, drive = amp_drives(p, gain)
    hp, tone, pres, xfmr = amp_stage_sos(p, srr)
    y = signal.sosfilt(amp_pre_sos(p, gain, sr), x, axis=1)
    y = signal.resample_poly(y, AMP_OS, 1, axis=1)
    y = np.stack([_tube(ch, d1, 0.25) for ch in y])
    y = signal.sosfilt(hp, y, axis=1)
    y = np.stack([_tube(ch, d2, 0.15) for ch in y]) * 0.5
    y = signal.sosfilt(tone, y, axis=1) * 3.0
    if pres is not None:
        y = signal.sosfilt(pres, y, axis=1)
    y = np.stack([_power(ch, drive, float(p['sag']), srr, np.zeros(1)) for ch in y])
    y = signal.sosfilt(xfmr, y, axis=1)                                 # output transformer
    y = signal.resample_poly(y, 1, AMP_OS, axis=1)[:, :n]
    if p['hiss_db'] > -119 or p['hum_db'] > -119:
        hiss = np.stack([g.standard_normal(n) for g in noise_streams(p['seed'])])
        hiss = signal.sosfilt(signal.butter(1, 800, 'highpass', fs=sr, output='sos'), hiss, axis=1)
        y = y + 10 ** (p['hiss_db'] / 20) * hiss + 10 ** (p['hum_db'] / 20) * amp_hum(np.arange(n) / sr)[None, :]
    return y * 0.5 * 10 ** (p['out_db'] / 20)


def _shelf(f, gain_db, sr, high=True):
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f / sr
    alpha = np.sin(w0) / 2 * np.sqrt(2)
    cw = np.cos(w0)
    sA = 2 * np.sqrt(A) * alpha
    if high:
        b = [A * ((A + 1) + (A - 1) * cw + sA), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sA)]
        a = [(A + 1) - (A - 1) * cw + sA, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sA]
    else:
        b = [A * ((A + 1) - (A - 1) * cw + sA), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sA)]
        a = [(A + 1) + (A - 1) * cw + sA, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sA]
    return signal.tf2sos(np.array(b) / a[0], np.array(a) / a[0])


# ------------------------------------------------------------------ cab

def cab_curve(f, low_hz=75.0, high_hz=5000.0, presence_db=4.0, breakup=1.0, seed=3, mic=0.0):
    """Magnitude (dB) of speaker + mic at frequencies f."""
    f = np.maximum(f, 1.0)
    # cone resonance: 2nd-order high-pass with a resonant peak at low_hz
    x = f / low_hz
    hp = 20 * np.log10(x ** 2 / np.sqrt((1 - x ** 2) ** 2 + (x / 1.6) ** 2))
    # presence: broad rise 1.5-3.5 kHz
    pres = presence_db * np.exp(-0.5 * (np.log2(f / 2400.0) / 0.7) ** 2)
    # lower-mid dip typical of closed 4x12s
    dip = -2.5 * np.exp(-0.5 * (np.log2(f / 400.0) / 0.6) ** 2)
    # top roll-off: steep (the cone stops radiating), 4th order above high_hz
    y = f / high_hz
    lp = -10 * np.log10(1 + y ** 8)
    # cone break-up: a fixed pattern of narrow peaks and dips above 1 kHz (seeded)
    rng = np.random.default_rng(int(seed))
    ripple = np.zeros_like(f)
    for _ in range(14):
        fc = 1000 * 2 ** rng.uniform(0, 3.2)
        g = rng.normal(0, 3.0) * breakup
        bw = rng.uniform(0.04, 0.15)
        ripple += g * np.exp(-0.5 * (np.log2(f / fc) / bw) ** 2)
    close = hp + pres + dip + lp + ripple
    # room mic: less presence, smoother top, more low-mid body
    room = hp + 0.4 * pres + 2.0 * np.exp(-0.5 * (np.log2(f / 200.0) / 1.0) ** 2) + lp * 1.3 + 0.4 * ripple
    return (1 - mic) * close + mic * room


def _minphase_fir(mag_db, n_fft):
    mag = 10 ** (mag_db / 20)
    full = np.concatenate([mag, mag[-2:0:-1]])
    cep = np.fft.ifft(np.log(np.maximum(full, 1e-6))).real
    w = np.zeros(n_fft)
    w[0] = 1
    w[1:n_fft // 2] = 2
    w[n_fft // 2] = 1
    h = np.fft.ifft(np.exp(np.fft.fft(cep * w))).real
    return h[:n_fft // 2] * np.hanning(n_fft)[n_fft // 2:]


def cab_irs(p, mic, sr):
    """(speaker + mic FIR, [left, right] room reflection FIRs or None)."""
    n_fft = 4096
    f = np.fft.rfftfreq(n_fft, 1 / sr)
    kw = dict(low_hz=p['low_hz'], high_hz=p['high_hz'], presence_db=p['presence_db'], breakup=p['breakup'],
              seed=p['seed'])
    h = _minphase_fir(cab_curve(f, mic=mic, **kw), n_fft)
    h /= np.sqrt(np.sum(h ** 2)) * 4
    if not (mic > 0 and p['width'] > 0):
        return h, None
    # room mic pair: a few early reflections, different per side
    rng = np.random.default_rng(int(p['seed']) + 1)
    rooms = []
    for ch in range(2):
        ir = np.zeros(int(sr * (p['room_ms'] * 4) / 1000) + 2)
        ir[0] = 1.0
        for _ in range(6):
            d = int(rng.uniform(0.3, 4.0) * p['room_ms'] / 1000 * sr)
            ir[min(d, len(ir) - 1)] += rng.uniform(-0.5, 0.5) * p['width'] * mic
        rooms.append(ir)
    return h, rooms


def cab(x, p, sr, P):
    n = x.shape[1]
    h, rooms = cab_irs(p, float(np.mean(_curve(P('mic'), n))), sr)
    y = signal.fftconvolve(x, h[None, :], axes=1)[:, :n]
    if rooms is not None:
        y = np.stack([signal.fftconvolve(y[ch], rooms[ch])[:n] for ch in range(2)])
    return y


# ------------------------------------------------------------------ rotary

@njit(cache=True)
def _ramp_speed(target, slow, fast, ramp_s, sr, st):
    # st: [speed, started]: the rotor starts at the speed asked for, then ramps
    n = len(target)
    out = np.empty(n)
    a = np.exp(-1.0 / (ramp_s * sr))
    v = st[0] if st[1] else slow + (fast - slow) * target[0]
    for i in range(n):
        goal = slow + (fast - slow) * target[i]
        v = a * v + (1 - a) * goal
        out[i] = v
    st[0] = v
    st[1] = 1.0
    return out


@njit(cache=True)
def _frac_delay(x, d):
    n = len(x)
    y = np.empty(n)
    for i in range(n):
        p = i - d[i]
        if p < 0:
            y[i] = 0.0
            continue
        j = int(p)
        fr = p - j
        a = x[j]
        b = x[j + 1] if j + 1 < n else a
        y[i] = a + (b - a) * fr
    return y


def rotary(x, p, sr, P):
    n = x.shape[1]
    mono = x.mean(0)
    if p['drive'] > 0:
        g = 1 + 6 * p['drive']
        mono = np.tanh(mono * g) / np.tanh(g) * 0.8 + mono * 0.2
    lo = signal.sosfilt(signal.butter(4, p['crossover_hz'], 'lowpass', fs=sr, output='sos'), mono)
    hi = signal.sosfilt(signal.butter(4, p['crossover_hz'], 'highpass', fs=sr, output='sos'), mono)
    spd = np.clip(_curve(P('speed'), n), 0, 1)
    h_rate = _ramp_speed(spd, p['horn_slow'], p['horn_fast'], p['horn_ramp_s'], sr, np.zeros(2))
    d_rate = _ramp_speed(spd, p['drum_slow'], p['drum_fast'], p['drum_ramp_s'], sr, np.zeros(2))
    h_ph = np.cumsum(h_rate) / sr
    d_ph = np.cumsum(d_rate) / sr + 0.37
    out = []
    for ch, ang in ((0, -p['spread'] * 0.25), (1, p['spread'] * 0.25)):
        hc = np.cos(2 * np.pi * (h_ph + ang))
        dc = np.cos(2 * np.pi * (d_ph + ang))
        dh = (1.0 + p['doppler_ms'] * hc) / 1000 * sr
        horn = _frac_delay(hi, dh) * (1 - p['horn_am'] * 0.5 * (1 - hc))
        # the horn's directivity: brighter pointing at the mic
        drum = _frac_delay(lo, (1.0 + 0.3 * p['doppler_ms'] * dc) / 1000 * sr) * (1 - p['drum_am'] * 0.5 * (1 - dc))
        out.append(horn + drum)
    wet = np.stack(out)
    m = _curve(P('mix'), n)
    return x * (1 - m) + wet * m


# ------------------------------------------------------------------ tape

def tape_saturate(x, d):
    g = 1 + 4 * d
    return (np.tanh(g * x + 0.05 * d) - np.tanh(0.05 * d)) / np.tanh(g) if d > 0 else x.copy()


def tape_sos(p, sr):
    sos = [signal.butter(2, min(p['hf_hz'], sr * 0.45), 'lowpass', fs=sr, output='sos')]
    if p['bump_db']:
        w0 = 2 * np.pi * p['bump_hz'] / sr
        A = 10 ** (p['bump_db'] / 40)
        alpha = np.sin(w0) / (2 * 1.2)
        b = [1 + alpha * A, -2 * np.cos(w0), 1 - alpha * A]
        a = [1 + alpha / A, -2 * np.cos(w0), 1 - alpha / A]
        sos.append(signal.tf2sos(np.array(b) / a[0], np.array(a) / a[0]))
    return np.vstack(sos)


WOW = ((0.55, 'wow', 1.0), (0.23, 'wow', 0.5), (7.3, 'flutter', 1.0), (12.1, 'flutter', 0.4))


def tape_wow(p, sr):
    """(speed deviation at times t -> fraction, the delay offset in samples that keeps the delay >= 2 whatever
    the phases): the delay is the running sum of the deviation plus that offset, so it is causal."""
    rng = np.random.default_rng(int(p['seed']))
    ph = [rng.uniform(0, 6), rng.uniform(0, 6), rng.uniform(0, 6), 0.0]

    def dev(t):
        return sum(p[k] * a * np.sin(2 * np.pi * f * t + phi) for (f, k, a), phi in zip(WOW, ph)) / 100.0
    # a running sum of sin(w i + phi) never leaves +-1 / sin(w / 2)
    bound = sum(p[k] * a / np.sin(np.pi * f / sr) for f, k, a in WOW) / 100.0
    return dev, bound + 2


def tape(x, p, sr, P):
    n = x.shape[1]
    y = signal.sosfilt(tape_sos(p, sr), tape_saturate(x, float(np.mean(_curve(P('drive'), n)))), axis=1)
    if p['wow'] > 0 or p['flutter'] > 0:
        dev, off = tape_wow(p, sr)
        dly = np.cumsum(dev(np.arange(n) / sr)) + off          # speed deviation, integrated: delay in samples
        y = np.stack([_frac_delay(ch, dly) for ch in y])
    if p['hiss_db'] > -120:
        hiss = np.stack([g.standard_normal(n) for g in noise_streams(int(p['seed']) + 5)]) * 10 ** (p['hiss_db'] / 20)
        hiss = signal.sosfilt(signal.butter(1, 2000, 'highpass', fs=sr, output='sos'), hiss, axis=1)
        y = y + hiss
    return y


# ------------------------------------------------------------------ wah

@njit(cache=True)
def _wah_core(x, fc, q, sr, st):
    n = len(x)
    y = np.empty(n)
    lp = st[0]
    bp = st[1]
    for i in range(n):
        f = 2 * np.sin(np.pi * min(fc[i], sr / 6) / sr)
        hp = x[i] - lp - bp / q
        bp += f * hp
        lp += f * bp
        y[i] = bp
    st[0] = lp
    st[1] = bp
    return y


@njit(cache=True)
def _peak_norm(e, sr, st):
    # the envelope over its own recent peak (held, then falling over ~2 s): playing hard reaches the toe whatever
    # the level, as a percentile over the whole part did, but only from what has already been played
    n = len(e)
    out = np.empty(n)
    r = np.exp(-1.0 / (2.0 * sr))
    pk = st[0]
    for i in range(n):
        pk = e[i] if e[i] > pk else r * pk
        out[i] = e[i] / (pk + 1e-9)
    st[0] = pk
    return out


def wah(x, p, sr, P):
    n = x.shape[1]
    pos = _curve(P('pos'), n).copy()
    if p['auto'] > 0:
        from .dsp import env_follow
        e = env_follow(np.abs(x).mean(0), p['attack_ms'] / 1000, p['release_ms'] / 1000, sr)
        pos = np.clip(pos + p['auto'] * _peak_norm(e, sr, np.zeros(1)), 0, 1)
    fc = p['lo_hz'] * (p['hi_hz'] / p['lo_hz']) ** pos
    wet = np.stack([_wah_core(ch, fc, p['q'], sr, np.zeros(2)) for ch in x]) * 1.6
    m = _curve(P('mix'), n)
    return x * (1 - m) + wet * m


APPLY = {"fuzz": fuzz, "univibe": univibe, "amp": amp, "cab": cab, "rotary": rotary, "tape": tape, "wah": wah}
