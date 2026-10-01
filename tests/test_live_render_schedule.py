"""Live render scheduling: renders go to the workers earliest-needed first, a render no queued clip wants is dropped
before it reaches a worker, a clip queued for later renders its first pass right away, and notes whose render came
back too late are counted and said in the next reply (a deck once lost its first 3 bars while late events read 0)."""
import numpy as np
import pytest

from ismail.dsp import SR
from ismail.live.engine import BLOCK, Engine


def run(eng, seconds):
    for _ in range(int(seconds * SR / BLOCK)):
        eng.tick()
        eng.mix_block()


class Sent(list):
    def put(self, payload):
        self.append(payload[0])


@pytest.fixture
def eng(tmp_path):
    e = Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')
    e.cmd_track('p', instrument='preset:pluck')
    return e


def as_pool(e, workers=1):
    """The headless engine, but rendering through a stub worker pool that records what it is handed."""
    e.n_workers = workers
    e._shared = Sent()
    return e._shared


def test_earliest_needed_first_and_unwanted_renders_dropped(eng):
    sent = as_pool(eng)
    eng.cmd_queue([{'track': 'p', 'notes': '0 C4 1; 4 E4 1; 8 G4 1; 12 B4 1', 'bars': 4, 'at': 'bar:3'}])
    eng.tick()
    order = [eng.jobs[j]['key'][3][0][1] for j in sent]
    assert order == sorted(order) and len(sent) == 2               # pitches in onset order, 2 per worker
    cid = next(iter(eng.tl.clips))
    eng.cmd_cancel([cid])
    for j in list(sent):                                           # the two in flight come back
        eng._result(j, None, 0.01, 'cancelled test')
    assert len(sent) == 2 and eng.stats['skipped'] == 2            # the other two never reach a worker


def test_a_clip_queued_ahead_renders_its_first_pass_now(eng):
    sent = as_pool(eng, workers=8)
    eng.cmd_queue([{'track': 'p', 'notes': '0 C4 1; 12 E4 1', 'bars': 4, 'at': 'bar:20'}])   # bar 20 = 38 s away
    eng.tick()
    assert len(sent) == 2                                           # both notes, well before the 8 s horizon


def test_notes_lost_to_a_late_render_are_said(eng):
    as_pool(eng)
    eng.cmd_queue([{'track': 'p', 'notes': '0 C4 1', 'bars': 1, 'loop': 1, 'at': 'bar:2'}])
    run(eng, 5.0)                                                   # the render never comes back; the clip ends
    news = eng.drain_news()
    assert any('never sounded' in n and 'p' in n for n in news), news
    assert eng.stats['lost'] >= 1 and 'never sounded 1' in eng.cmd_status()


def test_a_deck_loaded_on_air_waits_off_air_for_its_renders(tmp_path):
    from ismail import api
    song = str(tmp_path / 'song')
    api.project_new(song, bpm=120, length_bars=4)
    api.track_add(song, 'p', instrument='preset:pluck')
    api.notes_write(song, 'p', 1, '0 C4 1; 4 E4 1; 8 G4 1; 12 B4 1')
    e = Engine(str(tmp_path / 'eng'), bpm=120, bpb=4, workers=0, device='none')
    sent = as_pool(e)
    e._tasks, e._procs = [Sent()], [{'out': 0}]
    r = e.cmd_load('A', song, at='bar:2', loop=False)
    assert 'once its first bar is rendered' in r and e.decks['A'].held
    run(e, 2.5)                                                     # bar 2 starts at 2 s with nothing rendered
    assert e.decks['A'].cue and e.decks['A'].held[0] == 8          # still off air, now waiting for bar 3
    assert any('held off air' in n for n in e.drain_news())
    while sent:                                                     # the renders come back
        e._result(sent.pop(0), np.full((2, 64), 0.1, np.float32), 0.01, None)
    run(e, 2.0)
    assert not e.decks['A'].cue and e.decks['A'].held is None
    assert any('on air from bar 3' in n for n in e.drain_news())


def test_a_big_queue_is_placed_over_several_passes_each_event_once(tmp_path):
    from ismail.live.engine import TICK_EVENTS
    e = Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')
    e.cmd_track('p', instrument='preset:pluck')
    # 600 events in threes: 128 per pass would cut inside a chord, so the cut moves back to the chord's start
    notes = '; '.join(f"{k * 0.25:g} C4 0.1; {k * 0.25:g} E4 0.1; {k * 0.25:g} G4 0.1" for k in range(200))
    passes = []
    orig = e._place

    def place(cid, track, on, y):
        passes[-1].append(on)
        return orig(cid, track, on, y)
    e._place = place
    passes.append([])
    e.cmd_queue([{'track': 'p', 'notes': notes, 'beats': 50, 'loop': 1, 'at': 'bar:2'}])
    for _ in range(8):
        passes.append([])
        e.tick()
    sizes = [len(p) for p in passes if p]
    assert max(sizes) <= TICK_EVENTS and len(sizes) >= 3            # spread over passes, none over the cap
    placed = sorted(on for p in passes for on in p)
    assert len(placed) == 600 and all(placed.count(on) == 3 for on in set(placed))   # each event once
