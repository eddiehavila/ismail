"""A new person's first session (M110): guide notices someone who has made nothing yet, sketch gives them sound
in minutes on the measured voices, and keeping a sketch makes it the song and ends the first session (2026-10-05:
a creative-AI founder found ismail "good at doing covers but hard to make a new song")."""
import json
import os

import pytest

from ismail import api, handoffs, machine
from ismail import sketch as SK
from ismail.api import OpError


@pytest.fixture(autouse=True)
def cool(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_MACHINE_DIR', str(tmp_path / 'board'))
    monkeypatch.setattr(machine, 'gpu', lambda: None)
    monkeypatch.setattr(machine, 'memory', lambda: (40.0, 70.0, 30.0))
    monkeypatch.setattr(machine, 'cpu_load', lambda: (12.0, []))
    monkeypatch.setattr(machine, 'disks', lambda *a: [], raising=False)
    monkeypatch.setenv('ISMAIL_FIRST_SESSION', str(tmp_path / 'home' / 'first_session_done'))
    monkeypatch.setattr(handoffs, 'SONGS', str(tmp_path / 'songs'))
    (tmp_path / 'songs').mkdir()


def test_a_sketch_is_a_tune_not_block_chords():
    pl = SK.plan('a quiet song for a rainy morning', 'piano')
    assert pl['key'] == 'A minor' and pl['bars'] % 4 == 0
    mel = pl['parts']['melody']['notes']
    assert sum(1 for n in mel if n[1] != 0) > len(mel) / 2          # most notes off beat 1
    assert mel[-1][0] == pl['bars'] - 1 and mel[-1][2] % 12 == 9 and mel[-1][3] == 4   # home, held
    lo, hi = SK.STYLES['piano']['parts']['melody'][1]
    assert all(lo <= n[2] <= hi for n in mel)
    first = [n[2] for n in mel if n[0] < 4]
    second = [n[2] for n in mel if 4 <= n[0] < 8]
    assert first != second                                            # the second phrase moves
    assert SK.plan('bright and happy', 'band')['key'] == 'C major'
    assert SK.chord('V', 9, 'minor')[1] == [4, 8, 11]                 # E G# B in A minor
    assert SK.chord('F#m', 0, 'major')[1] == [6, 9, 1]
    assert SK.parse_key('Eb major') == (3, 'major') and SK.parse_key('c#m') == (1, 'minor')
    with pytest.raises(SK.SketchError):
        SK.parse_key('H dorian')


def test_guide_opens_with_the_first_session_only_for_someone_new(tmp_path):
    g = api.guide()
    assert g.startswith('FIRST SESSION') and 'sketch(project' in g and 'violin' in g and 'never required' in g
    r = tmp_path / 'songs' / 'old' / 'renders'
    r.mkdir(parents=True)
    (r / 'latest.wav').write_bytes(b'')
    assert not api.guide().startswith('FIRST SESSION')
    (r / 'latest.wav').unlink()
    SK.mark_done()
    assert not api.guide().startswith('FIRST SESSION')
    assert '*violin' in api.voices_list() and '*kit70' in api.voices_list() and '* showcase' in api.voices_list()


def test_sketch_then_keep_makes_the_song_and_ends_the_first_session(tmp_path):
    song = str(tmp_path / 'songs' / 'rain')
    out = api.sketch(song, 'a quiet song for a rainy morning', styles=['piano'], bars=4)
    assert 'a) solo piano' in out and 'sketch_keep' in out
    sp = os.path.join(song, 'sketches', 'a-piano')
    rendered = os.listdir(os.path.join(sp, 'renders'))
    assert any(f.startswith('sketch_a.') for f in rendered)
    assert api.guide().startswith('FIRST SESSION')                   # a sketch is not a finished song
    out = api.sketch(song, 'slower, with strings', styles='piano', bars=4)
    assert 'b) solo piano' in out                                     # a second round adds letters
    with pytest.raises(OpError) as e:
        api.sketch_keep(song, 'z')
    assert 'a-piano' in str(e.value)
    out = api.sketch_keep(song, 'a')
    assert 'First session marked done' in out and 'change just one thing' in out
    with open(os.path.join(song, 'project.json'), encoding='utf8') as f:
        d = json.load(f)
    assert set(d['tracks']) == {'melody', 'harmony'} and d['name'] == 'rain' and d['lineage'][0]['project'] == sp
    assert d['objectives'][0]['text'] == 'a quiet song for a rainy morning'
    assert not api.guide().startswith('FIRST SESSION')
    with pytest.raises(OpError) as e:
        api.sketch_keep(song, 'b')
    assert 'replace=True' in str(e.value)
    assert 'b-piano' in api.sketch_keep(song, 'b', replace=True)
    with pytest.raises(OpError):
        api.sketch(song, 'x', styles=['opera'])
