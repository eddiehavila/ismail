"""The cut list. python cut.py [--sheet a b n | --range a b]  (or: python -m ismail.video edit -s <song> -- --sheet a b n)"""
from ismail.video.edit import Cut

C = Cut(__file__)

# shots: key, file stem in renders/shots, frames, options (rain=True, gain=1.3, crop=(zoom, cx, cy))
C.shot('A', 's01_example', 96)

# sections set the intensity of punch, shake, chroma and grain
C.sections([(1, 17, 0.25), (17, 33, 0.5), (33, 65, 1.0), (65, 81, 0.35), (81, 97, 0.6), (97, 129, 1.15), (129, 200, 0.25)])

# the cut list, in bars. Later calls overwrite earlier ones, so write the base first, then the inserts.
C.seg(C.B(1), C.total, 'A')
# for e in C.ev('growl', 33, 65, fam='talk'):     # an insert for exactly one note
#     C.seg(e['f'], e['f'] + e['len'], 'B', 40)
# C.cycle_cuts(C.B(89), C.B(96), [e['f'] for e in C.ev('snare', 89, 96)], ['A', 'B'], {'A': 0, 'B': 0})

# glitches from the notes (named families such as talk words: C.fx_map.update({'name': 'talk'}))
C.auto_fx()
C.text(0, 75, 'PLAY >', 26, 110, 50)

if __name__ == '__main__':
    C.main()
