"""Voice library: `code` instruments kept as Python modules instead of code pasted into project.json.

A voice is a module `<name>.py` defining `voice(freq, t, vel, gate, sr)` -> mono (n,) or stereo (2, n) array
(t: seconds from note start, covering gate + tail; vel 0..1; gate: held seconds). It may define more functions
(a track picks one with "fn") and may accept keyword arguments: `bpm` is passed when the function takes it, and
the track's "params" dict is passed as keywords. A module-level INFO dict documents it for voices_list/voice_help:
{"summary": ..., "range": ..., "velocity": ..., "functions": {...}, "params": {...}}.

A track uses one with {"type": "code", "voice": "<name>", "fn": "voice", "params": {}, "tail": 1.0}.
Search order: <project>/voices/, then each directory in $ISMAIL_VOICES (os.pathsep-separated), then these
built-ins. A song voice with a built-in's name overrides it; it can also extend one
(`from ismail.voices.growl import *`). Data files sit next to the module and are found through __file__.
"""
import hashlib
import importlib
import importlib.util
import inspect
import os
import sys

BUILTIN = os.path.dirname(os.path.abspath(__file__))
_LOADED = {}


class VoiceError(ValueError):
    pass


def search_path(root=None):
    dirs = []
    if root:
        dirs.append(('song', os.path.join(root, 'voices')))
    for d in filter(None, os.environ.get('ISMAIL_VOICES', '').split(os.pathsep)):
        dirs.append(('env', d))
    dirs.append(('built-in', BUILTIN))
    return dirs


def _names(d):
    if not os.path.isdir(d):
        return []
    return sorted(f[:-3] for f in os.listdir(d) if f.endswith('.py') and not f.startswith('_'))


def find(name, root=None):
    for origin, d in search_path(root):
        p = os.path.join(d, name + '.py')
        if os.path.isfile(p):
            return origin, p
    have = sorted({n for _, d in search_path(root) for n in _names(d)})
    raise VoiceError(f"no voice {name!r}; available: {', '.join(have) or 'none'} (voices_list shows them; a song "
                     f"voice goes in <project>/voices/{name}.py)")


def load(name, root=None):
    origin, path = find(name, root)
    if origin == 'built-in':
        return importlib.import_module(f"{__name__}.{name}")
    key = (path, os.path.getmtime(path))
    if key not in _LOADED:
        mod_name = f"ismail_voice_{name}_{hashlib.sha1(path.encode()).hexdigest()[:8]}"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
        _LOADED[key] = mod
    return _LOADED[key]


def function(name, fn='voice', root=None):
    mod = load(name, root)
    f = getattr(mod, fn or 'voice', None)
    if not callable(f):
        fns = [k for k, v in vars(mod).items() if callable(v) and not k.startswith('_') and
               getattr(v, '__module__', None) == mod.__name__]
        raise VoiceError(f"voice {name!r} has no function {fn!r}; it has: {', '.join(fns)}")
    return f


def call(f, freq, t, vel, gate, sr, bpm, params):
    """Call a voice function, passing bpm and params only to functions that accept them."""
    sig = inspect.signature(f)
    takes_any = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
    kw = {}
    if 'bpm' in sig.parameters or takes_any:
        kw['bpm'] = bpm
    for k, v in (params or {}).items():
        if k not in sig.parameters and not takes_any:
            raise VoiceError(f"voice function {f.__name__} takes no parameter {k!r}; it takes "
                             f"{[p for p in sig.parameters if p not in ('freq', 't', 'vel', 'gate', 'sr')]}")
        kw[k] = v
    return f(freq, t, vel, gate, sr, **kw)


def fingerprint(inst, root=None):
    """Hash of every voice file (and its sibling data files) an instrument uses, for the render cache."""
    names = set()

    def walk(i):
        if isinstance(i, dict):
            if i.get('type') == 'code' and i.get('voice'):
                names.add(i['voice'])
            for v in (i.get('map') or {}).values():
                walk(v)
    walk(inst)
    h = hashlib.sha1()
    for n in sorted(names):
        try:
            _, p = find(n, root)
        except VoiceError:
            h.update(n.encode())
            continue
        d, base = os.path.dirname(p), n
        for f in sorted(os.listdir(d)):
            if f == base + '.py' or (f.startswith(base + '.') or f.startswith(base + '_')) and not f.endswith('.pyc'):
                fp = os.path.join(d, f)
                if os.path.isfile(fp):
                    with open(fp, 'rb') as fh:
                        h.update(fh.read())
    return h.hexdigest()[:12] if names else ''


def info(name, root=None):
    origin, path = find(name, root)
    mod = load(name, root)
    meta = dict(getattr(mod, 'INFO', {}) or {})
    doc = (mod.__doc__ or '').strip()
    if 'summary' not in meta:
        meta['summary'] = doc.split('\n')[0] if doc else '(no description)'
    return origin, path, meta, doc


def available(root=None):
    """[(name, origin, summary)] with song and env voices shadowing built-ins of the same name."""
    seen, out = set(), []
    for origin, d in search_path(root):
        for n in _names(d):
            if n in seen:
                continue
            seen.add(n)
            try:
                _, _, meta, _ = info(n, root)
                out.append((n, origin, meta.get('summary', '')))
            except Exception as e:  # a broken song voice should not hide the others
                out.append((n, origin, f"(fails to load: {e})"))
    return out
