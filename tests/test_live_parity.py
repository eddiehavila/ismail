"""Studio effects (ismail/fx.py) are the source of truth; each live processor (ismail/live/fx_blocks.py) must give
the same output over a whole window. A failure here means the two drifted: fix the live one."""
import numpy as np
import pytest

from ismail import fx as studio
from ismail.dsp import SR
from ismail.live import fx_blocks as live
from test_fx_blocks import BPM, CASES, N, signal_pair

# known, measured differences (everything else must match to 1e-9 of the peak)
LOOSE = {'hall': 1e-6,                  # FFT partitioned convolution vs one FFT: rounding
         'distortion:asym': None,       # live uses a 10 Hz DC blocker; studio subtracts the whole-window mean
         }
# oversampling filters differ at the window edges only (the studio's zero-phase resampler drops the filter's
# pre-ringing before t=0, the causal live one plays it): compare inside. fuzz and amp have state after their
# nonlinear stage (bias tracking, supply sag) that carries that edge for a few hundred ms, then match to 1e-13
WARMUP = {'distortion': 300, 'fuzz': 12000, 'amp': 18000}


class Ctx:
    sr, bpm, offset_samples, track = SR, BPM, 0, 'lead'

    def __init__(self, key):
        self.key = key
        self.ons = (np.arange(0, N, int(0.25 * SR)) + 0.5) / SR

    def param(self, idx, name, default):
        return default

    def track_audio(self, name):
        return self.key

    def track_onsets(self, name):
        return self.ons

    def modulator_audio(self, ref, n):
        return self.key[:, :n]

    def note_gr(self, idx, gr):
        pass


def _id(f):
    return f['type'] + (':' + f['mode'] if f.get('mode') and f['type'] == 'distortion' else '')


@pytest.mark.parametrize('fx', CASES, ids=lambda f: _id(f) + ':' + str(f.get('source', '')))
def test_live_matches_studio(fx):
    tol = LOOSE.get(_id(fx), 1e-9)
    if tol is None:
        pytest.skip('known design difference (see LOOSE)')
    x, key = signal_pair()
    f = studio.normalize(fx)
    a = studio.apply_fx(x.copy(), f, Ctx(key), 0)
    b = live.apply_fx(x.copy(), live.normalize(fx), Ctx(key), 0)
    scale = max(np.max(np.abs(a)), 1e-9)
    assert a.shape == b.shape
    w = WARMUP.get(fx['type'], 0)
    a, b = (a[:, w:-w], b[:, w:-w]) if w else (a, b)
    assert np.max(np.abs(a - b)) / scale < tol, f"{_id(fx)} drifted: {np.max(np.abs(a - b)) / scale:.2e}"


def test_every_studio_effect_has_a_live_path():
    """A studio effect with no live processor is baked (graph.split_chain), never refused."""
    from ismail.live import graph
    for t in studio.FX_DEFAULTS:
        fx = studio.normalize({'type': t, **({'modulator': 'k'} if t == 'vocoder' else {})})
        bake, run = graph.split_chain([fx])
        assert (t in live.PROCS and run and not bake) or (t not in live.PROCS and bake and not run)
