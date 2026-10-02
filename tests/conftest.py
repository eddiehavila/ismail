import os

import pytest

from ismail import machine


@pytest.fixture(scope='session', autouse=True)
def _the_suite_is_one_heavy_job():
    """The test suite is one CPU-heavy job on the shared machine: it waits its turn like a render (a busy or hot
    machine refuses it with the reason), and the renders inside it run in its slot. CI machines are not shared."""
    with machine.slot('cpu', 'pytest ismail', force=bool(os.environ.get('CI'))):
        yield
