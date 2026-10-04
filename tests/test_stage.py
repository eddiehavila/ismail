"""The stage without a headset: the server on a scratch scenes folder, a fake page that answers commands the way
live.js does, and the stage_* ops against both."""
import json
import threading
import time
import urllib.request

import pytest

from ismail.api import OPS, OpError
from ismail.stage import server as S
from ismail.stage import world as W


def _get(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/{path}', timeout=10) as r:
        body = r.read()
        return r.status, (json.loads(body) if r.headers.get('Content-Type', '').startswith('application/json') else body)


def _post(port, path, obj):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/{path}', data=json.dumps(obj).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


@pytest.fixture()
def stage(tmp_path, monkeypatch):
    scenes = tmp_path / 'scenes'
    for name in ('room', 'attic'):
        (scenes / name).mkdir(parents=True)
        (scenes / name / 'scene.glb').write_bytes(b'glTF')
        (scenes / name / 'manifest.json').write_text('{"objects": {}}', encoding='utf-8')
    (scenes / 'stage.json').write_text('{"default": "room"}', encoding='utf-8')
    monkeypatch.setenv('ISMAIL_STAGE_REGISTRY', str(tmp_path / 'reg'))
    S.LIVE.clear()
    S.configure(scenes)
    srv = S.Server(('127.0.0.1', 0), S.Handler)
    port = srv.server_address[1]
    S.register(port, 'http', '127.0.0.1')
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {'port': port, 'scenes': scenes, 'srv': srv}
    srv.shutdown()
    srv.server_close()


class FakePage:
    """Posts its state and answers each command with cmd_done, like live.js (refuse= types answer with an error)."""

    def __init__(self, port, scene, refuse=()):
        self.port, self.scene, self.refuse, self.stop = port, scene, set(refuse), False
        self.seen = []
        _post(port, f'live/state?scene={scene}', {'scene': scene, 'xr': False, 'camera': {'position': [1, 2, 1.6]}})
        self.since = _get(port, f'live/cmd?scene={scene}&since=-1')[1]['last']
        self.t = threading.Thread(target=self.run, daemon=True)
        self.t.start()

    def run(self):
        while not self.stop:
            got = _get(self.port, f'live/cmd?scene={self.scene}&since={self.since}&wait=1')[1]
            self.since = got['last']
            for c in got['cmds']:
                self.seen.append(c)
                if c['type'] in self.refuse:
                    ev = {'type': 'cmd_done', 'cmd_id': c['id'], 'cmd': c['type'], 'ok': False, 'error': 'no object chair', 'ms': 3}
                else:
                    ev = {'type': 'cmd_done', 'cmd_id': c['id'], 'cmd': c['type'], 'ok': True, 'ms': 4,
                          'result': {k: v for k, v in c.items() if k not in ('id', 'ts', 'type')}}
                _post(self.port, f'live/event?scene={self.scene}', ev)


def test_serves_page_scenes_and_world(stage):
    p = stage['port']
    assert _get(p, 'stage')[1] == {'scenes': ['attic', 'room'], 'default': 'room', 'code': S.code_version()}
    assert _get(p, 'scenes/room/manifest.json')[1] == {'objects': {}}
    assert b'<html' in _get(p, 'index.html')[1].lower()
    w = _get(p, 'world?scene=room')[1]
    assert w['actors'] == {} and w['floor'] == 0.0
    with pytest.raises(urllib.error.HTTPError):
        _get(p, 'scenes/../server.py')


def test_busy_port_is_refused(stage):
    with pytest.raises(OSError):
        S.Server(('127.0.0.1', stage['port']), S.Handler)


def test_session_files_go_to_the_state_folder(stage):
    _post(stage['port'], 'clientlog', {'page': 'x', 'scene': 'room', 'entries': [{'level': 'info', 'msg': 'hi'}]})
    assert (stage['scenes'] / '_stage' / 'clientlog.jsonl').is_file()
    assert 'room' in [n for n in S.scene_names()] and '_stage' not in S.scene_names()


def test_page_command_op_waits_for_the_answer(stage):
    page = FakePage(stage['port'], 'room')
    try:
        out = OPS['stage_object_set'](scene='room', object='chair', location=[1, 2, 0])
        assert out.startswith('set (4 ms):') and '"location": [1, 2, 0]' in out
        assert page.seen[-1]['type'] == 'set' and 'offset' not in page.seen[-1]    # None fields are left out
    finally:
        page.stop = True


def test_a_refused_command_raises_with_the_reason(stage):
    page = FakePage(stage['port'], 'room', refuse={'select'})
    try:
        with pytest.raises(OpError, match='no object chair'):
            OPS['stage_object_select'](scene='room', object='chair')
    finally:
        page.stop = True


def test_no_page_says_where_to_open_it(stage):
    with pytest.raises(OpError, match=r'no page is showing scene .room.*\?scene=room'):
        OPS['stage_say'](scene='room', text='hello')


def test_unknown_command_and_scene(stage):
    page = FakePage(stage['port'], 'room')
    try:
        with pytest.raises(OpError, match='unknown command'):
            OPS['stage_cmd'](scene='room', type='fly_to_the_moon')
        with pytest.raises(OpError, match='use stage_object_set'):
            OPS['stage_cmd'](scene='room', type='set', fields={'object': 'chair'})
        with pytest.raises(OpError, match="no running stage server has a scene 'kitchen'"):
            OPS['stage_say'](scene='kitchen', text='hi')
    finally:
        page.stop = True


def test_events_filtered_by_type(stage):
    p = stage['port']
    _post(p, 'live/event?scene=room', [{'type': 'gesture', 'hand': 'left'}, {'type': 'voice_message', 'text': 'more light'}])
    out = OPS['stage_events'](scene='room', types=['voice_message'])
    assert out.splitlines()[0].startswith('last 2;') and 'more light' in out and 'gesture' not in out


def test_world_roundtrip_and_checks(stage):
    sc = str(stage['scenes'])
    out = OPS['stage_world'](scene='room', scenes=sc, world={'actors': {'person_a': 'bf_pete'}, 'floor': 0.09,
                                                            'build': {'script': 'video/rooms/room.py'}})
    assert 'bf_pete' in out and _get(stage['port'], 'world?scene=room')[1]['floor'] == 0.09
    with pytest.raises(OpError, match='keep_out'):
        OPS['stage_world'](scene='room', scenes=sc, world={'keep_out': [[1, 0, 0, 1, 0, 1]]})
    script, cwd, env = W.build_of(stage['scenes'], 'room')
    assert script == (stage['scenes'] / 'room' / '../../../..' / 'video' / 'rooms' / 'room.py').resolve()


def test_update_notes_reach_the_page(stage):
    OPS['stage_note'](scenes=str(stage['scenes']), title='Panels on top', level='important')
    got = _get(stage['port'], 'updates.json')[1]
    assert got['updates'][-1]['title'] == 'Panels on top' and got['updates'][-1]['level'] == 'important'


def test_scene_go_answers_from_the_new_scene(stage):
    p = stage['port']
    _post(p, 'live/state?scene=room', {'scene': 'room'})

    def page():                                       # takes the command on room, answers on attic, like scenes.js
        since = _get(p, 'live/cmd?scene=room&since=-1')[1]['last']
        for _ in range(50):
            got = _get(p, f'live/cmd?scene=room&since={since}&wait=1')[1]
            since = got['last']
            if got['cmds']:
                _post(p, 'live/event?scene=attic', {'type': 'scene_switched', 'from': 'room', 'to': 'attic', 'objects': 3, 'ms': 900})
                return
    threading.Thread(target=page, daemon=True).start()
    time.sleep(0.2)
    out = OPS['stage_scene_go'](scene='room', name='attic')
    assert 'switched to attic' in out and 'scene="attic"' in out


def test_status_lists_the_server(stage):
    assert str(stage['scenes']) in OPS['stage_status']()


def test_no_server_says_how_to_start_one(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_STAGE_REGISTRY', str(tmp_path / 'empty'))
    with pytest.raises(OpError, match=r'no stage server is running; start one with stage_start'):
        OPS['stage_say'](scene='room', text='hello')


def test_a_page_seen_just_now_counts(stage, monkeypatch):
    """age_s 0.0 (Linux and macOS clocks) is a live page, not a missing one (CI caught `age or 1e9`)."""
    from ismail.stage import link
    page = FakePage(stage['port'], 'room')
    real = link.page_state
    monkeypatch.setattr(link, 'page_state', lambda rec, scene: {**real(rec, scene), 'age_s': 0.0})
    try:
        assert OPS['stage_object_deselect'](scene='room').startswith('deselect (')
    finally:
        page.stop = True
