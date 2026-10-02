"""Render memory: stems are kept from their first to their last sound (float32) and built full length when read, and
a track's whole output stays in memory only while an effect reads it. A 146-bar song of ~70 tracks, most playing a
few notes, needed ~20 GB and ran out of memory."""
import json
import os

import numpy as np

from ismail import api
from ismail.render import Renderer, _Stem


def project(root):
    api.project_new(root, bpm=120, length_bars=16)
    api.track_add(root, 'kick', instrument='preset:kick')
    api.notes_write(root, 'kick', 1, '0 C2 1 110; 2 C2 1 110', repeat=16)
    api.track_add(root, 'pad', instrument='preset:pad')
    api.notes_write(root, 'pad', 1, '0 C4 4 90; 0 E4 4 90', repeat=16)
    api.fx_add(root, 'pad', {'type': 'compressor', 'sidechain': 'kick', 'threshold_db': -30})
    api.track_add(root, 'hit', instrument='preset:clap')
    api.notes_write(root, 'hit', 9, '0 C4 1 100')                    # one note in a 16-bar song
    api.bus_add(root, 'verb', fx=[{'type': 'reverb', 'mix': 1.0}])
    api.track_set(root, 'hit', sends={'verb': -6})
    with open(os.path.join(root, 'project.json'), encoding='utf8') as f:
        d = json.load(f)
    d['master']['fx'] = []          # stems follow a master limiter only as a level curve; without one they sum exactly
    return d


def test_stems_sum_to_the_mix_and_a_sparse_track_keeps_only_its_sound(tmp_path):
    root = str(tmp_path / 's')
    d = project(root)
    R = Renderer(d, root, None, None, None, False)
    y, stems = R.run()
    total = sum(stems[k] for k in stems)
    assert np.abs(total - y).max() < 1e-5 * np.abs(y).max()           # float32 stems, float64 mix
    assert set(R.post_fx) == {'kick'}                                 # only the sidechain source stays whole
    s = stems._s['hit']
    assert s.y.shape[1] < 0.3 * s.n and s.y.dtype == np.float32
    assert stems['hit'].shape == y.shape


def test_a_window_crops_stems_like_the_mix(tmp_path):
    root = str(tmp_path / 's')
    d = project(root)
    full, fst = Renderer(d, root, None, None, None, False).run()
    win, wst = Renderer(d, root, 9, 10, None, False).run()
    assert all(wst[k].shape == win.shape for k in wst)
    a = int(8 * 2 * 44100)
    assert np.abs(wst['hit'][:, :44100] - fst['hit'][:, a:a + 44100]).max() < 1e-4


def test_a_stem_of_silence_is_empty_and_reads_back_as_zeros():
    s = _Stem(np.zeros((2, 1000)))
    assert s.y.shape == (2, 0)
    s.scale(np.ones(1000))
    s.crop(100)
    assert s.full().shape == (2, 900) and not s.full().any()
