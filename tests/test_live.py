"""Live engine: queue rules (pure) and a headless engine driven block by block (inline renders, no device)."""
import numpy as np
import pytest

from ismail.dsp import SR
from ismail.live.engine import BLOCK, Engine, LiveError
from ismail.live.safety import Safety
from ismail.live.timeline import QueueError, Timeline


# ------------------------------------------------------------------ timeline

def test_quantized_launch_and_bump():
    tl = Timeline(4)
    assert tl.resolve_at('next_bar', 5.0, 5.0) == (8.0, None)
    assert tl.resolve_at('next_4', 5.0, 5.0)[0] == 16.0
    assert tl.resolve_at('next_beat', 5.2, 5.2)[0] == 6.0
    beat, note = tl.resolve_at('next_bar', 7.5, 9.0)      # render needs until beat 9: next bar is too soon
    assert beat == 12.0 and 'moved' in note
    with pytest.raises(QueueError, match='already played'):
        tl.resolve_at('bar:2', 9.0, 9.0)


def test_replace_rule_cuts_and_removes():
    tl = Timeline(4)
    a = tl.add('bass', [(0, 40, 1, 100)], 4, None, 0.0, 'next_bar')
    b = tl.add('bass', [(0, 43, 1, 100)], 4, 2, 16.0, 'bar:5')
    removed, cut = tl.claim('bass', 8.0)
    assert removed == [b.id] and cut == [a.id] and a.end == 8.0


def test_after_needs_finite_clip():
    tl = Timeline(4)
    a = tl.add('x', [(0, 60, 1, 100)], 4, None, 0.0, 'next_bar')
    with pytest.raises(QueueError, match='forever'):
        tl.resolve_at(f'after:{a.id}', 0.0, 0.0)
    b = tl.add('y', [(0, 60, 1, 100)], 4, 3, 4.0, 'next_bar')
    assert tl.resolve_at(f'after:{b.id}', 0.0, 0.0)[0] == 16.0


def test_events_stop_at_cut():
    tl = Timeline(4)
    c = tl.add('x', [(0, 60, 1, 100), (2, 62, 1, 100)], 4, None, 4.0, 'next_bar')
    c.cut = 10.0
    ev = list(tl.events(c, 0.0, 100.0, [[0], [1]]))
    assert [on for _, _, on in ev] == [4.0, 6.0, 8.0]


# ------------------------------------------------------------------ safety

def test_safety_holds_the_ceiling_and_caps_loudness():
    s = Safety(SR)
    x = np.random.default_rng(0).standard_normal((2, BLOCK * 400)) * 3.0     # far too hot
    y = np.concatenate([s.process(x[:, i:i + BLOCK]) for i in range(0, x.shape[1], BLOCK)], axis=1)
    assert np.max(np.abs(y)) <= 10 ** (s.ceiling_db / 20) + 1e-9
    tail = y[:, -SR:]
    assert 10 * np.log10(np.mean(tail ** 2)) < s.cap_db + 3
    y2 = s.process(np.full((2, BLOCK), np.nan))
    assert np.all(np.isfinite(y2)) and s.bad_blocks == 1


# ------------------------------------------------------------------ headless engine

def run(eng, seconds):
    for _ in range(int(seconds * SR / BLOCK)):
        eng.tick()
        eng.mix_block()


def onset_times(eng, thresh=0.02, gap=0.3):
    """Sample indices where the air log crosses up through `thresh` (first sample of each hit)."""
    y = np.abs(eng.air[0, :eng.pos])
    above = y > thresh
    idx = np.nonzero(above[1:] & ~above[:-1])[0] + 1
    keep = []
    for i in idx:
        if not keep or i - keep[-1] > SR * gap:
            keep.append(i)
    return keep


@pytest.fixture
def eng(tmp_path):
    return Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')


def test_clip_lands_on_the_grid_and_loops(eng):
    eng.cmd_track('k', instrument={'type': 'kick'})
    out = eng.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...x...x...x...'}, 'at': 'next_bar'}])
    assert 'c1 k: bar 2' in out
    run(eng, 6.0)                                  # bars 1-3 at 120 BPM (2 s per bar)
    hits = onset_times(eng)
    beat = 0.5 * SR
    assert len(hits) >= 7
    assert abs(hits[0] - 4 * beat) < 0.001 * SR    # bar 2 = beat 4, to the millisecond
    assert all(abs((h - hits[0]) / beat - round((h - hits[0]) / beat)) < 0.02 for h in hits)


def test_replace_and_stop(eng):
    eng.cmd_track('k', instrument={'type': 'kick'})
    eng.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...x...x...x...'}}])
    run(eng, 2.5)
    out = eng.cmd_queue([{'track': 'k', 'stop': True, 'at': 'next_bar'}])
    assert 'stop k at bar 3' in out and 'cuts c1' in out
    run(eng, 4.0)
    y = eng.air[0, :eng.pos]
    bar3 = int(4.0 * SR)
    assert np.max(np.abs(y[bar3 + int(0.5 * SR):])) < 1e-3     # bar 3 on: only the last kick's tail, then silence


def test_batch_is_atomic_and_errors_point_forward(eng):
    eng.cmd_track('k', instrument={'type': 'kick'})
    with pytest.raises(LiveError, match='live_track'):
        eng.cmd_queue([{'track': 'nope', 'notes': '0 C4 1'}])
    with pytest.raises(LiveError, match='Nothing was queued'):
        eng.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...'}, 'loop': 2},
                       {'track': 'k', 'lanes': {'C1': 'x.x.'}, 'at': 'after:c99'}])
    assert not eng.tl.clips
    with pytest.raises(LiveError, match='beats long'):
        eng.cmd_queue([{'track': 'k', 'notes': '5 C1 1', 'bars': 1}])


def test_arc_chain_and_runway(eng):
    eng.cmd_track('p', instrument='preset:pluck')
    out = eng.cmd_queue([{'track': 'p', 'notes': '0 C4 1; 1 E4 1; 2 G4 1', 'bars': 1, 'loop': 2},
                         {'track': 'p', 'notes': '0 A3 2', 'bars': 1, 'loop': 1, 'at': 'after:c1'},
                         {'track': 'p', 'notes': '0 F3 4', 'bars': 1, 'at': 'after:c2'}])
    assert 'c2 p: bar 4' in out and 'c3 p: bar 5' in out
    assert 'bar 5' in out.splitlines()[-1] and 'p c3 loop forever' in out
    view = eng.cmd_view(bars=6)
    assert 'c1' in view and 'c3' in view


def test_status_and_listen(eng):
    eng.cmd_track('k', instrument={'type': 'kick'}, volume_db=-3)
    eng.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...x...x...x...'}}])
    run(eng, 5.0)
    st = eng.cmd_status()
    assert 'playing c1' in st and 'limiter' in st
    d = eng.cmd_listen_dump(bars=2)
    assert d['first'] == 1 and d['last'] == 2


# ------------------------------------------------------------------ effects in the live graph

def level(eng, t0, t1):
    """RMS dBFS of the air log between song seconds t0 and t1."""
    y = eng.air[:, int(t0 * SR):int(t1 * SR)]
    return 10 * np.log10(np.mean(y ** 2) + 1e-20)


def test_delay_echo_lands_on_the_grid(eng):
    eng.cmd_track('k', instrument={'type': 'hat'}, fx=[{'type': 'delay', 'time_beats': 0.5, 'feedback': 0.0,
                                                                'mix': 0.5, 'hp_hz': None}])
    eng.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...............'}, 'loop': 1}])
    run(eng, 4.5)
    hits = onset_times(eng, thresh=0.005, gap=0.1)
    beat = 0.5 * SR
    assert abs(hits[0] - 4 * beat) < 0.001 * SR          # dry hit at bar 2
    assert abs(hits[1] - 4.5 * beat) < 0.001 * SR        # its echo half a beat later


def test_lookahead_tracks_stay_aligned(eng):
    eng.cmd_track('a', instrument={'type': 'kick'}, fx=[{'type': 'limiter', 'lookahead_ms': 5}, {'type': 'hall', 'mix': 0.0}])
    eng.cmd_track('b', instrument={'type': 'kick'}, pan=1.0)
    eng.cmd_track('a', pan=-1.0)
    eng.cmd_queue([{'track': 'a', 'lanes': {'C1': 'x...'}, 'loop': 1}, {'track': 'b', 'lanes': {'C1': 'x...'}, 'loop': 1}])
    run(eng, 3.0)
    left = np.nonzero(np.abs(eng.air[0, :eng.pos]) > 0.01)[0][0]
    right = np.nonzero(np.abs(eng.air[1, :eng.pos]) > 0.01)[0][0]
    assert abs(int(left) - int(right)) <= 2 and abs(left - 2 * SR) < 0.001 * SR


def test_chain_swap_lets_the_reverb_ring_out(eng):
    eng.cmd_track('p', instrument='preset:pluck', fx=[{'type': 'reverb', 'size': 0.95, 'mix': 0.6}])
    eng.cmd_queue([{'track': 'p', 'notes': '0 C4 0.25', 'loop': 1}])
    run(eng, 2.6)                                            # note at 2.0 s (bar 2)
    eng.cmd_track('p', fx=[], at='now')                      # dry from now on
    run(eng, 1.0)
    assert level(eng, 2.7, 3.0) > -60                        # the old chain's tail is still sounding


def test_send_bus_and_param_ramp(eng):
    eng.cmd_bus('verb', fx=[{'type': 'hall', 'rt60': 1.5, 'mix': 1.0}])
    eng.cmd_track('p', instrument='preset:pluck', sends={'verb': 0}, fx=[{'type': 'gain', 'gain_db': 0}])
    eng.cmd_queue([{'track': 'p', 'notes': '0 C4 0.25; 2 E4 0.25', 'bars': 1}])
    run(eng, 4.2)
    st = eng.cmd_status()
    assert 'bus verb' in st and 'hall' in st and 'fed by p' in st
    before = level(eng, 3.0, 4.0)
    out = eng.cmd_fx('p', 0, {'gain_db': -30}, ramp_beats=1)
    assert '0 -> -30' in out
    run(eng, 2.5)
    assert level(eng, 5.9, 6.4) < before - 12              # ramped down (the hall still carries a little)


def test_duck_on_source_notes(eng):
    eng.cmd_track('k', instrument={'type': 'kick'}, volume_db=-40)
    eng.cmd_track('pad', instrument='preset:pad', fx=[{'type': 'duck', 'source': 'k', 'depth_db': -24,
                                                       'release_ms': 250}])
    eng.cmd_queue([{'track': 'pad', 'notes': '0 C4 4', 'bars': 1}, {'track': 'k', 'lanes': {'C1': 'x...'}}])
    run(eng, 5.0)
    on = level(eng, 4.0 + 0.01, 4.0 + 0.06)                 # just after a kick (bar 3)
    off = level(eng, 4.0 + 0.35, 4.0 + 0.45)                # recovered
    assert off - on > 10


def test_graph_errors_point_forward(eng):
    eng.cmd_track('k', instrument={'type': 'kick'})
    with pytest.raises(LiveError, match='live_bus first'):
        eng.cmd_track('k', sends={'nope': -6})
    with pytest.raises(LiveError, match='not a live track'):
        eng.cmd_track('k', fx=[{'type': 'compressor', 'sidechain': 'ghost'}])
    with pytest.raises(LiveError, match='itself'):
        eng.cmd_track('k', fx=[{'type': 'duck', 'source': 'k'}])
    with pytest.raises(LiveError, match='budget'):
        eng.cmd_track('k', fx=[{'type': 'limiter', 'lookahead_ms': 200}])
    eng.cmd_track('s', instrument={'type': 'snare'}, fx=[{'type': 'compressor', 'sidechain': 'k'}])
    with pytest.raises(LiveError, match='loop'):
        eng.cmd_track('k', fx=[{'type': 'compressor', 'sidechain': 's'}])
    with pytest.raises(LiveError, match='valid'):
        eng.cmd_fx('s', 0, {'nonsense': 1})
    with pytest.raises(LiveError, match='out of range'):
        eng.cmd_fx('s', 3, {'mix': 1})
