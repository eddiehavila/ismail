"""Performer voices (a voice module with perform() and no voice()) play a whole part at once, with expression
lanes: automation 'inst.lane.<name>' in the studio, clip 'expr' lanes live, and a deck turns the first into the
second."""
import os

import numpy as np
import soundfile as sf

from ismail import api

BENDER = '''
import numpy as np

INFO = {"summary": "test performer: a sine per note, bent by the bend lane (semitones)"}


def perform(notes, total_n, sr, bpm=120.0, lanes=None, **params):
    out = np.zeros(total_n)
    bend = (lanes or {}).get("bend")
    for st, m, d, v in notes:
        a, b = int(st * sr), min(total_n, int((st + d) * sr))
        f = 440.0 * 2 ** ((m - 69) / 12) * 2 ** ((bend[a:b] if bend is not None else 0.0) / 12)
        out[a:b] += 0.3 * np.sin(2 * np.pi * np.cumsum(f) / sr)
    return out
'''


def song(root):
    api.project_new(root, bpm=120, length_bars=2)
    os.makedirs(os.path.join(root, 'voices'), exist_ok=True)
    with open(os.path.join(root, 'voices', 'bender.py'), 'w') as f:
        f.write(BENDER)
    api.track_add(root, 'lead', instrument={'type': 'code', 'voice': 'bender', 'tail': 0.1})
    api.notes_write(root, 'lead', 1, '0 A3 8')
    api.automation_set(root, 'lead', 'inst.lane.bend', [[1, 0], [2, 0], [2.5, 12]])
    return root


def peak_hz(y, sr):
    y = y.mean(1) if y.ndim > 1 else y
    S = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    return np.fft.rfftfreq(len(y), 1 / sr)[np.argmax(S)]


def test_studio_performer_follows_its_lane(tmp_path):
    root = song(str(tmp_path / 'song'))
    api.render(root)
    y, sr = sf.read(os.path.join(root, 'renders', 'latest.wav'))
    first = peak_hz(y[int(0.2 * sr):int(1.8 * sr)], sr)          # bar 1: no bend, A3
    last = peak_hz(y[int(3.1 * sr):int(3.9 * sr)], sr)            # second half of bar 2: bent up an octave
    assert abs(first - 220) < 5 and abs(last - 440) < 15, (first, last)


def test_deck_turns_studio_lanes_into_clip_expr(tmp_path):
    from ismail.live.engine import Engine
    from ismail.live.ops import _song_performers
    root = song(str(tmp_path / 'song'))
    assert _song_performers(root) == ['lead']                    # what live_load passes to the engine
    eng = Engine(str(tmp_path / 'live'), bpm=120, bpb=4, workers=0, device='none')
    out = eng.cmd_load('A', root, at='bar:2', loop=False, performers=_song_performers(root))
    assert 'automation:' not in out
    tr = eng.tracks['A.lead']
    assert tr['inst'].get('performer')
    clip = [c for c in eng.tl.clips.values() if c.track == 'A.lead'][0]
    assert clip.expr and [b for b, _ in clip.expr['bend']] == [0.0, 4.0, 6.0]
