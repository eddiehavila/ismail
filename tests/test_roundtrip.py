"""Write known material, render it, read it back through the analysis tools. Run: python -m pytest tests -q"""
import os
import shutil
import tempfile

import numpy as np
import pytest

from ismail import api, notation

BPM = 120


@pytest.fixture(scope='module')
def proj():
    d = tempfile.mkdtemp(prefix='ismail_test_')
    p = os.path.join(d, 'p')
    api.project_new(p, bpm=BPM, length_bars=4)
    api.track_add(p, 'drums', instrument='preset:kit_basic')
    api.track_add(p, 'bass', instrument={"type": "synth", "oscs": [{"wave": "saw"}], "mono": True,
                                         "filter": {"type": "lp24", "cutoff": 900}}, volume_db=-6)
    api.track_add(p, 'chords', instrument={"type": "synth", "oscs": [{"wave": "saw", "unison": 2, "detune": 6}],
                                           "filter": {"type": "lp24", "cutoff": 3000}}, volume_db=-10)
    api.pattern_write(p, 'drums', 1, {"C1": "x...x...x...x...", "D1": "....x.......x..."}, repeat=4)
    api.notes_write(p, 'bass', 1, "0 E2 1; 1 G2 1; 2 A2 1; 3 D3 1", repeat=4)
    api.notes_write(p, 'chords', 1, "0 E4,G4,B4 4; 4 D4,F#4,A4 4", repeat=2)
    api.render(p, stems=True)
    yield p
    shutil.rmtree(d, ignore_errors=True)


def test_notation():
    assert notation.pitch_to_midi('C4') == 60
    assert notation.pitch_to_midi('F#2') == 42
    assert notation.parse_notes("0 F#4 1 90 # comment")[0] == (0.0, 66, 1.0, 90)
    hits, span = notation.parse_steps("x..X")
    assert span == 1.0 and hits[1] == (0.75, 0.25, 127)


def test_render_levels(proj):
    out = api.render(proj)
    assert 'SILENT' not in out and 'CLIPPING' not in out


def test_drums_readback(proj):
    txt = api.analyze_drums(proj, source='track:drums', bars=[2, 2])
    row = [l for l in txt.split('\n') if l.startswith('bar   2')][0]
    low = row.split('low')[1].split('snare')[0].replace(' ', '')
    snare = row.split('snare')[1].split('hat')[0].replace(' ', '')
    assert [i for i, c in enumerate(low) if c != '.'] == [0, 4, 8, 12]
    assert [i for i, c in enumerate(snare) if c in 'Xx'] == [4, 12]


def test_melody_readback(proj):
    txt = api.analyze_melody(proj, source='track:bass', bars=[2, 2], fmin='C1', fmax='C5')
    notes = [l.split()[:2] for l in txt.split('\n') if l and not l.startswith('#')]
    assert notes == [['0', 'E2'], ['1', 'G2'], ['2', 'A2'], ['3', 'D3']]


def test_polyphonic_readback(proj):
    txt = api.analyze_pitches(proj, source='track:chords', bars=[1, 2], per_bar=1, max_notes=3)
    assert set(txt.split('\n')[1].split(':')[1].replace('-', ' ').split()[::2]) == {'E4', 'G4', 'B4'}
    assert set(txt.split('\n')[2].split(':')[1].replace('-', ' ').split()[::2]) == {'D4', 'F#4', 'A4'}


def test_self_alignment(proj):
    txt = api.align(proj, a='track:drums', b='track:drums')
    assert '+0.0 ms' in txt or '-0.0 ms' in txt


def test_undo(proj):
    api.notes_clear(proj, 'bass', [1, 4])
    assert api.notes_read(proj, 'bass', [1, 1]) == '(no notes in range)'
    api.undo(proj)
    assert 'E2' in api.notes_read(proj, 'bass', [1, 1])


def test_errors_point_forward(proj):
    with pytest.raises(api.OpError, match='track_add'):
        api.notes_write(proj, 'nope', 1, '0 C4 1')
    with pytest.raises(api.OpError, match='duration'):
        api.notes_write(proj, 'bass', 1, '0 C4')


def test_batch_is_atomic(proj):
    before = api.notes_read(proj, 'bass', [1, 4])
    with pytest.raises(api.OpError, match='rolled back'):
        api.batch(proj, [{"op": "notes_clear", "track": "bass", "bars": [1, 4]},
                         {"op": "notes_write", "track": "missing", "bar": 1, "notes": "0 C4 1"}])
    assert api.notes_read(proj, 'bass', [1, 4]) == before


def test_sound_fit_improves(proj):
    api.sound_make(proj, 'target', {"type": "snare", "tone_hz": 150, "noise_hp": 2000}, notes='0 C1 0.5',
                   describe=False)
    out = api.OPS['instrument_fit'](proj, target='sound:target', instrument={"type": "snare"},
                                    params={"tone_hz": [80, 300], "noise_hp": [300, 6000]}, notes='0 C1 0.5', iters=40)
    d0, d1 = [float(x) for x in out.split('\n')[0].split('distance ')[1].split(' after')[0].split(' -> ')]
    assert d1 < d0 * 0.6


def _bar_db(txt, bar):
    return float([l for l in txt.split('\n') if l.split()[:1] == [str(bar)]][0].split()[1])


def test_windowed_render_uses_song_bars():
    d = tempfile.mkdtemp(prefix='ismail_test_')
    p = os.path.join(d, 'p')
    try:
        api.project_new(p, bpm=BPM, length_bars=8)
        api.track_add(p, 'bass', instrument={"type": "synth", "oscs": [{"wave": "saw"}]}, volume_db=-6)
        api.notes_write(p, 'bass', 6, "0 A2 4")  # bar 6 only: bar 5 silent, bar 6 loud
        api.render(p, bars=[5, 8], stems=True)
        for src in ('render', 'track:bass'):
            txt = api.analyze_bars(p, source=src, bars=[5, 6])
            assert _bar_db(txt, 6) > -40 and _bar_db(txt, 6) - _bar_db(txt, 5) > 30
        assert 'A' in api.analyze_spectrum(p, source='render', span=[6, 6.5])
        with pytest.raises(api.OpError, match='bars 5-8'):
            api.analyze_drums(p, source='render', bars=[2, 3])
        api.render(p)  # a full render drops the window: bar 6 is still bar 6
        assert _bar_db(api.analyze_bars(p, source='render', bars=[6, 6]), 6) > -40
        assert _bar_db(api.analyze_bars(p, source='track:bass', bars=[6, 6]), 6) > -40  # stems keep their window
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_downbeat_after_silence_is_read():
    # a kick returning on beat 1 after a silent bar must read as a hit, whatever the analysis window
    d = tempfile.mkdtemp(prefix='ismail_test_')
    p = os.path.join(d, 'p')
    try:
        api.project_new(p, bpm=BPM, length_bars=6)
        api.track_add(p, 'drums', instrument='preset:kit_basic')
        api.pattern_write(p, 'drums', 1, {"C1": "x...x...x...x..."}, repeat=2)
        api.pattern_write(p, 'drums', 4, {"C1": "x...x...x...x..."}, repeat=2)
        api.render(p)
        for bars in ([1, 5], [3, 4], [4, 4]):
            txt = api.analyze_drums(p, source='render', bars=bars)
            line = [ln for ln in txt.splitlines() if ln.startswith('bar   4')][0]
            assert line.split('low')[1].split()[0][0] in 'Xx', (bars, line)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_render_mp3(proj):
    if not (os.environ.get('ISMAIL_FFMPEG') or shutil.which('ffmpeg')):
        pytest.skip('ffmpeg not installed')
    txt = api.render(proj, bars=[1, 1], out='preview', mp3='only')
    rd = os.path.join(proj, 'renders')
    assert 'preview.mp3' in txt and os.path.getsize(os.path.join(rd, 'preview.mp3')) > 1000
    assert not os.path.exists(os.path.join(rd, 'preview.wav'))
