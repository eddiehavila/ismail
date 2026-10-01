"""Live engine quality of life, from a one-hour set: one `at` vocabulary, sweeps on a scheduled chain, a chain
swap that drops only the old chain's sweeps, clearing scheduled moves, problems said in the next reply, levels
held over 10 s, a stalled device named, other engines found, and a stop that cannot hang."""
import json
import os
import subprocess
import sys
import time

import pytest

from ismail.dsp import SR
from ismail.live.engine import BLOCK, Engine, LiveError
from ismail.live.graph import Ramp, Schedule


def run(eng, seconds):
    for _ in range(int(seconds * SR / BLOCK)):
        eng.tick()
        eng.mix_block()


@pytest.fixture
def eng(tmp_path):
    return Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')


def test_now_and_asap_mean_the_same_everywhere(eng):
    eng.cmd_track('p', instrument='preset:pad', fx=[{'type': 'gain', 'gain_db': 0}])
    eng.cmd_track('p', fx=[{'type': 'gain', 'gain_db': -3}], at='asap')     # live_fx's word on live_track
    eng.cmd_track('p', fx=[{'type': 'gain', 'gain_db': -3}], at='now')
    assert 'gain_db' in eng.cmd_fx('p', 0, {'gain_db': -6}, at='asap')     # live_track's word on live_fx
    out = eng.cmd_queue([{'track': 'p', 'notes': '0 C4 1', 'at': 'now'}])
    assert 'c1 p' in out


def test_sweep_targets_a_scheduled_chain(eng):
    eng.cmd_track('p', instrument='preset:pad', fx=[{'type': 'gain', 'gain_db': 0}])
    eng.cmd_track('p', fx=[{'type': 'gain', 'gain_db': 0}, {'type': 'filter', 'cutoff': 8000}], at='bar:3')
    with pytest.raises(LiveError, match='out of range'):
        eng.cmd_fx('p', 1, {'cutoff': 500}, at='bar:2')                     # the old chain has one effect
    out = eng.cmd_fx('p', 1, {'cutoff': 500}, ramp_beats=4, at='bar:4')     # the new chain is live by then
    assert 'scheduled then' in out
    run(eng, 7.0)                                                            # into bar 4: swapped, sweeping
    sch = eng.ramps[('track:p', 1, 'cutoff')]
    assert eng.tracks['p']['path'].chain.fx[1]['type'] == 'filter'
    assert sch.value(eng.sample(16)) == pytest.approx(500)


def test_a_move_now_starts_where_the_param_is(eng):
    eng.cmd_track('p', instrument='preset:pad', fx=[{'type': 'filter', 'cutoff': 9000}])
    eng.cmd_fx('p', 'filter', {'cutoff': 300}, ramp_beats=8, at='bar:3')   # a sweep later on
    assert '9000 -> 2000' in eng.cmd_fx('p', 'filter', {'cutoff': 2000}, at='now')


def test_swap_drops_old_sweeps_and_keeps_volume(eng):
    eng.cmd_track('p', instrument='preset:pad', fx=[{'type': 'gain', 'gain_db': 0}])
    eng.cmd_fx('p', 0, {'gain_db': -20}, ramp_beats=4, at='bar:5')         # old choreography, after the swap
    eng.ramps[('track:p', -1, 'volume_db')] = vol = Schedule()
    vol.add(Ramp(0, 0.0, eng.sample(40), -12.0, False))                     # a loaded song's fade
    eng.cmd_track('p', fx=[{'type': 'gain', 'gain_db': 0}], at='bar:3')
    run(eng, 5.0)                                                            # past the swap at bar 3
    assert ('track:p', 0, 'gain_db') not in eng.ramps                        # it would have hit the new chain
    assert ('track:p', -1, 'volume_db') in eng.ramps                         # the fade goes on


def test_clear_holds_every_scheduled_move(eng):
    eng.cmd_track('p', instrument='preset:pad', fx=[{'type': 'gain', 'gain_db': 0},
                                                    {'type': 'filter', 'cutoff': 8000}])
    eng.cmd_fx('p', 0, {'gain_db': -20}, ramp_beats=8, at='bar:2')
    eng.cmd_fx('p', 1, {'cutoff': 300}, ramp_beats=4, at='bar:6')
    run(eng, 3.0)                                                            # half way into the gain ramp
    out = eng.cmd_fx('p', clear=True)
    assert 'cleared' in out and 'fx[0].gain_db' in out and 'fx[1].cutoff' in out
    g = eng.ramps[('track:p', 0, 'gain_db')]
    held = g.value(eng.pos)
    assert -20 < held < 0 and g.value(eng.sample(40)) == pytest.approx(held)
    assert eng.ramps[('track:p', 1, 'cutoff')].value(eng.sample(40)) == pytest.approx(8000)
    assert 'nothing scheduled' in eng.cmd_fx('p', clear=True, at='bar:30')


def test_problems_arrive_in_the_next_reply(eng, tmp_path):
    os.makedirs(tmp_path / 'voices', exist_ok=True)
    (tmp_path / 'voices' / 'loud.py').write_text(
        "import numpy as np\n\ndef voice(freq, t, vel, gate, sr):\n    return 40 * np.sin(2 * np.pi * freq * t)\n")
    eng.cmd_track('x', instrument={'type': 'code', 'voice': 'loud', 'tail': 0.1}, warm=False)
    eng.cmd_queue([{'track': 'x', 'notes': '0 C4 1', 'at': 'now'}])
    run(eng, 1.5)
    news = eng.drain_news()
    assert any('x' in n and 'dBFS' in n for n in news), news
    assert eng.drain_news() == []                                            # said once


def test_levels_hold_the_loudest_second(eng):
    eng.cmd_track('k', instrument={'type': 'kick'})
    eng.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...............'}, 'loop': 1, 'at': 'now'}])
    run(eng, 4.0)                                                            # one hit, then 3 s of tail and silence
    st = eng.cmd_status()
    line = [l for l in st.splitlines() if l.strip().startswith('k ')][0]
    now_db = float(line.split('level')[1].split('dBFS')[0])
    held = float(line.split('max 10 s')[1].split(')')[0])
    assert held > now_db + 20


def test_a_stalled_device_is_named_once(eng):
    eng.stream = object()                                                    # a device that stopped pulling
    eng.last_pull = time.time() - 5
    assert 'STALLED' in eng.cmd_status()
    assert any('STALLED' in n for n in eng.drain_news())
    assert not any('STALLED' in n for n in eng.drain_news())


def test_other_engines_are_found_and_dead_notes_dropped(tmp_path, monkeypatch):
    from ismail.live import ops
    reg = tmp_path / 'reg'
    reg.mkdir()
    monkeypatch.setenv('ISMAIL_LIVE_REGISTRY', str(reg))
    (reg / f'{os.getpid()}.json').write_text(json.dumps({'pid': os.getpid(), 'project': str(tmp_path / 'yoga'),
                                                         'device': 'default', 'started': time.time() - 7200}))
    (reg / '999999.json').write_text(json.dumps({'pid': 999999, 'project': str(tmp_path / 'gone')}))
    others = ops._other_engines(str(tmp_path / 'set'))
    assert [o['project'] for o in others] == [str(tmp_path / 'yoga')]
    assert not (reg / '999999.json').exists()
    assert ops._other_engines(str(tmp_path / 'yoga')) == []                  # not itself


def test_stop_kills_an_engine_that_does_not_answer(tmp_path):
    from ismail.live import ops
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                         start_new_session=os.name != 'nt')
    try:
        os.makedirs(tmp_path / 'live')
        (tmp_path / 'live' / 'engine.json').write_text(json.dumps({'port': 9, 'pid': p.pid}))   # nobody on port 9
        out = ops.live_stop(str(tmp_path), fade_sec=0.0)
        assert 'killed' in out and p.wait(timeout=10) is not None
        assert not (tmp_path / 'live' / 'engine.json').exists()
    finally:
        if p.poll() is None:
            p.kill()
