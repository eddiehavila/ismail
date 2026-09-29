"""Sound-design ops: compare two sounds, fit an instrument's parameters to a target sound."""
import json
import math

import numpy as np
import soundfile as sf

from .api import op, OpError, _load, _resolve_instrument, _write_sound
from . import sounddesign as SD
from . import instruments as inst_mod
from .notation import parse_notes, NotationError


def _audio(P, src, window=None, span=None):
    path, g = P.source(src, span=span)
    y, sr = sf.read(path, dtype='float64', always_2d=True)
    y = y.T
    if y.shape[0] == 1:
        y = np.vstack([y, y])
    if span:
        window = [g.bar_time(span[0]), g.bar_time(span[1])]
    if window:
        y = y[:, int(max(window[0], 0) * sr):int(window[1] * sr)]
    if sr != SD.SR:
        from scipy.signal import resample_poly
        y = resample_poly(y, SD.SR, sr, axis=1)
    if y.shape[1] < 256:
        raise OpError("selected audio is shorter than 6 ms; widen the window")
    return y


@op()
def sound_compare(project: str, a: str, b: str, a_window: list = None, b_window: list = None, a_span: list = None,
                  b_span: list = None, fmin: float = 25.0, fmax: float = 16000.0) -> str:
    """A/B two sounds: 1/3-octave bands side by side (with << >> where A is >6 dB off), envelope from onset,
    centroid, stereo width, and one distance number. a/b are sources ('sound:<name>', 'ref:drums', 'track:x',
    ...); window=[t0, t1] seconds or span=[start_bar, end_bar] (fractional) selects a slice."""
    P = _load(project)
    da = SD.descriptor(_audio(P, a, a_window, a_span))
    db = SD.descriptor(_audio(P, b, b_window, b_span))
    return SD.compare_text(da, db, a.split(':')[-1], b.split(':')[-1], fmin, fmax)[1]


@op(mutates=True)
def instrument_fit(project: str, target: str, instrument, params: dict, notes: str = '0 C4 1',
                   length_sec: float = None, fx: list = None, iters: int = 80, save_as: str = None,
                   apply_to_track: str = None, target_window: list = None, seed: int = 0, fmin: float = 25.0,
                   fmax: float = 16000.0) -> str:
    """Search instrument parameters so its sound matches a target (spectrum + envelope + width).
    target: a source like 'sound:refsnare' (cut one first with sound_import); instrument: dict, 'preset:x' or
    'track:<name>' (start from that track's instrument); params: {"path": [lo, hi]} e.g. {"tone_hz": [100, 250],
    "filter.cutoff": [300, 8000], "oscs.0.detune": [0, 40]}; notes: what to play (beats at project tempo; use the
    target's pitch); fmin/fmax restrict the spectral match to a range (e.g. ignore kick bleed below 70 Hz). Saves the result as sound save_as and/or sets it on apply_to_track."""
    P = _load(project)
    if isinstance(instrument, str) and instrument.startswith('track:'):
        base = P.track(instrument[6:]).get('instrument')
        if not base:
            raise OpError("that track has no instrument")
    else:
        base = _resolve_instrument(instrument, P)
    try:
        full = inst_mod.normalize(base)
    except inst_mod.InstrumentError as e:
        raise OpError(str(e))
    from . import fx as fxmod
    fx_full = [fxmod.normalize(f) for f in (fx or [])]
    for k, rng in params.items():
        try:
            SD._get({'inst': full, 'fx': fx_full}, k if k.startswith('fx.') else 'inst.' + k)
        except (KeyError, IndexError, ValueError, TypeError):
            raise OpError(f"param path {k!r} not found; instrument paths like 'filter.cutoff' (instrument_show "
                          f"full=True), fx paths like 'fx.0.depth_db' (index into the fx list you passed)")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2 and rng[1] > rng[0]):
            raise OpError(f"param {k!r} needs a [lo, hi] range with hi > lo")
    tgt = _audio(P, target, target_window)
    tdesc = SD.descriptor(tgt)
    spb = 60 / P.d['bpm']
    try:
        rel = parse_notes(notes)
    except NotationError as e:
        raise OpError(str(e))
    notes_sec = [(s * spb, p, d * spb, v) for s, p, d, v in rel]
    L = length_sec or max(tgt.shape[1] / SD.SR, max(s + d for s, _, d, _ in notes_sec) + 0.3)
    best, d1, d0, vals = SD.fit(full, params, tdesc, notes_sec, L, fx, P.d['bpm'], iters, seed, fmin=fmin, fmax=fmax,
                                root=P.root)
    y = SD.render_oneshot(best['inst'], notes_sec, L, best['fx'], P.d['bpm'], root=P.root)
    _, cmp_txt = SD.compare_text(SD.descriptor(y), tdesc, 'fitted', target.split(':')[-1], fmin, fmax)
    out = [f"fit: distance {d0:.2f} -> {d1:.2f} after {iters} renders",
           "fitted params: " + json.dumps({k: round(v, 4) for k, v in vals.items()})]
    # keep only the keys the caller gave plus type, so the stored instrument stays readable
    compact = json.loads(json.dumps(base))
    for k in params:
        if k.startswith('fx.'):
            continue
        v = SD._get(best['inst'], k)
        SD._set(compact, k, v) if _has(compact, k) else _set_deep(compact, k, v)
    fitted_fx = best['fx']
    if save_as:
        y = y / (np.max(np.abs(y)) + 1e-12) * 0.891
        _write_sound(P, save_as, y, SD.SR, note=f"fitted to {target}")
        out.append(f"saved sound {save_as!r}")
    if apply_to_track:
        tr = P.track(apply_to_track)
        tr['instrument'] = compact
        out.append(f"applied instrument to track {apply_to_track!r} (its fx chain is unchanged; fitted fx below)")
    if save_as or apply_to_track:
        P.save()
    out.append("instrument: " + json.dumps(compact))
    if fitted_fx:
        out.append("fx: " + json.dumps(fitted_fx))
    out.append(cmp_txt)
    return '\n'.join(out)


@op(mutates=True)
def sound_extract(project: str, name: str, source: str, bars: list, step: int, steps_per_bar: int = 16,
                  length_sec: float = 0.4, which: str = 'all', pre_ms: float = 5.0, normalize: bool = True,
                  every: int = 1) -> str:
    """Build a clean one-shot of a repeated event by averaging every occurrence at grid position `step`
    (0-based within the bar, 16ths by default) over bars [a, b] (which='all'|'odd'|'even'; every=8 takes bars
    a, a+8, a+16... i.e. the same position of an 8-bar loop), aligned by
    cross-correlation. Sounds that repeat identically (drum samples, stabs) add up; everything else averages down.
    Reports how consistent the occurrences were."""
    P = _load(project)
    path, g = P.source(source, bars)
    y, sr = sf.read(path, dtype='float64', always_2d=True)
    y = y.T
    if y.shape[0] == 1:
        y = np.vstack([y, y])
    n = int(length_sec * sr)
    pre = int(pre_ms / 1000 * sr)
    bars_list = [b for b in range(bars[0], bars[1] + 1, max(1, every))
                 if which == 'all' or (which == 'odd' and b % 2) or (which == 'even' and not b % 2)]
    segs, used, skipped = [], [], []
    for b in bars_list:
        t = g.bar_time(b + step / steps_per_bar)
        a = int(t * sr) - pre - int(0.02 * sr)
        L = n + int(0.04 * sr)
        if a + L > y.shape[1]:
            skipped.append(b)  # runs past the end of the audio
            continue
        seg = y[:, max(a, 0):a + L]
        if a < 0:  # event right at the start of the file: pad the pre-roll with silence
            seg = np.concatenate([np.zeros((y.shape[0], -a)), seg], axis=1)
        segs.append(seg)
        used.append(b)
    if len(segs) < 2:
        raise OpError(f"fewer than 2 occurrences: bars tried {bars_list}, usable {used}"
                      f"{f', past the end of the audio {skipped}' if skipped else ''}; widen bars, lower every, or "
                      f"check step (0-based 16th within the bar)")
    ref = segs[0].mean(0)
    shift = int(0.02 * sr)
    aligned = []
    for s in segs:
        m = s.mean(0)
        best = max(range(0, 2 * shift + 1), key=lambda k: float(np.dot(ref[shift:shift + n], m[k:k + n])))
        aligned.append(s[:, best:best + n])
    A = np.stack(aligned)
    avg = A.mean(0)
    cons = float(np.mean([np.corrcoef(a.mean(0), avg.mean(0))[0, 1] for a in aligned]))
    if normalize:
        avg = avg / (np.max(np.abs(avg)) + 1e-12) * 0.891
    _write_sound(P, name, avg, sr, note=f"avg of {len(aligned)} x {source} step {step} bars {bars}")
    P.save()
    d = SD.descriptor(avg if sr == SD.SR else avg)
    return (f"sound {name!r}: average of {len(aligned)} occurrences (bars {used}"
            f"{f'; skipped {skipped}, past the end' if skipped else ''}); consistency {cons:.2f} "
            f"(1 = identical each time, <0.5 = the event varies or is buried; widen/narrow the bar set)\n"
            f"centroid {d['centroid']:.0f} Hz, width {d['width']:.2f}")


def _tts(text, voice, rate, tmp_base):
    """Speak text into an audio file with the OS's own engine: Windows SAPI, macOS `say`, Linux espeak-ng/espeak.
    A voice the engine doesn't have falls back to its default voice. Returns (path, voice actually used)."""
    import shutil
    import subprocess
    import sys
    if sys.platform == 'win32':
        tmp = tmp_base + '.wav'
        v = voice or 'David'
        safe = text.replace("'", "''")
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like '*{v}*' }} | Select-Object -First 1; "
              "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
              f"$s.Rate = {int(rate)}; $s.SetOutputToWaveFile('{tmp}'); $s.Speak('{safe}'); $s.Dispose()")
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, timeout=60)
        return tmp, v, r
    wpm = int(round(175 * 1.1 ** max(-10, min(10, rate))))  # SAPI-style rate -10..10 -> words per minute
    if sys.platform == 'darwin' and shutil.which('say'):
        tmp = tmp_base + '.aiff'
        names = subprocess.run(['say', '-v', '?'], capture_output=True, text=True).stdout.split('\n')
        match = next((ln.split()[0] for ln in names if voice and ln.lower().startswith(voice.lower())), None)
        cmd = ['say', '-o', tmp, '-r', str(wpm)] + (['-v', match] if match else []) + [text]
        return tmp, match or 'default', subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    eng = shutil.which('espeak-ng') or shutil.which('espeak')
    if eng:
        tmp = tmp_base + '.wav'
        r = subprocess.run([eng, '-w', tmp, '-s', str(wpm)] + (['-v', voice] if voice else []) + [text],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0 and voice:  # unknown voice name: use the default one
            r = subprocess.run([eng, '-w', tmp, '-s', str(wpm), text], capture_output=True, text=True, timeout=60)
            voice = None
        return tmp, voice or 'default', r
    raise OpError("no text-to-speech engine found: sound_speak uses Windows SAPI, macOS `say`, or espeak-ng on Linux "
                  "(apt install espeak-ng); or record the words and bring them in with sound_import")


@op(mutates=True)
def sound_speak(project: str, name: str, text: str, voice: str = None, rate: int = 0, normalize: bool = True) -> str:
    """Text-to-speech into the sound bank with the OS's own engine: Windows SAPI (voices like David, Zira; the
    default is David), macOS `say` (Alex, Samantha ...), Linux espeak-ng (en-us, en-gb ...). A voice the engine
    doesn't have falls back to its default. rate -10..10. Use as a vocoder modulator (vocoder fx,
    modulator='sound:<name>' or a muted track holding it as audio clips), a sampler source, or an audio clip."""
    import tempfile
    import os
    P = _load(project)
    tmp, used, r = _tts(text, voice, rate, os.path.join(tempfile.gettempdir(), f"ismail_tts_{os.getpid()}"))
    if r.returncode != 0 or not os.path.exists(tmp):
        raise OpError(f"TTS failed: {(r.stderr or r.stdout).strip()[:300]}")
    voice = used
    y, sr = sf.read(tmp, dtype='float64', always_2d=True)
    os.remove(tmp)
    y = y.T
    if y.shape[0] == 1:
        y = np.vstack([y, y])
    a = np.max(np.abs(y), axis=0)
    nz = np.nonzero(a > 1e-3)[0]
    if len(nz):
        y = y[:, nz[0]:nz[-1] + 1]
    if normalize:
        y = y / (np.max(np.abs(y)) + 1e-12) * 0.891
    _write_sound(P, name, y, sr, note=f"tts '{text}' ({voice})")
    P.save()
    return f"sound {name!r}: {y.shape[1] / sr:.2f}s of speech '{text}' ({voice}, {sr} Hz)"


def _has(d, path):
    try:
        SD._get(d, path)
        return True
    except (KeyError, IndexError, ValueError, TypeError):
        return False


def _set_deep(d, path, v):
    ks = path.split('.')
    for k in ks[:-1]:
        if isinstance(d, list):
            d = d[int(k)]
        else:
            d = d.setdefault(k, {})
    d[ks[-1]] = v


@op(mutates=True)
def track_fit(project: str, track: str, params: dict, bars: list, iters: int = 30, apply: bool = False,
              seed: int = 0) -> str:
    """Tune a track IN CONTEXT: render the track's whole stem group (stem_map) over bars [a, b] and score it against
    the same window of the reference stem with the perceptual (CLAP) metric plus band levels. params:
    {path: [lo, hi]} with 'inst.<param path>' (inst.filter.cutoff, inst.oscs.0.detune ...), 'fx.<i>.<param>',
    'volume_db' or 'pan'. 8-16 bars and 20-40 iterations is a good budget (each iteration renders the window).
    apply=True writes the best values into the track."""
    from . import trackfit as TF
    from .api_cmp import ref_stems
    P = _load(project)
    tr = P.track(track)
    sm = P.d.get('stem_map') or {}
    if track not in sm:
        raise OpError(f"{track!r} is not in the stem map; stem_map_set({{'{track}': '<stem>'}}) first")
    stem = sm[track]
    refs = ref_stems(P)
    if stem not in refs:
        raise OpError(f"no reference stem {stem!r}; separate(source='ref') first")
    group = [t for t, s in sm.items() if s == stem and t in P.d['tracks'] and not P.d['tracks'][t].get('mute')]
    for k in params:
        if not (k.startswith('inst.') or k.startswith('fx.') or k in ('volume_db', 'pan')):
            raise OpError(f"param {k!r}: use 'inst.<path>', 'fx.<index>.<param>', 'volume_db' or 'pan'")
    if bars[1] - bars[0] + 1 > 24:
        raise OpError("use at most 24 bars per fit (each iteration renders the window)")
    vals, s1, s0, p1, p0 = TF.fit_track(P.d, P.root, P.grid(), track, params, bars, group, refs[stem], iters, seed)
    out = [f"track_fit {track} in stem group {stem} {group}, bars {bars[0]}-{bars[1]}: score {s0:.2f} -> {s1:.2f}",
           f"  perceptual {p0['perceptual']:.3f} -> {p1['perceptual']:.3f}; band error {p0['band_db']:.1f} -> "
           f"{p1['band_db']:.1f} dB; width diff {p0['width_diff']:+.2f} -> {p1['width_diff']:+.2f}",
           "  best: " + json.dumps({k: round(v, 4) for k, v in vals.items()})]
    if apply and s1 < s0:
        from .trackfit import _path_set
        for k, v in vals.items():
            _path_set(tr, k, v)
        P.save()
        out.append("  applied (render + cmp_run to confirm on the whole song)")
    elif apply:
        out.append("  not applied: no improvement over the current settings")
    return '\n'.join(out)


@op(mutates=True)
def eq_match(project: str, track: str, bars: list, max_db: float = 12.0, apply: bool = True,
             level: bool = True) -> str:
    """Match a track's long-term spectrum to the reference stem over bars [a, b]: renders the track's stem group
    (stem_map), compares 1/3-octave levels with the same window of the reference stem, and writes a peaking EQ
    at octave centres (63 Hz .. 16 kHz, gains clipped to +-max_db) as the track's fx 0 (replacing an earlier
    eq_match EQ), plus the level difference on the fader when level=True. Best where that track dominates its
    stem in the window (e.g. a pad in an intro)."""
    from .api_cmp import ref_stems
    from .render import Renderer
    P = _load(project)
    tr = P.track(track)
    sm = P.d.get('stem_map') or {}
    if track not in sm:
        raise OpError(f"{track!r} is not in the stem map; stem_map_set first")
    refs = ref_stems(P)
    stem = sm[track]
    if stem not in refs:
        raise OpError(f"no reference stem {stem!r}; separate(source='ref') first")
    group = [t for t, s in sm.items() if s == stem and t in P.d['tracks'] and not P.d['tracks'][t].get('mute')]
    d = json.loads(json.dumps(P.d))
    fxl = d['tracks'][track].get('fx', [])
    if fxl and fxl[0].get('name') == 'eq_match':
        fxl.pop(0)  # measure without the previous match
    R = Renderer(d, P.root, bars[0], bars[1] + 1, group, cache=True)
    y, _ = R.run()
    g = P.grid()
    n_win = int((g.bar_time(bars[1] + 1) - g.bar_time(bars[0])) * R.sr)
    y = y[:, :n_win]
    yr, srr = sf.read(refs[stem], always_2d=True, dtype='float64')
    a = int(max(g.bar_time(bars[0]), 0) * srr)
    yr = yr[a:a + n_win].T

    def third_oct(x, sr):
        m = x.mean(0)
        nfft = 1 << int(np.ceil(np.log2(len(m))))
        Pw = np.abs(np.fft.rfft(m * np.hanning(len(m)), n=nfft)) ** 2
        f = np.fft.rfftfreq(nfft, 1 / sr)
        out = []
        for c in SD.THIRD_OCT:
            msk = (f >= c / 2 ** (1 / 6)) & (f < c * 2 ** (1 / 6))
            out.append(10 * np.log10(Pw[msk].sum() + 1e-15) if msk.any() else -150)
        return np.array(out)
    mine, ref = third_oct(y, R.sr), third_oct(yr, srr)
    live = (mine > mine.max() - 60) & (ref > ref.max() - 60) & (SD.THIRD_OCT >= 40) & (SD.THIRD_OCT <= 16000)
    # level: energy difference; shape: per-band difference after removing the level offset
    lvl = 10 * np.log10(np.sum(10 ** (ref[live] / 10)) / np.sum(10 ** (mine[live] / 10)))
    diff = np.where(live, (ref - mine) - lvl, 0.0)
    centers = [63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
    bands = []
    for c in centers:
        msk = live & (SD.THIRD_OCT >= c / 2 ** 0.5) & (SD.THIRD_OCT < c * 2 ** 0.5)
        if msk.any():
            gdb = float(np.clip(np.mean(diff[msk]), -max_db, max_db))
            if abs(gdb) >= 1.0:
                bands.append({"type": "peak", "freq": c, "gain_db": round(gdb, 1), "q": 1.2})
    lines = [f"eq_match {track} (stem group {group}) bars {bars[0]}-{bars[1]}: level {lvl:+.1f} dB",
             "  band gains: " + ', '.join(f"{b['freq']}Hz {b['gain_db']:+.1f}" for b in bands)]
    if apply:
        tfx = tr.setdefault('fx', [])
        if tfx and tfx[0].get('name') == 'eq_match':
            tfx.pop(0)
        if bands:
            tfx.insert(0, {"type": "eq", "name": "eq_match", "bands": bands})
            # automation indices on this track's fx shift by one
            auto = tr.get('automation', {})
            tr['automation'] = {(f"fx.{int(k.split('.')[1]) + 1}.{k.split('.', 2)[2]}" if k.startswith('fx.') else k): v
                                for k, v in auto.items()}
        if level:
            tr['volume_db'] = round(tr.get('volume_db', 0.0) + float(np.clip(lvl, -24, 24)), 2)
        P.save()
        lines.append(f"  applied: eq as fx 0, fader now {tr.get('volume_db')} dB (render + cmp_run to confirm)")
    return '\n'.join(lines)
