"""Studio against live: the same bars rendered by the studio and played by a silent live engine deck, compared per
track, per bus and as a mix. Offline and deterministic: the engine renders inline (no workers, nothing is late) and
its master safety chain is bypassed, so any difference is the live path itself. The studio side is the song with its
master effects left out, because a deck has none (it says so). The live mix is the deck's input: its strip is an
allpass at flat settings (the isolator's bands sum flat in level, not in phase), which is the DJ's, not the song's."""
import copy
import json
import os
import shutil
import tempfile

import numpy as np
from scipy import signal as sg

from ..dsp import SR
from . import graph as G
from .engine import Engine
from .ops import _song_performers

BANDS = (63, 125, 250, 500, 1000, 2000, 4000, 8000)
# a pass: what a listener cannot tell apart on a level meter or a spectrum, and the envelope follows the studio
LEVEL_DB = 0.5
CORR = 0.99
BAND_DB = 1.0


class _Unity:
    """Stands in for the master safety chain: trim, rider and limiter would change the take, not the engine."""
    la = 0

    def process(self, x):
        return x


def _studio(d, root, bars, tracks):
    from ..render import Renderer
    d = copy.deepcopy(d)
    d.setdefault('master', {})['fx'] = []
    R = Renderer(d, root, bars[0], bars[1] + 1, tracks, cache=False)
    y, stems = R.run()
    out = {('track:' + k if not k.startswith('bus:') else k): v for k, v in stems.items()}
    out['mix'] = y
    return out


def _live(song, d, bars, n):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        eng = Engine(tmp, bpm=float(d['bpm']), bpb=d.get('beats_per_bar', 4), workers=0, device='none')
        eng.safety = _Unity()
        got = {}

        def tap(key, p0, y, lag):
            got.setdefault(key, []).append((p0 - lag, y.copy()))
        eng.tap = tap
        head = eng.cmd_load('P', song, bars=list(bars), at='next_bar', loop=False, performers=_song_performers(song))
        start = eng.sample(min(c.start for c in eng.tl.clips.values()))
        while eng.pos < start + n + G.LAT_BUDGET:
            eng.tick()
            eng.mix_block()
        eng.shutdown()
    got['mix'] = got.pop('deck:P', [])
    out = {}
    for key, blocks in got.items():
        y = np.zeros((2, n))
        for p, b in blocks:
            a, z = max(p, start), min(p + b.shape[1], start + n)
            if z > a:
                y[:, a - start:z - start] += b[:, a - p:z - p]
        out[key.replace('track:P.', 'track:').replace('bus:P.', 'bus:')] = y
    return out, head


def _db(x):
    return 10 * np.log10(np.mean(x ** 2) + 1e-20)


def _env_db(x, floor_db=50):
    f = int(0.05 * SR)
    m = x.mean(0)
    e = np.array([np.sqrt(np.mean(m[i:i + f] ** 2)) for i in range(0, len(m) - f + 1, f)])
    d = 20 * np.log10(e + 1e-9)
    return np.maximum(d, d.max() - floor_db)


def _bands(x):
    # Hann-framed: one unwindowed FFT over a take cut mid-note leaks a broadband top 50-60 dB under a loud note
    fr, S = sg.welch(x.mean(0), SR, nperseg=min(8192, x.shape[1]))
    return np.array([10 * np.log10(S[(fr >= c / 2 ** .5) & (fr < c * 2 ** .5)].sum() + 1e-20) for c in BANDS])


def compare(studio, live):
    """Numbers for one pair of (2, n) takes: the studio level (dBFS rms), live minus studio level, 50 ms envelope correlation (dB, 50 dB floor),
    the residual (live - studio) under the studio level, the best lag in samples (should be 0), octave bands
    63..8k live minus studio (bands under 60 dB below the loudest are left out, as None)."""
    n = min(studio.shape[1], live.shape[1])
    st, lv = studio[:, :n], live[:, :n]
    if _db(st) < -100 and _db(lv) < -100:
        return {'silent': True}
    es, el = _env_db(st), _env_db(lv)
    corr = float(np.corrcoef(es, el)[0, 1]) if es.std() > 1e-6 and el.std() > 1e-6 else float(np.allclose(es, el, atol=0.5))
    m = min(n, 4 * SR)
    a, b = lv.mean(0)[:m], st.mean(0)[:m]
    xc = sg.correlate(a, b, mode='full', method='fft') / (np.sqrt(np.sum(a * a) * np.sum(b * b)) + 1e-30)
    mid = m - 1
    w = xc[mid - 256:mid + 257]
    # a lag only means something when the two line up at all (noise or a free phase never does)
    lag = int(np.argmax(np.abs(w))) - 256 if np.abs(w).max() > 0.5 else 0
    bs, bl = _bands(st), _bands(lv)
    keep = bs > bs.max() - 60
    return {'silent': False, 'studio_db': _db(st), 'level_db': _db(lv) - _db(st), 'corr': corr, 'resid_db': _db(lv - st) - _db(st),
            'lag': lag,
            'bands': [float(b) if k else None for b, k in zip(bl - bs, keep)]}


def verdict(m):
    """'ok' or the reasons it is not."""
    if m.get('silent'):
        return 'ok (silent in both)'
    why = []
    if abs(m['level_db']) > LEVEL_DB:
        why.append(f"level {m['level_db']:+.1f} dB")
    if m['corr'] < CORR:
        why.append(f"envelope corr {m['corr']:.3f}")
    worst = max((abs(b) for b in m['bands'] if b is not None), default=0.0)
    if worst > BAND_DB:
        why.append(f"a band off by {worst:.1f} dB")
    if m['lag']:
        why.append(f"{m['lag']:+d} samples late" if m['lag'] > 0 else f"{-m['lag']} samples early")
    return 'ok' if not why else 'DIFFERS: ' + ', '.join(why)


def run(song, bars, tracks=None):
    """-> ({key: metrics}, takes {key: (studio, live)}, the deck's load message). Keys: 'mix', 'track:<name>',
    'bus:<name>', judged from the window's second bar, and 'mix, bar <a> (edge)' for the first. tracks limits both sides to those tracks (the mix is then theirs alone)."""
    song = os.path.abspath(song)
    with open(os.path.join(song, 'project.json'), encoding='utf8') as f:
        d = json.load(f)
    if tracks:
        d = copy.deepcopy(d)
        d['tracks'] = {k: v for k, v in d['tracks'].items() if k in tracks}
        missing = set(tracks) - set(d['tracks'])
        if missing:
            raise ValueError(f"no track {', '.join(sorted(missing))} in {song}")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            # the deck reads a song folder: a copy of the project file next to the song's own voices and sounds
            sub = os.path.join(tmp, os.path.basename(song))
            os.makedirs(sub)
            for name in os.listdir(song):
                if name not in ('project.json', 'renders', 'cache', 'history', 'live'):
                    src = os.path.join(song, name)
                    try:
                        os.symlink(src, os.path.join(sub, name), target_is_directory=os.path.isdir(src))
                    except OSError:
                        (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(sub, name))
            with open(os.path.join(sub, 'project.json'), 'w', encoding='utf8') as f:
                json.dump(d, f)
            return _run(sub, song, d, bars)
    return _run(song, song, d, bars)


def _run(deck_song, root, d, bars):
    st = _studio(d, root, bars, None)
    n = st['mix'].shape[1]
    lv, head = _live(deck_song, d, bars, n)
    # a window's first bar is its edge: the studio rings in what was played before it, a deck starts clean (only
    # notes still held come in). Judged from the second bar on; the edge is reported as a line of its own.
    edge = int(round(d.get('beats_per_bar', 4) * 60.0 / float(d['bpm']) * SR)) if bars[0] > 1 and bars[1] > bars[0] else 0
    keys = ['mix'] + sorted(k for k in st if k != 'mix')
    res, takes = {}, {}
    for k in keys:
        s = st[k]
        v = lv.get(k, np.zeros_like(s))
        res[k] = compare(s[:, edge:], v[:, edge:])
        takes[k] = (s, v)
    if edge:
        res[f'mix, bar {bars[0]} (edge)'] = compare(takes['mix'][0][:, :edge], takes['mix'][1][:, :edge])
    return res, takes, head


def report(res, head=''):
    L = []
    for k, m in res.items():
        if m.get('silent'):
            L.append(f"  {k:<22} silent in both")
            continue
        bands = ' '.join('  . ' if b is None else f"{b:+4.1f}" for b in m['bands'])
        L.append(f"  {k:<22} {m['studio_db']:6.1f} dB rms  live {m['level_db']:+5.2f} dB  corr {m['corr']:.3f}  residual {m['resid_db']:+6.1f} dB  "
                 f"bands {bands}  {verdict(m)}")
    notes = [ln.strip() for ln in head.splitlines() if 'not live' in ln]
    return '\n'.join(L + [f"  deck: {x}" for x in notes])

