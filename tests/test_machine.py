"""The machine governor: heavy jobs take slots on a board every session shares, and refuse with the reason when the
machine is busy, hot or short of memory (2026-10-02: six sessions stacked heavy jobs until the GPU sat at 92 C)."""
import json
import os
import subprocess
import sys

import pytest

from ismail import api, machine

COOL = {'temp': 60.0, 'clock': 139.0, 'max_clock': 1911.0, 'util': 0.0, 'reasons': 0x1, 'mem_used_gb': 0.5,
        'mem_total_gb': 8.0}


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_MACHINE_DIR', str(tmp_path / 'board'))
    monkeypatch.setattr(machine, 'gpu', lambda: dict(COOL))
    monkeypatch.setattr(machine, 'memory', lambda: (40.0, 70.0, 30.0))
    monkeypatch.setattr(machine, 'cpu_load', lambda: (12.0, []))
    monkeypatch.setattr(machine, 'disks', lambda *a: [('D:', 100.0)])
    monkeypatch.setattr(machine, 'pagefiles', lambda: [])
    depth = getattr(machine._held, 'depth', 0)
    machine._held.depth = 0                  # the suite's own slot (conftest) would make every slot pass through
    yield tmp_path / 'board'
    machine._held.depth = depth


def test_an_idle_gpu_at_139_mhz_is_not_trouble_but_a_thermal_bit_or_heat_is():
    assert machine.gpu_trouble(dict(COOL)) == ''
    assert 'thermal' in machine.gpu_trouble(dict(COOL, reasons=0x20, temp=92))
    assert '86 C' in machine.gpu_trouble(dict(COOL, reasons=0x0, temp=86))


def test_slots_fill_and_a_refusal_says_who_holds_them_and_what_to_do(board):
    with machine.slot('gpu', 'whisper medium', est_s=600, who='vox'):
        with pytest.raises(machine.MachineBusy) as e:
            machine._held.depth = 0
            with machine.slot('gpu', 'demucs'):
                pass
        msg = str(e.value)
        assert "whisper medium" in msg and 'vox' in msg and 'expected done in' in msg and 'force=True' in msg
        machine._held.depth = 0
        with machine.slot('gpu', 'demucs', force=True):       # the user said so
            pass
        machine._held.depth = 1
    assert machine.jobs() == []


def test_two_cpu_slots_and_a_live_engine_holds_one(board):
    with machine.slot('live', 'live engine set', threads=None):
        machine._held.depth = 0
        with machine.slot('cpu', 'render a'):
            machine._held.depth = 0
            assert 'cpu slots are full' in machine.check('cpu')
            assert machine.check('gpu') == ''
            machine._held.depth = 1
        machine._held.depth = 1


def test_a_hot_gpu_stops_cpu_jobs_too_and_memory_that_does_not_fit_is_refused(board, monkeypatch):
    monkeypatch.setattr(machine, 'gpu', lambda: dict(COOL, temp=91, reasons=0x20))
    assert 'share one cooler' in machine.check('cpu')
    monkeypatch.setattr(machine, 'gpu', lambda: dict(COOL))
    assert 'needs about 50.0 GB' in machine.check('cpu', mem_gb=50)
    assert machine.check('cpu', mem_gb=10) == ''


def test_load_that_is_not_on_the_board_still_stops_a_cpu_job_and_names_who(board, monkeypatch):
    # 2026-10-02: 98% CPU from the desktop app and a node server, an empty board, and the governor said go
    monkeypatch.setattr(machine, 'cpu_load', lambda: (98.0, [(59.0, 'claude.exe', 1), (31.0, 'node.exe', 2)]))
    why = machine.check('cpu')
    assert '98% busy' in why and 'claude.exe 59%' in why and 'node.exe 31%' in why
    assert machine.check('gpu') == ''
    assert 'BUSY' in machine.board()


def test_a_job_of_a_dead_process_leaves_the_board(board):
    os.makedirs(board / 'jobs')
    dead = {'kind': 'gpu', 'what': 'crashed', 'who': 'x', 'pid': 2 ** 22 + 7, 'pid_start': 0, 'started': 0}
    (board / 'jobs' / 'dead.json').write_text(json.dumps(dead))
    assert machine.jobs() == [] and not os.listdir(board / 'jobs')


def test_a_slot_is_reentrant_so_a_fit_that_renders_holds_one_slot(board):
    with machine.slot('cpu', 'instrument_fit'):
        with machine.slot('cpu', 'render inside the fit'):
            assert len(machine.jobs()) == 1


def test_a_busy_machine_turns_a_render_into_an_op_error_that_says_why(board, tmp_path):
    root = str(tmp_path / 's')
    api.project_new(root, bpm=120, length_bars=1)
    api.track_add(root, 'k', instrument='preset:kick')
    api.notes_write(root, 'k', 1, '0 C2 1')
    with machine.slot('cpu', 'render one', who='tears'):
        machine._held.depth = 0                              # as if the live engine were another process
        with machine.slot('live', 'live set', threads=None):
            machine._held.depth = 0
            with pytest.raises(api.OpError) as e:
                api.render(root)
            machine._held.depth = 1
        machine._held.depth = 1
    assert 'cpu slots are full' in str(e.value) and 'tears' in str(e.value)
    assert 'rendered' in api.render(root)
    assert 'heavy jobs (0' in api.OPS['machine_status']()


def test_the_cli_runs_a_command_in_a_slot_and_waits_its_turn(board):
    env = dict(os.environ, ISMAIL_MACHINE_DIR=str(board))
    code = "import json,os; d=os.environ['ISMAIL_MACHINE_DIR']; print(len(os.listdir(os.path.join(d, 'jobs'))))"
    # --force: this checks the wrapper, not today's load (the real machine may be hot while the test runs)
    out = subprocess.run([sys.executable, '-m', 'ismail.machine', 'run', '--cpu', '--force', '--what', 'probe', '--',
                          sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == '1'      # its own job was on the board while it ran


def test_an_estimate_takes_a_unit_and_a_bare_number_of_seconds_is_refused():
    # M54: `--est 600` (meant as seconds) put a 10-minute render on the board as 585 min
    assert machine.duration_s('10m') == 600 and machine.duration_s('600s') == 600 and machine.duration_s('1.5h') == 5400
    assert machine.duration_s('12') == 720                                   # a bare number stays minutes
    with pytest.raises(ValueError, match='600s'):
        machine.duration_s('600')
    with pytest.raises(ValueError, match='10m'):
        machine.duration_s('ten')


def test_the_board_shows_a_python_c_job_by_its_first_line_and_how_late_it_runs():
    # M32: the board printed a `python -c` job's whole code
    import time
    job = {'kind': 'cpu', 'what': 'python -c import x\nfor a in b:\n    run(a)', 'who': 'ismail', 'pid': 1,
           'started': time.time() - 600, 'est_s': 300}
    d = machine._describe(job)
    assert "'python -c import x ...'" in d and '\n' not in d and '5 min past its estimate' in d


def test_priority_from_the_user_puts_a_session_first_in_line_and_heat_still_holds(board, monkeypatch):
    # M63 (vox, the user's words): finish the voice exams first; --force skips the heat limit, so it is not the answer
    import threading
    import time
    monkeypatch.setattr(machine, 'WAIT_POLL_S', 0.05)
    with pytest.raises(ValueError, match='the user'):
        machine.set_priority('vox', 3600, by='')
    machine.set_priority('vox', 3600, by='the user', why='finish the voice exams')
    assert machine.priority()['who'] == 'vox'
    got, errors = [], []

    def take(who, what):
        machine._held.depth = 0
        try:
            with machine.slot('gpu', what, who=who, wait=10):
                got.append(who)
        except machine.MachineBusy as e:
            errors.append(str(e))
    with machine.slot('gpu', 'demucs stems', who='crossroads'):
        machine._held.depth = 0
        bg = threading.Thread(target=take, args=('tambopata', 'render draft 5'))
        bg.start()

        def in_line(n):                                   # wait for the line, not a fixed time (a busy machine is slow)
            t_end = time.time() + 10
            while len(machine.waiters()) < n and time.time() < t_end:
                time.sleep(0.02)
        in_line(1)                                        # tambopata is in line first
        vx = threading.Thread(target=take, args=('vox', 'whisper small.en'))
        vx.start()
        in_line(2)
        line = machine.waiters()
        assert [w['who'] for w in line] == ['vox', 'tambopata']             # priority first, then arrival
        b = machine.board()
        assert 'priority: vox goes first in line' in b and 'given by the user: finish the voice exams' in b
        assert 'waiting in line (2)' in b
        assert 'slots are full' in machine.check('gpu', who='crossroads')
        machine._held.depth = 1
    vx.join(30)
    bg.join(30)
    assert got == ['vox', 'tambopata'] and not errors and machine.waiters() == []
    # a job that does not wait yields to a waiter ahead of it, with the reason (the slot is free here)
    me = __import__('psutil').Process()
    os.makedirs(board / 'waiting', exist_ok=True)
    (board / 'waiting' / 'w1.json').write_text(json.dumps({'id': 'w1', 'kind': 'gpu', 'what': 'whisper', 'who': 'vox',
                                                           'pid': me.pid, 'pid_start': me.create_time(),
                                                           'since': time.time()}), encoding='utf8')
    why = machine.check('gpu', who='tambopata')
    assert "1 waiting ahead for the gpu slot: 'whisper' (vox, priority from the user)" in why
    assert machine.check('gpu', who='vox', me='w1') == ''                 # vox itself is not behind its own place
    os.remove(board / 'waiting' / 'w1.json')
    # the heat limit holds for the priority session too
    monkeypatch.setattr(machine, 'gpu', lambda: dict(COOL, temp=88.0, reasons=0x0))
    assert '88 C' in machine.check('gpu', who='vox')
    machine.clear_priority()
    assert machine.priority() is None


def test_an_expired_priority_is_gone_and_the_cli_sets_one(board):
    machine.set_priority('vox', -1, by='the user')
    assert machine.priority() is None
    env = dict(os.environ, ISMAIL_MACHINE_DIR=str(board))
    out = subprocess.run([sys.executable, '-m', 'ismail.machine', 'priority', 'vox', '--for', '3h', '--by', 'the user'],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and 'vox goes first in line until' in out.stdout
    out = subprocess.run([sys.executable, '-m', 'ismail.machine', 'priority', 'vox', '--for', '3h'],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode != 0 and 'the user' in out.stderr


def test_the_board_lock_survives_waiters_racing_its_holders(board):
    """Three sessions waiting at once once killed a queued job: a holder let go between a waiter's failed create and
    its look at the lock (FileNotFoundError). Many threads now take turns with no error and never overlap."""
    import threading
    inside, overlaps, errors = [0], [0], []

    def worker():
        try:
            for _ in range(60):
                with machine._board_lock(timeout=30):
                    inside[0] += 1
                    if inside[0] > 1:
                        overlaps[0] += 1
                    inside[0] -= 1
        except Exception as e:                       # noqa: BLE001
            errors.append(repr(e))
    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == [] and overlaps[0] == 0
    assert not os.path.exists(os.path.join(str(board), 'lock'))


def test_a_dead_holders_lock_is_taken_and_a_live_one_is_never_removed(board):
    os.makedirs(str(board), exist_ok=True)
    lock = os.path.join(str(board), 'lock')
    with open(lock, 'w') as f:
        f.write('a holder that died')
    old = os.path.getmtime(lock) - machine.STALE_LOCK_S - 5
    os.utime(lock, (old, old))
    with machine._board_lock(timeout=5):
        assert open(lock).read() != 'a holder that died'
        with open(lock, 'w') as f:                   # a waiter broke our lock meanwhile and took it
            f.write('someone else')
    assert open(lock).read() == 'someone else'       # our release left their lock alone


def test_every_finished_job_leaves_one_line_of_history_and_history_sums_it_by_song(board, monkeypatch, tmp_path):
    """M87: speed claims need a record of what ran, for which song, how long it waited and what it used."""
    monkeypatch.setattr(machine, '_GpuSampler', lambda: type('G', (), {'stop': lambda self: {
        'gpu_busy_s': 3.0, 'gpu_mem_peak_gb': 1.5, 'gpu_samples': 4}})())
    song = tmp_path / 'songs' / 'tambopata'
    song.mkdir(parents=True)
    monkeypatch.chdir(song)
    with machine.slot('gpu', 'render draft 5', who='tambopata', est_s=60):
        sum(i * i for i in range(300000))                 # a little CPU
    with pytest.raises(RuntimeError):
        with machine.slot('cpu', 'a fit that crashed', who='tambopata'):
            raise RuntimeError('boom')
    js = machine.history()
    assert [j['what'] for j in js] == ['render draft 5', 'a fit that crashed']
    a, b = js
    assert a['song'] == 'tambopata' and a['kind'] == 'gpu' and a['exit'] == 'ok' and a['est_s'] == 60
    assert a['gpu_busy_s'] == 3.0 and a['cpu_s'] >= 0 and a['seconds'] >= 0 and a['waited_s'] >= 0
    assert a['at_start']['gpu_temp'] == COOL['temp'] and 'gpu_reasons' in a['at_start']
    assert b['exit'] == 'RuntimeError'
    assert machine.history(song='other') == []
    text = machine.history_text()
    assert 'tambopata: 2 jobs' in text and '1 did not end well' in text
    assert 'never kept' in machine.history_text(song='nobody')


def test_the_cli_records_the_commands_exit_and_its_cpu(board):
    env = dict(os.environ, ISMAIL_MACHINE_DIR=str(board))
    code = "import sys; sum(i * i for i in range(2000000)); sys.exit(3)"   # shorter than one meter sample on CI
    out = subprocess.run([sys.executable, '-m', 'ismail.machine', 'run', '--cpu', '--force', '--what', 'busy probe', '--',
                          sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 3
    j = [x for x in machine.history() if x['what'] == 'busy probe'][-1]
    assert j['exit'] == 3 and j['cpu_s'] > 0.05 and j['rss_peak_gb'] > 0
    out = subprocess.run([sys.executable, '-m', 'ismail.machine', 'history', '--since', '1d', '--jobs', '1'],
                         capture_output=True, text=True, env=env, timeout=60)
    assert "'busy probe'" in out.stdout and 'exit 3' in out.stdout


def test_a_drive_under_the_floor_holds_every_heavy_job_and_says_where_the_space_went(board, monkeypatch, tmp_path):
    """M72: D: filled four times in five days (render caches, takes, the pagefile); a job that would leave a drive
    under the floor waits, with the numbers and what to do, and a render says cache=False writes less."""
    monkeypatch.setattr(machine, 'disks', lambda *a: [('D:', 20.0)])
    assert machine.check('gpu') == ''
    why = machine.check('cpu', disk_gb=6.0, disk_hint='cache=False skips the track cache')
    assert why.startswith('disk: it writes about 6.0 GB and D: has 20.0 GB free') and 'cache=False' in why
    assert '_reclaim' in why and 'never delete' in why
    monkeypatch.setattr(machine, 'disks', lambda *a: [('D:', 3.7)])
    monkeypatch.setattr(machine, 'pagefiles', lambda: [('D:', 33.6)])
    with pytest.raises(machine.MachineBusy) as e:
        with machine.slot('gpu', 'whisper'):
            pass
    assert 'D: has 3.7 GB free' in str(e.value)
    text = machine.board()
    assert 'disk: D: 3.7 GB free; pagefile D: 33.6 GB  LOW' in text and 'a new gpu job: WAIT: disk' in text
    assert 'D: 3.7 GB free' in machine.pressure_line()
    root = str(tmp_path / 's')
    api.project_new(root, bpm=120, length_bars=1)
    api.track_add(root, 'k', instrument='preset:kick')
    with pytest.raises(api.OpError) as e:
        api.render(root)
    assert 'cache=False skips the track cache' in str(e.value)
    with machine.slot('live', 'live set', threads=None):     # a set on air is never held by the disk
        pass


def test_low_commit_holds_new_jobs_and_names_the_job_past_its_memory(board, monkeypatch):
    """M72: 2026-10-05 a job declared 7 GB, took 10.7 GB, and the pagefile took D: from 9 GB to 0.2 GB."""
    monkeypatch.setattr(machine, 'METER_S', 0.05)
    monkeypatch.setattr(machine, 'MEM_OVER_MIN_GB', 0.0)
    monkeypatch.setattr(machine, '_GpuSampler', lambda: type('G', (), {'stop': lambda self: {}})())
    with machine.slot('gpu', 'blender bvh', mem_gb=0.001, who='film') as job:
        hog = b'x' * (64 * 2 ** 20)                       # what the job adds; the holder's own memory before it is not counted
        import time
        t = time.time()
        while not (machine.jobs() and machine.jobs()[0].get('over')) and time.time() - t < 10:
            time.sleep(0.05)
        on_board = machine.jobs()[0]
        assert on_board['over'] > 0.001 and on_board['mem_now_gb'] > 0.001
        assert 'OVER: peaked at' in machine._describe(on_board)
        monkeypatch.setattr(machine, 'memory', lambda: (4.0, 70.0, 2.0))
        why = machine.check('cpu')
        assert why.startswith('memory: 4.0 GB of commit free') and "'blender bvh' (film" in why
        assert 'LOW (heavy jobs wait below 6 GB)' in machine.board()
        monkeypatch.setattr(machine, 'memory', lambda: (40.0, 70.0, 30.0))
    j = machine.history()[-1]
    assert j['over_gb'] > 0.001 and j['mem_peak_gb'] > 0 and j['write_gb'] >= 0
    assert j['at_start']['disk_free_gb'] == 100.0 and 'disk_free_end_gb' in j
    assert 'went past their declared memory' in machine.history_text()
    assert not [f for f in os.listdir(board / 'jobs') if f.endswith('.tmp')]


def test_the_cli_says_over_memory_in_the_jobs_own_output(board):
    env = dict(os.environ, ISMAIL_MACHINE_DIR=str(board))
    code = "import time; b = b'x' * (700 * 2 ** 20); time.sleep(2.5)"
    out = subprocess.run([sys.executable, '-m', 'ismail.machine', 'run', '--cpu', '--force', '--mem', '0.05', '--what',
                          'hog', '--', sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0 and 'OVER MEMORY' in out.stderr and "'hog'" in out.stderr
    j = [x for x in machine.history() if x['what'] == 'hog'][-1]
    assert j['over_gb'] > 0.55 and j['mem_peak_gb'] >= 0.65


def test_a_render_in_a_big_process_is_not_over_its_estimate(board, monkeypatch):
    """The holder's memory before the slot is not the job's: an agent's 0.7 GB Python process rendering a 0.15 GB
    window was flagged OVER on every render (2026-10-05)."""
    monkeypatch.setattr(machine, 'METER_S', 0.05)
    monkeypatch.setattr(machine, '_GpuSampler', lambda: type('G', (), {'stop': lambda self: {}})())
    keep = b'x' * (300 * 2 ** 20)                          # the process was already big
    with machine.slot('cpu', 'render a window', mem_gb=0.15, who='song'):
        import time
        time.sleep(0.3)
        assert not machine.jobs()[0].get('over')
    assert 'over_gb' not in machine.history()[-1] and len(keep)


def test_machine_disk_lists_the_songs_their_growth_and_reclaim(board, tmp_path):
    root = tmp_path / 'songs'
    (root / 'big' / 'renders').mkdir(parents=True)
    (root / 'big' / 'renders' / 'a.wav').write_bytes(b'0' * 3 * 2 ** 20)
    (root / 'small' / 'live' / '_reclaim').mkdir(parents=True)
    (root / 'small' / 'live' / '_reclaim' / 'take.wav').write_bytes(b'0' * 2 ** 20)
    (board / 'disk').mkdir(parents=True)
    (board / 'disk' / '2000-01-01.json').write_text(json.dumps({'big': 1 * 2 ** 20}))
    text = machine.disk_text(root=str(root))
    assert 'growth since 2000-01-01' in text and 'big  +0.00 GB' not in text
    lines = text.splitlines()
    assert any(l.strip().startswith('0.00 GB  big') for l in lines)
    assert '_reclaim (moved out, waiting for the user to clear)' in text
    assert os.path.join('small', 'live', '_reclaim') in text
    assert sorted(os.listdir(board / 'disk')) == ['2000-01-01.json', __import__('time').strftime('%Y-%m-%d') + '.json']
    assert 'songs/' in api.OPS['machine_disk']()

