"""The machine is shared: many agent sessions render, measure, separate and run Blender on one computer. This is
the governor every heavy job goes through, so no session starts one blind (2026-10-02: six sessions stacked heavy
jobs on a laptop GTX 1080 until it sat at 92 C pinned at 139 MHz and the user stopped everything).

    python -m ismail.machine                              # the board: GPU, CPU, memory, every heavy job running
    python -m ismail.machine run --gpu -- <command ...>   # run a command in the GPU slot (Blender, whisper, demucs)
    python -m ismail.machine run --cpu --mem 6 -- <cmd>   # a CPU-heavy command expected to need ~6 GB
    with machine.slot('cpu', 'render song bars 1-64', mem_gb=3): ...     # from Python

Rules (the slots): one GPU-heavy job machine-wide, two CPU-heavy jobs (a live engine on air holds one). No new heavy
job while the GPU is in thermal or hardware slowdown or above GPU_HOT_C: CPU and GPU share one cooler, so a hot GPU
is not a free CPU. No new CPU job while the CPU is CPU_BUSY % busy or more, whoever is using it: most of the load on
this machine is not on the board (the desktop app, servers, other tools), and the refusal names the top processes. A job whose memory estimate does not fit the free commit (minus a reserve) is refused instead of
dying with a MemoryError. A refused job says what is running, whose it is and when to retry; force=True (only when
the user says so) runs it anyway. Jobs of processes that died are cleared on the next look.

Waiting and priority: a job may wait for its slot (`run --wait 30m`, `slot(..., wait=1800)`) instead of being
refused. Waiters line up: the session the user gave priority to first (`python -m ismail.machine priority vox --for
3h --by "the user"`, it expires by itself), then by arrival; a job that does not wait yields to every waiter ahead
of it. Priority orders the line only: the heat limit, the busy CPU and the memory reserve hold for everyone.

The board lives in <songs>/_machine/ (one per machine, shared by every checkout and worktree), or $ISMAIL_MACHINE_DIR.
"""
import argparse
import contextlib
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

import psutil

from .handoffs import SONGS

SLOTS = {'gpu': 1, 'cpu': 2}
GPU_HOT_C = 85
# nvidia-smi clocks_throttle_reasons bits that mean the card is slowing itself down (0x1 is idle: fine)
GPU_BAD = {0x8: 'hardware slowdown', 0x20: 'thermal slowdown (driver)', 0x40: 'thermal slowdown (hardware)',
           0x80: 'power brake'}
CPU_BUSY = 80.0                    # % of all cores, averaged over CPU_SAMPLE_S
CPU_SAMPLE_S = 2.0
RESERVE_GB = 4.0                   # commit kept free for the desktop, the sessions and the live engine
WAIT_POLL_S = 5.0                  # a waiting job looks again this often
THREADS = 2                        # numeric threads per heavy job


class MachineBusy(RuntimeError):
    pass


def board_dir():
    return os.environ.get('ISMAIL_MACHINE_DIR') or os.path.join(SONGS, '_machine')


# ------------------------------------------------------------------ readings

def _gpu_query():
    """-> dict or None (no NVIDIA GPU or no nvidia-smi)."""
    q = 'temperature.gpu,clocks.sm,clocks.max.sm,utilization.gpu,clocks_throttle_reasons.active,memory.used,memory.total'
    try:
        out = subprocess.run(['nvidia-smi', f'--query-gpu={q}', '--format=csv,noheader,nounits'], capture_output=True,
                             text=True, timeout=5).stdout.strip().splitlines()[0]
        t, clk, mx, util, reasons, mu, mt = [x.strip() for x in out.split(',')]
        return {'temp': float(t), 'clock': float(clk), 'max_clock': float(mx), 'util': float(util),
                'reasons': int(reasons, 16), 'mem_used_gb': float(mu) / 1024, 'mem_total_gb': float(mt) / 1024}
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        return None


_gpu_cache = [0.0, None]


def gpu():
    if time.time() - _gpu_cache[0] > 5:
        _gpu_cache[:] = [time.time(), _gpu_query()]
    return _gpu_cache[1]


def gpu_trouble(g):
    """Why the GPU should take no new heavy job ('' when it can)."""
    if g is None:
        return ''
    why = [name for bit, name in GPU_BAD.items() if g['reasons'] & bit]
    if g['temp'] >= GPU_HOT_C:
        why.append(f"{g['temp']:.0f} C (limit {GPU_HOT_C} C)")
    return ', '.join(why)


_cpu_cache = [0.0, None]


def cpu_load():
    """-> (% of all cores busy over CPU_SAMPLE_S, [(% of all cores, process name, pid)] for the top 4), cached 10 s."""
    if time.time() - _cpu_cache[0] < 10 and _cpu_cache[1] is not None:
        return _cpu_cache[1]
    procs = []
    for p in psutil.process_iter(['name']):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except psutil.Error:
            pass
    total = psutil.cpu_percent(interval=CPU_SAMPLE_S)
    n = psutil.cpu_count() or 1
    top = []
    for p in procs:
        try:
            c = p.cpu_percent(None) / n
        except psutil.Error:
            continue
        if c >= 1.0 and p.pid and p.info.get('name') not in ('System Idle Process', 'idle'):
            top.append((c, p.info.get('name') or '?', p.pid))
    top.sort(reverse=True)
    _cpu_cache[:] = [time.time(), (total, top[:4])]
    return _cpu_cache[1]


def _top_text(top):
    return ', '.join(f"{name} {c:.0f}%" for c, name, _ in top) or 'no single process stands out'


def memory():
    """-> (commit free GB, commit limit GB, RAM free GB). On Windows the commit limit is the wall a job hits."""
    vm = psutil.virtual_memory()
    if sys.platform == 'win32':
        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullAvailPageFile / 2 ** 30, m.ullTotalPageFile / 2 ** 30, vm.available / 2 ** 30
    sw = psutil.swap_memory()
    return (vm.available + sw.free) / 2 ** 30, (vm.total + sw.total) / 2 ** 30, vm.available / 2 ** 30


# ------------------------------------------------------------------ the job board

def _alive(job):
    try:
        p = psutil.Process(job['pid'])
        return abs(p.create_time() - job.get('pid_start', p.create_time())) < 1.0
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def jobs():
    """Heavy jobs running now (the dead ones are removed from the board)."""
    d = os.path.join(board_dir(), 'jobs')
    out = []
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        try:
            with open(p, encoding='utf8') as fh:
                job = json.load(fh)
        except (OSError, ValueError):
            continue
        if _alive(job):
            out.append(job)
        else:
            try:
                os.remove(p)
            except OSError:
                pass
    return out


def priority():
    """-> the priority grant {'who', 'until', 'by', 'why', 'set'} if one is in force, else None."""
    try:
        with open(os.path.join(board_dir(), 'priority.json'), encoding='utf8') as f:
            p = json.load(f)
    except (OSError, ValueError):
        return None
    return p if p.get('until', 0) > time.time() else None


def set_priority(who, for_s, by, why=''):
    """Give `who` (a session's name on the board) first place in the line for for_s seconds. Only the user decides
    this: by names who asked (a session asking for itself is not enough)."""
    if not by or not str(by).strip():
        raise ValueError("by: who gave the priority (the user); a session does not give itself priority")
    p = {'who': who, 'until': time.time() + float(for_s), 'by': str(by).strip(), 'why': why, 'set': time.time()}
    with _board_lock():
        with open(os.path.join(board_dir(), 'priority.json'), 'w', encoding='utf8') as f:
            json.dump(p, f)
    return p


def clear_priority():
    with _board_lock():
        try:
            os.remove(os.path.join(board_dir(), 'priority.json'))
        except OSError:
            pass


def waiters():
    """Jobs waiting for a slot, alive ones only, in line order."""
    d = os.path.join(board_dir(), 'waiting')
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            try:
                with open(p, encoding='utf8') as fh:
                    w = json.load(fh)
            except (OSError, ValueError):
                continue
            if _alive(w):
                w['_path'] = p
                out.append(w)
            else:
                try:
                    os.remove(p)
                except OSError:
                    pass
    pr = priority()
    return sorted(out, key=lambda w: _rank(w['who'], w['since'], pr))


def _rank(who, since, pr):
    return (0 if pr and who == pr['who'] else 1, since)


def _ahead(kind, who, since, me=None):
    """Waiters for this kind of slot that are ahead of a job (who, since) in the line."""
    pr = priority()
    mine = _rank(who, since, pr)
    return [w for w in waiters() if w.get('id') != me and (w['kind'] == kind or (kind == 'cpu' and w['kind'] == 'live'))
            and _rank(w['who'], w['since'], pr) < mine]


STALE_LOCK_S = 30.0    # a board lock older than this was left by a holder that died mid-update


def _read(path):
    try:
        with open(path, encoding='utf8') as f:
            return f.read()
    except OSError:
        return None


def _break_stale(lock):
    """Take a dead holder's lock away. Renaming it is atomic, so of several waiters that all judged it stale only
    one moves it; a waiter that moved a lock someone took meanwhile (fresh again) puts it back."""
    moved = f"{lock}.stale.{os.getpid()}.{threading.get_ident()}"
    try:
        os.rename(lock, moved)
    except OSError:                                    # gone already, or another waiter moved it
        return
    try:
        if time.time() - os.path.getmtime(moved) < STALE_LOCK_S:
            os.link(moved, lock)                       # never over a lock that exists (FileExistsError)
    except OSError:
        pass
    try:
        os.remove(moved)
    except OSError:
        pass


@contextlib.contextmanager
def _board_lock(timeout=10.0):
    """One writer at a time on the shared board, across every session's processes. A waiter retries while the lock
    changes hands under it (a holder can let go between our failed create and our look at the lock: that race once
    killed a job waiting in line), and a holder removes only its own lock."""
    os.makedirs(os.path.join(board_dir(), 'jobs'), exist_ok=True)
    lock = os.path.join(board_dir(), 'lock')
    token = f"{os.getpid()} {threading.get_ident()} {time.time()!r}"
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, token.encode())
            break
        except (FileExistsError, PermissionError):     # PermissionError: Windows, a lock being deleted
            try:
                age = time.time() - os.path.getmtime(lock)
            except OSError:                            # its holder let go just now: try again
                age = 0.0
            if age > STALE_LOCK_S:
                _break_stale(lock)
            if time.time() - t0 > timeout:
                raise MachineBusy(f"the job board {lock} stayed locked for {timeout:.0f} s; try again")
            time.sleep(0.02 + 0.03 * (threading.get_ident() % 7) / 7)
    try:
        yield
    finally:
        os.close(fd)
        if _read(lock) == token:                       # never remove a lock another holder took
            try:
                os.remove(lock)
            except OSError:
                pass


def _ago(t):
    m = (time.time() - t) / 60
    return f"{m:.0f} min" if m >= 1 else f"{m * 60:.0f} s"


def _describe(job):
    eta = ''
    if job.get('est_s'):
        left = job['started'] + job['est_s'] - time.time()
        eta = f", expected done in {left / 60:.0f} min" if left > 0 else f", {-left / 60:.0f} min past its estimate"
    what = str(job['what']).strip().splitlines() or ['']
    what = what[0] + (' ...' if len(what) > 1 else '')          # a `python -c` job shows its first line
    return f"{job['kind']} '{what}' ({job['who']}, pid {job['pid']}, {_ago(job['started'])}{eta})"


def duration_s(text):
    """'10m', '600s', '1.5h' -> seconds. A bare number is minutes; above 240 it is refused, because a number of
    seconds passed as minutes put a 10-minute render on the board as 585 min and a peer thought a job had hung."""
    t = str(text).strip().lower()
    unit = {'s': 1, 'm': 60, 'h': 3600}.get(t[-1:]) if t[-1:].isalpha() else None
    try:
        v = float(t[:-1] if unit else t)
    except ValueError:
        raise ValueError(f"--est {text!r}: give a duration like 10m, 600s or 1.5h")
    if unit is None and v > 240:
        raise ValueError(f"--est {text}: a bare number is minutes ({v / 60:.1f} h). If you meant seconds, "
                         f"write --est {t}s; if you meant minutes, write --est {t}m")
    return v * (unit or 60)


def check(kind, mem_gb=0.0, _jobs=None, who=None, since=None, me=None):
    """-> '' when a `kind` job ('gpu' or 'cpu') of mem_gb may start now, else why not and what to do. who/since:
    the asking job's place in the line (a job that is not waiting stands at the back of it, now)."""
    js = jobs() if _jobs is None else _jobs
    why = []
    hot = gpu_trouble(gpu())
    if hot:
        why.append(f"the GPU is {hot}: the machine is hot (CPU and GPU share one cooler), no new heavy job until it cools")
    if kind == 'cpu':
        busy, top = cpu_load()
        if busy >= CPU_BUSY:
            why.append(f"the CPU is {busy:.0f}% busy (limit {CPU_BUSY:.0f}%), mostly load that is not on the board "
                       f"({_top_text(top)}): wait for it to settle, or ask the user whether something can close")
    same = [j for j in js if j['kind'] == kind or (kind == 'cpu' and j['kind'] == 'live')]
    if len(same) >= SLOTS[kind]:
        why.append(f"the {kind} slots are full ({SLOTS[kind]}): " + '; '.join(_describe(j) for j in same))
    else:
        ahead = _ahead(kind, who or _who(), time.time() if since is None else since, me)
        free = SLOTS[kind] - len(same)
        if len(ahead) >= free:
            pr = priority()
            why.append(f"{len(ahead)} waiting ahead for the {kind} slot: " + '; '.join(
                f"'{w['what']}' ({w['who']}" + (', priority from ' + pr['by'] if pr and w['who'] == pr['who'] else '')
                + ")" for w in ahead) + ": wait in line (`run --wait`), or do lighter work")
    if mem_gb:
        free, limit, _ = memory()
        if mem_gb > free - RESERVE_GB:
            why.append(f"it needs about {mem_gb:.1f} GB and {free:.1f} GB of commit is free (limit {limit:.0f} GB, "
                       f"{RESERVE_GB:.0f} GB kept in reserve): render a shorter window or fewer tracks")
    return '; '.join(why)


_held = threading.local()

METER_S = 1.0          # the job meter samples CPU, memory and the GPU this often


class _GpuSampler:
    """One nvidia-smi for a whole job, printing the GPU's load and memory every second (never a process per
    sample). The GPU is shared: these are the whole GPU's numbers while the job held its slot."""

    def __init__(self):
        self.busy_s, self.mem_peak_gb, self.n = 0.0, 0.0, 0
        try:
            self.p = subprocess.Popen(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used',
                                       '--format=csv,noheader,nounits', f'--loop-ms={int(METER_S * 1000)}'],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            self.p = None
            return
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self):
        for line in self.p.stdout:
            try:
                util, mem = (float(x) for x in line.split(','))
            except ValueError:
                continue
            self.busy_s += util / 100 * METER_S
            self.mem_peak_gb = max(self.mem_peak_gb, mem / 1024)
            self.n += 1

    def stop(self):
        if self.p is not None:
            self.p.terminate()
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
            return {'gpu_busy_s': round(self.busy_s, 1), 'gpu_mem_peak_gb': round(self.mem_peak_gb, 2),
                    'gpu_samples': self.n}
        return {}


class _Meter:
    """While a job holds its slot: the CPU seconds and peak memory of the process that holds it and of every child
    it starts (a `machine run` command, Blender, a render worker), and the GPU's load."""

    def __init__(self, job, gpu_sampler=True):
        self.job, self.cpu, self.rss_peak, self.stop_ = job, {}, 0, threading.Event()
        me = psutil.Process()
        t = me.cpu_times()
        self.base = (me.pid, t.user + t.system)       # the holder's CPU before the slot is not the job's
        self.gpu = _GpuSampler() if gpu_sampler else None
        self.t = threading.Thread(target=self._loop, daemon=True)
        self.t.start()

    def _sample(self):
        try:
            me = psutil.Process()
            procs = [me] + me.children(recursive=True)
        except psutil.Error:
            return
        rss = 0
        for p in procs:
            try:
                t = p.cpu_times()
                self.cpu[(p.pid, p.create_time())] = t.user + t.system
                rss += p.memory_info().rss
            except psutil.Error:
                pass
        self.rss_peak = max(self.rss_peak, rss)

    def _loop(self):
        while not self.stop_.wait(METER_S):
            self._sample()

    def stop(self):
        self._sample()
        self.stop_.set()
        for pid, secs in (self.job.get('exited_cpu') or {}).items():   # a child that ended between two samples
            self.cpu = {k: v for k, v in self.cpu.items() if k[0] != pid}
            self.cpu[(pid, 'exited')] = secs
        cpu = sum(v for (pid, _), v in self.cpu.items() if pid != self.base[0])
        cpu += max(0.0, max((v for (pid, _), v in self.cpu.items() if pid == self.base[0]), default=0.0) - self.base[1])
        out = {'cpu_s': round(cpu, 1), 'rss_peak_gb': round(self.rss_peak / 2 ** 30, 2)}
        if self.gpu is not None:
            out.update(self.gpu.stop())
        return out


def _child_cpu_s(p, before=None):
    """CPU seconds a finished child used, read from the system after it exited (a child shorter than one meter
    sample is never seen alive). Windows: the process handle Popen still holds; elsewhere: the children's rusage
    since `before`."""
    if sys.platform == 'win32':
        FT = ctypes.c_ulonglong
        c, e, k, u = FT(), FT(), FT(), FT()
        if ctypes.windll.kernel32.GetProcessTimes(int(p._handle), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k),
                                                  ctypes.byref(u)):
            return (k.value + u.value) / 1e7
        return None
    import resource
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime - (before or 0.0)


def _children_cpu_now():
    if sys.platform == 'win32':
        return None
    import resource
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def _song_of(cwd):
    """The song a job ran for: the folder under songs/ in its working directory, if any."""
    parts = os.path.normpath(cwd).replace('\\', '/').split('/')
    for i, part in enumerate(parts[:-1]):
        if part == 'songs' and parts[i + 1] and not parts[i + 1].startswith('_'):
            return parts[i + 1]
    return None


def _record(job, wait_s, state, meter, outcome):
    """One line per finished job in <board>/history.jsonl, append only: what ran, for which song, when, how long it
    waited, how it ended, and what it used. Speed claims are made from this file."""
    ended = time.time()
    line = {'what': str(job['what'])[:200], 'who': job['who'], 'song': job.get('song') or _song_of(os.getcwd()),
            'kind': job['kind'], 'cwd': os.getcwd(), 'est_s': job.get('est_s'), 'started': round(job['started'], 2),
            'ended': round(ended, 2), 'seconds': round(ended - job['started'], 1), 'waited_s': round(wait_s, 1),
            'exit': job.get('exit', outcome), 'forced': job['forced'], 'at_start': state}
    line.update(meter)
    try:
        with _board_lock():
            with open(os.path.join(board_dir(), 'history.jsonl'), 'a', encoding='utf8') as f:
                f.write(json.dumps(line) + '\n')
    except (OSError, MachineBusy):
        pass                                           # a full disk or a stuck board never fails the job itself


@contextlib.contextmanager
def slot(kind, what, est_s=None, mem_gb=0.0, who=None, force=False, threads=THREADS, wait=None):
    """Hold a heavy-job slot while the block runs. Re-entrant: a job inside a job of this thread (a fit that
    renders) runs in the slot it already holds. Raises MachineBusy with what to do when it may not start; with
    wait (seconds) it stands in line until it may, then raises only if the wait runs out."""
    if getattr(_held, 'depth', 0):
        _held.depth += 1
        try:
            yield
        finally:
            _held.depth -= 1
        return
    if kind not in SLOTS and kind != 'live':
        raise ValueError(f"kind is 'gpu', 'cpu' or 'live', not {kind!r}")
    who = who or _who()
    me = psutil.Process()
    since, wid, wpath = time.time(), None, None
    deadline = since + float(wait) if wait else None
    try:
        while True:
            if kind == 'cpu' and not force:
                cpu_load()             # sample outside the board's lock (it takes CPU_SAMPLE_S); check() reuses it
            with _board_lock():
                why = '' if force or kind == 'live' else check(kind, mem_gb, who=who, since=since, me=wid)
                if not why or not deadline or time.time() >= deadline:
                    if why:
                        raise MachineBusy(f"not starting {kind} job '{what}': {why}. Retry when that clears (the "
                                          f"machine op shows the board), wait in line (`run --wait 30m`), do lighter "
                                          f"work meanwhile, or pass force=True only if the user says so.")
                    break
                if wid is None:        # stand in line
                    wid = f"{me.pid}_{int(since * 1000)}_{os.urandom(3).hex()}"
                    os.makedirs(os.path.join(board_dir(), 'waiting'), exist_ok=True)
                    wpath = os.path.join(board_dir(), 'waiting', wid + '.json')
                    with open(wpath, 'w', encoding='utf8') as f:
                        json.dump({'id': wid, 'kind': kind, 'what': what, 'who': who, 'pid': me.pid,
                                   'pid_start': me.create_time(), 'since': since}, f)
            time.sleep(WAIT_POLL_S)
    finally:
        if wpath:
            try:
                os.remove(wpath)
            except OSError:
                pass
    g = gpu()
    state = {'gpu_temp': g['temp'], 'gpu_clock': g['clock'], 'gpu_reasons': hex(g['reasons']),
             'gpu_trouble': gpu_trouble(g) or None} if g else {}
    if _cpu_cache[1] is not None:
        state['cpu_busy'] = round(_cpu_cache[1][0])
    with _board_lock():
        job = {'kind': kind, 'what': what, 'who': who, 'pid': me.pid, 'pid_start': me.create_time(),
               'started': time.time(), 'est_s': est_s, 'mem_gb': mem_gb, 'forced': bool(force)}
        # unique per slot: two slots taken in the same millisecond by one process overwrote each other
        path = os.path.join(board_dir(), 'jobs', f"{me.pid}_{int(job['started'] * 1000)}_{os.urandom(3).hex()}.json")
        with open(path, 'w', encoding='utf8') as f:
            json.dump(job, f)
    _held.depth = 1
    limits = None
    meter = _Meter(job, gpu_sampler=g is not None)
    outcome = 'ok'
    try:
        if threads:
            try:
                from threadpoolctl import threadpool_limits
                limits = threadpool_limits(threads)
            except ImportError:
                pass
        yield job
    except BaseException as e:
        outcome = type(e).__name__
        raise
    finally:
        _held.depth = 0
        if limits is not None:
            limits.unregister()
        try:
            os.remove(path)
        except OSError:
            pass
        _record(job, job['started'] - since, state, meter.stop(), outcome)


def _who():
    return os.environ.get('ISMAIL_SESSION') or os.path.basename(os.getcwd().rstrip('\\/')) or 'unknown'


def render_memory_gb(n_samples, n_tracks, n_buses=0, n_sources=0):
    """Peak memory of one studio render: the mix, buses, sidechain sources and one track in float64, plus the
    stems as float32 spans (assumed half full)."""
    full = n_samples * 2 * 8
    return (full * (3 + n_buses + n_sources) + n_samples * 2 * 4 * n_tracks * 0.5) / 2 ** 30


# ------------------------------------------------------------------ the board as text

def board():
    g = gpu()
    free, limit, ram = memory()
    L = []
    if g is None:
        L.append("GPU: none found (no nvidia-smi)")
    else:
        hot = gpu_trouble(g)
        L.append(f"GPU: {g['temp']:.0f} C, {g['util']:.0f}% busy, core {g['clock']:.0f}/{g['max_clock']:.0f} MHz"
                 f"{' (idle)' if g['reasons'] & 0x1 else ''}, VRAM {g['mem_used_gb']:.1f}/{g['mem_total_gb']:.1f} GB"
                 + (f"  HOT: {hot}" if hot else ''))
    busy, top = cpu_load()
    L.append(f"CPU: {busy:.0f}% busy over {CPU_SAMPLE_S:.0f} s, {psutil.cpu_count()} threads; top: {_top_text(top)}"
             + (f"  BUSY (limit {CPU_BUSY:.0f}%)" if busy >= CPU_BUSY else ''))
    L.append(f"memory: {free:.1f} GB of {limit:.0f} GB commit free, {ram:.1f} GB RAM free")
    js = jobs()
    L.append(f"heavy jobs ({len(js)}; slots: gpu {SLOTS['gpu']}, cpu {SLOTS['cpu']}, a live engine holds a cpu slot):")
    L += [f"  {_describe(j)}" for j in js] or ["  none"]
    pr = priority()
    if pr:
        L.append(f"priority: {pr['who']} goes first in line until {time.strftime('%H:%M', time.localtime(pr['until']))}"
                 f" (given by {pr['by']}" + (f": {pr['why']}" if pr.get('why') else '') + ")")
    ws = waiters()
    if ws:
        L.append(f"waiting in line ({len(ws)}):")
        L += [f"  {w['kind']} '{w['what']}' ({w['who']}, waiting {_ago(w['since'])})" for w in ws]
    for kind in ('gpu', 'cpu'):
        why = check(kind, _jobs=js)
        L.append(f"a new {kind} job: " + ('go' if not why else f"WAIT: {why}"))
    return '\n'.join(L)


def history(song=None, since=None):
    """Finished jobs from <board>/history.jsonl, oldest first (song: only that song's; since: epoch seconds)."""
    out = []
    try:
        with open(os.path.join(board_dir(), 'history.jsonl'), encoding='utf8') as f:
            for line in f:
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if (song is None or j.get('song') == song) and (since is None or j.get('started', 0) >= since):
                    out.append(j)
    except OSError:
        pass
    return out


def _since(text):
    t = str(text).strip().lower()
    if t[-1:] == 'd' and t[:-1].replace('.', '', 1).isdigit():
        return time.time() - float(t[:-1]) * 86400
    if t[-1:] in 'hms' and t[:-1].replace('.', '', 1).isdigit():
        return time.time() - duration_s(t)
    try:
        return time.mktime(time.strptime(t, '%Y-%m-%d'))
    except ValueError:
        raise ValueError(f"--since {text!r}: a date (2026-10-04) or a span (7d, 12h)")


def history_text(song=None, since=None, n_jobs=0):
    js = history(song, since)
    if not js:
        return ("no finished jobs recorded" + (f" for {song}" if song else '') + " (the history starts with the first "
                "job that finished after it was added; earlier jobs were never kept)")
    first = time.strftime('%Y-%m-%d %H:%M', time.localtime(js[0]['started']))
    by = {}
    for j in js:
        s = by.setdefault(j.get('song') or '(no song)', {'jobs': 0, 'wall': 0.0, 'cpu': 0.0, 'gpu': 0.0, 'failed': 0})
        s['jobs'] += 1
        s['wall'] += j.get('seconds', 0)
        s['cpu'] += j.get('cpu_s', 0)
        s['gpu'] += j.get('gpu_busy_s', 0)
        s['failed'] += j.get('exit') not in (0, 'ok')
    L = [f"{len(js)} jobs since {first} (wall = time holding a slot; CPU = seconds of CPU across cores; GPU = whole-GPU "
         f"busy seconds while the job held its slot; the GPU is shared)"]
    for name, s in sorted(by.items(), key=lambda kv: -kv[1]['wall']):
        L.append(f"  {name}: {s['jobs']} jobs, {s['wall'] / 3600:.2f} h wall, {s['cpu'] / 3600:.2f} h CPU, "
                 f"{s['gpu'] / 3600:.2f} h GPU busy" + (f", {s['failed']} did not end well" if s['failed'] else ''))
    if n_jobs:
        L.append(f"last {min(n_jobs, len(js))} jobs:")
        for j in js[-n_jobs:]:
            L.append(f"  {time.strftime('%m-%d %H:%M', time.localtime(j['started']))} {j['kind']} '{j['what'][:60]}' "
                     f"({j.get('song') or '-'}) {j.get('seconds', 0) / 60:.1f} min, waited {j.get('waited_s', 0):.0f} s,"
                     f" CPU {j.get('cpu_s', 0):.0f} s, exit {j.get('exit')}")
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description='The shared machine: the board, or run a command in a heavy-job slot.')
    sub = ap.add_subparsers(dest='cmd')
    r = sub.add_parser('run', help='run a command in a slot: python -m ismail.machine run --gpu -- blender -b ...')
    k = r.add_mutually_exclusive_group(required=True)
    k.add_argument('--gpu', action='store_true')
    k.add_argument('--cpu', action='store_true')
    r.add_argument('--mem', type=float, default=0.0, help='expected peak memory, GB')
    r.add_argument('--est', default=None, help='expected duration: 10m, 600s, 1.5h (a bare number is minutes)')
    r.add_argument('--what', default=None, help='what it is, for the board')
    r.add_argument('--force', action='store_true', help='only when the user says so')
    r.add_argument('--wait', nargs='?', const='30m', default=None,
                   help='stand in line for the slot instead of being refused: a duration (default 30m)')
    r.add_argument('command', nargs=argparse.REMAINDER)
    p = sub.add_parser('priority', help='the user gives a session first place in line: priority vox --for 3h --by "the user"')
    p.add_argument('who', nargs='?', help="the session's name as the board shows it")
    p.add_argument('--for', dest='for_', default='2h', help='how long: 30m, 3h (default 2h)')
    p.add_argument('--by', default=None, help='who gave it (the user)')
    p.add_argument('--why', default='', help='what it is for, for the board')
    p.add_argument('--clear', action='store_true')
    h = sub.add_parser('history', help='what ran and what it used: compute time per song (history --song tambopata)')
    h.add_argument('--song', default=None)
    h.add_argument('--since', default=None, help='a date (2026-10-04) or a span back from now (7d, 12h)')
    h.add_argument('--jobs', type=int, default=0, help='also list the last N jobs')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if a.cmd == 'priority':
        if a.clear:
            clear_priority()
            print("priority cleared")
            return 0
        if not a.who:
            pr = priority()
            print(f"priority: {pr['who']} until {time.strftime('%H:%M', time.localtime(pr['until']))} (by {pr['by']})"
                  if pr else "no priority in force")
            return 0
        try:
            pr = set_priority(a.who, duration_s(a.for_), a.by, a.why)
        except ValueError as e:
            ap.error(str(e))
        print(f"priority: {pr['who']} goes first in line until {time.strftime('%H:%M', time.localtime(pr['until']))} "
              f"(given by {pr['by']}); the heat limit and the busy CPU still hold")
        return 0
    if a.cmd == 'history':
        try:
            print(history_text(a.song, _since(a.since) if a.since else None, a.jobs))
        except ValueError as e:
            ap.error(str(e))
        return 0
    if a.cmd != 'run':
        print(board())
        return 0
    cmd = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not cmd:
        ap.error('run needs a command after --')
    kind = 'gpu' if a.gpu else 'cpu'
    try:
        est_s = duration_s(a.est) if a.est else None
    except ValueError as e:
        ap.error(str(e))
    try:
        wait_s = duration_s(a.wait) if a.wait else None
    except ValueError as e:
        ap.error(str(e))
    try:
        with slot(kind, a.what or ' '.join(cmd)[:80], est_s=est_s, mem_gb=a.mem,
                  force=a.force, threads=None, wait=wait_s) as job:
            before = _children_cpu_now()
            p = subprocess.Popen(cmd)
            try:
                psutil.Process(p.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == 'win32' else 10)
            except (psutil.Error, AttributeError):
                pass
            job['exit'] = p.wait()
            try:
                secs = _child_cpu_s(p, before)
                if secs is not None:
                    job['exited_cpu'] = {p.pid: secs}
            except (OSError, AttributeError, ValueError):
                pass
            return job['exit']
    except MachineBusy as e:
        print(e, file=sys.stderr)
        return 75                                            # EX_TEMPFAIL: try again later


if __name__ == '__main__':
    sys.exit(main())
