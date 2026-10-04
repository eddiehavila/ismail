"""mimic.render computes a partial only while it sounds, and can skip weak partials or the second channel (ledger
M76: 152 s of section audio took 30 minutes)."""
import numpy as np
import pytest

from ismail import mimic
from ismail.dsp import SR


@pytest.fixture(scope='module')
def cello():
    return mimic.load_profile('cello')


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)))


def test_a_long_tail_after_the_release_is_silence_and_stays_so(cello):
    t = np.arange(int(4 * SR)) / SR
    y = mimic.render(cello, 65.4, t, 0.7, 0.5, SR, room=0)
    assert rms(y[:, :int(0.5 * SR)]) > 1e-3
    assert np.max(np.abs(y[:, int(3.5 * SR):])) < 1e-3


def test_mono_gives_two_equal_channels(cello):
    t = np.arange(int(1.5 * SR)) / SR
    y = mimic.render(cello, 130.8, t, 0.7, 1.0, SR, mono=True)
    assert y.shape == (2, len(t)) and np.array_equal(y[0], y[1]) and rms(y) > 1e-3


def test_floor_skips_weak_partials_and_none_keeps_them(cello):
    t = np.arange(int(1.0 * SR)) / SR
    full = mimic.render(cello, 65.4, t, 0.7, 0.8, SR, room=0, seed=3)
    same = mimic.render(cello, 65.4, t, 0.7, 0.8, SR, room=0, seed=3, floor=None)
    cut = mimic.render(cello, 65.4, t, 0.7, 0.8, SR, room=0, seed=3, floor=40)
    assert np.array_equal(full, same)
    d = rms(full - cut) / rms(full)
    assert 0 < d < 0.2
