"""The machine is shared: many agent sessions render, measure, separate and run Blender on one computer. This is
the governor every heavy job goes through, so no session starts one blind (2026-10-02: six sessions stacked heavy
jobs on a laptop GTX 1080 until it sat at 92 C pinned at 139 MHz and the user stopped everything).

    python -m ismail.machine                              # the board: GPU, CPU, memory, every heavy job running
    python -m ismail.machine run --gpu -- <command ...>   # run a command in the GPU slot (Blender, whisper, demucs)
    python -m ismail.machine run --cpu --mem 6 -- <cmd>   # a CPU-heavy command expected to need ~6 GB
    with machine.slot('cpu', 'render song bars 1-64', mem_gb=3): ...     # from Python

Rules (the slots): one GPU-heavy job machine-wide, two CPU-heavy jobs (a live engine on air holds one). No new heavy
job while the GPU is in thermal or hardware slowdown or above GPU_HOT_C: CPU and GPU share one cooler, so a hot GPU
is not a free CPU. A job whose memory estimate does not fit the free commit (minus a reserve) is refused instead of
dying with a MemoryError. A refused job says what is running, whose it is and when to retry; force=True (only when
the user says so) runs it anyway. Jobs of processes that died are cleared on the next look.

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
RESERVE_GB = 4.0                   # commit kept free for the desktop, the sessions and the live engine
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


@contextlib.contextmanager
def _board_lock(timeout=10.0):
    os.makedirs(os.path.join(board_dir(), 'jobs'), exist_ok=True)
    lock = os.path.join(board_dir(), 'lock')
    t0 = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - os.path.getmtime(lock) > 30:      # a holder that died mid-update
                os.remove(lock)
            elif time.time() - t0 > timeout:
                raise MachineBusy(f"the job board {lock} stayed locked for {timeout:.0f} s; try again")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        os.remove(lock)


def _ago(t):
    m = (time.time() - t) / 60
    return f"{m:.0f} min" if m >= 1 else f"{m * 60:.0f} s"


def _describe(job):
    eta = ''
    if job.get('est_s'):
        left = job['started'] + job['est_s'] - time.time()
        eta = f", expected done in {left / 60:.0f} min" if left > 0 else ", past its estimate"
    return f"{job['kind']} '{job['what']}' ({job['who']}, pid {job['pid']}, {_ago(job['started'])}{eta})"


def check(kind, mem_gb=0.0, _jobs=None):
    """-> '' when a `kind` job ('gpu' or 'cpu') of mem_gb may start now, else why not and what to do."""
    js = jobs() if _jobs is None else _jobs
    why = []
    hot = gpu_trouble(gpu())
    if hot:
        why.append(f"the GPU is {hot}: the machine is hot (CPU and GPU share one cooler), no new heavy job until it cools")
    same = [j for j in js if j['kind'] == kind or (kind == 'cpu' and j['kind'] == 'live')]
    if len(same) >= SLOTS[kind]:
        why.append(f"the {kind} slots are full ({SLOTS[kind]}): " + '; '.join(_describe(j) for j in same))
    if mem_gb:
        free, limit, _ = memory()
        if mem_gb > free - RESERVE_GB:
            why.append(f"it needs about {mem_gb:.1f} GB and {free:.1f} GB of commit is free (limit {limit:.0f} GB, "
                       f"{RESERVE_GB:.0f} GB kept in reserve): render a shorter window or fewer tracks")
    return '; '.join(why)


_held = threading.local()


@contextlib.contextmanager
def slot(kind, what, est_s=None, mem_gb=0.0, who=None, force=False, threads=THREADS):
    """Hold a heavy-job slot while the block runs. Re-entrant: a job inside a job of this thread (a fit that
    renders) runs in the slot it already holds. Raises MachineBusy with what to do when it may not start."""
    if getattr(_held, 'depth', 0):
        _held.depth += 1
        try:
            yield
        finally:
            _held.depth -= 1
        return
    if kind not in SLOTS and kind != 'live':
        raise ValueError(f"kind is 'gpu', 'cpu' or 'live', not {kind!r}")
    with _board_lock():
        why = '' if force or kind == 'live' else check(kind if kind != 'live' else 'cpu', mem_gb)
        if why:
            raise MachineBusy(f"not starting {kind} job '{what}': {why}. Retry when that clears (the machine op "
                              f"shows the board), do lighter work meanwhile, or pass force=True only if the user says so.")
        me = psutil.Process()
        job = {'kind': kind, 'what': what, 'who': who or _who(), 'pid': me.pid, 'pid_start': me.create_time(),
               'started': time.time(), 'est_s': est_s, 'mem_gb': mem_gb, 'forced': bool(force)}
        # unique per slot: two slots taken in the same millisecond by one process overwrote each other
        path = os.path.join(board_dir(), 'jobs', f"{me.pid}_{int(job['started'] * 1000)}_{os.urandom(3).hex()}.json")
        with open(path, 'w', encoding='utf8') as f:
            json.dump(job, f)
    _held.depth = 1
    limits = None
    try:
        if threads:
            try:
                from threadpoolctl import threadpool_limits
                limits = threadpool_limits(threads)
            except ImportError:
                pass
        yield job
    finally:
        _held.depth = 0
        if limits is not None:
            limits.unregister()
        try:
            os.remove(path)
        except OSError:
            pass


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
    L.append(f"CPU: {psutil.cpu_percent(interval=0.3):.0f}% busy, {psutil.cpu_count()} threads")
    L.append(f"memory: {free:.1f} GB of {limit:.0f} GB commit free, {ram:.1f} GB RAM free")
    js = jobs()
    L.append(f"heavy jobs ({len(js)}; slots: gpu {SLOTS['gpu']}, cpu {SLOTS['cpu']}, a live engine holds a cpu slot):")
    L += [f"  {_describe(j)}" for j in js] or ["  none"]
    for kind in ('gpu', 'cpu'):
        why = check(kind, _jobs=js)
        L.append(f"a new {kind} job: " + ('go' if not why else f"WAIT: {why}"))
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description='The shared machine: the board, or run a command in a heavy-job slot.')
    sub = ap.add_subparsers(dest='cmd')
    r = sub.add_parser('run', help='run a command in a slot: python -m ismail.machine run --gpu -- blender -b ...')
    k = r.add_mutually_exclusive_group(required=True)
    k.add_argument('--gpu', action='store_true')
    k.add_argument('--cpu', action='store_true')
    r.add_argument('--mem', type=float, default=0.0, help='expected peak memory, GB')
    r.add_argument('--est', type=float, default=None, help='expected minutes')
    r.add_argument('--what', default=None, help='what it is, for the board')
    r.add_argument('--force', action='store_true', help='only when the user says so')
    r.add_argument('command', nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if a.cmd != 'run':
        print(board())
        return 0
    cmd = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not cmd:
        ap.error('run needs a command after --')
    kind = 'gpu' if a.gpu else 'cpu'
    try:
        with slot(kind, a.what or ' '.join(cmd)[:80], est_s=a.est * 60 if a.est else None, mem_gb=a.mem,
                  force=a.force, threads=None):
            p = subprocess.Popen(cmd)
            try:
                psutil.Process(p.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == 'win32' else 10)
            except (psutil.Error, AttributeError):
                pass
            return p.wait()
    except MachineBusy as e:
        print(e, file=sys.stderr)
        return 75                                            # EX_TEMPFAIL: try again later


if __name__ == '__main__':
    sys.exit(main())
