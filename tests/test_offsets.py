"""Placement offsets (ledger M8): a track's offset_ms and a note's @offset move a sound off its beat by milliseconds,
so a sound whose attack comes late can start early and land its attack on the beat (tambopata, 2026-10-02: phrases
were time-warped to fake this and the player sounded "synthy"). A nudged note is the same as a note written at its
nudged time, in the studio, in any window and on a deck."""
import json
import os

import numpy as np
import pytest

from ismail import api, machine, notation
from ismail.api import OpError
from ismail.live import parity
from ismail.render import Renderer

BPM = 120                       # 1 beat = 500 ms, so 40 ms = 0.08 beat


@pytest.fixture(autouse=True)
def cool(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_MACHINE_DIR', str(tmp_path / 'board'))
    monkeypatch.setattr(machine, 'gpu', lambda: None)
    monkeypatch.setattr(machine, 'memory', lambda: (40.0, 70.0, 30.0))
    monkeypatch.setattr(machine, 'cpu_load', lambda: (12.0, []))


def proj(root, inst='preset:pluck', bars=4):
    api.project_new(root, bpm=BPM, length_bars=bars)
    api.track_add(root, 'p', instrument=inst)
    return root


def mix(root, bars=None):
    R = Renderer(json.load(open(os.path.join(root, 'project.json'), encoding='utf8')), root,
                 bars[0] if bars else None, (bars[1] + 1) if bars else None, cache=False)
    y, _ = R.run()
    return y, R


def onset(y, thr=1e-3):
    return int(np.argmax(np.abs(y).max(0) > thr))


def test_the_text_form_reads_and_writes_back(tmp_path):
    r = proj(str(tmp_path / 's'))
    api.notes_write(r, 'p', 2, '0 C4 1 100 @-40ms; 1 E4 1 90 @+12.5ms; 2 G4 1')
    assert api.notes_read(r, 'p', [2, 2], view='rel') == '0 C4 1 100 @-40ms\n1 E4 1 90 @+12.5ms\n2 G4 1 100'
    assert 'v=100 @-40ms' in api.notes_read(r, 'p', [2, 2])
    stored = json.load(open(os.path.join(r, 'project.json'), encoding='utf8'))['tracks']['p']['notes']
    assert stored == [[4, 60, 1.0, 100, -40.0], [5, 64, 1.0, 90, 12.5], [6, 67, 1.0, 100]]
    api.notes_write(r, 'p', 3, api.notes_read(r, 'p', [2, 2], view='rel'))        # read -> write back: the same
    again = json.load(open(os.path.join(r, 'project.json'), encoding='utf8'))['tracks']['p']['notes']
    assert [n[1:] for n in again[3:]] == [n[1:] for n in stored]
    assert api.notes_read(r, 'p', [2, 2], view='roll').split('\n')[-1].startswith('  C4 #')  # roll on the grid
    for bad, msg in (('0 C4 1 @-40s', 'milliseconds'), ('0 C4 1 @-5000ms', 'at most'), ('0 C4 1 @1 @2', 'one @offset')):
        with pytest.raises(OpError, match=msg):
            api.notes_write(r, 'p', 1, bad)
    with pytest.raises(OpError, match='not read here'):
        api.sound_make(r, 'x', 'preset:pluck', notes='0 C4 1 @-10ms')


def test_a_nudged_note_is_a_note_written_at_its_nudged_time(tmp_path):
    a = proj(str(tmp_path / 'a'))
    api.notes_write(a, 'p', 2, '1 C4 1 100 @-40ms')
    b = proj(str(tmp_path / 'b'))
    api.notes_write(b, 'p', 2, '0.92 C4 1 100')
    ya, _ = mix(a)
    yb, _ = mix(b)
    assert np.max(np.abs(ya - yb)) < 1e-9
    c = proj(str(tmp_path / 'c'))
    api.notes_write(c, 'p', 2, '1 C4 1 100')
    yc, _ = mix(c)
    assert onset(yc) - onset(ya) == pytest.approx(0.040 * 44100, abs=2)


def test_a_track_offset_moves_every_sound_and_keeps_the_notes_on_the_grid(tmp_path):
    r = proj(str(tmp_path / 's'))
    api.notes_write(r, 'p', 2, '0 C4 1 100 @-10ms; 2 E4 1')
    y0, _ = mix(r)
    api.track_set(r, 'p', offset_ms=-25)
    assert '| offset -25 ms' in api.project_info(r) and '1 notes nudged' in api.project_info(r)
    assert api.notes_read(r, 'p', [2, 2]).startswith('(track offset -25 ms')
    assert 'bar   2 +0' in api.notes_read(r, 'p', [2, 2])
    y1, _ = mix(r)
    assert onset(y0) - onset(y1) == pytest.approx(0.025 * 44100, abs=4)             # the two add up per note
    api.track_set(r, 'p', offset_ms=0)
    assert 'offset_ms' not in json.load(open(os.path.join(r, 'project.json'), encoding='utf8'))['tracks']['p']
    with pytest.raises(OpError, match='at most'):
        api.track_set(r, 'p', offset_ms=-3000)


def test_editing_keeps_a_nudge_and_can_set_it(tmp_path):
    r = proj(str(tmp_path / 's'))
    api.notes_write(r, 'p', 2, '0.03 C4 1 100 @-40ms; 1 E4 1')
    api.notes_transform(r, 'p', [2, 2], quantize=0.25)
    assert api.notes_read(r, 'p', [2, 2], view='rel').split('\n')[0] == '0 C4 1 100 @-40ms'
    api.notes_copy(r, 'p', [2, 2], 3)
    assert '@-40ms' in api.notes_read(r, 'p', [3, 3], view='rel')
    api.notes_transform(r, 'p', [3, 3], offset_ms=-15, pitches=['E4'])
    assert api.notes_read(r, 'p', [3, 3], view='rel') == '0 C4 1 100 @-40ms\n1 E4 1 100 @-15ms'
    api.notes_transform(r, 'p', [3, 3], offset_ms=0)
    assert '@' not in api.notes_read(r, 'p', [3, 3], view='rel')


def test_a_window_renders_a_nudged_note_as_the_whole_song_does(tmp_path):
    r = proj(str(tmp_path / 's'), bars=6)
    # bar 4's first note sounds 120 ms early, inside bar 3: a window of bars 2-3 must still have it
    api.notes_write(r, 'p', 2, '0 C4 0.5 100; 3.5 E4 0.25 90; 0 G4 0.5 100 @-120ms', bars=1)
    api.notes_write(r, 'p', 4, '0 G4 1 100 @-120ms')
    p = os.path.join(r, 'project.json')
    d = json.load(open(p, encoding='utf8'))
    d['master']['fx'] = []                       # a limiter's state depends on where a render starts
    json.dump(d, open(p, 'w', encoding='utf8'))
    full, _ = mix(r)
    win, W = mix(r, [2, 3])                      # run() returns the window from its first beat, pre-roll cropped
    a = int(round((W.offset + W.win_b0 * W.spb) * 44100))
    n = int(round(2 * 4 * W.spb * 44100))
    assert np.max(np.abs(win[:, :n] - full[:, a:a + n])) < 1e-6
    assert np.max(np.abs(full[:, a + n - 6000:a + n])) > 1e-3       # the nudged note does sound in bar 3's end


def test_a_note_nudged_before_the_song_starts_at_zero_and_says_so(tmp_path):
    r = proj(str(tmp_path / 's'))
    api.notes_write(r, 'p', 1, '0 C4 1 100 @-50ms')
    out = api.render(r)
    assert '1 nudged notes would sound before 0 s' in out and 'offset_sec' in out


@pytest.mark.parametrize('inst', ['preset:pluck', 'preset:kick', {'type': 'mimic', 'profile': 'cello'}])
def test_a_deck_plays_nudged_notes_where_the_studio_does(tmp_path, inst):
    r = proj(str(tmp_path / 's'), inst=inst)
    api.notes_write(r, 'p', 2, '0 C3 0.5 100 @-30ms; 1 E3 0.5 90 @+20ms; 2 G3 1 100; 3 C4 0.5 80 @-45ms', repeat=3)
    api.track_set(r, 'p', offset_ms=-12)
    res, _, _ = parity.run(r, [2, 3])
    assert parity.verdict(res['track:p']) == 'ok' and res['track:p']['resid_db'] < -80, res['track:p']


def test_live_clip_text_reads_offsets_the_same_way():
    ns = notation.with_offsets(notation.parse_notes('1 C4 1 100 @-40ms; 2 D4 1', offsets=True), BPM)
    assert ns == [(pytest.approx(0.92), 60, 1.0, 100), (2.0, 62, 1.0, 100)]
