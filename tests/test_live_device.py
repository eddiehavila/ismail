"""The live output follows the device (ledger M34): with device 'default' a set moves to a speaker that becomes the
system default (a Bluetooth speaker connecting), a device that stops taking audio falls back to the default, and
live_device moves a running set by hand, its clock carrying on. Silent: device='none' and a fake stream."""
import time

import pytest

from ismail.dsp import SR
from ismail.live import outputs as O
from ismail.live.engine import BLOCK, Engine


def run(eng, seconds):
    for _ in range(int(seconds * SR / BLOCK)):
        eng.tick()
        eng.mix_block()


@pytest.fixture
def eng(tmp_path):
    e = Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')
    e.cmd_track('k', instrument={'type': 'kick'})
    e.cmd_queue([{'track': 'k', 'lanes': {'C1': 'x...x...x...x...'}}])
    return e


class _FakeStream:
    device = 0

    def stop(self):
        pass

    def close(self):
        pass


def test_the_output_follows_a_new_default_and_recovers_a_vanished_device(eng, monkeypatch):
    opened = []

    def fake_open(device, rescan=True):
        opened.append(device)
        eng.stream, eng.out_name = _FakeStream(), {'default': 'Speakers (JBL Go 3)'}.get(device, str(device))
        eng.last_pull = time.time()
    monkeypatch.setattr(eng, '_open_output', fake_open)
    eng.device, eng.stream, eng.out_name, eng.last_pull = 'default', _FakeStream(), 'Laptop speakers', time.time()
    monkeypatch.setattr(O, 'default_output_name', lambda timeout=5.0: 'Speakers (JBL Go 3)')
    eng._check_output()
    assert opened == ['default'] and eng.out_name == 'Speakers (JBL Go 3)'
    assert any('moved from Laptop speakers to Speakers (JBL Go 3)' in x for x in eng.news)
    eng._check_output()                               # nothing changed: nothing happens
    assert opened == ['default']
    # a named device that stops taking audio falls back to the default
    eng.device, eng.out_name, eng._out_tried = 'Headphones', 'Headphones', 0.0
    eng.last_pull -= 10
    eng._check_output()
    assert opened[-1] == 'default' and eng.device == 'default'
    assert 'output Speakers (JBL Go 3) (follows the default)' in eng.cmd_status()


def test_follow_off_stays_where_it_opened(eng, monkeypatch):
    monkeypatch.setattr(eng, '_open_output', lambda device, rescan=True: pytest.fail('reopened'))
    eng.device, eng.stream, eng.out_name, eng.last_pull, eng.follow = 'default', _FakeStream(), 'Laptop', \
        time.time(), False
    monkeypatch.setattr(O, 'default_output_name', lambda timeout=5.0: 'Speakers (JBL Go 3)')
    eng._check_output()
    assert eng.out_name == 'Laptop'


def test_moving_to_no_device_and_back_keeps_the_clock(eng):
    run(eng, 0.5)
    pos = eng.pos
    out = eng.cmd_device('none')
    assert 'output: none' in out and eng.stream is None
    run(eng, 0.5)
    assert eng.pos > pos
