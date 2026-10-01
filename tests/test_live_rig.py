"""The guitar rig runs live (ismail/live/rig_blocks.py) instead of baked into each note: a chain left in silence
must not slow down (denormal floats once took a fuzz chain to 100% of real time), and a track whose amp only hisses
goes dormant like a silent one."""
import numpy as np

from ismail.dsp import SR
from ismail.live import fx_blocks as F
from ismail.live import graph as G
from ismail.live.engine import BLOCK, Engine


class Blk(F.Block):
    def __init__(self, pos, n):
        self.pos, self.n = pos, n


def test_a_rig_left_in_silence_never_reaches_denormals():
    chain = G.Chain([F.normalize({'type': 'fuzz'}), F.normalize({'type': 'amp'}), F.normalize({'type': 'cab'})],
                    120.0, 1.0)
    note = 0.3 * np.sin(2 * np.pi * 110 * np.arange(BLOCK) / SR)
    chain.process(np.stack([note, note]), lambda i: Blk(0, BLOCK))
    z = np.zeros((2, BLOCK))
    for k in range(1, 1600):                    # ~37 s of silence: a bare fuzz decays below 1e-308 by then
        y = chain.process(z, lambda i, k=k: Blk(k * BLOCK, BLOCK))
    fz = chain.procs[0]
    tiny = lambda a: np.any((np.abs(a) > 0) & (np.abs(a) < 1e-300))  # noqa: E731
    assert not tiny(y) and not any(tiny(s) for s in fz.st) and not tiny(chain.procs[1].pw[0])


def test_a_track_whose_amp_only_hisses_goes_dormant(tmp_path):
    e = Engine(str(tmp_path), bpm=120, bpb=4, workers=0, device='none')
    e.cmd_track('g', instrument='preset:pluck', fx=[{'type': 'amp', 'hiss_db': -75, 'hum_db': -82}, {'type': 'cab'}])
    assert e.tracks['g']['path'].chain.noise > 0
    for _ in range(int(2.0 * SR / BLOCK)):
        e.tick()
        e.mix_block()
    assert e.tracks['g']['quiet'] > 0              # no notes and only its own hiss: asleep, costs nothing
