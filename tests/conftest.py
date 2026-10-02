import os

import pytest

from ismail import machine

HEAVY_RUN = 30          # tests: a run this size (the full suite) is a heavy job; a few touched tests are not


def pytest_collection_modifyitems(config, items):
    config._ismail_n_tests = len(items)


@pytest.fixture(scope='session', autouse=True)
def _the_suite_is_one_heavy_job(request):
    """A big test run is one CPU-heavy job on the shared machine: it waits its turn like a render (a busy or hot
    machine refuses it with the reason), and the renders inside it run in its slot. A few touched tests are light
    and run without a slot. CI machines are not shared."""
    if getattr(request.config, '_ismail_n_tests', 0) < HEAVY_RUN:
        yield
        return
    with machine.slot('cpu', 'pytest ismail', force=bool(os.environ.get('CI'))):
        yield
