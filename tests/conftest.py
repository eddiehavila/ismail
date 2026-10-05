import os

import pytest

from ismail import machine

HEAVY_FILES = 4         # a run across this many test files (the full suite) is a heavy job
RENDER_HEAVY = {'test_live_parity.py', 'test_live_song_parity.py', 'test_roundtrip.py'}   # heavy on their own:
                        # they render whole windows; any other single file, however many tests, is light


def pytest_collection_modifyitems(config, items):
    files = {os.path.basename(str(it.fspath)) for it in items}
    config._ismail_heavy = len(files) >= HEAVY_FILES or bool(files & RENDER_HEAVY)


@pytest.fixture(scope='session', autouse=True)
def _the_suite_is_one_heavy_job(request):
    """A big test run is one CPU-heavy job on the shared machine: it waits its turn like a render (a busy or hot
    machine refuses it with the reason), and the renders inside it run in its slot. The tests of a few touched files
    are light and run without a slot, unless a file renders whole windows. CI machines are not shared."""
    if not getattr(request.config, '_ismail_heavy', False):
        yield
        return
    with machine.slot('cpu', 'pytest ismail', force=bool(os.environ.get('CI'))):
        yield
