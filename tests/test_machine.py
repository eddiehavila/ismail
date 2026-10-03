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
        time.sleep(0.3)                                   # tambopata is in line first
        vx = threading.Thread(target=take, args=('vox', 'whisper small.en'))
        vx.start()
        time.sleep(0.3)
        line = machine.waiters()
        assert [w['who'] for w in line] == ['vox', 'tambopata']             # priority first, then arrival
        b = machine.board()
        assert 'priority: vox goes first in line' in b and 'given by the user: finish the voice exams' in b
        assert 'waiting in line (2)' in b
        assert 'slots are full' in machine.check('gpu', who='crossroads')
        machine._held.depth = 1
    vx.join(5)
    bg.join(5)
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
