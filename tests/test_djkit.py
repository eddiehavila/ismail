"""The DJ kit: pure note and move builders, and moves sent in one call to a headless engine."""
import pytest

from ismail.live import djkit as K
from ismail.live.engine import Engine, LiveError


def test_steps_per_bar_and_notes_on_another_grid():
    s = K.steps('X...x... o...g...', pitch='C1', swing=0.05, seed=1)
    assert [round(t, 3) for t, *_ in s] == [0.0, 1.0, 2.0, 3.0]
    assert s[0][3] > s[1][3] > s[2][3] > s[3][3]                      # X > x > o > g
    assert K.steps('.x', swing=0.05)[0][0] == pytest.approx(0.30)     # the second step is swung
    cyc = K.per_bar(4, lambda b: [] if b == 2 else [(0, 'C1', 0.1, 100)])
    assert [t for t, *_ in cyc] == [0, 4, 12]                          # bar 2 is the break
    r = K.metric(126, 84)
    assert r == pytest.approx(2 / 3) and K.clip_bars(36, r) == pytest.approx(24)
    assert K.notes([(3, 'D3', 1.5, 90)], ratio=r) == '2.0000 D3 1.0000 90'
    with pytest.raises(ValueError):
        K.steps('Xz')


def test_moves_are_live_fx_calls():
    g = K.gap(['kick', 'bass'], bar=33)
    assert g[0] == {'target': 'kick', 'index': 'gain', 'params': {'gain_db': -60}, 'ramp_beats': 0,
                    'at': 'bar:32.6667'}
    assert g[1]['at'] == 'bar:33' and len(g) == 4
    t = K.throw('stab', at=16.5, hold_beats=2)
    assert t[0]['params'] == {'mix': 0.5} and t[1]['at'] == 'bar:17' and t[1]['ramp_beats'] == 4
    assert K.with_gain([{'type': 'delay'}])[0]['type'] == 'gain'


def test_engine_takes_a_choreography_in_one_call(tmp_path):
    eng = Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')
    eng.cmd_track('pad', instrument='preset:pad',
                  fx=K.with_gain([{'type': 'filter', 'cutoff': 8000}, {'type': 'delay', 'mix': 0.1}]))
    out = eng.cmd_moves(K.gap(['pad'], bar=9) + K.throw('pad', at=6) +
                        [K.sweep('pad', 'filter', 'cutoff', 400, 16, at=2)])
    assert out.startswith('5 moves scheduled')
    assert ('track:pad', 2, 'mix') in eng.ramps and ('track:pad', 1, 'cutoff') in eng.ramps
    with pytest.raises(LiveError, match=r"move \[1\].*1 moves before it"):
        eng.cmd_moves([K.sweep('pad', 'filter', 'cutoff', 500, 4, at=3), K.sweep('pad', 'reverb', 'mix', 1, 4, at=3)])
    with pytest.raises(LiveError, match="no 'filter:2'"):
        eng.cmd_fx('pad', 'filter:2', {'cutoff': 100})
    assert 'cleared' in eng.cmd_fx('pad', 'filter', clear=True)


class FakeOps(dict):
    def __init__(self):
        super().__init__()
        self.calls = []
        st = ("live 120 BPM 4/4 | heard bar 21 (40 s)\nsafety: ok\ntracks:\n"
              "  kick       kick                   vol +0 pan +0 level  -80.0 dBFS (max 10 s  -12.5) | x | y\n"
              "  bus hall   fx hall | vol +0 | level  -40.0 dBFS (max 10 s  -30.0) | fed by kick")
        self['live_status'] = lambda P: st
        self['live_queue'] = lambda P, clips: 'c7 kick: bar 25\nc8 bass: bar 25'
        self['live_cancel'] = lambda P, ids: self.calls.append(ids) or f"cancelled {ids}"
        self['live_fx'] = lambda P, *a, **kw: self.calls.append(kw) or '3 moves scheduled'


def test_set_logs_sections_levels_and_boundaries(tmp_path):
    ops = FakeOps()
    S = K.Set(str(tmp_path), ops=ops)
    S.q([{'track': 'kick', 'notes': '0 C1'}], section='s02_house')
    assert S.sections == {'s02_house': ['c7', 'c8']}
    S.cancel('s02_house')
    assert ops.calls[-1] == ['c7', 'c8']
    assert S.levels() == {'kick': (-80.0, -12.5), 'bus hall': (-40.0, -30.0)}
    assert S.next_boundary(start=5, every=8) == 29                     # heard 21 + 2 -> the cycle bar after
    S.moves([K.gap(['kick'], 29), K.sweep('kick', 'gain', 'gain_db', -6, 4, 30)])
    assert len(ops.calls[-1]['moves']) == 3
    log = (tmp_path / 'set' / 'setlog.md').read_text(encoding='utf8')
    assert 'queue [s02_house]' in log and 'moves (3)' in log
