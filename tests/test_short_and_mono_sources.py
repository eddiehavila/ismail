"""Measuring short notes and mono files: mimic_measure on a 0.3 s note produced a non-finite buffer (its level
window started after the note ended), and analyze_timbre crashed on a mono source (it read channel 1)."""
import numpy as np
import soundfile as sf

from ismail import analysis, mimic

SR = 44100


def tone(dur, seed=1):
    t = np.arange(int(dur * SR)) / SR
    rng = np.random.default_rng(seed)
    y = np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 880 * t) + 0.05 * rng.standard_normal(len(t))
    y *= np.minimum(1, t / 0.03) * np.minimum(1, (dur - t) / 0.05)
    return np.concatenate([np.zeros(2205), 0.5 * y, np.zeros(4410)])


def test_a_short_note_measures_and_renders_finite():
    for dur in (0.15, 0.3):
        for kind in ('sustained', 'decaying'):
            n = mimic.measure_notes([(tone(dur), 69, 100)], kind=kind)[0]
            assert np.isfinite(n['atk_ref_db']) and np.isfinite(np.array(n['atk_tf'])).all(), (dur, kind)
            z = mimic.render(mimic.profile_from_notes([n]), 440.0, np.arange(SR) / SR, 0.8, dur, SR)
            assert np.isfinite(z).all() and np.abs(z).max() > 0


def test_a_mono_file_reads_as_two_equal_channels_and_timbre_works(tmp_path):
    p = str(tmp_path / 'mono.wav')
    sf.write(p, tone(1.0), SR)
    ys = analysis.load(p, stereo=True)
    assert ys.shape[0] == 2 and np.array_equal(ys[0], ys[1])
    info, text = analysis.timbre(p, 0.1, 0.9)
    assert 'stereo: side/mid 0.00' in text and np.isfinite(info['centroid'])
