"""Every track says what its sound is modeled on (measured, designed, unstated), so measuring first is in the tool
replies and survives a context summary (2026-10-02: agents skipped the measuring ops when the rule was only in the
skill)."""
import numpy as np
import pytest

from ismail import api, machine
from ismail.api import OpError
from ismail.render import write_wav


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_MACHINE_DIR', str(tmp_path / 'board'))
    monkeypatch.setattr(machine, 'gpu', lambda: None)
    monkeypatch.setattr(machine, 'memory', lambda: (40.0, 70.0, 30.0))
    monkeypatch.setattr(machine, 'cpu_load', lambda: (12.0, []))
    p = str(tmp_path / 'song')
    api.project_new(p, bpm=120, length_bars=1)
    return p


def rows(p):
    info = api.project_info(p)
    return {ln.split()[0]: ln.split()[1] for ln in info.split('models (')[1].splitlines()[1:] if ln.startswith('  ')
            and not ln.startswith('  unstated:')}


def test_what_a_track_plays_says_whether_it_is_measured(proj, tmp_path):
    api.track_add(proj, 'lead', instrument={'type': 'synth'})
    api.track_add(proj, 'violin', instrument={'type': 'mimic', 'profile': 'violin'})
    api.track_add(proj, 'piano', instrument='preset:grand_piano')
    api.track_add(proj, 'wobble', instrument='preset:growl')
    t = np.linspace(0, 0.3, 13230)
    write_wav(str(tmp_path / 'hit.wav'), np.vstack([np.sin(2 * np.pi * 220 * t)] * 2) * np.exp(-t * 9), 44100)
    api.sound_import(proj, 'hit', str(tmp_path / 'hit.wav'))
    api.track_add(proj, 'perc', instrument={'type': 'sampler', 'sound': 'hit'})
    api.sound_make(proj, 'blip', {'type': 'synth'}, describe=False)
    api.track_add(proj, 'blips', instrument={'type': 'sampler', 'sound': 'blip'})
    assert rows(proj) == {'lead': 'unstated', 'violin': 'measured', 'piano': 'measured', 'wobble': 'designed',
                          'perc': 'measured', 'blips': 'unstated'}
    info = api.project_info(proj)
    assert 'models (what each sound is modeled on): 3 measured, 1 designed, 2 unstated' in info
    assert 'mimic_measure' in info and "track_model(track, on='designed')" in info


def test_track_model_records_an_example_or_a_design_and_clears(proj, tmp_path):
    api.track_add(proj, 'bass', instrument={'type': 'synth'})
    api.track_add(proj, 'pad', instrument={'type': 'synth'})
    assert 'designed' in api.track_model(proj, 'pad', on='designed')
    ex = tmp_path / 'bass_note.wav'
    write_wav(str(ex), np.zeros((2, 4410)), 44100)
    assert 'modeled on' in api.track_model(proj, 'bass', on=str(ex), by='ear exam')
    assert rows(proj) == {'bass': 'measured', 'pad': 'designed'}
    assert 'unstated' in api.track_model(proj, 'bass', on='')
    with pytest.raises(OpError, match='sound_import'):
        api.track_model(proj, 'bass', on='sound:nothing')
    with pytest.raises(OpError, match='no reference'):
        api.track_model(proj, 'bass', on='ref:bass')
    with pytest.raises(OpError, match='not found'):
        api.track_model(proj, 'bass', on='takes/missing.wav')


def test_a_new_kind_of_instrument_drops_the_old_record_and_a_tweak_keeps_it(proj):
    api.track_add(proj, 'bass', instrument={'type': 'synth'})
    api.track_model(proj, 'bass', on='designed')
    assert 'cleared' not in api.instrument_set(proj, 'bass', {'filter': {'cutoff': 900}})
    assert rows(proj)['bass'] == 'designed'
    assert 'no longer applies' in api.instrument_set(proj, 'bass', {'type': 'kick'}, merge=False)
    assert rows(proj)['bass'] == 'unstated'


def test_a_kit_is_measured_only_when_every_piece_is(proj, tmp_path):
    t = np.linspace(0, 0.2, 8820)
    write_wav(str(tmp_path / 'k.wav'), np.vstack([np.sin(2 * np.pi * 60 * t)] * 2) * np.exp(-t * 20), 44100)
    api.sound_import(proj, 'k', str(tmp_path / 'k.wav'))
    api.track_add(proj, 'drums', instrument={'type': 'kit', 'map': {'C1': {'type': 'sampler', 'sound': 'k'},
                                                                    'D1': {'type': 'snare'}}})
    assert rows(proj)['drums'] == 'unstated'
    assert 'kit of 2: 1 measured, 1 unstated' in api.project_info(proj)


def test_render_names_the_unstated_tracks_and_stays_quiet_when_all_are_said(proj):
    api.track_add(proj, 'lead', instrument={'type': 'synth'})
    api.notes_write(proj, 'lead', 1, '0 C4 1')
    assert 'models: lead unstated' in api.render(proj)
    api.track_model(proj, 'lead', on='designed')
    assert 'models:' not in api.render(proj)
