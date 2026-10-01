"""The guitar rig effects (fuzz, univibe, amp, cab, rotary, tape, wah): each renders, stays bounded and changes the
sound; automation moves them; live runs them baked into each rendered note."""
import os
import shutil
import tempfile

import numpy as np
import pytest
import soundfile as sf

from ismail import api, rig

TYPES = sorted(rig.DEFAULTS)


@pytest.fixture(scope='module')
def proj():
    d = tempfile.mkdtemp(prefix='ismail_rig_')
    p = os.path.join(d, 'p')
    api.project_new(p, bpm=120, length_bars=2)
    api.track_add(p, 'gtr', instrument={"type": "synth", "oscs": [{"wave": "saw"}], "filter": {"type": "lp24",
                                                                                               "cutoff": 3000}})
    api.notes_write(p, 'gtr', 1, "0 E3 2 100; 2 A3 2 90", repeat=2)
    yield p
    shutil.rmtree(d, ignore_errors=True)


def render(p, fx):
    t = api._load(p).d['tracks']['gtr']
    t['fx'] = fx
    P = api._load(p)
    P.d['tracks']['gtr'] = t
    P.save()
    api.render(p)
    y, _ = sf.read(os.path.join(p, 'renders', 'latest.wav'))
    return y


def test_rig_types_are_registered():
    from ismail import fx
    for t in TYPES:
        assert t in fx.FX_DEFAULTS and t in rig.DOCS and t in rig.APPLY
    assert 'fuzz' in api.fx_help(type='fuzz')


@pytest.mark.parametrize('t', TYPES)
def test_each_rig_effect_renders_and_changes_the_sound(proj, t):
    dry = render(proj, [])
    wet = render(proj, [{'type': t}])
    assert np.isfinite(wet).all()
    pk = np.abs(wet).max()
    assert 1e-3 < pk <= 1.0, f"{t} peak {pk}"
    n = min(len(dry), len(wet))
    diff = np.sqrt(np.mean((wet[:n] - dry[:n]) ** 2)) / (np.sqrt(np.mean(dry[:n] ** 2)) + 1e-12)
    assert diff > 0.05, f"{t} barely changed the signal ({diff:.3f})"


def test_wah_position_automation_moves_the_tone(proj):
    def centroid(y):
        S = np.abs(np.fft.rfft(y.mean(1)))
        f = np.fft.rfftfreq(len(y), 1 / 44100)
        return float((S * f).sum() / S.sum())
    lo = render(proj, [{'type': 'wah', 'pos': 0.0}])
    hi = render(proj, [{'type': 'wah', 'pos': 1.0}])
    assert centroid(hi) > centroid(lo) * 1.2
    api.automation_set(proj, 'gtr', 'fx.0.pos', [[1, 0.0], [3, 1.0]])
    sweep = render(proj, [{'type': 'wah', 'pos': 0.0}])
    half = len(sweep) // 2
    assert centroid(sweep[half:]) > centroid(sweep[:half])


def test_live_startup_warmup_skips_studio_only_effects():
    # the rig types are registered in FX_DEFAULTS but have no live block: the warm-up at engine start crashed on them
    from ismail.live import fx_blocks
    from ismail.live.engine import warm_effects
    assert any(t not in fx_blocks.PROCS for t in rig.DEFAULTS)
    warm_effects()


def test_live_bakes_rig_effects(tmp_path):
    from ismail.live.engine import Engine
    eng = Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')
    out = eng.cmd_track('g', instrument={'type': 'synth', 'oscs': [{'wave': 'saw'}]},
                        fx=[{'type': 'fuzz'}, {'type': 'amp'}, {'type': 'cab'}])
    assert out.startswith('g: new track')
    assert 'baked' in eng.tracks['g']['path'].chain.describe() or eng.tracks['g'].get('bake')
