"""A 1970 rock/jazz kit as a performer: every drum and cymbal is a bank of resonating modes that keeps ringing
across the part, re-excited by stick hits (so a ride builds wash and a re-struck tom beats against itself).

Pitches (GM-style): 36 kick, 38 snare, 37 snare ghost (soft, wires-forward), 40 rimshot, 42 closed hat,
44 pedal hat, 46 open hat, 51 ride, 53 ride bell, 49 crash, 57 crash 2, 48 high tom (12"), 45 mid tom,
41 floor tom (16"), 43 floor tom 2.
Velocity is stick strength: level over a wide range (ghosts really are quiet) and colour (harder = brighter,
more stick click, more snare wires, cymbals bloom). Output is stereo from the drummer's seat (hats left).
"""
import numpy as np
from numba import njit
from scipy import signal

# The chain fitted in the Pali Gap study (a late-60s record, 2026-09-30): a dark, mid-forward overhead sound.
RIGS = {
    "kit": {"preset": "kit70",
            "note": "fitted against the record's drum stem; route the kit to a drum bus",
            "fx": [{"type": "eq", "bands": [{"type": "lowcut", "freq": 35},
                                            {"type": "peak", "freq": 400, "gain_db": 2.5, "q": 0.9},
                                            {"type": "peak", "freq": 1900, "gain_db": -8, "q": 0.6},
                                            {"type": "peak", "freq": 4500, "gain_db": -4, "q": 0.8},
                                            {"type": "highshelf", "freq": 9500, "gain_db": 1.5}]}]},
}

INFO = {
    "summary": "1970 acoustic kit (22\" kick, 5x14 metal snare, 13\" hats, 22\" ride, 18\" crash, 12/16\" toms) "
               "as modal resonator banks re-excited by stick hits",
    "range": "36 kick 37 ghost 38 snare 40 rimshot 41/43 floor toms 45 mid tom 48 high tom 42/44/46 hats "
             "49/57 crashes 51 ride 53 bell",
    "velocity": "stick strength: level (about 40 dB range) and brightness",
    "rigs": RIGS,
    "params": {"kick_hz": "kick fundamental", "snare_hz": "snare head fundamental", "tom_hz": "[high, mid, floor, floor2]",
               "wires": "snare wire level", "cym_bright": "cymbal brightness 0-1", "ride_t60": "ride sustain, s",
               "hat_open_t60": "open hat sustain, s", "buzz": "sympathetic snare buzz from kick/toms",
               "humanize_ms": "timing jitter", "seed": "random seed", "level": "output gain"},
}

MEMBRANE = np.array([1.0, 1.59, 2.14, 2.30, 2.65, 2.92, 3.16, 3.50])


@njit(cache=False)
def _bank(exc, freqs, t60, gains, damp, glide, sr):
    """Sum of 2-pole resonators, each normalized to a unit-peak impulse response. exc: excitation; damp:
    per-sample multiplier on decay rate (>1 = damped); glide: per-sample frequency multiplier (pitch drop)."""
    n = len(exc)
    m = len(freqs)
    y = np.zeros(n)
    y1 = np.zeros(m)
    y2 = np.zeros(m)
    rr = np.zeros(m)
    cc = np.zeros(m)
    gg = np.zeros(m)
    last_d = -1.0
    last_g = -1.0
    for i in range(n):
        if damp[i] != last_d or glide[i] != last_g:
            last_d = damp[i]
            last_g = glide[i]
            for k in range(m):
                f = min(freqs[k] * last_g, sr * 0.45)
                tau = t60[k] / 6.91 / last_d
                r = np.exp(-1.0 / (tau * sr))
                w = 2.0 * np.pi * f / sr
                rr[k] = r
                cc[k] = 2.0 * r * np.cos(w)
                gg[k] = gains[k] * np.sin(w) if freqs[k] * last_g < sr * 0.45 else 0.0
        x = exc[i]
        acc = 0.0
        for k in range(m):
            v = gg[k] * x + cc[k] * y1[k] - rr[k] * rr[k] * y2[k]
            y2[k] = y1[k]
            y1[k] = v
            acc += v
        y[i] = acc
    return y


def _pulse(width_s, sr):
    n = max(3, int(width_s * sr))
    return np.hanning(n + 2)[1:-1]


def _level(v):
    # stick strength -> amplitude: ~40 dB between a ghost (v 20) and a full hit (127)
    return (v / 127.0) ** 2.2


def _cymbal_modes(rng, n, lo, hi, cluster=0.0):
    f = np.sort(lo * (hi / lo) ** rng.random(n))
    if cluster:
        f *= 1 + cluster * rng.normal(0, 0.01, n)
    return f


def perform(notes, total_n, sr, bpm=120.0, lanes=None, kick_hz=58.0, snare_hz=190.0,
            tom_hz=(150.0, 118.0, 92.0, 80.0), wires=1.0, cym_bright=0.6, ride_t60=4.5, hat_open_t60=1.0,
            buzz=0.15, humanize_ms=3.0, seed=5, level=1.0, **_):
    rng = np.random.default_rng(int(seed))
    by = {}
    for st, m, d, v in notes:
        st = max(0.0, st + rng.normal(0, humanize_ms / 1000.0))
        by.setdefault(int(m), []).append((st, v))
    L = np.zeros(total_n)
    R = np.zeros(total_n)
    one = np.ones(total_n)

    def add(y, pan):
        gl, gr = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        L[:len(y)] += y[:total_n] * gl
        R[:len(y)] += y[:total_n] * gr

    def exc_stream(hits, width_lo, width_hi, click=0.0, noise_ms=0.0, noise_hp=2000.0):
        e = np.zeros(total_n)
        for st, v in hits:
            i = int(st * sr)
            if i >= total_n:
                continue
            a = _level(v)
            w = width_hi - (width_hi - width_lo) * (v / 127.0)
            p = _pulse(w, sr) * a
            j = min(total_n, i + len(p))
            e[i:j] += p[:j - i]
            if noise_ms:
                nn = int(noise_ms / 1000 * sr)
                z = rng.standard_normal(nn) * np.exp(-np.arange(nn) / (nn / 4)) * a * click
                z = signal.lfilter(*signal.butter(1, noise_hp / (sr / 2), 'high'), z)
                j = min(total_n, i + nn)
                e[i:j] += z[:j - i]
        return e

    def glide_stream(hits, amount, tau):
        g = np.ones(total_n)
        for st, v in hits:
            i = int(st * sr)
            if i >= total_n:
                continue
            k = min(total_n - i, int(tau * 6 * sr))
            g[i:i + k] = 1 + amount * (v / 127.0) * np.exp(-np.arange(k) / (tau * sr))
        return g

    low_env = np.zeros(total_n)     # kick + toms, for the snare's sympathetic buzz

    # ---- kick: membrane modes with a pitch drop, beater click, the front head's ring
    hits = by.get(36, [])
    if hits:
        e = exc_stream(hits, 0.0015, 0.004, click=0.6, noise_ms=4, noise_hp=1500)
        fr = kick_hz * np.array([1.0, 1.52, 1.98, 2.44, 2.9])
        y = _bank(e, fr, np.array([0.42, 0.22, 0.15, 0.1, 0.07]), np.array([1.0, 0.45, 0.3, 0.2, 0.12]),
                  one, glide_stream(hits, 0.55, 0.012), float(sr))
        click = signal.lfilter(*signal.butter(2, [2500 / (sr / 2), 6000 / (sr / 2)], 'band'), e) * 3.0
        y = (y * 0.05 + click) * 0.45
        low_env += np.abs(y)
        add(y, 0.0)

    # ---- toms
    for pitch, f0, pan in ((48, tom_hz[0], 0.25), (45, tom_hz[1], 0.4), (41, tom_hz[2], 0.6), (43, tom_hz[3], 0.7)):
        hits = by.get(pitch, [])
        if not hits:
            continue
        e = exc_stream(hits, 0.0008, 0.003, click=0.3, noise_ms=3, noise_hp=2500)
        fr = f0 * MEMBRANE[:6]
        y = _bank(e, fr, np.array([0.7, 0.35, 0.25, 0.2, 0.15, 0.12]) * (130 / f0) ** 0.4,
                  np.array([1.0, 0.6, 0.45, 0.35, 0.25, 0.2]), one, glide_stream(hits, 0.12, 0.05), float(sr))
        y *= 0.035 * 0.47
        low_env += np.abs(y)
        add(y, pan)

    # ---- snare: head modes + wires driven by the head's energy (and a little by kick/toms)
    hits = [(s, v) for s, v in by.get(38, [])] + [(s, min(v, 50)) for s, v in by.get(37, [])] + \
        [(s, v) for s, v in by.get(40, [])]
    if hits or buzz:
        hits.sort()
        e = exc_stream(hits, 0.0004, 0.002, click=0.5, noise_ms=3, noise_hp=3000)
        fr = snare_hz * MEMBRANE
        head = _bank(e, fr, np.array([0.28, 0.18, 0.14, 0.12, 0.1, 0.08, 0.07, 0.06]),
                     np.array([1.0, 0.8, 0.7, 0.55, 0.45, 0.4, 0.3, 0.25]), one,
                     glide_stream(hits, 0.05, 0.02), float(sr)) * 0.03
        drive = np.abs(head) + buzz * low_env
        env = signal.lfilter([1 - 0.9985], [1, -0.9985], drive)          # the wires follow the head
        noise = rng.standard_normal(total_n)
        wire = signal.lfilter(*signal.butter(2, [1800 / (sr / 2), 9000 / (sr / 2)], 'band'), noise) * env * 2.2 * wires
        # rimshots: a metallic crack
        rim = by.get(40, [])
        if rim:
            er = exc_stream(rim, 0.0003, 0.0006)
            wire += _bank(er, np.array([880.0, 1360.0, 2240.0, 3310.0]), np.array([0.05, 0.04, 0.03, 0.02]),
                          np.array([1.0, 0.7, 0.5, 0.3]), one, one, float(sr)) * 0.02
        add((head + wire) * 0.66, 0.0)

    # ---- hi-hat: one cymbal, damped by the pedal state (closed, open, pedal chick)
    hh = sorted([(s, v, m) for m in (42, 44, 46) for s, v in by.get(m, [])])
    if hh:
        damp = np.full(total_n, 14.0)
        state = 14.0
        for k, (s, v, m) in enumerate(hh):
            i = int(s * sr)
            nxt = int(hh[k + 1][0] * sr) if k + 1 < len(hh) else total_n
            d = {42: 14.0, 44: 40.0, 46: 1.0}[m]
            damp[i:nxt] = d
        damp = signal.lfilter([0.02], [1, -0.98], damp)                 # the pedal moves in a few ms
        fr = _cymbal_modes(np.random.default_rng(13), 90, 700, 16500)
        t60 = hat_open_t60 * (fr / 3000.0) ** -0.35
        g = (fr / 3000.0) ** (1.2 * cym_bright) * rng.uniform(0.4, 1.0, len(fr))
        e = exc_stream([(s, v) for s, v, m in hh if m != 44], 0.00004, 0.0002, click=1.0, noise_ms=6, noise_hp=5000)
        e += exc_stream([(s, v * 0.6) for s, v, m in hh if m == 44], 0.001, 0.002)
        y = _bank(e, fr, t60, g, damp, one, float(sr)) * 0.02 * 0.18
        add(y, -0.45)

    # ---- ride (and bell): dense modes, long sustain; the stick ping is its own bright set
    rd = sorted(by.get(51, []) + [(s, v) for s, v in by.get(53, [])])
    if rd:
        fr = _cymbal_modes(np.random.default_rng(21), 120, 420, 16500)
        t60 = ride_t60 * (fr / 2000.0) ** -0.45
        g = (fr / 2000.0) ** (1.0 * cym_bright) * np.random.default_rng(22).uniform(0.3, 1.0, len(fr))
        e = exc_stream(rd, 0.00005, 0.0003, click=0.6, noise_ms=4, noise_hp=4000)
        y = _bank(e, fr, t60, g, one, one, float(sr)) * 0.008 * 0.28
        bell = by.get(53, [])
        if bell:
            eb = exc_stream(bell, 0.0003, 0.0008)
            y += _bank(eb, np.array([622.0, 1480.0, 2350.0, 3510.0, 4890.0]), np.array([3.0, 2.2, 1.6, 1.2, 0.9]),
                       np.array([1.0, 0.8, 0.6, 0.4, 0.3]), one, one, float(sr)) * 0.01
        add(y, 0.45)

    # ---- crashes: bright, noisy, bloom (high modes are slow to rise because the excitation is long)
    for pitch, sd, pan in ((49, 31, -0.5), (57, 37, 0.55)):
        hits = by.get(pitch, [])
        if not hits:
            continue
        fr = _cymbal_modes(np.random.default_rng(sd), 120, 250, 17000)
        t60 = 2.4 * (fr / 2000.0) ** -0.3
        g = (fr / 2000.0) ** (1.0 * cym_bright) * np.random.default_rng(sd + 1).uniform(0.3, 1.0, len(fr))
        e = exc_stream(hits, 0.0001, 0.0005, click=1.5, noise_ms=25, noise_hp=1500)
        y = _bank(e, fr, t60, g, one, one, float(sr)) * 0.006 * 0.32
        add(y, pan)

    # ---- congas (a second player): 62 mute high, 63 open high, 64 open low, 65 slap high
    for pitch, f0, t, pan, slap in ((62, 330.0, 0.05, 0.5, 0.2), (63, 330.0, 0.35, 0.5, 0.0),
                                    (64, 235.0, 0.45, 0.65, 0.0), (65, 330.0, 0.08, 0.5, 1.0)):
        hits = by.get(pitch, [])
        if not hits:
            continue
        e = exc_stream(hits, 0.0012 - 0.0009 * slap, 0.004, click=0.4 + slap, noise_ms=5, noise_hp=1500 + 1500 * slap)
        fr = f0 * np.array([1.0, 1.5, 1.98, 2.44, 2.9, 3.4])
        y = _bank(e, fr, t * np.array([1.0, 0.6, 0.45, 0.35, 0.25, 0.2]), np.array([1.0, 0.5, 0.35, 0.25, 0.2, 0.15]),
                  one, glide_stream(hits, 0.04, 0.03), float(sr)) * 0.02
        add(y, pan)

    return np.stack([L, R]) * 0.5 * float(level)
