"""A note still sounding when a window starts (a drone, a pad, a held string) plays in that window: in a studio
render of a bar range and on a deck loaded with a bar range. Both used to drop it, and the deck said "silent in
range" for the hum and the contrabass lines of a song whose full render had them."""
import os

import numpy as np
import soundfile as sf

from ismail import api
from ismail.live import decks


def song(root):
    api.project_new(root, bpm=120, length_bars=12)
    api.track_add(root, 'drone', instrument='preset:pad')
    api.notes_write(root, 'drone', 1, '0 D3 40 90')                  # bars 1-10
    api.track_add(root, 'pluck', instrument='preset:pluck')
    api.notes_write(root, 'pluck', 1, '0 A4 0.5 90')                 # bar 1 only, long gone by bar 9
    return root


def test_studio_window_keeps_a_held_note(tmp_path):
    root = song(str(tmp_path / 's'))
    api.render(root, bars=[9, 10])
    y, sr = sf.read(os.path.join(root, 'renders', 'latest.wav'))
    db = 20 * np.log10(np.sqrt(np.mean(y[: 2 * sr] ** 2)) + 1e-12)
    assert db > -40, db                                            # the drone sounds through bars 9-10


def test_deck_window_keeps_a_held_note(tmp_path):
    root = song(str(tmp_path / 's'))
    _, _, tracks, clips, skipped = decks.read_song(root, 'A', [7, 10], 4)
    drone = [c for c in clips if c['track'] == 'A.drone']
    assert drone and drone[0]['notes'].startswith('0 ') and 'drone' not in skipped['silent in range']
    start, pitch, dur = drone[0]['notes'].split()[:3]
    assert float(dur) == 16                                         # bars 7-10 of a note that ends at bar 10's end
    assert 'pluck' in skipped['silent in range']                    # a short note from bar 1 is not dragged in
