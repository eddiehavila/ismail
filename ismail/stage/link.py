"""The agent's side of the live link: find the stage server that serves a scene, queue a command for its page, wait
for the page's answer, read events. Plain HTTP to 127.0.0.1 (the server's registry, ~/.ismail/stage/<port>.json)."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..api import OpError

PAGE_FRESH_S = 120         # a page that posted its state within this long is "showing the scene" (a hidden
                           # tab or a lifted headset posts about once a minute; the command waits in its queue)


def registry_dir():
    return Path(os.environ.get('ISMAIL_STAGE_REGISTRY') or Path.home() / '.ismail' / 'stage')


def _pid_alive(pid):
    from ..live.ops import _pid_alive as alive
    return alive(pid)


def servers():
    """Running stage servers, newest first (records of dead ones are removed)."""
    out = []
    d = registry_dir()
    for f in d.glob('*.json') if d.is_dir() else []:
        try:
            rec = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not _pid_alive(rec.get('pid', -1)):
            try:
                f.unlink()
            except OSError:
                pass
            continue
        out.append(rec)
    return sorted(out, key=lambda r: -r.get('started', 0))


def server_for(scene=None, port=None):
    """The server for a port, or the one whose scenes folder holds `scene`, or the only/newest one."""
    srv = servers()
    if not srv:
        raise OpError('no stage server is running; start one with stage_start(scenes="<song>/video/vr/scenes")')
    if port:
        for r in srv:
            if int(r['port']) == int(port):
                return r
        raise OpError(f'no stage server on port {port}; running: {[r["port"] for r in srv]}')
    if scene:
        for r in srv:
            if (Path(r['scenes']) / scene / 'scene.glb').is_file():
                return r
        raise OpError(f'no running stage server has a scene {scene!r}; servers: '
                      + '; '.join(f'{r["port"]}: {r["scenes"]}' for r in srv) + ' (stage_scenes lists them)')
    return srv[0]


def http(rec, path, body=None, timeout=30):
    url = f'http://127.0.0.1:{rec["port"]}/{path.lstrip("/")}'
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'} if data else {},
                                 method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b'null')
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get('error')
        except (ValueError, AttributeError):
            msg = str(e)
        raise OpError(f'stage server: {msg}')
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise OpError(f'the stage server on port {rec["port"]} does not answer ({e}); stage_status, or stage_start again')


def q(**kw):
    return urllib.parse.urlencode({k: v for k, v in kw.items() if v is not None})


def page_state(rec, scene):
    return http(rec, f'live/state?{q(scene=scene)}', timeout=10)


def page_cmd(scene, ctype, fields, timeout=30):
    """Queue one command for the page showing `scene`; wait for its cmd_done; reply with the page's answer."""
    rec = server_for(scene)
    st = page_state(rec, scene)
    if st.get('state') is None or (st.get('age_s') or 1e9) > PAGE_FRESH_S:
        raise OpError(f'no page is showing scene {scene!r} (last seen {st.get("age_s")} s ago); open '
                      f'{rec["url"]}?scene={scene} in the headset or a browser, then try again')
    cmd = {'type': ctype, **{k: v for k, v in fields.items() if v is not None}}
    # a scene switch answers on the scene it switched to (the page listens there from then on)
    watch = [scene] + ([fields['name']] if ctype == 'scene_go' and fields.get('name') not in (None, scene) else [])
    since = {s: http(rec, f'live/events?{q(scene=s, limit=1)}')['last'] for s in watch if (Path(rec['scenes']) / s).is_dir()}
    ids = http(rec, f'live/cmd?{q(scene=scene)}', cmd)['ids']
    t_end = time.time() + timeout
    while time.time() < t_end:
        for s in since:
            got = http(rec, f'live/events?{q(scene=s, since=since[s], wait=min(10 if len(since) == 1 else 1, max(1, t_end - time.time())), limit=500)}',
                       timeout=20)
            since[s] = got['last']
            for e in got['events']:
                if e.get('type') == 'cmd_done' and e.get('cmd_id') in ids and s == scene:
                    return reply(ctype, e)
                if ctype == 'scene_go' and s != scene and e.get('type') == 'scene_switched':
                    return f'scene_go: switched to {s} ({e.get("objects")} objects, {e.get("ms")} ms); send further ops with scene="{s}"'
    raise OpError(f'the page took no answer to {ctype} within {timeout:.0f} s (command {ids[0]}); a panel or question '
                  f'waiting for the person blocks the queue: stage_events(scene="{scene}", types=["cmd_done"]) shows it')


def reply(ctype, e):
    if e.get('ok') is False or e.get('error'):
        raise OpError(f'{ctype}: {e.get("error") or "the page refused it"}')
    res = e.get('result')
    txt = json.dumps(res, separators=(', ', ': '), default=str) if res is not None else 'done'
    if len(txt) > 2000:
        txt = txt[:2000] + ' ...'
    return f'{ctype} ({e.get("ms", "?")} ms): {txt}'
