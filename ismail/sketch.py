"""First sketches: a brief in, two or three short contrasting pieces on the showcase voices out, so a person hears
something within minutes and picks a direction by ear (the pick becomes the song's example). Each sketch is a
normal project the agent can edit: a motif that comes back and answers itself, chords that move, parts in their
own registers and rhythms, never block chords on every beat 1."""
import json
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SHOWCASE = os.path.join(HERE, 'voices', 'showcase.json')

NAMES = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
SCALES = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10]}
ROMAN = ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii']
PROGRESSIONS = {'major': [['I', 'V', 'vi', 'IV'], ['I', 'vi', 'IV', 'V'], ['IV', 'I', 'V', 'vi']],
                'minor': [['i', 'VI', 'III', 'VII'], ['i', 'iv', 'VII', 'III'], ['i', 'VI', 'iv', 'V']]}
DARK = re.compile(r'\b(sad|dark|melanchol\w*|night\w*|lonely|grief|rain\w*|minor|moody|haunt\w*|tense|cold|loss)\b', re.I)

# style -> what it is, tempo, parts (role -> showcase voice, register, level)
STYLES = {
    'piano': {'what': 'solo piano: a melody over a broken-chord left hand', 'bpm': (72, 88),
              'parts': {'melody': ('grand_piano', (60, 84), -2.0), 'harmony': ('grand_piano', (36, 60), -10.0)}},
    'chamber': {'what': 'string trio and piano: violin melody, cello counterline, contrabass, soft piano',
                'bpm': (68, 84),
                'parts': {'melody': ('violin', (62, 84), -1.0), 'counter': ('cello', (48, 64), 1.0),
                          'bass': ('contrabass', (31, 48), -6.0), 'harmony': ('grand_piano', (55, 72), 2.0)}},
    'band': {'what': 'a small band: drums, bass guitar, rhythm guitar, piano melody', 'bpm': (92, 112),
             'parts': {'drums': ('kit70', None, 7.0), 'bass': ('pbass70', (28, 50), -9.0),
                       'chords': ('strat70_rhythm', (52, 67), -3.0), 'melody': ('grand_piano', (64, 86), 2.0)}},
}
ORDER = ['piano', 'chamber', 'band']
MOTIF_RHYTHMS = [   # (start beat, length) over two bars of 4/4; none of them only lands on beat 1
    [(0, 1.5), (1.5, 0.5), (2, 1), (3, 1), (4, 3), (7, 1)],
    [(0.5, 0.5), (1, 1), (2, 0.5), (2.5, 1.5), (4.5, 0.5), (5, 1), (6, 2)],
    [(1, 1), (2, 1), (3, 0.5), (3.5, 0.5), (4, 2), (6, 1), (7, 1)],
]


class SketchError(ValueError):
    pass


def showcase():
    with open(SHOWCASE, encoding='utf8') as f:
        return json.load(f)


def showcase_text():
    sc = showcase()
    L = [f"  {v['name']:<15} {v['family']:<8} {v['range']:<12} {v['why']}" for v in sc['voices']]
    L.append(f"  never in a first sketch: {sc['never_first']}")
    L.append(f"  not covered yet: {'; '.join(sc['gaps'])}")
    return '\n'.join(L)


def parse_key(key, brief=''):
    """'A minor', 'Am', 'Eb', 'F# major' -> (tonic pitch class, mode). Empty: from the brief's words (minor for
    dark words, else major), tonic A for minor and C for major."""
    if not key:
        return (9, 'minor') if DARK.search(brief or '') else (0, 'major')
    m = re.fullmatch(r'\s*([A-Ga-g])([#b]?)\s*(m|min|minor|maj|major)?\s*', key)
    if not m:
        raise SketchError(f"key {key!r}: write it like 'A minor', 'Am', 'Eb major' or 'F#'")
    pc = (NAMES[m.group(1).upper()] + {'#': 1, 'b': -1, '': 0}[m.group(2)]) % 12
    return pc, ('minor' if m.group(3) in ('m', 'min', 'minor') else 'major')


def chord(sym, tonic, mode):
    """'vi', 'V', 'bVII' or a chord name ('Am', 'F', 'C#m') -> (root pitch class, [pitch classes of the triad])."""
    m = re.fullmatch(r'([A-G])([#b]?)(m?)', sym)
    if m:
        root = (NAMES[m.group(1)] + {'#': 1, 'b': -1, '': 0}[m.group(2)]) % 12
        return root, [root, (root + (3 if m.group(3) else 4)) % 12, (root + 7) % 12]
    m = re.fullmatch(r'([b#]?)([ivIV]+)', sym)
    if not m or m.group(2).lower() not in ROMAN:
        raise SketchError(f"chord {sym!r}: a roman numeral (I, vi, bVII) or a chord name (Am, F, C#m)")
    deg = ROMAN.index(m.group(2).lower())
    sc = SCALES[mode]
    root = (tonic + sc[deg] + {'b': -1, '#': 1, '': 0}[m.group(1)]) % 12
    if m.group(1):
        third = 3 if m.group(2).islower() else 4
    else:
        third = (sc[(deg + 2) % 7] - sc[deg]) % 12
        if mode == 'minor' and m.group(2) == 'V':
            third = 4                                        # the dominant of a minor key is major
    return root, [root, (root + third) % 12, (root + 7) % 12]


def near(pc, target, lo, hi):
    """The pitch of class pc nearest to target inside [lo, hi]."""
    best = None
    for p in range(lo, hi + 1):
        if p % 12 == pc and (best is None or abs(p - target) < abs(best - target)):
            best = p
    return best if best is not None else target


def scale_pitches(tonic, mode, lo, hi):
    return [p for p in range(lo, hi + 1) if (p - tonic) % 12 in SCALES[mode]]


def melody(chords, tonic, mode, reg, rng, rhythm, alt):
    """A 2-bar motif and its answer make a 4-bar phrase. Each later phrase keeps the motif's steps (that is what
    makes it a tune) but moves: the second lifts and answers in another rhythm, the third lifts further, the last
    falls home. Strong-beat and long notes land on chord tones; the last bar holds the tonic."""
    lo, hi = reg
    sp = scale_pitches(tonic, mode, lo, hi)
    n_steps = max(len(rhythm), len(alt))
    steps = [rng.choice([1, 1, 2, -1]) if i < n_steps // 2 else rng.choice([-1, -1, -2, 1]) for i in range(n_steps)]
    out = []
    home = lo + int((hi - lo) * 0.35)                        # phrases start near here, so a tune never drifts to an edge
    last = home
    end = len(chords) - 1
    for c in range((len(chords) + 1) // 2):
        b0, ph = c * 2, c // 2
        rh = alt if ph % 2 == 1 and c % 2 == 1 else rhythm
        lift = [0, 2, 3, 1][ph % 4] if b0 + 2 <= end - 3 or ph == 0 else 0
        start = near(chords[b0][1][(c % 2) * 2], home if c % 2 == 0 else last, lo, hi)   # motif: the root; answer: the fifth
        idx = min(range(len(sp)), key=lambda i: abs(sp[i] - start)) + lift
        for n, (beat, dur) in enumerate(rh):
            bar = b0 + int(beat // 4)
            if bar >= end:
                break
            if n:
                idx += steps[n - 1] * (-1 if c % 2 and n > len(rh) // 2 else 1)
            idx = max(0, min(len(sp) - 1, idx))
            p = sp[idx]
            if (beat % 1 == 0 and beat % 2 == 0) or dur >= 2:
                pcs = chords[bar][1]
                q = min(pcs, key=lambda q: abs(near(q, p, lo, hi) - p))
                p = near(q, p, lo, hi)
                idx = min(range(len(sp)), key=lambda i: abs(sp[i] - p))
            vel = 76 + (8 if beat % 4 == 0 else 0) - (10 if beat % 1 else 0) + 3 * min(ph, 2) + rng.randint(-4, 4)
            out.append((bar, beat % 4, p, dur, vel))
            last = p
    out.append((end, 0, near(tonic, home, lo, hi), 4, 80))
    return out


def broken_chord(chords, reg, rng, pattern='8ths'):
    """Left-hand broken chords held into the bar (a pedal): root, fifth, octave, tenth."""
    lo, hi = reg
    out = []
    for bar, (root, pcs) in enumerate(chords):
        r = near(root, lo + 7, lo, hi)
        seq = [r, r + 7, r + 12, near(pcs[1], r + 16, lo, hi + 12)]
        beats = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5] if pattern == '8ths' else [0, 1, 2, 3]
        for i, b in enumerate(beats):
            p = seq[[0, 1, 2, 3, 2, 1, 2, 3][i % 8]] if pattern == '8ths' else seq[[0, 1, 3, 2][i % 4]] + 12
            out.append((bar, b, p, 4 - b, 52 + (6 if b == 0 else 0) + rng.randint(-3, 3)))
    return out


def counterline(chords, reg, rng):
    """Half notes on chord tones, each the nearest to the one before (voice leading), moving on beat 3."""
    lo, hi = reg
    out, last = [], (lo + hi) // 2
    for bar, (root, pcs) in enumerate(chords):
        for b, pc in ((0, pcs[1]), (2, pcs[2] if rng.random() < 0.5 else pcs[0])):
            p = near(pc, last, lo, hi)
            out.append((bar, b, p, 2, 64 + rng.randint(-4, 4)))
            last = p
    return out


def roots(chords, reg, rng, walk=False):
    lo, hi = reg
    out = []
    for bar, (root, pcs) in enumerate(chords):
        r = near(root, lo + 5, lo, hi)
        if not walk:
            out.append((bar, 0, r, 4, 70 + rng.randint(-3, 3)))
            continue
        nxt = chords[(bar + 1) % len(chords)][0]
        approach = near(nxt, r, lo, hi)
        approach += -1 if approach > r else 1                 # a half step into the next root
        out += [(bar, 0, r, 1.5, 92), (bar, 1.5, r, 0.5, 70), (bar, 2, near(pcs[2], r, lo, hi), 1.5, 84),
                (bar, 3.5, approach, 0.5, 74)]
    return out


def stabs(chords, reg, rng):
    lo, hi = reg
    out = []
    for bar, (root, pcs) in enumerate(chords):
        v = sorted(near(pc, (lo + hi) // 2, lo, hi) for pc in pcs)
        for b in (1.5, 3.5) if bar % 4 != 3 else (1.5, 2.5, 3.5):
            out.append((bar, b, v, 0.5, 82 + rng.randint(-5, 5)))
    return out


def drums(n_bars, rng):
    out = []
    for bar in range(n_bars):
        fill = bar == n_bars - 2
        out += [(bar, 0, 36, 0.5, 100), (bar, 2.5, 36, 0.5, 86)]
        if bar % 2:
            out.append((bar, 1.75, 36, 0.25, 72))
        out += [(bar, 1, 38, 0.5, 96), (bar, 3, 38, 0.5, 98 if not fill else 90)]
        for i in range(8):
            if fill and i >= 4:
                break
            out.append((bar, i / 2, 42, 0.5, (70 if i % 2 == 0 else 50) + rng.randint(-4, 4)))
        if fill:
            for i, t in enumerate((48, 48, 45, 45, 41, 41, 41, 38)):
                out.append((bar, 2 + i * 0.25, t, 0.25, 80 + i * 2))
        if bar == 0 or bar == n_bars // 2:
            out.append((bar, 0, 49, 2, 92))
    out.append((n_bars - 1, 0, 49, 4, 96))
    return out


def plan(brief, style, key=None, bpm=None, bars=None, progression=None, seed=0, variant=0):
    """-> a dict: style, key, bpm, bars, chords per bar, and every part's notes as (bar, beat, pitch, dur, vel)."""
    if style not in STYLES:
        raise SketchError(f"style {style!r}: one of {', '.join(STYLES)}")
    st = STYLES[style]
    rng = random.Random(f"{seed}:{style}:{brief}")
    tonic, mode = parse_key(key, brief)
    bpm = bpm or rng.randint(*st['bpm'])
    if not bars:
        bars = max(8, min(16, int(round(30 * bpm / 240 / 4)) * 4))   # about 30 seconds, whole 4-bar phrases
    prog = progression or PROGRESSIONS[mode][variant % len(PROGRESSIONS[mode])]
    if isinstance(prog, str):
        prog = [x for x in re.split(r'[\s,|-]+', prog) if x]
    loop = [chord(s, tonic, mode) for s in prog]
    chords = [loop[i % len(loop)] for i in range(bars - 1)] + [chord('i' if mode == 'minor' else 'I', tonic, mode)]
    rhythm = MOTIF_RHYTHMS[(variant + len(style)) % len(MOTIF_RHYTHMS)]
    alt = MOTIF_RHYTHMS[(variant + len(style) + 1) % len(MOTIF_RHYTHMS)]
    parts = {}
    for role, (voice, reg, level) in st['parts'].items():
        if role == 'melody':
            notes = melody(chords, tonic, mode, reg, rng, rhythm, alt)
        elif role == 'harmony':
            notes = broken_chord(chords, reg, rng, '8ths' if style == 'piano' else 'quarters')
        elif role == 'counter':
            notes = counterline(chords, reg, rng)
        elif role == 'bass':
            notes = roots(chords, reg, rng, walk=style == 'band')
        elif role == 'chords':
            notes = stabs(chords, reg, rng)
        else:
            notes = drums(bars, rng)
        if style == 'chamber' and role == 'harmony':
            notes = [n for n in notes if n[0] >= 4]           # the piano enters with the answer
        parts[role] = {'voice': voice, 'level': level, 'notes': notes}
    names = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    return {'style': style, 'what': st['what'], 'key': f"{names[tonic]} {mode}", 'bpm': bpm, 'bars': bars,
            'progression': prog, 'parts': parts}


def note_text(notes, bar):
    """The notes of one bar as notes_write text."""
    L = []
    for b, beat, p, dur, vel in notes:
        if b != bar:
            continue
        pitch = ','.join(str(x) for x in p) if isinstance(p, list) else str(p)
        L.append(f"{beat:g} {pitch} {dur:g} {max(1, min(127, int(vel)))}")
    return '; '.join(L)


# ------------------------------------------------------------------ the first session

def marker_path():
    return os.environ.get('ISMAIL_FIRST_SESSION') or os.path.join(os.path.expanduser('~'), '.ismail',
                                                                  'first_session_done')


def mark_done():
    p = marker_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf8') as f:
        f.write('the person kept a first sketch; guide no longer opens with the first session\n')


def _has_render(root, depth=4):
    """A finished render somewhere under root: a renders/ folder holding a wav or mp3 (sketches do not count)."""
    stack = [(root, 0)]
    while stack:
        d, k = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if not e.is_dir(follow_symlinks=False) or e.name in ('sketches', 'cache', '.git', 'node_modules'):
                continue
            if e.name == 'renders':
                try:
                    if any(f.endswith(('.wav', '.mp3')) for f in os.listdir(e.path)):
                        return True
                except OSError:
                    pass
            elif k < depth:
                stack.append((e.path, k + 1))
    return False


def is_new(project=None):
    """A person who has made nothing with ismail yet: no first-session mark and no finished render in the songs
    folder or next to the given project."""
    if os.path.exists(marker_path()):
        return False
    from .handoffs import SONGS
    roots = [SONGS] + ([os.path.dirname(os.path.abspath(project))] if project else [])
    return not any(os.path.isdir(r) and _has_render(r) for r in roots)
