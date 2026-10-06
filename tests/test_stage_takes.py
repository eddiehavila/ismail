"""Takes keep what the person said while recording (their own audio, or the performance they came from), and are
found by it."""
import json
import time

import pytest

from ismail.api import OPS, OpError
from ismail.stage import perform as P
from ismail.stage import server as S
from test_stage import _get, _post, stage  # noqa: F401  (the fixture)
from test_stage_perform import _raw, _voice_wav


def _wait(port, typ, scene='room'):
    for _ in range(100):
        got = [e for e in _get(port, f'live/events?scene={scene}&limit=500')[1]['events'] if e['type'] == typ]
        if got:
            return got
        time.sleep(0.05)
    raise AssertionError(f'no {typ} event')


def _take(stage, tid, **meta):
    d = stage['scenes'] / 'room' / 'takes' / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / 'meta.json').write_text(json.dumps({'id': tid, **meta}), encoding='utf-8')
    return d


def test_a_takes_audio_is_transcribed_when_it_lands(stage, monkeypatch, tmp_path):
    port = stage['port']
    wav = tmp_path / 'v.wav'
    _voice_wav(wav)                       # voice from 0.8 to 1.4 s
    monkeypatch.setattr(S, 'stt_words', lambda a, n: {'text': 'bartender take three', 'words': [
        {'word': 'bartender', 'start': 0.3, 'end': 1.0}, {'word': 'take', 'start': 1.0, 'end': 1.2}, {'word': 'three', 'start': 1.2, 'end': 1.8}]})
    _take(stage, '20261005_174800_person_bartender', name='person_bartender', seconds=12.0)
    _raw(port, 'voice/in?scene=room&kind=take&take=20261005_174800_person_bartender&seconds=12', wav.read_bytes(), 'audio/wav')
    ev = _wait(port, 'take_voice')[-1]
    assert ev['take'] == '20261005_174800_person_bartender' and ev['text'] == 'bartender take three'
    assert ev['words'][0][1] == pytest.approx(0.8 - P.MARGIN_S, abs=0.03)       # snapped onto the voice
    v = json.loads((stage['scenes'] / 'room' / 'takes' / '20261005_174800_person_bartender' / 'voice.json').read_text(encoding='utf-8'))
    assert v['file'] == 'audio.wav' and v['voice'] == pytest.approx([0.8, 1.4], abs=0.03)
    out = OPS['stage_takes'](scene='room', query='three')
    assert '20261005_174800_person_bartender' in out and 'said: "bartender take three"' in out and 'three@' in out


def test_a_take_from_a_follow_carries_its_performances_words(stage):
    sd = stage['scenes'] / 'room'
    perf = sd / 'performances' / 'p1'
    perf.mkdir(parents=True)
    (perf / 'perf.json').write_text(json.dumps({'clips': [
        {'n': 1, 'at': 1.0, 'words': [{'word': 'before', 'start': 0.0, 'end': 0.3}]},
        {'n': 2, 'at': 5.0, 'words': [{'word': 'glass', 'start': 0.5, 'end': 0.9}, {'word': 'up', 'start': 1.0, 'end': 1.2}]}]}),
        encoding='utf-8')
    _take(stage, '20261005_175000_sam', name='person_bar_lean', **{'for': 'person_bar_lean'}, kept=True,
          performance='p1', perf_shift=3.0, seconds=10.0)
    out = OPS['stage_takes'](scene='room', query='glass', kept=True)
    # Follow clock 5.5 s is 2.5 s into the take (it began 3 s into the Follow); "before" fell before the take
    assert 'glass@2.5s' in out and 'said: "glass up"' in out and 'KEPT' in out
    assert 'no takes' in OPS['stage_takes'](scene='room', query='before')


def test_takes_are_named_noted_and_filtered(stage, monkeypatch, tmp_path):
    _take(stage, '20261005_175100_a', name='cyrus', seconds=4.0)
    _take(stage, '20261005_175200_b', name='lucy', seconds=6.0, kept=True)
    out = OPS['stage_take_note'](scene='room', take='20261005_175100_a', label='cyrus nod', note='too fast at the end', at=3.2, sender='crossroads film')
    assert "label 'cyrus nod', 1 notes" in out
    lst = OPS['stage_takes'](scene='room')
    assert lst.index('20261005_175200_b') < lst.index('20261005_175100_a')          # newest first
    assert '[cyrus nod]' in lst and 'note @3.2s (crossroads film): too fast at the end' in lst
    assert '20261005_175100_a' in OPS['stage_takes'](scene='room', query='too fast')
    assert '20261005_175200_b' not in OPS['stage_takes'](scene='room', person='cyrus')
    assert '20261005_175100_a' not in OPS['stage_takes'](scene='room', kept=True)
    with pytest.raises(OpError, match='no take'):
        OPS['stage_take_note'](scene='room', take='nope', note='x')
    with pytest.raises(OpError, match='label= and/or note='):
        OPS['stage_take_note'](scene='room', take='20261005_175100_a')
    # an older take with audio and no words yet
    d = _take(stage, '20261005_170000_old', name='cyrus', seconds=2.0)
    wav = tmp_path / 'v.wav'
    _voice_wav(wav)
    (d / 'audio.wav').write_bytes(wav.read_bytes())
    monkeypatch.setattr(S, 'stt_words', lambda a, n: {'text': 'old one', 'words': [{'word': 'old', 'start': 0.8, 'end': 1.0}, {'word': 'one', 'start': 1.0, 'end': 1.4}]})
    assert '"old one" (2 words)' in OPS['stage_take_transcribe'](scene='room', take='20261005_170000_old')
    with pytest.raises(OpError, match='no audio'):
        OPS['stage_take_transcribe'](scene='room', take='20261005_175200_b')
