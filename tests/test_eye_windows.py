"""Spectrogram windows for eyes (ledger:M165 step 1, vox's eyeword.crop_png2 moved into main). Nate: "the
spectrogram scope clipping". Two pictures of one window line up pixel for pixel, a word's start is drawn and named,
and a spot reads as the same address on both sides (person and agent). Parity with vox's own code was checked on its
files, outside the repository: 20 of 20 pictures identical, every click on the plot box the same address."""
import json

import numpy as np
import soundfile as sf
import matplotlib.image as mpimg

from ismail import analysis as A


def _tone(path, hz, sr=44100, dur=1.0):
    t = np.arange(int(sr * dur)) / sr
    sf.write(str(path), 0.3 * np.sin(2 * np.pi * hz * t), sr)


def test_two_sounds_in_one_window_line_up_and_a_spot_has_one_address(tmp_path):
    _tone(tmp_path / 'a.wav', 3000)
    _tone(tmp_path / 'b.wav', 6000)
    words = [{'w': 'this', 't0': 0.30, 't1': 0.52}, {'w': 'is', 't0': 0.55, 't1': 0.70}]
    for k in 'ab':
        A.spectrogram_png(tmp_path / f'{k}.wav', tmp_path / f'{k}.png', 0.25, 0.75, words=words, target=words[0],
                          ruler=True)
    va, vb = (json.load(open(tmp_path / f'{k}.png.json')) for k in 'ab')
    assert va['axes'] == vb['axes'] == list(A.EYE_BOX) and va['px'] == [640, 420]
    ia, ib = mpimg.imread(tmp_path / 'a.png'), mpimg.imread(tmp_path / 'b.png')
    assert ia.shape == ib.shape and not np.array_equal(ia, ib)
    l, b, w, h = A.EYE_BOX                                # the 3 kHz line sits where the address says 3 kHz
    fx, fy = l + w * 0.2, 1 - (b + h * 3000 / 16000)
    assert A.eye_address(va, fx, fy, 'r1 p1 A') == 'r1 p1 A 0.10 s 3.0 kHz "this" vowel bands'
    col, row = int(fx * ia.shape[1]), int(fy * ia.shape[0])
    assert ia[row, col, :3].sum() > ib[row, col, :3].sum() + 0.5        # bright on a, dark on b
    assert A.eye_address(va, l + w * 0.8, 0.5) == '0.40 s 7.3 kHz "is" hiss'
    assert A.eye_address(va, 0.02, 0.5) is None          # off the plot box: no address, as on vox's page


def test_a_band_and_window_zoom(tmp_path):
    _tone(tmp_path / 'a.wav', 1500)
    A.spectrogram_png(tmp_path / 'a.wav', tmp_path / 'z.png', 0.1, 0.4, f_lo=1000, f_hi=2000)
    v = json.load(open(tmp_path / 'z.png.json'))
    t, f = A.eye_point(v, A.EYE_BOX[0] + A.EYE_BOX[2], 1 - (A.EYE_BOX[1] + A.EYE_BOX[3] / 2))
    assert abs(t - 0.4) < 1e-6 and abs(f - 1500) < 1e-6
    try:
        A.spectrogram_png(tmp_path / 'a.wav', tmp_path / 'y.png', 2.0, 3.0, ruler=True)
        raise AssertionError('a window past the end must say so')
    except ValueError as e:
        assert 'holds no frame' in str(e)
