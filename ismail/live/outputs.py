"""Where the live engine's sound goes, and what reaches back into it.

Streams: the master or any bus or deck as raw PCM (int16, little-endian, interleaved stereo, SR Hz) over a plain HTTP
GET on the engine's localhost port, `/stream?name=bus:lucy`. Each streamed bus passes its own safety limiter, as the
master does; a client that falls more than MAX_QUEUE_S behind loses its oldest audio instead of slowing the set. A
stage page reaches it through its own server (same origin, https), which relays the stream; the engine never listens
beyond localhost.

Controls: a named control (a knob, a switch, a slider on the VR stage) is mapped once by an agent to a live parameter
(a track, bus or deck volume, a deck EQ, an effect param). Its moves then apply in the engine in milliseconds, with no
model in the loop, and every move is logged with the bar it happened at, so a take's knob moves read back as
automation points.

The default output: a speaker that connects after the engine started is not in this process's device list, so the
current default is asked of a fresh process.
"""
import collections
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np

from .safety import Safety

MAX_QUEUE_S = 1.0
FORMAT = {'format': 's16le', 'channels': 2}


class StreamHub:
    def __init__(self, sr):
        self.sr = sr
        self.subs = collections.defaultdict(list)       # name -> [Sub]
        self.limit = {}                                  # name -> Safety (buses and decks; the master has its own)
        self.lock = threading.Lock()
        self.dropped = collections.Counter()

    def wants(self, name):
        return bool(self.subs.get(name))

    def names(self):
        with self.lock:
            return {k: len(v) for k, v in self.subs.items() if v}

    def subscribe(self, name):
        s = _Sub(int(MAX_QUEUE_S * self.sr) * 4)
        with self.lock:
            self.subs[name].append(s)
            if name != 'master' and name not in self.limit:
                self.limit[name] = Safety(self.sr)
        return s

    def unsubscribe(self, name, s):
        with self.lock:
            if s in self.subs.get(name, []):
                self.subs[name].remove(s)

    def push(self, name, y, limited=False):
        """y: float (2, n) after the fader (and the fade of a stopping set). The master arrives limited already."""
        subs = self.subs.get(name)
        if not subs:
            return
        if not limited:
            y = self.limit[name].process(y)
        b = (np.clip(np.asarray(y, dtype=np.float32).T, -1.0, 1.0) * 32767.0).astype('<i2').tobytes()
        for s in list(subs):
            if s.put(b):
                self.dropped[name] += 1


class _Sub:
    def __init__(self, cap_bytes):
        self.q = collections.deque()
        self.n = 0
        self.cap = cap_bytes
        self.cv = threading.Condition()
        self.closed = False

    def put(self, b):
        dropped = False
        with self.cv:
            self.q.append(b)
            self.n += len(b)
            while self.n > self.cap and len(self.q) > 1:      # too far behind: lose the oldest, never slow the set
                self.n -= len(self.q.popleft())
                dropped = True
            self.cv.notify()
        return dropped

    def get(self, timeout=1.0):
        with self.cv:
            if not self.q:
                self.cv.wait(timeout)
            if not self.q:
                return b''
            out = b''.join(self.q)
            self.q.clear()
            self.n = 0
            return out


# ------------------------------------------------------------------ controls

CURVES = ('linear', 'log', 'switch', 'raw')
DECK_PARAMS = ('volume_db', 'low_db', 'mid_db', 'high_db', 'filter', 'transpose')


def parse_param(target, param):
    """-> ('track'|'bus'|'deck', name, kind, detail). kind: 'volume_db', 'pan', a deck param, or 'fx' with detail
    (index or 'type[:n]', param name)."""
    if target.startswith('deck:'):
        if param not in DECK_PARAMS:
            raise ValueError(f"a deck control drives one of {', '.join(DECK_PARAMS)}, not {param!r}")
        return 'deck', target[5:], param, None
    kind = 'bus' if target.startswith('bus:') else 'track'
    name = target[4:] if kind == 'bus' else target
    if param in ('volume_db', 'pan') and not (kind == 'bus' and param == 'pan'):
        return kind, name, param, None
    if param.startswith('fx:') and '.' in param:
        which, _, p = param[3:].rpartition('.')
        idx = int(which) if which.isdigit() else which
        return kind, name, 'fx', (idx, p)
    raise ValueError(f"param {param!r}: 'volume_db'" + (", 'pan'" if kind == 'track' else '') +
                     ", or an effect param as 'fx:<index or type>.<param>' (e.g. 'fx:filter.cutoff', 'fx:0.mix', "
                     "'fx:delay:2.feedback')")


def scale(value, rng, curve):
    v = float(value)
    if curve == 'raw' or rng is None:
        return v
    lo, hi = float(rng[0]), float(rng[1])
    v = min(1.0, max(0.0, v))
    if curve == 'switch':
        return hi if v >= 0.5 else lo
    if curve == 'log':
        return lo * (hi / lo) ** v
    return lo + (hi - lo) * v


class Controls:
    def __init__(self, log_path):
        self.maps = {}
        self.log_path = log_path
        self.last = {}

    def set(self, control, target, param, rng=None, curve='linear', at='now'):
        if curve not in CURVES:
            raise ValueError(f"curve {curve!r}: one of {', '.join(CURVES)}")
        if curve != 'raw':
            if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
                raise ValueError("range: [value at 0, value at 1] (the control sends 0..1), or curve='raw' to pass "
                                 "the value through in the param's own units")
            if curve == 'log' and (float(rng[0]) <= 0 or float(rng[1]) <= 0):
                raise ValueError("a log curve needs a range above 0 (Hz, a ratio); use linear for dB")
        spec = parse_param(target, param)
        self.maps[control] = {'target': target, 'param': param, 'spec': spec, 'range': rng, 'curve': curve, 'at': at}
        return self.maps[control]

    def log(self, rec):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'a', encoding='utf8') as f:
                f.write(json.dumps(rec) + '\n')
        except OSError:
            pass

    def read(self, control=None):
        if not os.path.exists(self.log_path):
            return []
        out = []
        with open(self.log_path, encoding='utf8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if control is None or r.get('control') == control:
                    out.append(r)
        return out


def describe(m):
    rng = '' if m['curve'] == 'raw' else f" {m['range'][0]:g}..{m['range'][1]:g}"
    return f"{m['target']} {m['param']} ({m['curve']}{rng}" + (f", at {m['at']}" if m['at'] not in ('now', None) else '') + ')'


# ------------------------------------------------------------------ the default output

def default_output_name(timeout=5.0):
    """The system's default output as PortAudio names it now, asked of a fresh process (this one's device list was
    read when it started). None when it cannot tell."""
    code = "import sounddevice as sd; print(sd.query_devices(kind='output')['name'])"
    kw = {}
    if sys.platform == 'win32':
        kw['creationflags'] = 0x08000000 | 0x00004000        # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
    try:
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=timeout, **kw)
        name = r.stdout.strip()
        return name or None
    except (OSError, subprocess.SubprocessError):
        return None
