"""Measurement ops against audio with known answers: tuning, swing, backbeat, kit, sections, levels from the ref."""
import os
import shutil
import tempfile

import numpy as np
import pytest
import soundfile as sf

from ismail import analysis as A
from ismail import api

SR = 22050
OPS = api.OPS


@pytest.fixture
def tmp():
    d = tempfile.mkdtemp(prefix='ismail_measure_')
    yield d
    shutil.rmtree(d, ignore_errors=True)


def tones(cents, sec=8.0, sr=SR):
    t = np.arange(int(sec * sr)) / sr
    y = np.zeros_like(t)
    for i, midi in enumerate([57, 60, 64, 67, 52, 55]):
        f = 440 * 2 ** ((midi - 69 + cents / 100) / 12)
        seg = (t >= i * sec / 6) & (t < (i + 2) * sec / 6)
        for k in range(1, 6):
            y += seg * np.sin(2 * np.pi * f * k * t) * 0.3 / k
    return 0.5 * y / np.abs(y).max()


def hit(kind, sr=SR, rng=np.random.default_rng(1)):
    n = int(0.12 * sr)
    t = np.arange(n) / sr
    if kind == 'kick':
        return np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 40)) * t) * np.exp(-t * 25)
    noise = rng.normal(0, 1, n)
    if kind == 'hat':
        noise = np.diff(np.r_[0, noise])
        return 0.3 * noise * np.exp(-t * 90)
    return 0.6 * (noise * np.exp(-t * 30) + np.sin(2 * np.pi * 190 * t) * np.exp(-t * 40))


def drum_loop(bpm, lead_in, bars, swing16=0.0, sr=SR):
    spb = 60 / bpm
    y = np.zeros(int((lead_in + bars * 4 * spb + 1) * sr))

    def put(kind, beat, gain=1.0):
        h = hit(kind) * gain
        a = int((lead_in + beat * spb) * sr)
        y[a:a + len(h)] += h[:len(y) - a]
    for b in range(bars):
        for beat in range(4):
            q = b * 4 + beat
            put('hat', q, 0.25)
            put('hat', q + 0.5, 0.2)
            put('hat', q + 0.75 + swing16, 0.15)
        put('kick', b * 4)
        put('kick', b * 4 + 2.5)
        put('snare', b * 4 + 1)
        put('snare', b * 4 + 3)
    return 0.5 * y / np.abs(y).max()


def test_tuning_reads_a_detuned_record():
    for cents in (40, -25, 0):
        got, r = A.tuning(tones(cents))
        assert abs(got - cents) < 3 and r > 0.5, (cents, got, r)


def test_swing_reads_late_sixteenths(tmp):
    p = os.path.join(tmp, 'drums.wav')
    sf.write(p, drum_loop(100, 0.5, 16, swing16=0.03), SR)
    data, txt = A.swing(p, 100, 0.5)
    assert abs(data['swing16'] - 0.03) < 0.008 and abs(data['swing8']) < 0.008, txt


def test_backbeat_puts_the_snare_on_two_and_four(tmp):
    p = os.path.join(tmp, 'loop.wav')
    sf.write(p, drum_loop(96, 1.3, 24), SR)
    g, txt = A.beat_grid(p, 96, 4)
    bar = 4 * 60 / 96
    off = (g['offset_sec'] - 1.3) % bar
    assert min(off, bar - off) < 0.03, txt
    assert max(g['backbeat_scores']) > 0.15, txt
