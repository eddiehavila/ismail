"""The phone page (ismail/phone): a live set in the person's pocket. Nate, 2026-10-05: "make it ergonomic ... easy to
talk back just like I do in VR, and give live feedback through the phone ... while my phone screen is off", with the
agents able to drive the page. The Live DJ asked for its words stamped with the bar he actually heard."""
import json
import math
import os
import shutil
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from ismail import api  # noqa: F401  (the op table loads)
from ismail.phone import ops as P
from ismail.phone import server as S

STATUS = "live 120 BPM 4/4 | heard bar 5 beat 2 (9 s) | mixed ahead 0.50 s | output none | recording rec_1.wav\n" \
         "deck a: gain 0 dB | 3 tracks\n  lead       code:grand_piano           vol +0 pan +0 level  -18.0 dBFS " \
         "(max 2 s  -12.0) | playing ch3 (pass 1/inf), next ch4 at bar 9 | renders 9x realtime"


class FakeEngine(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        req = json.loads(self.rfile.read(n))
        b = json.dumps({'ok': True, 'result': STATUS if req['op'] == 'status' else ''}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self.send_response(200)
        self.send_header('X-Sample-Rate', '44100')
        self.end_headers()
        t = np.arange(4410) / 44100
        y = (0.3 * np.sin(2 * math.pi * 220 * t) * 32767).astype('<i2')
        block = np.stack([y, y], axis=1).tobytes()
        try:
            for _ in range(200):
                self.wfile.write(block)
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass


@pytest.fixture
def phone(tmp_path, monkeypatch):
    home, reg, proj = tmp_path / 'phone', tmp_path / 'live', tmp_path / 'song'
    reg.mkdir()
    proj.mkdir()
    monkeypatch.setattr(S, 'HOME', home)
    monkeypatch.setenv('ISMAIL_LIVE_REGISTRY', str(reg))
    eng = ThreadingHTTPServer(('127.0.0.1', 0), FakeEngine)
    eng.daemon_threads = True
    threading.Thread(target=eng.serve_forever, daemon=True).start()
    (reg / '1.json').write_text(json.dumps({'port': eng.server_address[1], 'started': time.time(),
                                            'project': str(proj)}))
    ph = S.Phone()
    monkeypatch.setattr(ph, '_cpu_busy', lambda: '')
    S.Handler.ph, S.Handler.agent = ph, S.Agent(ph)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), S.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    (home / 'server.json').write_text(json.dumps({'port': httpd.server_address[1], 'pid': os.getpid()}))
    for _ in range(50):
        if ph.engine:
            break
        time.sleep(0.1)
    yield ph, f'http://127.0.0.1:{httpd.server_address[1]}', proj
    httpd.shutdown()
    eng.shutdown()
    for enc in list(ph.encoders.values()):
        enc.close()
    ph.encoders.clear()


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.loads(r.read())


def test_status_text_is_read():
    s = S.parse_status(STATUS)
    assert s['bpm'] == 120 and s['bpb'] == 4 and s['beat'] == 17.0 and s['ahead'] == 0.5
    assert s['recording'] == 'rec_1.wav' and s['next'] == 'ch4 at bar 9' and s['playing'] == ['ch3 (lead)']
    assert S.parse_status('nonsense') is None
    assert S.bar_text(17.0, 4) == 'bar 5 beat 2'


def test_taps_and_words_reach_the_agent_with_where_they_were(phone):
    ph, base, proj = phone
    page = urllib.request.urlopen(base + '/', timeout=5).read().decode()
    assert 'Hold to talk' in page and 'Love this' in page and 'Change it up' in page
    st = get(base, '/api/state?since=0&wait=0')
    assert st['engine']['playing'] and st['engine']['next'] == 'ch4 at bar 9' and st['rec']['on']
    assert st['listening'] == []
    assert 'lines' in P.phone_listen('dj', wait=0)                  # the DJ is now listening
    assert get(base, '/api/state?since=0&wait=0')['listening'] == ['dj']
    since = json.loads(P.phone_listen('dj', wait=0))['since']
    assert post(base, '/api/tap', {'what': 'love'})['ok']
    assert post(base, '/api/tap', {'what': 'mood', 'mood': 'lift'})['ok']
    with pytest.raises(urllib.error.HTTPError):
        post(base, '/api/tap', {'what': 'explode'})
    lines = json.loads(P.phone_listen('dj', since=since, wait=0))['lines']
    assert [x['kind'] for x in lines] == ['tap', 'mood'] and lines[0]['what'] == 'love' and 'highlight' in lines[0]['means']
    routed = (proj / 'notes' / 'phone_inbox.jsonl').read_text(encoding='utf8')   # the DJ's own inbox file
    assert '"love"' in routed and '"lift"' in routed
    assert get(base, '/api/state?since=0&wait=0')['mood'] == 'lift'


def test_the_agent_drives_the_page(phone, tmp_path):
    ph, base, _ = phone
    first = get(base, '/api/state?since=0&wait=0')['cmd']
    assert 'shown on the phone' in P.phone_say('dropping the pads at bar 9', pin=True, sender='dj')
    P.phone_now(now='Canopy Psy, chapter 3', next='chapter 4 at bar 225', recording_why='set take', sender='dj')
    P.phone_buttons(['darker', {'id': 'drop', 'label': 'drop it now'}])
    st = get(base, f'/api/state?since={first}&wait=0')
    assert st['engine']['now'] == 'Canopy Psy, chapter 3' and st['rec']['why'] == 'set take'
    assert st['pinned']['text'] == 'dropping the pads at bar 9' and [b['id'] for b in st['buttons']] == ['darker', 'drop']
    assert any(c['type'] == 'caption' for c in st['cmds'])
    post(base, '/api/tap', {'what': 'button:drop'})
    assert json.loads(P.phone_listen('dj', since=0, wait=0))['lines'][-1]['label'] == 'drop it now'
    out = P.phone_ask('keep the acid line?')
    qid = get(base, '/api/state?since=0&wait=0')['panels'][-1]['id']
    assert 'answer' in out and post(base, '/api/answer', {'id': qid, 'answer': 'yes'})['ok']
    assert json.loads(P.phone_listen('dj', since=0, wait=0))['lines'][-1]['answer'] == 'yes'
    assert get(base, '/api/state?since=0&wait=0')['panels'] == []
    f = tmp_path / 'take.txt'
    f.write_text('a take')
    P.phone_offer(str(f), auto=True)
    o = get(base, '/api/state?since=0&wait=0')['offers'][-1]
    assert urllib.request.urlopen(base + o['url'], timeout=5).read() == b'a take'
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(base + '/files/notatoken', timeout=5)


def test_a_blind_exam_on_the_phone_writes_its_answers(phone, tmp_path):
    ph, base, _ = phone
    a, b = tmp_path / 'a.wav', tmp_path / 'b.wav'
    a.write_bytes(b'RIFFa')
    b.write_bytes(b'RIFFb')
    ans = tmp_path / 'exam' / 'answers.jsonl'
    P.phone_exam('round 35', [{'label': 'A', 'path': str(a)}, {'label': 'B', 'path': str(b)}],
                   question='which is the record?', chips=['harsh', 'thin'], choices=['A', 'B', "can't tell"],
                   answers_path=str(ans), exam_id='r35')
    p = get(base, '/api/state?since=0&wait=0')['panels'][-1]
    assert p['kind'] == 'exam' and [c['label'] for c in p['clips']] == ['A', 'B']
    assert urllib.request.urlopen(base + p['clips'][1]['url'], timeout=5).read() == b'RIFFb'
    post(base, '/api/answer', {'id': 'r35', 'answers': {'choice': "can't tell", 'clips': {'A': ['thin'], 'B': []}}})
    assert json.loads(ans.read_text(encoding='utf8').splitlines()[0])['answers']['choice'] == "can't tell"
    assert json.loads(P.phone_listen('x', since=0, wait=0))['lines'][-1]['kind'] == 'exam'


def test_a_voice_note_is_stamped_and_transcribed(phone, monkeypatch):
    ph, base, _ = phone
    monkeypatch.setattr(S, 'stt', lambda audio, name: 'more acid please')
    req = urllib.request.Request(base + '/api/voice?sid=&t=', data=b'\x1a' * 2000,
                                 headers={'Content-Type': 'audio/webm;codecs=opus'})
    vid = json.loads(urllib.request.urlopen(req, timeout=5).read())['id']
    for _ in range(50):
        lines = json.loads(P.phone_listen('dj', since=0, wait=0))['lines']
        if any(x['kind'] == 'voice_text' for x in lines):
            break
        time.sleep(0.1)
    v = [x for x in lines if x.get('id') == vid]
    assert [x['kind'] for x in v] == ['voice', 'voice_text'] and v[1]['text'] == 'more acid please'
    assert os.path.exists(v[0]['file'])


@pytest.mark.skipif(not S.ffmpeg(), reason='ffmpeg is not installed')
def test_the_stream_plays_and_knows_the_bar_heard(phone):
    ph, base, _ = phone
    r = urllib.request.urlopen(base + '/stream.mp3?sid=s1&kbps=64', timeout=15)
    assert r.headers['Content-Type'] == 'audio/mpeg'
    got, t0 = b'', time.time()
    while len(got) < 16000 and time.time() - t0 < 10:
        got += r.read1(4096)
    r.close()
    assert len(got) >= 16000 and b'\xff\xfb' in got[:4000] or b'\xff\xf3' in got[:4000]   # mp3 frames
    h = ph.heard('s1', 0.5)
    assert 'behind_s' in h and h.get('bar', 0) >= 5 and h['of'].startswith('bar ')
    st = P.phone_status()
    assert 'phone server' in st and 'engine: playing' in st
