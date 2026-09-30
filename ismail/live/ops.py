"""live_* ops: the agent's controls for the live engine (registered into api.OPS on import).

Each op talks to the engine process of a project over local HTTP; live_start launches it."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from ..api import OpError, op
from .. import analysis as A

VIEWS = {'bars': A.bar_table, 'envelope': A.envelope, 'pitches': A.pitches, 'drums': A.drums, 'chords': A.chords}


def _info_path(project):
    return os.path.join(os.path.abspath(project), 'live', 'engine.json')


def _call(project, name, timeout=30, **args):
    try:
        with open(_info_path(project), encoding='utf8') as f:
            port = json.load(f)['port']
    except (OSError, ValueError, KeyError):
        raise OpError(f"no live engine for {project}; start one with live_start(project='{project}', bpm=...)")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=json.dumps({'op': name, 'args': args}).encode(),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise OpError(f"the live engine for {project} does not answer ({e}); it may have stopped. live_start again "
                      f"(its log is {os.path.join(os.path.abspath(project), 'live', 'engine.log')})")
    if not res.get('ok'):
        raise OpError(res.get('error', 'engine error'))
    return res['result']


def _alive(project):
    try:
        _call(project, 'status', timeout=3)
        return True
    except OpError:
        return False


@op()
def live_start(project: str, bpm: float, beats_per_bar: int = 4, device: str = 'default', workers: int = None) -> str:
    """Start the live engine for `project` (any folder; a project.json there lends its sound bank, song voices and
    'track:<name>' instruments). It plays from bar 1 immediately, silent until you queue clips, and keeps playing
    between your calls: clips loop until replaced. Tempo is fixed for the run (live_stop, then start again to change
    it). device: 'default' (speakers), a device name/index, or 'none' (no audio out; for testing and listen-only
    analysis). workers: render processes (default: cores - 4, from 2 to 4; more for many mimic voices). Output always passes a limiter and loudness cap you cannot raise. Next: live_track, then live_queue."""
    root = os.path.abspath(project)
    if workers is None:
        workers = min(4, max(2, (os.cpu_count() or 4) - 4))
    if _alive(project):
        return "already running (live_stop first to change tempo or device)\n" + _call(project, 'status')
    if str(device).lower() not in ('none', 'null'):
        try:
            import sounddevice  # noqa: F401
        except (ImportError, OSError) as e:
            raise OpError(f"playing to speakers needs sounddevice ({e}): pip install -e \".[live]\" (on Linux also "
                          f"PortAudio: sudo apt install libportaudio2), or start with device='none' to run without "
                          f"audio out")
    os.makedirs(os.path.join(root, 'live'), exist_ok=True)
    try:
        os.remove(_info_path(project))
    except OSError:
        pass
    pkg_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, PYTHONPATH=pkg_root + os.pathsep + os.environ.get('PYTHONPATH', ''))
    log = open(os.path.join(root, 'live', 'engine.log'), 'w', encoding='utf8')
    flags = 0
    if os.name == 'nt':
        # a hidden console, not none: the render workers inherit it instead of each opening a window
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, '-m', 'ismail.live.engine', '--project', root, '--bpm', str(bpm),
                      '--bpb', str(beats_per_bar), '--device', str(device), '--workers', str(workers)],
                     cwd=pkg_root, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    t0 = time.time()
    while time.time() - t0 < 60:
        if os.path.exists(_info_path(project)) and _alive(project):
            return f"live engine started ({time.time() - t0:.1f} s)\n" + _call(project, 'status')
        time.sleep(0.3)
    raise OpError(f"the live engine did not come up in 60 s; read {os.path.join(root, 'live', 'engine.log')}")


@op()
def live_stop(project: str, fade_sec: float = 1.0) -> str:
    """Fade out and stop the live engine (closes any recording)."""
    return _call(project, 'stop', fade_s=fade_sec)


@op()
def live_status(project: str, deck: str = None) -> str:
    """Where the live set is: bar heard, each deck (on air or cued, fader, eq, filter, level, song), each track
    not on a deck (instrument, fader, level, playing/next clip, render cost, errors), the safety chain's gain
    reduction since the last status, runway (the last scheduled change and what loops after it) and render health
    (backlog, late events, underruns). deck='B' lists that deck's tracks and buses instead."""
    return _call(project, 'status', deck=deck)


def _project_fx(project, spec):
    """'track:<name>' | 'bus:<name>' -> that chain from the folder's project.json."""
    try:
        with open(os.path.join(os.path.abspath(project), 'project.json'), encoding='utf8') as f:
            d = json.load(f)
    except (OSError, ValueError):
        raise OpError(f"fx={spec!r} copies a chain from project.json, but {project} has none")
    kind, name = spec.split(':', 1)
    src = d.get('tracks' if kind == 'track' else 'buses', {}).get(name)
    if src is None:
        raise OpError(f"fx={spec!r}: project.json has no {kind} {name!r}")
    return src.get('fx', [])


def _mark_performer(inst, project):
    """A code voice whose module has perform() and no voice function plays whole phrases: flag it so the engine
    groups overlapping notes into one event and passes clip expr lanes (the module is imported here, in the op
    process, never in the engine)."""
    if not isinstance(inst, dict) or inst.get('type') != 'code' or not inst.get('voice'):
        return inst
    from .. import voices
    try:
        mod = voices.load(inst['voice'], os.path.abspath(project))
    except Exception:
        return inst
    if callable(getattr(mod, 'perform', None)) and not callable(getattr(mod, inst.get('fn') or 'voice', None)):
        return dict(inst, performer=True)
    return inst


@op()
def live_track(project: str, track: str, instrument=None, volume_db: float = None, pan: float = None,
               fx=None, sends: dict = None, remove: bool = False, at: str = 'next_bar', deck: str = None) -> str:
    """Create or change a live track. instrument: a dict (instrument_help), 'preset:<name>' (presets_list),
    {'type': 'code', 'voice': '<name>'} (voices_list) or 'track:<name>' (copy from the folder's project.json).
    fx: the track's whole effect chain, a list of effect dicts (fx_help), or 'track:<name>' to copy a project
    track's chain; [] removes all. Sidechain/duck/vocoder sources must be live tracks. sends: {bus: dB} replaces
    the track's sends (post-fader; live_bus creates buses). A new instrument or chain on a playing track takes
    over at `at` (live_queue values, or 'now'); a replaced chain's tail rings out. New instruments warm up off the
    air first (live_status shows WARMING). volume_db <= +6. remove=True silences and deletes the track now.
    To move one effect param (a sweep, a fade), use live_fx instead of resending the chain. deck='B' puts a new
    track on deck B (created if needed): it then plays through that deck's strip and cue."""
    if isinstance(fx, str):
        if not fx.startswith(('track:', 'bus:')):
            raise OpError("fx: a list of effect dicts, or 'track:<name>' / 'bus:<name>' to copy from project.json")
        fx = _project_fx(project, fx)
    if instrument is not None:
        from .. import api
        P = api.Project(project) if os.path.exists(os.path.join(os.path.abspath(project), 'project.json')) else None
        if isinstance(instrument, str) and instrument.startswith('track:') and P is None:
            raise OpError(f"instrument {instrument!r} copies a project track, but {project} has no project.json; "
                          f"pass a dict or 'preset:<name>'")
        # a folder without project.json still has song voices in <folder>/voices: check against that root
        instrument = api._resolve_instrument(instrument, P or type('Root', (), {'root': os.path.abspath(project)})())
        instrument = _mark_performer(instrument, project)
    return _call(project, 'track', track=track, instrument=instrument, volume_db=volume_db, pan=pan, remove=remove,
                 at=at, fx=fx, sends=sends, deck=deck)


@op()
def live_deck(project: str, deck: str, volume_db: float = None, low_db: float = None, mid_db: float = None,
              high_db: float = None, filter: float = None, transpose: int = None, cue: bool = None,
              ramp_beats: float = 0, at: str = 'now', remove: bool = False) -> str:
    """A deck's channel strip (a deck = a group of tracks, e.g. a loaded song). volume_db: fader (-60 or less =
    off). low_db / mid_db / high_db: 3-band isolator, bands split at 250 Hz and 2.5 kHz; -40 or less kills the
    band. filter: one knob, -1 (low-pass closed) .. 0 (off) .. +1 (high-pass closed). These glide over ramp_beats
    from `at` ('now' or a live_queue value), like live_fx. transpose: semitones for the deck's pitched tracks
    (drums stay), from `at`. cue=True takes the deck off the air (live_listen(deck=...) still hears it: prepare
    the next part there); cue=False puts it on air. remove=True deletes the deck and its tracks."""
    return _call(project, 'deck', deck=deck, volume_db=volume_db, low_db=low_db, mid_db=mid_db, high_db=high_db,
                 filter=filter, transpose=transpose, cue=cue, ramp_beats=ramp_beats, at=at, remove=remove)


@op()
def live_load(project: str, deck: str, song: str, bars: list = None, at: str = 'next_bar', loop: bool = True,
              cue: bool = None) -> str:
    """Load an ismail song (its project folder: tracks, instruments, effects, buses, notes) onto a deck; every
    track starts on the same bar. bars=[a, b] takes a section. It plays at the house tempo (re-rendered, not
    time-stretched) and loops unless loop=False. Cued (off air) by default while another deck is on air: listen
    with live_listen(deck=...), then bring it in with live_transition. The song's mix comes over as rendered:
    its automation (effect params and volume as ramps, instrument params rendered with the notes, the master fade;
    repeated every pass on a looping deck) and its group buses (a reverb on a drum bus keeps the dry drums). Placed
    audio clips and the master effect chain do not (the reply lists what was left out). Loading replaces what a
    cued deck held."""
    if not os.path.isabs(song):
        cand = os.path.join(os.path.abspath(project), song)
        song = cand if os.path.exists(cand) else os.path.abspath(song)
    return _call(project, 'load', deck=deck, song=song, bars=bars, at=at, loop=loop, cue=cue, timeout=120)


@op()
def live_transition(project: str, to: str, from_deck: str = None, at: str = 'next_8', bars: int = 16,
                    style: str = 'blend', stop_from: bool = True) -> str:
    """Queue a mix from one deck to another as ramps on their strips, starting at `at` (a phrase boundary).
    style: blend (new deck fades up without bass, bass swap half-way, old fades out) | bass_swap (both full, one
    bass at a time, old leaves in the last quarter) | filter (old thins out through a rising high-pass while the
    new opens from a low-pass) | cut (switch on the boundary). The `to` deck must be playing by then (live_load
    or live_queue it first, cued); it goes on air at the start. from_deck defaults to the one deck on air. With
    stop_from, the old deck's tracks stop when the transition ends. The reply is the timeline of every move."""
    return _call(project, 'transition', to=to, from_deck=from_deck, at=at, bars=bars, style=style,
                 stop_from=stop_from)


@op()
def live_bus(project: str, bus: str, fx=None, volume_db: float = None, remove: bool = False, at: str = 'now') -> str:
    """Create or change a send bus (a shared effect such as one hall for many tracks; tracks feed it with
    live_track(sends={bus: dB})). fx: its chain (list, or 'bus:<name>' / 'track:<name>' to copy from project.json);
    reverbs and delays on a bus output only the wet signal unless given 'dry'. A replaced chain's tail rings out.
    remove=True deletes it and the sends into it."""
    if isinstance(fx, str):
        if not fx.startswith(('track:', 'bus:')):
            raise OpError("fx: a list of effect dicts, or 'track:<name>' / 'bus:<name>' to copy from project.json")
        fx = _project_fx(project, fx)
    return _call(project, 'bus', bus=bus, fx=fx, volume_db=volume_db, remove=remove, at=at)


@op()
def live_fx(project: str, target: str, index: int, params: dict, ramp_beats: float = 0, at: str = 'now') -> str:
    """Change params of one effect in a live chain. target: a track, or 'bus:<name>'; index: 0-based position in
    its chain (live_status lists chains). Automatable params (fx_help lists them: cutoff, mix, gain_db, depth ...)
    glide from their current value to the new one over ramp_beats, starting at `at` ('now' or a live_queue
    value): one call = a filter sweep over 8 bars, a fade, a build. Frequencies glide in log space. Other params
    rebuild that chain at `at` (the old tail rings out)."""
    return _call(project, 'fx', target=target, index=index, params=params, ramp_beats=ramp_beats, at=at)


@op()
def live_queue(project: str, clips: list) -> str:
    """Queue clips (a batch; all or nothing). Each clip: {track, notes and/or lanes, bars, loop, at}.
      notes: '<beat> <pitch> <dur_beats> [vel]; ...' with beats from the clip start (same as notes_write).
      lanes: {pitch: 'x...x...'} step strings (same as pattern_write), step = beats per char (0.25).
      bars (or beats, for odd lengths): clip length; default = whole bars covering the notes. It repeats every length.
      loop: repeats before it ends (default 'forever': it plays until something replaces it).
      expr: {lane: [[beat, value], ...]} expression for a performer voice (bend in semitones, vib in cents ...),
          beats from the clip start; the voice's INFO lists its lanes.
      at: next_bar (default) | next_beat | next_2 | next_4 | next_8 | next_16 (phrase boundaries counted from bar 1)
          | asap | bar:<n> | after:<clip id> (when that clip ends; chain clips to pre-program an arc)
          | after:#<k> (when item k of this same batch ends: a whole arc in one call, no ids needed).
    A clip on a track replaces whatever that track would play from its start (a playing clip is cut there; its
    last notes ring out). {track, stop: true, at} silences a track. The reply gives each clip's id and the exact
    bar it lands on (moved later when its first notes cannot render in time) and the runway: how long until the
    queue stops changing. Before a long job (sound design, fitting), queue enough that the runway covers it."""
    return _call(project, 'queue', clips=clips)


@op()
def live_cancel(project: str, clips: list) -> str:
    """Remove clips that have not started yet (ids from live_queue / live_view). A playing clip cannot be
    cancelled: queue {track, stop: true} or a replacement instead."""
    return _call(project, 'cancel', clips=clips)


@op()
def live_view(project: str, bars: int = 8, clip: str = None) -> str:
    """The queue ahead: which clip each track plays at each bar for the next `bars` bars (max 64), plus the
    runway. clip='c3' shows that clip's notes and timing instead."""
    return _call(project, 'view', bars=bars, clip=clip)


@op()
def live_listen(project: str, bars=4, view: str = 'bars', band: str = None, recording: str = None,
                deck: str = None) -> str:
    """Hear the live output: analyse the last `bars` complete bars (max 32; bar numbers are the live set's).
    view: bars (level, bands, centroid, onsets, chord per bar) | envelope (level per 16th, max 8 bars; band=
    sub|bass|lowmid|mid|himid|air) | pitches | drums | chords. This is the audio after the safety chain.
    recording='rec_<time>.wav' (in <project>/live/) analyses a finished live_record take instead, with bars=[a, b]
    in the set's own bar numbers; works after live_stop too. deck='B' hears only that deck, after its strip, even
    while it is cued (off the air): the headphones for preparing the next part."""
    if view not in VIEWS:
        raise OpError(f"view={view!r}; use one of {', '.join(VIEWS)}")
    if recording:
        path = recording if os.path.isabs(recording) else os.path.join(os.path.abspath(project), 'live', recording)
        try:
            with open(path[:-4] + '.json', encoding='utf8') as f:
                meta = json.load(f)
        except (OSError, ValueError):
            raise OpError(f"no recording {path} with its .json sidecar; recordings: " + ', '.join(
                sorted(x for x in os.listdir(os.path.join(os.path.abspath(project), 'live')) if x.endswith('.wav'))))
        bpb, first = meta['beats_per_bar'], meta['first_bar']
        g = A.Grid(meta['bpm'], -(first - 1) * bpb * 60.0 / meta['bpm'], bpb)
        if not isinstance(bars, (list, tuple)) or len(bars) != 2:
            raise OpError(f"with recording=, bars is [first, last] in set bars; this take starts at bar {first}")
        kw = {'band': band} if view == 'envelope' else {}
        head = f"{os.path.basename(path)} bars {bars[0]}-{bars[1]} ({view})"
        return head + '\n' + VIEWS[view](path, g, list(bars), **kw)[1]
    d = _call(project, 'listen', bars=bars, deck=deck)
    bar_sec = d['bpb'] * 60.0 / d['bpm']
    g = A.Grid(d['bpm'], -(d['first'] - 1) * bar_sec, d['bpb'])
    rng = [d['first'], d['last']]
    kw = {'band': band} if view == 'envelope' else {}
    txt = VIEWS[view](d['path'], g, rng, **kw)[1]
    return f"live bars {d['first']}-{d['last']} ({view})\n" + txt


@op()
def live_record(project: str, on: bool = True) -> str:
    """Record the live output (after the safety chain) to <project>/live/rec_<time>.wav; on=False stops it."""
    return _call(project, 'record', on=on)
