"""Text <-> note conversion. Pitches, beat fractions, note lists, step patterns, piano rolls."""
import re
from fractions import Fraction

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_PITCH_RE = re.compile(r'^([A-Ga-g])([#b]*)(-?\d+)$')


class NotationError(ValueError):
    pass


MAX_OFFSET_MS = 2000.0
_OFFSET_RE = re.compile(r'^@([+-]?\d+(?:\.\d+)?)(ms)?$')


def parse_offset(tok):
    """'@-40ms', '@-40', '@+12.5ms' -> milliseconds (negative = earlier than the beat)."""
    m = _OFFSET_RE.match(tok)
    if not m:
        raise NotationError(f"offset {tok!r}: write it in milliseconds after an @, e.g. '@-40ms' (earlier) or "
                            f"'@15ms' (later); to move a note by beats, change its start")
    ms = float(m.group(1))
    if abs(ms) > MAX_OFFSET_MS:
        raise NotationError(f"offset {tok!r}: at most {MAX_OFFSET_MS:g} ms either way; a larger move is a new start")
    return ms


def fmt_offset(ms):
    return f"@{fmt_num(ms) if ms < 0 else '+' + fmt_num(ms)}ms"


def placed(notes, bpm, track_offset_ms=0.0):
    """Stored notes [[start, midi, dur, vel(, offset_ms)]] -> [(start, midi, dur, vel)] with each start moved by the
    track's and the note's offset, in beats at `bpm`. A nudged note is the same as a note written at its nudged
    time: the studio and the live decks both place notes through this, so they agree."""
    k = bpm / 60000.0
    out = []
    for n in notes:
        off = float(track_offset_ms or 0.0) + (float(n[4]) if len(n) > 4 else 0.0)
        out.append((n[0] + off * k if off else n[0], n[1], n[2], n[3]))
    return out


def with_offsets(notes5, bpm):
    """[(start, midi, dur, vel, offset_ms)] from parse_notes(offsets=True) -> 4-tuples with starts moved."""
    return placed(notes5, bpm)


def pitch_to_midi(p):
    """'C4' -> 60, 'F#2' -> 42, 'Bb3' -> 58, 60 -> 60, '60' -> 60."""
    if isinstance(p, (int, float)):
        return int(p)
    s = str(p).strip()
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    m = _PITCH_RE.match(s)
    if not m:
        raise NotationError(f"bad pitch {p!r}: use a name like C4, F#2, Bb3 (C4 = 60) or a MIDI number")
    base = _SEMI[m.group(1).upper()]
    acc = m.group(2).count('#') - m.group(2).count('b')
    return base + acc + 12 * (int(m.group(3)) + 1)


def midi_to_name(n):
    n = int(round(n))
    return f"{NAMES[n % 12]}{n // 12 - 1}"


def midi_to_hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def hz_to_midi(f):
    import math
    return 69 + 12 * math.log2(f / 440.0)


def parse_num(s):
    """'0.5', '1/4', '3', '1+1/2' -> float."""
    s = str(s).strip()
    try:
        return float(sum(Fraction(part) for part in s.split('+')))
    except (ValueError, ZeroDivisionError):
        raise NotationError(f"bad number {s!r}: use decimals (0.5) or fractions (1/4)")


def fmt_num(x):
    x = round(float(x), 4)
    return str(int(x)) if x == int(x) else f"{x:g}"


def parse_notes(text, default_vel=100, default_dur=None, offsets=False):
    """Parse a note list. One note per line or ';'-separated:
         <start_beats> <pitch> [<dur_beats>] [<velocity>] [@<offset>ms]
       Pitch may be a chord 'C4,E4,G4'. ' #' starts a comment (F#4 is a pitch). @offset moves the sound off its
       beat by milliseconds (negative = earlier: a sound whose attack comes late starts early so the attack lands on
       the beat); the note still belongs to its beat.
       Returns [(start, midi, dur, vel)], or with offsets=True [(start, midi, dur, vel, offset_ms)]."""
    out = []
    for lineno, raw in enumerate(re.split(r'[;\n]', text), 1):
        line = re.sub(r'(^|\s)#.*$', '', raw).strip()
        if not line:
            continue
        parts = line.split()
        offs = [p for p in parts if p.startswith('@')]
        parts = [p for p in parts if not p.startswith('@')]
        if len(offs) > 1:
            raise NotationError(f"note {lineno} {raw.strip()!r}: one @offset per note")
        off = parse_offset(offs[0]) if offs else 0.0
        if offs and not offsets:
            raise NotationError(f"note {lineno} {raw.strip()!r}: an @offset is not read here; write the note "
                                f"without it, or move its start")
        if len(parts) < 2:
            raise NotationError(f"note {lineno} {raw.strip()!r}: need at least '<start> <pitch>' e.g. '0 E2 0.5 100'")
        start = parse_num(parts[0])
        if len(parts) >= 3:
            dur = parse_num(parts[2])
        elif default_dur is not None:
            dur = default_dur
        else:
            raise NotationError(f"note {lineno} {raw.strip()!r}: missing duration e.g. '0 E2 0.5'")
        vel = int(parts[3]) if len(parts) >= 4 else default_vel
        if dur <= 0:
            raise NotationError(f"note {lineno}: duration must be > 0")
        if not 1 <= vel <= 127:
            raise NotationError(f"note {lineno}: velocity must be 1..127")
        for p in parts[1].split(','):
            out.append((start, pitch_to_midi(p), dur, vel, off) if offsets else (start, pitch_to_midi(p), dur, vel))
    return out


STEP_VEL = {'X': 127, 'x': 100, 'o': 70, '-': 45}


def parse_steps(pattern, step=0.25, dur=None, vel_map=None):
    """'x...x...X...x..o' -> [(start, dur, vel)]. '.' rest, X accent 127, x 100, o 70, - ghost 45,
       '_' extends the previous step (tie). Spaces and '|' are ignored."""
    vm = dict(STEP_VEL, **(vel_map or {}))
    s = re.sub(r'[\s|]', '', pattern)
    out = []
    for i, ch in enumerate(s):
        if ch == '.':
            continue
        if ch == '_':
            if out:
                st, d, v = out[-1]
                out[-1] = (st, d + step, v)
            continue
        if ch not in vm:
            raise NotationError(f"bad step char {ch!r} in {pattern!r}: use . x X o - _")
        out.append((i * step, dur if dur else step, vm[ch]))
    return out, len(s) * step


def format_notes(notes, beats_per_bar, bar_origin=1):
    """notes: [(start_abs_beats, midi, dur, vel(, offset_ms))] -> 'bar | +beat | pitch | dur | vel | @offset' lines."""
    lines = []
    for n in sorted(notes):
        st, p, d, v = n[:4]
        bar = int(st // beats_per_bar) + bar_origin
        off = st - (bar - bar_origin) * beats_per_bar
        lines.append(f"bar {bar:>3} +{fmt_num(off):<6} {midi_to_name(p):<4} d={fmt_num(d):<6} v={v}"
                     + (f" {fmt_offset(n[4])}" if len(n) > 4 and n[4] else ''))
    return '\n'.join(lines)


def piano_roll(notes, start_beat, n_beats, step=0.25, beats_per_bar=4):
    """ASCII roll: one row per used pitch (high to low), one column per step. '#' onset, '=' sustain."""
    if not notes:
        return '(no notes in range)'
    ncols = int(round(n_beats / step))
    notes = [tuple(n[:4]) for n in notes]
    pitches = sorted({p for _, p, _, _ in notes}, reverse=True)
    rows = {p: ['.'] * ncols for p in pitches}
    for st, p, d, v in notes:
        c0 = int(round((st - start_beat) / step))
        c1 = max(c0 + 1, int(round((st + d - start_beat) / step)))
        for c in range(max(c0, 0), min(c1, ncols)):
            rows[p][c] = '#' if c == c0 else '='
    steps_per_bar = int(round(beats_per_bar / step))
    out = []
    for p in pitches:
        cells = ''.join(ch + ('|' if (i + 1) % steps_per_bar == 0 and i + 1 < ncols else '') for i, ch in enumerate(rows[p]))
        out.append(f"{midi_to_name(p):>4} {cells}")
    return '\n'.join(out)
