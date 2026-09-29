"""The live engine: one process that plays a queue of clips forever and takes commands over local HTTP.

Threads: the mixer keeps ~0.3 s of finished audio ahead of the device; the scheduler turns clips into note
events inside a ~4 s horizon and sends each event (a note, or a mono phrase) to render worker processes; the
device callback only copies finished blocks. An event renders once per clip and is reused on every repeat.

Run: python -m ismail.live.engine --project <dir> --bpm 120 [--bpb 4] [--device default|none|<name>] [--workers 2]
Normally started by the live_start op, which also writes <project>/live/engine.json (port, pid).
"""
import argparse
import collections
import copy
import heapq
import json
import math
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from .. import instruments
from ..dsp import SR
from ..notation import NotationError, format_notes, parse_notes, parse_steps, pitch_to_midi, fmt_num
from ..presets import PRESETS
from . import worker
from .safety import Safety
from .timeline import EPS, QueueError, Timeline, fmt_bar

BLOCK = 512
AHEAD_S = 0.3           # finished audio kept ahead of the device
HORIZON_S = 4.0         # how far ahead events are sent to render
AIR_S = 120.0           # output history kept for live_listen
MARGIN_S = 0.5          # render estimate safety margin (quantized launches make this inaudible)
DEFAULT_EVENT_S = 0.3   # per-event render time before a track has measured one


class LiveError(ValueError):
    pass


class Seg:
    __slots__ = ('start', 'y', 'track', 'cid', 'on', 'dead')

    def __init__(self, start, y, track, cid, on):
        self.start, self.y, self.track, self.cid, self.on, self.dead = start, y, track, cid, on, False


def _mono_groups(notes, inst):
    if inst.get('type') == 'synth' and inst.get('mono'):
        groups = []
        for i, (st, _, d, _) in enumerate(notes):
            if groups and st < max(notes[j][0] + notes[j][2] for j in groups[-1]) - EPS:
                groups[-1].append(i)
            else:
                groups.append([i])
        return groups
    return [[i] for i in range(len(notes))]


class Engine:
    def __init__(self, root, bpm, bpb=4, workers=2, device='default'):
        self.root = os.path.abspath(root)
        self.bpm = float(bpm)
        self.bpb = int(bpb)
        self.spb = 60.0 / self.bpm
        self.device = device
        self.lock = threading.RLock()
        self.tl = Timeline(self.bpb)
        self.tracks = {}
        self.meta = {}                  # clip id -> {'groups', 'placed'}
        self.cache = {}                 # (clip id, event) -> array | 'pending' | 'error'
        self.waiting = collections.defaultdict(list)    # (clip id, event) -> [onset beat]
        self.jobs = {}                  # job id -> (clip id, event, track, submitted time)
        self.pending = []               # heap of (start, seq, Seg)
        self.active = []
        self.seq = 0
        self.pos = 0                    # samples mixed
        self.played = 0                 # samples handed to the device
        self.safety = Safety(SR)
        self.air = np.zeros((2, int(AIR_S * SR)), dtype=np.float32)
        self.fade = None                # (start gain, samples left, total) when stopping
        self.gain = 1.0
        self.rec = None
        self.rec_path = None
        self.stats = collections.Counter()
        self.last_late = None
        self.last_underrun = None
        self.last_cmd = time.time()
        self.running = True
        self.stopped = threading.Event()
        self.n_workers = int(workers)
        self._jid = 0
        self._procs = []
        self._fifo = collections.deque()
        self._fifo_n = 0
        self._fifo_lock = threading.Lock()
        self._head = 0
        if self.n_workers > 0:
            import multiprocessing as mp
            ctx = mp.get_context('spawn')
            self._results = ctx.Queue()
            self._tasks = []
            for _ in range(self.n_workers):
                q = ctx.Queue()
                p = ctx.Process(target=worker.main, args=(q, self._results, self.root), daemon=True)
                p.start()
                self._tasks.append(q)
                self._procs.append({'p': p, 'out': 0})
        else:
            bank = worker.SoundBank(self.root)
            instruments.set_resolvers(bank.sound, bank.table)

    # ------------------------------------------------------------------ time
    def beat(self, pos):
        return pos / SR / self.spb

    def sample(self, beat):
        return int(round(beat * self.spb * SR))

    # ------------------------------------------------------------------ rendering
    def _submit(self, key, track, notes_s, lead_s, warm=False):
        tr = self.tracks[track]
        inst = tr['inst']
        self._jid += 1
        jid = self._jid
        self.jobs[jid] = {'key': key, 'track': track, 'warm': warm, 'wi': None, 'gen': tr['gen']}
        if self.n_workers == 0:
            t0 = time.time()
            try:
                y = worker.render_event(inst, notes_s, lead_s, self.bpm, self.root)
                err = worker.check(y)
            except Exception as e:
                y, err = None, f"{type(e).__name__}: {e}"
            self._result(jid, None if err else y, time.time() - t0, err)
            return
        wi = min(range(self.n_workers), key=lambda i: self._procs[i]['out'])
        self._procs[wi]['out'] += 1
        self.jobs[jid]['wi'] = wi
        self._tasks[wi].put((jid, inst, notes_s, lead_s, self.bpm))

    def _warm(self, track):
        """Render one throwaway note on every worker so first-use compilation happens off the air."""
        inst = self.tracks[track]['inst']
        pitch = int(next(iter(inst['map']))) if inst.get('type') == 'kit' else 60
        n = max(1, self.n_workers)
        self.tracks[track]['warming'] += 2 * n
        for i in [k for k in range(n) for _ in range(2)]:
            if self.n_workers == 0:
                self._submit(('warm', track), track, [(0.0, pitch, 0.25, 100)], 0.0, warm=True)
            else:
                self._jid += 1
                self.jobs[self._jid] = {'key': ('warm', track), 'track': track, 'warm': True, 'wi': i,
                                        'gen': self.tracks[track]['gen']}
                self._procs[i]['out'] += 1
                self._tasks[i].put((self._jid, inst, [(0.0, pitch, 0.25, 100)], 0.0, self.bpm))

    def _result(self, jid, y, secs, err):
        with self.lock:
            job = self.jobs.pop(jid, None)
            if job is None:
                return
            key, track, warm = job['key'], job['track'], job['warm']
            if job['wi'] is not None:
                self._procs[job['wi']]['out'] -= 1
            tr = self.tracks.get(track)
            if tr is None or job['gen'] != tr['gen']:      # rendered with an instrument the track no longer has
                return
            if warm:
                if tr:
                    tr['warming'] = max(0, tr['warming'] - 1)
                    tr['warm_s'] = round(secs, 2)
                    if tr['est'] is None or tr['warming'] < max(1, self.n_workers):
                        tr['est'] = secs              # the later warm-ups run compiled: the steady cost
                    if err:
                        tr['errors'].append(f"warm-up: {err}")
                return
            if tr is not None:
                tr['est'] = secs if tr['est'] is None else 0.7 * tr['est'] + 0.3 * secs
            if key not in self.cache:          # clip was replaced or its instrument changed meanwhile
                self.waiting.pop(key, None)
                return
            if err:
                self.cache[key] = 'error'
                self.stats['rejected'] += 1
                if tr is not None:
                    tr['errors'] = (tr['errors'] + [err])[-3:]
                self.waiting.pop(key, None)
                return
            self.cache[key] = y
            for on in self.waiting.pop(key, []):
                self._place(key[0], track, on, y)

    def _collect(self):
        while self.running:
            try:
                jid, y, secs, err = self._results.get(timeout=0.2)
            except Exception:
                continue
            self._result(jid, y, secs, err)

    def _place(self, cid, track, on, y):
        c = self.tl.clips.get(cid)
        if c is None or (c.end is not None and on >= c.end - EPS):
            return
        start = self.sample(on)
        if start < self.pos:
            self.stats['late'] += 1
            self.last_late = f"{track} {fmt_bar(on, self.bpb)} by {(self.pos - start) / SR * 1000:.0f} ms"
            if start + y.shape[1] <= self.pos:
                return
        self.seq += 1
        heapq.heappush(self.pending, (start, self.seq, Seg(start, y, track, cid, on)))

    # ------------------------------------------------------------------ scheduler
    def tick(self):
        with self.lock:
            now = self.beat(self.pos)
            horizon = self.beat(self.pos + int(HORIZON_S * SR))
            gone = set(self.tl.clips)
            self.tl.prune(now)
            gone -= set(self.tl.clips)
            for cid in gone:
                self.meta.pop(cid, None)
                for key in [k for k in self.cache if k[0] == cid]:
                    del self.cache[key]
            todo = []
            for c in list(self.tl.clips.values()):
                m = self.meta[c.id]
                b0 = m['placed'] if m['placed'] is not None else c.start
                if horizon <= b0:
                    continue
                for k, ei, on in self.tl.events(c, b0, horizon, m['groups']):
                    todo.append((on, c, ei))
                m['placed'] = horizon
            for on, c, ei in sorted(todo, key=lambda x: x[0]):     # render in the order they will sound
                key = (c.id, ei)
                have = self.cache.get(key)
                if isinstance(have, np.ndarray):
                    self._place(c.id, c.track, on, have)
                elif have != 'error':
                    self.waiting[key].append(on)
                    if have is None:
                        self.cache[key] = 'pending'
                        g = self.meta[c.id]['groups'][ei]
                        t0 = c.notes[g[0]][0]
                        notes_s = [((c.notes[j][0] - t0) * self.spb, c.notes[j][1], c.notes[j][2] * self.spb,
                                    c.notes[j][3]) for j in g]
                        self._submit(key, c.track, notes_s, (t0 % self.bpb) * self.spb)

    def _schedule_loop(self):
        while self.running:
            try:
                self.tick()
            except Exception:
                traceback.print_exc()
            time.sleep(0.02)

    # ------------------------------------------------------------------ mixer
    def mix_block(self, n=BLOCK):
        p0, p1 = self.pos, self.pos + n
        with self.lock:
            while self.pending and self.pending[0][0] < p1:
                self.active.append(heapq.heappop(self.pending)[2])
            params = {k: (t['gl'], t['gr']) for k, t in self.tracks.items()}
        bufs = {}
        keep = []
        for s in self.active:
            if s.dead or s.track not in params:
                continue
            a, b = max(s.start, p0), min(s.start + s.y.shape[1], p1)
            if b > a:
                buf = bufs.get(s.track)
                if buf is None:
                    buf = bufs[s.track] = np.zeros((2, n))
                buf[:, a - p0:b - p0] += s.y[:, a - s.start:b - s.start]
            if s.start + s.y.shape[1] > p1:
                keep.append(s)
        self.active = keep
        master = np.zeros((2, n))
        with self.lock:
            for name, t in self.tracks.items():
                gl0, gr0 = t['cur']
                gl1, gr1 = params[name] if name in params else (0.0, 0.0)
                t['cur'] = (gl1, gr1)
                buf = bufs.get(name)
                ms = 0.0
                if buf is not None:
                    ramp = np.linspace(0, 1, n)
                    buf[0] *= gl0 + (gl1 - gl0) * ramp
                    buf[1] *= gr0 + (gr1 - gr0) * ramp
                    master += buf
                    ms = float(np.mean(buf ** 2))
                a = math.exp(-n / SR / 0.3)
                t['ms'] = t['ms'] * a + ms * (1 - a)
        if self.fade is not None:
            left, total = self.fade
            g0 = left / total
            g1 = max(0.0, (left - n) / total)
            master *= np.linspace(g0, g1, n)
            self.fade = (max(0, left - n), total)
        y = self.safety.process(master).astype(np.float32)
        i = (p0 - self.safety.la) % self.air.shape[1]      # the limiter delays by its lookahead: keep bars aligned
        j = min(i + n, self.air.shape[1])
        self.air[:, i:j] = y[:, :j - i]
        if j - i < n:
            self.air[:, :n - (j - i)] = y[:, j - i:]
        if self.rec is not None:
            self.rec.write(y.T)
        self.pos = p1
        return y

    def _mix_loop(self):
        ahead = int(AHEAD_S * SR)
        while self.running:
            if self._fifo_n < ahead:
                y = self.mix_block()
                with self._fifo_lock:
                    self._fifo.append(y.T.copy())
                    self._fifo_n += y.shape[1]
            else:
                time.sleep(0.003)
            if self.fade is not None and self.fade[0] == 0 and self._fifo_n == 0:
                self.running = False

    def _pull(self, frames):
        out = np.zeros((frames, 2), dtype=np.float32)
        got = 0
        with self._fifo_lock:
            while got < frames and self._fifo:
                blk = self._fifo[0]
                take = min(frames - got, blk.shape[0] - self._head)
                out[got:got + take] = blk[self._head:self._head + take]
                got += take
                self._head += take
                if self._head >= blk.shape[0]:
                    self._fifo.popleft()
                    self._head = 0
            self._fifo_n -= got
        if got < frames and self.pos > 0 and self.fade is None:
            self.stats['underruns'] += 1
            self.last_underrun = fmt_bar(self.beat(self.played), self.bpb)
        self.played += got
        return out

    def _null_loop(self):
        t0 = time.time()
        done = 0
        while self.running:
            want = int((time.time() - t0) * SR) - done
            if want >= BLOCK:
                self._pull(want)
                done += want
            time.sleep(0.005)

    def start(self):
        threads = [self._schedule_loop, self._mix_loop]
        if self.n_workers:
            threads.append(self._collect)
        for fn in threads:
            threading.Thread(target=fn, daemon=True).start()
        if self.device in (None, 'none', 'null'):
            threading.Thread(target=self._null_loop, daemon=True).start()
            self.stream = None
        else:
            import sounddevice as sd

            def cb(outdata, frames, t, status):
                outdata[:] = self._pull(frames)
            dev = None if self.device in ('default', '') else (int(self.device) if str(self.device).isdigit() else self.device)
            self.stream = sd.OutputStream(samplerate=SR, channels=2, dtype='float32', callback=cb, device=dev,
                                          latency='high')
            self.stream.start()

    def shutdown(self):
        self.running = False
        if getattr(self, 'stream', None) is not None:
            self.stream.stop()
            self.stream.close()
        if self.rec is not None:
            self.rec.close()
            self.rec = None
        for q in getattr(self, '_tasks', []):
            q.put(None)
        self.stopped.set()

    # ------------------------------------------------------------------ commands
    def _resolve_instrument(self, spec):
        if isinstance(spec, str) and spec.startswith('track:'):
            try:
                with open(os.path.join(self.root, 'project.json'), encoding='utf8') as f:
                    tracks = json.load(f)['tracks']
            except (OSError, ValueError, KeyError):
                raise LiveError(f"instrument {spec!r}: the live folder {self.root} has no project.json with tracks")
            if spec[6:] not in tracks or not tracks[spec[6:]].get('instrument'):
                raise LiveError(f"instrument {spec!r}: project tracks with instruments: "
                                f"{[k for k, v in tracks.items() if v.get('instrument')]}")
            spec = copy.deepcopy(tracks[spec[6:]]['instrument'])
        elif isinstance(spec, str):
            name = spec[7:] if spec.startswith('preset:') else spec
            if name not in PRESETS:
                raise LiveError(f"unknown preset {name!r}; presets: {', '.join(PRESETS)} (or pass an instrument dict)")
            spec = copy.deepcopy(PRESETS[name])
        if not isinstance(spec, dict):
            raise LiveError("instrument: a dict, 'preset:<name>' or 'track:<project track>'")
        if spec.get('fx'):
            raise LiveError("live tracks have no effects yet (effects are the next milestone); drop 'fx' and shape the "
                            "tone inside the instrument")
        try:
            # voice modules are checked by the op before they get here: importing one in this process could hold
            # the GIL for seconds and starve the audio
            inst = instruments.normalize(spec)
        except (instruments.InstrumentError, ValueError) as e:
            raise LiveError(f"instrument invalid: {e}")
        return inst

    def cmd_track(self, track, instrument=None, volume_db=None, pan=None, remove=False, at='next_bar'):
        with self.lock:
            now = self.beat(self.pos)
            if remove:
                if track not in self.tracks:
                    raise LiveError(f"no live track {track!r}; tracks: {list(self.tracks) or 'none'}")
                self.tl.claim(track, now)
                for s in self.active + [p[2] for p in self.pending]:
                    if s.track == track:
                        s.dead = True
                del self.tracks[track]
                return f"removed track {track}"
            msg = []
            if track not in self.tracks:
                if instrument is None:
                    raise LiveError(f"new track {track!r} needs an instrument: a dict, 'preset:<name>' (presets_list) "
                                    f"or {{'type': 'code', 'voice': '<name>'}} (voices_list)")
                self.tracks[track] = {'inst': None, 'volume_db': 0.0, 'pan': 0.0, 'gl': 0.0, 'gr': 0.0, 'cur': (0.0, 0.0),
                                      'ms': 0.0, 'est': None, 'warming': 0, 'warm_s': None, 'errors': [], 'gen': 0}
                msg.append(f"new track {track}")
            tr = self.tracks[track]
            if instrument is not None:
                inst = self._resolve_instrument(instrument)
                old = tr['inst']
                tr['inst'] = inst
                tr['errors'] = []
                tr['gen'] += 1
                tr['warming'] = 0
                if old is not None:
                    # the new sound takes over at `at`: drop events from there on and render them again
                    onsets = sorted({c.notes[g[0]][0] for c in self.tl.track_clips(track) for g in _mono_groups(c.notes, inst)})
                    beat, _ = self.tl.resolve_at(at, now, now + self._lead_beats(track, onsets[:8]))
                    for s in self.active + [p[2] for p in self.pending]:
                        if s.track == track and s.on >= beat - EPS:
                            s.dead = True
                    for c in self.tl.track_clips(track):
                        for key in [k for k in self.cache if k[0] == c.id]:
                            del self.cache[key]
                            self.waiting.pop(key, None)
                        m = self.meta[c.id]
                        m['groups'] = _mono_groups(c.notes, inst)
                        m['placed'] = max(beat, c.start) if m['placed'] is not None else None
                    msg.append(f"instrument changed from {fmt_bar(beat, self.bpb)}")
                self._warm(track)
                msg.append(f"{inst['type']}" + (f" voice {inst['voice']}" if inst.get('voice') else '') + ", warming up")
            if volume_db is not None:
                if volume_db > 6:
                    raise LiveError(f"volume_db {volume_db:g} is above the +6 dB fader limit; lower the others instead")
                tr['volume_db'] = float(volume_db)
            if pan is not None:
                tr['pan'] = max(-1.0, min(1.0, float(pan)))
            g = 10 ** (tr['volume_db'] / 20)
            th = (tr['pan'] + 1) * math.pi / 4
            tr['gl'], tr['gr'] = g * math.cos(th) * math.sqrt(2), g * math.sin(th) * math.sqrt(2)
            msg.append(f"vol {tr['volume_db']:g} dB, pan {tr['pan']:g}")
            return f"{track}: " + ', '.join(msg)

    def _lead_beats(self, track, onsets, extra=0):
        """Beats a new clip on `track` must start after now so that each event (sorted onsets, in beats from the
        clip start) is rendered before it sounds; events render in onset order across the workers."""
        tr = self.tracks[track]
        per = tr['est'] if tr['est'] is not None else DEFAULT_EVENT_S
        w = max(1, self.n_workers)
        backlog = sum(1 for j in self.jobs.values() if not j['warm']) + extra
        warm = (tr['warm_s'] or 2.0) if tr['warming'] else 0.0
        need = 0.0
        for i, on in enumerate(onsets[:64]):
            done_s = MARGIN_S + warm + (backlog + i + 1) * per / w
            need = max(need, done_s / self.spb - on)
        return need

    def _parse_clip(self, i, it):
        if not isinstance(it, dict) or 'track' not in it:
            raise LiveError(f"clip [{i}]: each item is a dict with 'track' and 'notes' and/or 'lanes' (or 'stop': true)")
        track = it['track']
        if track not in self.tracks:
            raise LiveError(f"clip [{i}]: no live track {track!r}; create it with live_track(project, track="
                            f"'{track}', instrument=...). Live tracks: {list(self.tracks) or 'none'}")
        known = {'track', 'notes', 'lanes', 'step', 'bars', 'beats', 'loop', 'at', 'stop'}
        extra = set(it) - known
        if extra:
            raise LiveError(f"clip [{i}]: unknown keys {sorted(extra)}; valid: {sorted(known)}")
        if it.get('stop'):
            return track, None, None, None
        notes = []
        try:
            if it.get('notes'):
                notes += parse_notes(it['notes'])
            span = max((s + d for s, _, d, _ in notes), default=0.0)
            for pitch, pat in (it.get('lanes') or {}).items():
                m = pitch_to_midi(pitch)
                hits, length = parse_steps(pat, float(it.get('step', 0.25)))
                notes += [(s, m, d, v) for s, d, v in hits]
                span = max(span, length)
        except NotationError as e:
            raise LiveError(f"clip [{i}]: {e}")
        if not notes:
            raise LiveError(f"clip [{i}]: no notes. Give notes='<beat> <pitch> <dur> [vel]; ...' or lanes={{'C1': "
                            f"'x...x...'}}, or 'stop': true to silence the track")
        if it.get('beats') is not None:
            length = float(it['beats'])
        elif it.get('bars') is not None:
            length = float(it['bars']) * self.bpb
        else:
            length = max(1, math.ceil(span / self.bpb - 1e-9)) * self.bpb
        late = [s for s, _, _, _ in notes if s >= length - EPS]
        if late:
            raise LiveError(f"clip [{i}]: notes start at beat {fmt_num(max(late))} but the clip is {fmt_num(length)} "
                            f"beats long; raise bars/beats or drop those notes")
        loop = it.get('loop')
        if loop in (None, 'forever', 0):
            loop = None
        else:
            try:
                loop = int(loop)
                assert loop >= 1
            except (ValueError, AssertionError):
                raise LiveError(f"clip [{i}]: loop={it.get('loop')!r}; use a count >= 1 or 'forever'")
        return track, notes, length, loop

    def cmd_queue(self, clips):
        if not isinstance(clips, list) or not clips:
            raise LiveError("clips: a list of {track, notes | lanes, bars, loop, at} (or {track, stop: true, at})")
        parsed = [self._parse_clip(i, it) + (it.get('at') or 'next_bar',) for i, it in enumerate(clips)]
        with self.lock:
            now = self.beat(self.pos)
            tl = copy.deepcopy(self.tl)
            claims, lines, added = [], [], []
            extra = 0                        # events of earlier clips in this batch, rendered alongside
            for i, (track, notes, length, loop, at) in enumerate(parsed):
                inst = self.tracks[track]['inst']
                onsets = [notes[g[0]][0] for g in _mono_groups(sorted(notes), inst)] if notes else []
                ready = now + self._lead_beats(track, onsets, extra)
                extra += len(onsets)
                try:
                    beat, note = tl.resolve_at(at, now, ready if notes else now)
                except QueueError as e:
                    raise LiveError(f"clip [{i}] ({track}): {e}. Nothing was queued.")
                removed, cut = tl.claim(track, beat)
                claims.append((track, beat, set(removed) | set(cut)))
                what = []
                if cut:
                    what.append(f"cuts {', '.join(cut)} there")
                if removed:
                    what.append(f"replaces queued {', '.join(removed)}")
                if notes is None:
                    tl.stop(track, beat)
                    lines.append(f"stop {track} at {fmt_bar(beat, self.bpb)}" + (f"; {'; '.join(what)}" if what else '')
                                 + (f"\n  note: {note}" if note else ''))
                    continue
                c = tl.add(track, notes, length, loop, beat, at)
                added.append(c)
                bars = length / self.bpb
                lines.append(f"{c.id} {track}: {fmt_bar(beat, self.bpb)} ({at}), {fmt_num(bars)} bars x "
                             f"{'forever' if loop is None else loop}, {len(notes)} notes"
                             + (f"; ends {fmt_bar(c.end, self.bpb)}" if c.end is not None else '')
                             + (f"; {'; '.join(what)}" if what else '') + (f"\n  note: {note}" if note else ''))
            self.tl = tl
            for track, beat, ids in claims:
                for s in self.active + [p[2] for p in self.pending]:
                    if s.cid in ids and s.on >= beat - EPS:
                        s.dead = True
            for c in added:
                self.meta[c.id] = {'groups': _mono_groups(c.notes, self.tracks[c.track]['inst']), 'placed': None}
            for cid in list(self.meta):
                if cid not in self.tl.clips:
                    self.meta.pop(cid)
        self.tick()
        return '\n'.join(lines) + '\n' + self._runway()

    def cmd_cancel(self, clips):
        out = []
        with self.lock:
            now = self.beat(self.pos)
            for cid in clips:
                try:
                    c = self.tl.cancel(cid, now)
                except QueueError as e:
                    raise LiveError(str(e))
                self.meta.pop(cid, None)
                for s in [p[2] for p in self.pending]:
                    if s.cid == cid:
                        s.dead = True
                out.append(f"cancelled {cid} ({c.track}, was due {fmt_bar(c.start, self.bpb)})")
        return '\n'.join(out) + '\n' + self._runway()

    def _runway(self):
        now = self.beat(self.pos)
        last = self.tl.last_change(now)
        loops = []
        for t in self.tracks:
            cs = self.tl.track_clips(t)
            if cs and cs[-1].end is None:
                loops.append(f"{t} {cs[-1].id}")
        tail = f"after that: {', '.join(loops)} loop forever" if loops else "after that: silence"
        if last is None:
            return f"runway: nothing scheduled to change; {tail}"
        return f"runway: last scheduled change at {fmt_bar(last, self.bpb)} (in {(last - now) * self.spb:.1f} s); {tail}"

    def cmd_status(self):
        with self.lock:
            now = self.beat(self.pos)
            heard = self.beat(self.played)
            lines = [f"live {fmt_num(self.bpm)} BPM {self.bpb}/4 | heard {fmt_bar(math.floor(heard), self.bpb)} "
                     f"({self.played / SR:.0f} s) | mixed ahead {max(0.0, (self.pos - self.played) / SR):.2f} s | "
                     f"device {self.device}" + (f" | recording {os.path.basename(self.rec_path)}" if self.rec else '')]
            lines.append("safety: " + self.safety.report())
            lines.append("tracks:" if self.tracks else "tracks: none (live_track to add one)")
            for name, t in self.tracks.items():
                lvl = 10 * math.log10(t['ms'] + 1e-12)
                inst = t['inst']
                what = inst['type'] + (f":{inst['voice']}" if inst.get('voice') else '')
                cs = self.tl.track_clips(name)
                play = self.tl.playing(name, now)
                nxt = [c for c in cs if c.start > now + EPS]
                seg = f"playing {play.id}" if play else "silent"
                if play:
                    k = int((now - play.start) // play.length) + 1
                    seg += f" (pass {k}/{'inf' if play.loop is None else play.loop})"
                if nxt:
                    seg += f", next {nxt[0].id} at {fmt_bar(nxt[0].start, self.bpb)}"
                stops = self.tl.stops.get(name)
                if stops:
                    seg += f", stop at {fmt_bar(stops[0], self.bpb)}"
                est = f"{t['est']:.2f} s/event" if t['est'] is not None else "no renders yet"
                lines.append(f"  {name:<10} {what:<22} vol {t['volume_db']:+g} pan {t['pan']:+g} "
                             f"level {lvl:6.1f} dBFS | {seg} | {est}" + (" | WARMING" if t['warming'] else ''))
                for e in t['errors']:
                    lines.append(f"      ERROR {e}")
            lines.append(self._runway())
            backlog = sum(1 for j in self.jobs.values() if not j['warm'])
            lines.append(f"render: {self.n_workers or 'inline'} workers, backlog {backlog}, late events "
                         f"{self.stats['late']}" + (f" (last: {self.last_late})" if self.last_late else '') +
                         f", rejected {self.stats['rejected']}, underruns {self.stats['underruns']}" +
                         (f" (last at {self.last_underrun})" if self.last_underrun else ''))
            return '\n'.join(lines)

    def cmd_view(self, bars=8, clip=None):
        with self.lock:
            if clip:
                c = self.tl.clips.get(clip)
                if c is None:
                    raise LiveError(f"no clip {clip!r} (finished clips are forgotten); clips: {sorted(self.tl.clips)}")
                head = (f"{c.id} on {c.track}: starts {fmt_bar(c.start, self.bpb)}, {fmt_num(c.length / self.bpb)} bars x "
                        f"{'forever' if c.loop is None else c.loop}" +
                        (f", ends {fmt_bar(c.end, self.bpb)}" if c.end is not None else '') + f" (at={c.at})")
                return head + '\nnotes (bar = bar within the clip):\n' + format_notes(c.notes, self.bpb)
            now = self.beat(self.pos)
            b0 = int(now // self.bpb) + 1
            n = max(1, min(int(bars), 64))
            lines = [f"bars {b0}-{b0 + n - 1} (now {fmt_bar(math.floor(now), self.bpb)}); a cell = the clip sounding at the bar's "
                     f"downbeat, '.' silent, '|' marks every 4 bars"]
            head = ''.join(f"{b:<5}" + ('| ' if (b % 4 == 0) else '') for b in range(b0, b0 + n))
            lines.append(f"{'':<10} {head}")
            for name in self.tracks:
                cells = []
                for b in range(b0, b0 + n):
                    c = self.tl.playing(name, (b - 1) * self.bpb)
                    cells.append(f"{(c.id if c else '.'):<5}" + ('| ' if (b % 4 == 0) else ''))
                lines.append(f"{name:<10} {''.join(cells)}")
            lines.append(self._runway())
            return '\n'.join(lines)

    def cmd_listen_dump(self, bars=4):
        with self.lock:
            done = int(self.beat(self.pos) // self.bpb)          # bars 1..done are fully mixed
            if done < 1:
                raise LiveError("no complete bar has played yet; wait one bar and call again")
            keep = int(AIR_S / (self.bpb * self.spb))
            n = max(1, min(int(bars), done, keep, 32))
            first = done - n + 1
            s0 = self.sample((first - 1) * self.bpb)
            s1 = self.sample(done * self.bpb)
            N = self.air.shape[1]
            idx = np.arange(s0, s1) % N
            y = self.air[:, idx]
        import soundfile as sf
        os.makedirs(os.path.join(self.root, 'live'), exist_ok=True)
        path = os.path.join(self.root, 'live', 'listen.wav')
        sf.write(path, y.T, SR)
        return {'path': path, 'first': first, 'last': done, 'bpm': self.bpm, 'bpb': self.bpb}

    def cmd_record(self, on=True):
        import soundfile as sf
        with self.lock:
            if on and self.rec is None:
                d = os.path.join(self.root, 'live')
                os.makedirs(d, exist_ok=True)
                self.rec_path = os.path.join(d, time.strftime('rec_%Y%m%d_%H%M%S.wav'))
                self.rec = sf.SoundFile(self.rec_path, 'w', SR, 2, 'PCM_24')
                self.rec_from = self.pos
                return f"recording to {self.rec_path} from {fmt_bar(self.beat(self.pos), self.bpb)}"
            if not on and self.rec is not None:
                self.rec.close()
                self.rec = None
                return f"stopped recording: {self.rec_path} ({(self.pos - self.rec_from) / SR:.1f} s)"
            return "recording already " + ("on: " + self.rec_path if self.rec else "off")

    def cmd_stop(self, fade_s=1.0):
        with self.lock:
            n = max(1, int(float(fade_s) * SR))
            self.fade = (n, n)
        threading.Thread(target=self._finish, daemon=True).start()
        return f"fading out over {fade_s:g} s and stopping"

    def _finish(self):
        while self.running and not (self.fade and self.fade[0] == 0):
            time.sleep(0.05)
        time.sleep(AHEAD_S + 0.3)
        self.shutdown()


# ------------------------------------------------------------------ control server

def serve(engine, port=0, idle_min=None):
    idle_min = float(os.environ.get('ISMAIL_LIVE_IDLE_MIN', 60)) if idle_min is None else idle_min
    ops = {'status': engine.cmd_status, 'track': engine.cmd_track, 'queue': engine.cmd_queue,
           'cancel': engine.cmd_cancel, 'view': engine.cmd_view, 'listen': engine.cmd_listen_dump,
           'record': engine.cmd_record, 'stop': engine.cmd_stop}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                engine.last_cmd = time.time()
                fn = ops.get(req.get('op'))
                if fn is None:
                    res = {'ok': False, 'error': f"unknown op {req.get('op')!r}; ops: {sorted(ops)}"}
                else:
                    res = {'ok': True, 'result': fn(**(req.get('args') or {}))}
            except (LiveError, QueueError) as e:
                res = {'ok': False, 'error': str(e)}
            except TypeError as e:
                res = {'ok': False, 'error': f"bad arguments: {e}"}
            except Exception as e:
                traceback.print_exc()
                res = {'ok': False, 'error': f"engine error {type(e).__name__}: {e}"}
            body = json.dumps(res).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(('127.0.0.1', port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def idle():
        while not engine.stopped.is_set():
            if time.time() - engine.last_cmd > idle_min * 60 and engine.fade is None:
                print(f"no commands for {idle_min:g} min: stopping", flush=True)
                engine.cmd_stop(3.0)
            time.sleep(5)
    threading.Thread(target=idle, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', required=True)
    ap.add_argument('--bpm', type=float, required=True)
    ap.add_argument('--bpb', type=int, default=4)
    ap.add_argument('--device', default='default')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--port', type=int, default=0)
    a = ap.parse_args()
    import scipy.signal  # noqa: F401  (seconds to import: do it before audio starts, never mid-set)
    eng = Engine(a.project, a.bpm, a.bpb, a.workers, a.device)
    httpd = serve(eng, a.port)
    eng.start()
    d = os.path.join(eng.root, 'live')
    os.makedirs(d, exist_ok=True)
    info = os.path.join(d, 'engine.json')
    with open(info, 'w', encoding='utf8') as f:
        json.dump({'port': httpd.server_address[1], 'pid': os.getpid(), 'bpm': a.bpm, 'bpb': a.bpb,
                   'device': a.device, 'started': time.time()}, f)
    print(f"live engine on 127.0.0.1:{httpd.server_address[1]} ({a.bpm:g} BPM)", flush=True)
    try:
        eng.stopped.wait()
    except KeyboardInterrupt:
        eng.shutdown()
    finally:
        httpd.shutdown()
        try:
            os.remove(info)
        except OSError:
            pass


if __name__ == '__main__':
    main()
