"""Keyed motion between keys (page/interp.js, run in node) and trial moves (the ops' side)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ismail.api import OPS, OpError
from test_stage import FakePage, stage  # noqa: F401  (the fixture)

INTERP = (Path(__file__).resolve().parents[1] / 'ismail' / 'stage' / 'page' / 'interp.js').as_uri()


def _node(expr):
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    js = f"import('{INTERP}').then((m) => {{ console.log(JSON.stringify({expr})); }});"
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


KEYS = [{'t': 0, 'location': [0, 0, 0]}, {'t': 5, 'location': [10, 0, 0]}, {'t': 10, 'location': [10, 10, 0]}]


def test_smooth_glides_through_a_key_and_stop_halts_there():
    ks = json.dumps(KEYS)
    got = _node(f"""(() => {{ const ks = {ks}, v = (t, m) => m.vec(ks, t, 'location', m.mode);
      const at = (t, mode) => m.vec(ks, t, 'location', mode);
      const speed = (mode) => Math.hypot(...at(5.01, mode).map((x, j) => (x - at(4.99, mode)[j]) / 0.02));
      return {{ keys: [0, 5, 10].map((t) => at(t, 'smooth')), stopSpeed: speed('stop'), smoothSpeed: speed('smooth'),
               mid: at(2.5, 'smooth'), midStop: at(2.5, 'stop') }}; }})()""")
    assert got['keys'] == [[0, 0, 0], [10, 0, 0], [10, 10, 0]]          # both pass through every key
    assert got['stopSpeed'] < 0.05                                     # stop: at rest on the middle key
    # smooth: the tangent at the middle key is (p2 - p0) / (t2 - t0) = (1, 1, 0) m/s, length sqrt(2)
    assert got['smoothSpeed'] == pytest.approx(2 ** 0.5, rel=0.01)
    assert got['midStop'] == [5, 0, 0] and got['mid'][1] < 0             # Hermite overshoots a little before the turn


def test_slerp_share_follows_the_mode():
    got = _node("[m.slerpK(0.25, 'stop'), m.slerpK(0.25, 'smooth'), m.segment([{t: 0}, {t: 4}], 1)]")
    assert got[0] == pytest.approx(0.15625) and got[1] == 0.25 and got[2] == {'i': 0, 'u': 0.25}


def test_key_interp_and_trial_set_reach_the_page(stage):
    page = FakePage(stage['port'], 'room')
    try:
        OPS['stage_key_interp'](scene='room', object='cf_hall_wide_cam')
        assert (page.seen[-1]['type'], page.seen[-1]['name'], page.seen[-1]['mode']) == ('key_interp', 'cf_hall_wide_cam', 'smooth')
        with pytest.raises(OpError, match="'stop' or 'smooth'"):
            OPS['stage_key_interp'](scene='room', object='x', mode='bezier')
        OPS['stage_object_set'](scene='room', object='cf_hall_wide_cam', offset=[0, 0, 0.5], trial=True)
        assert page.seen[-1]['trial'] is True
        OPS['stage_object_set'](scene='room', object='cf_hall_wide_cam', offset=[0, 0, 0.5])
        assert 'trial' not in page.seen[-1]
        with pytest.raises(OpError, match='stage_key_interp'):
            OPS['stage_cmd'](scene='room', type='key_interp')
    finally:
        page.stop = True
