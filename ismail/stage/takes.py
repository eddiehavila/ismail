"""What the person said while recording, kept with the take (the user, 2026-10-05: while he records he often says the
take's name or something about it; "some data about the take that you should probably store with the take"), and
finding takes by it, since he records many takes of one thing.

A take's words come from one of two places, on the take's own clock (seconds since its first frame):
  - takes/<id>/voice.json: the take's own audio (the mic runs for a whole take), transcribed when it lands
  - the performance it was kept from or recorded in (meta "performance", "perf_shift"; perform.py): the clips'
    words that fall inside the take, shifted onto its clock
meta.json carries what an agent or the person adds: "label" (a name for it) and "notes" ([{at, text, by}]).
Word times are snapped onto the measured voice (perform.snap_words), never whisper's raw times.
"""
import json
import time

from . import perform


def _meta(d):
    f = d / 'meta.json'
    try:
        return json.loads(f.read_text(encoding='utf-8')) if f.is_file() else {}
    except ValueError:
        return {}


def _write_meta(d, m):
    with perform.LOCK:
        cur = _meta(d)
        cur.update(m)
        (d / 'meta.json').write_text(json.dumps(cur, indent=1), encoding='utf-8')
        return cur


def transcribe(d, stt_words):
    """The take's own audio into voice.json: {text, words: [{word, start, end}], voice, file}. Returns it."""
    files = sorted(d.glob('audio.*'))
    if not files:
        raise FileNotFoundError(f'{d.name} has no audio')
    got = stt_words(files[0].read_bytes(), files[0].name)
    out = {'file': files[0].name, 'text': got.get('text', ''), 'words': None, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if got.get('words') is None:
        out['words_missing'] = 'the speech server gave no word times (restart speakwright for verbose_json)'
    else:
        try:
            v = perform.voiced(perform.pcm(files[0]))
        except perform.NoDecoder as e:                    # the text still counts; raw times never do
            out['words_missing'] = str(e)
        else:
            out['voice'] = perform.voice_span(v)
            out['words'] = perform.snap_words(got['words'], v)
    (d / 'voice.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def transcribe_and_tell(name, d, stt_words, emit):
    """For the server: transcribe a take's audio as it lands and emit take_voice (or its error)."""
    try:
        v = transcribe(d, stt_words)
        emit({'type': 'take_voice', 'take': d.name, 'text': v['text'],
              **({'words': [[w['word'], w['start'], w['end']] for w in v['words']]} if v.get('words') else {}),
              **({'words_missing': v['words_missing']} if 'words_missing' in v else {})})
    except Exception as e:                                    # noqa: BLE001
        emit({'type': 'take_voice', 'take': d.name, 'text': None, 'error': str(e)})


def words(scene_dir, d, m=None):
    """(text, [{word, start, end}]) the person said during a take, on its clock; ('', []) when nothing."""
    m = m if m is not None else _meta(d)
    vf = d / 'voice.json'
    if vf.is_file():
        try:
            v = json.loads(vf.read_text(encoding='utf-8'))
            return v.get('text') or '', v.get('words') or []
        except ValueError:
            pass
    if m.get('performance'):
        p = perform.read(scene_dir / 'performances' / m['performance'])
        shift, span = float(m.get('perf_shift') or 0), float(m.get('seconds') or 1e9)
        out = []
        for c in p.get('clips', []):
            for w in c.get('words') or []:
                t0 = c['at'] + w['start'] - shift
                if -0.5 <= t0 <= span + 0.5:
                    out.append({'word': w['word'], 'start': round(t0, 2), 'end': round(c['at'] + w['end'] - shift, 2)})
        return ' '.join(w['word'] for w in out), out
    return '', []


def listing(scene_dir, query=None, person=None, kept=None, limit=30):
    """Takes newest first, each with what was said; query= words that must all appear (in what was said, the label
    or the notes), case-insensitive. Returns a list of dicts."""
    root = scene_dir / 'takes'
    terms = [t.lower() for t in (query or '').split() if t]
    out = []
    for d in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True) if root.is_dir() else []:
        m = _meta(d)
        who = m.get('for') or m.get('name') or ''
        if person and person not in (who, m.get('name')):
            continue
        if kept is not None and bool(m.get('kept')) != kept:
            continue
        text, ws = words(scene_dir, d, m)
        notes = m.get('notes') or []
        hay = ' '.join([text, m.get('label') or '', *[n.get('text', '') for n in notes]]).lower()
        if terms and not all(t in hay for t in terms):
            continue
        hits = [w for w in ws if any(t in w['word'].lower() for t in terms)] if terms else []
        out.append({'id': d.name, 'person': who, 'label': m.get('label'), 'seconds': m.get('seconds'), 'kept': bool(m.get('kept')),
                    'from': m.get('from'), 'said': text, 'hits': [[w['word'], w['start']] for w in hits][:10], 'notes': notes,
                    'words': len(ws)})
        if len(out) >= limit:
            break
    return out


def note(scene_dir, take, label=None, text=None, at=None, by='agent'):
    """Name a take (label) and/or add a note (at: seconds on the take's clock)."""
    d = scene_dir / 'takes' / take
    if not (d / 'meta.json').is_file():
        raise FileNotFoundError(take)
    m = _meta(d)
    patch = {}
    if label is not None:
        patch['label'] = label
    if text:
        patch['notes'] = (m.get('notes') or []) + [{'text': text, 'by': by, **({'at': at} if at is not None else {})}]
    return _write_meta(d, patch)
