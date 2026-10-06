"""The phone page (ismail/phone): a live set in the person's pocket. Nate, 2026-10-05: "make it ergonomic ... easy to
talk back just like I do in VR, and give live feedback through the phone ... while my phone screen is off", with the
agents able to drive the page. The Live DJ asked for its words stamped with the bar he actually heard."""
import json
import subprocess
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
    import soundfile as sf
    a, b = tmp_path / 'a.wav', tmp_path / 'b.wav'
    t = np.arange(22050) / 44100
    sf.write(str(a), 0.1 * np.sin(2 * np.pi * 220 * t), 44100)
    sf.write(str(b), 0.1 * np.sin(2 * np.pi * 230 * t), 44100)
    ans = tmp_path / 'exam' / 'answers.jsonl'
    P.phone_exam('round 35', [{'label': 'A', 'path': str(a)}, {'label': 'B', 'path': str(b)}],
                   question='which is the record?', chips=['harsh', 'thin'], choices=['A', 'B', "can't tell"],
                   answers_path=str(ans), exam_id='r35')
    p = get(base, '/api/state?since=0&wait=0')['panels'][-1]
    assert p['kind'] == 'exam' and [c['label'] for c in p['clips']] == ['A', 'B']
    assert urllib.request.urlopen(base + p['clips'][1]['url'], timeout=5).read() == b.read_bytes()
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


def test_a_short_note_that_is_a_command_acts_as_one(phone):
    """Nate, 10-05: the Dime 3 earbud's one button takes the voice note, and the voice does the rest out and about."""
    ph, base, _ = phone
    since = ph.seq
    assert ph.voice_command('Love this!', 'v1', {'of': 'bar 9'}) == 'love'
    assert ph.voice_command('okay, change it up please', 'v2') == 'change'
    assert ph.voice_command('stop listening', 'v3') == 'stop_listening'
    assert ph.voice_command('I love this part but change it up soon', 'v4') is None    # a real note stays a note
    lines = json.loads(P.phone_listen('dj', since=since, wait=0))['lines']
    assert [(x['kind'], x['what']) for x in lines] == [('tap', 'love'), ('tap', 'change'), ('control', 'stop_listening')]
    assert lines[0]['via'] == 'voice' and lines[0]['id'] == 'v1' and lines[0]['heard']['of'] == 'bar 9'
    assert any(c['type'] == 'stop_listening' for c in ph.cmds)
    page = urllib.request.urlopen(base + '/app.js', timeout=5).read().decode()
    assert "if (want && keysOn) return keyNote();" in page and "h('pause'" in page and 'CUES' in page


def test_an_open_page_off_the_stream_still_hears_a_spoken_answer(phone):
    """2026-10-06, Nate's walk: the page reloaded, the stream stayed off, voice notes still came in, and a spoken
    phone_say was dropped ('nobody is listening'). The open page now gets the words as a clip; status says so."""
    ph, base, _ = phone
    import io
    import numpy as np
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, np.zeros(24000, dtype='float32'), 24000, format='WAV')
    ph._tts = lambda text, voice=None: buf.getvalue()
    assert 'no page is open' in P.phone_say('rain music coming', speak=True)
    get(base, '/api/state?since=0&wait=0')                       # the page is open, not on the stream
    assert 'NOT listening to the stream' in P.phone_status()
    out = P.phone_say('rain music coming', speak=True, sender='dj')
    assert 'spoken clip, 1.0 s' in out
    c = [c for c in ph.cmds if c['type'] == 'say_clip'][-1]
    assert c['text'] == 'rain music coming'
    with urllib.request.urlopen(base + c['url'], timeout=5) as r:
        assert r.status == 200 and len(r.read()) > 1000


def test_what_they_loved_is_kept_and_marks_the_piece_when_it_returns(phone):
    """Nate 10-06: keys stay pressed and nothing shows what he asked for; and a small mark beside now/next for a piece
    he loved before, one played again, or one just made."""
    ph, base, _ = phone
    P.phone_now(now='chapter 3: rain piano', next='chapter 4: dub')
    post(base, '/api/tap', {'what': 'love'})
    post(base, '/api/tap', {'what': 'mood', 'mood': 'lift'})
    s = get(base, '/api/state?since=0&wait=0')
    assert [t['what'] for t in s['taps']] == ['mood', 'love'] and s['taps'][1]['now'] == 'chapter 3: rain piano'
    assert s['tally'] == {'love': 1, 'mood': 1} and s['asked_mood']['mood'] == 'lift'
    assert s['engine']['now_mark'] == 'loved' and s['engine']['next_mark'] is None     # a heart without the DJ saying
    out = P.phone_now(now='chapter 5: new strings', now_mark='new', next_mark='replay')
    assert "(new)" in out and "(replay)" in out
    s = get(base, '/api/state?since=0&wait=0')
    assert s['engine']['now_mark'] == 'new' and s['engine']['next_mark'] == 'replay'
    P.phone_now(now='chapter 3: rain piano')
    assert get(base, '/api/state?since=0&wait=0')['engine']['now_mark'] == 'loved'   # it came back
    with pytest.raises(Exception, match='one of'):
        P.phone_now(now_mark='great')
    assert ph._recent_taps()[-1]['what'] == 'mood'                                      # a restart still has them
    for name in ('icon-192.png', 'icon-512.png', 'icon-maskable.png', 'apple-touch-icon.png'):
        with urllib.request.urlopen(base + '/' + name, timeout=10) as r:
            assert r.read()[:4] == b'\x89PNG'


def test_the_phone_session_is_a_take_on_one_clock(phone):
    """Nate 10-06 08:16: 'can you see when I download stuff? where I'm scrolling? ... like a VR take, but for the
    mobile interface ... do you know if I'm on my phone?' The page reports its actions, timed; phone_timeline lays
    them over the voice notes with the bar playing in the room."""
    ph, base, _ = phone
    P.phone_now(now='chapter 3: rain piano')
    ph.room = lambda age_s=0.0: {'beat': 400.0 - age_s * 2, 'bar': 101, 'of': 'bar 101'}
    r = post(base, '/api/events', {'sid': None, 'events': [
        {'what': 'open', 'mobile': True, 'app': True, 'w': 412, 'h': 915, 'age_ms': 9000},
        {'what': 'scroll', 'to': 'downloads', 'y': 1200, 'age_ms': 4000},
        {'what': 'download', 'file': 'take3.wav', 'age_ms': 3000},
        {'what': 'Bad-Name', 'age_ms': 0},
        {'what': 'note_end', 'dur': 72.5, 'by': 'quiet', 'sent': True, 'nested': {'x': 1}}]})
    assert r['n'] == 4
    rows = json.loads(P.phone_listen('dj', since=0, wait=0, page=True))['lines']
    pg = [x for x in rows if x['kind'] == 'page']
    assert [x['what'] for x in pg] == ['open', 'scroll', 'download', 'note_end']
    assert pg[0]['mobile'] is True and 'ua' in pg[0] and pg[0]['room']['of'] == 'bar 101'
    assert pg[0]['ts'] < pg[3]['ts'] and 'nested' not in pg[3] and pg[1]['now'] == 'chapter 3: rain piano'
    assert not [x for x in json.loads(P.phone_listen('dj', since=0, wait=0))['lines'] if x['kind'] == 'page']
    req = urllib.request.Request(base + '/api/voice?sid=&t=&dur=72.5&end=quiet', data=b'\x1a' * 2000,
                                 headers={'Content-Type': 'audio/webm;codecs=opus'})
    urllib.request.urlopen(req, timeout=5).read()
    tl = P.phone_timeline(minutes=5)
    assert '-- chapter 3: rain piano' in tl and 'download file=take3.wav' in tl and 'scroll to=downloads' in tl
    assert 'voice note 72.5 s, ended by quiet' in tl and 'bar 101' in tl


def test_an_open_panel_and_its_files_survive_a_restart(phone, tmp_path):
    """10-06: a server restart (a merge) dropped an unanswered panel Nate had not read yet."""
    ph, base, _ = phone
    img = tmp_path / 'cover.png'
    img.write_bytes(b'\x89PNG' + b'0' * 100)
    P.phone_panel_show(panel_id='visibility', title='What the agents can see', text='...', image=str(img))
    saved = json.loads((S.HOME / 'state.json').read_text(encoding='utf8'))
    assert [x['id'] for x in saved['panels']] == ['visibility']
    tok = saved['panels'][0]['image'].split('/')[-1]
    assert saved['files'][tok].endswith('cover.png')


def test_an_agent_sets_the_pages_vibe_and_it_stays_readable(phone, tmp_path):
    """Nate 10-06 08:18: 'change the colors ... how the headers look ... song covers in the background, blurred
    ... JavaScript effects ... I feel like you're there'. A vibe is data, checked by the server."""
    ph, base, _ = phone
    assert 'presets: default, rain' in P.phone_vibe(menu=True)
    out = P.phone_vibe(preset='rain')
    assert 'effect rain' in out and 'heading fraunces' in out
    v = get(base, '/api/state?since=0&wait=0')['vibe']
    assert v['css']['--ground'] == '#0b0f14' and 'Fraunces' in v['font_css'] and v['css']['--head'].startswith("'Fraunces'")
    cover = tmp_path / 'cover.jpg'
    cover.write_bytes(b'\xff\xd8' + b'0' * 200)
    P.phone_vibe(image=str(cover), blur=20, accent='#ff8844', effect='pulse')
    v = get(base, '/api/state?since=0&wait=0')['vibe']
    assert v['image'].startswith('/files/') and v['blur'] == 20 and v['effect'] == 'pulse' and v['heading'] == 'fraunces'
    with urllib.request.urlopen(base + v['image'], timeout=5) as r:
        assert r.read()[:2] == b'\xff\xd8'
    for bad, why in ((dict(ground='#f0f0f0'), 'light'), (dict(ink='#333333'), '7:1'), (dict(accent='#202020'), '3:1'),
                     (dict(heading='comic sans'), 'one of'), (dict(effect='fire'), 'one of'), (dict(preset='x'), 'one of')):
        with pytest.raises(Exception, match=why):
            P.phone_vibe(**bad)
    assert get(base, '/api/state?since=0&wait=0')['vibe']['effect'] == 'pulse'        # a refusal changes nothing
    assert 'no art' in P.phone_vibe(image='', reset=True)
    assert any(c['type'] == 'vibe' for c in ph.cmds)
    saved = json.loads((S.HOME / 'state.json').read_text(encoding='utf8'))
    assert saved['vibe']['effect'] == 'none'


def test_time_into_the_piece_rides_with_every_line(phone):
    """Nate 10-06 08:24: bars are one way; a casual listener talks in time ('2:31 into it')."""
    ph, base, _ = phone
    P.phone_now(now='chapter 7: plume house')
    ph.piece = ('chapter 7: plume house', time.time() - 151)
    post(base, '/api/tap', {'what': 'love'})
    s = get(base, '/api/state?since=0&wait=0')
    assert 150 <= s['into_s'] <= 155 and len(s['clock']) == 8
    assert 150 <= s['taps'][0]['into_s'] <= 155
    assert '2:3' in P.phone_timeline(minutes=5)


def test_a_restart_is_announced_and_the_page_can_tell_it_happened(phone):
    """10-06 08:38: a restart after a merge dropped Nate's stream mid-set ("Why'd you stop?"), and a page whose
    command count was past the new server's missed every command after it. The page is told first, and sees the
    boot and the page build change."""
    ph, base, _ = phone
    s = get(base, '/api/state?since=0&wait=0')
    assert s['boot'] == S.BOOT and len(s['build']) == 10
    assert 'told the page' in post(base, '/agent', {'op': 'restarting', 'args': {'back_in_s': 5}})['result']
    c = [c for c in ph.cmds if c['type'] == 'restarting'][-1]
    assert c['back_in_s'] == 5.0
    assert S.page_build() == S.BUILD


def test_downloads_have_names_and_mp3s_carry_ismail(phone, tmp_path):
    """Nate 10-06 09:09: a readable download name, the title in the mp3, and 'ismail with the GitHub link in the ID3
    data, very important for provenance whenever we ship mp3s'. Their own file is never changed."""
    from ismail import tags
    ph, base, _ = phone
    if not S.ffmpeg():
        pytest.skip('ffmpeg is not installed')
    src = tmp_path / 'rec_20261006_090713_hl2.mp3'
    subprocess.run([S.ffmpeg(), '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-t', '1',
                    '-b:a', '64k', str(src)], check=True)
    before = src.read_bytes()
    P.phone_offer(str(src), label='Clair de lune / rain bed (highlight)', album='ismail live 10-06')
    o = get(base, '/api/state?since=0&wait=0')['offers'][-1]
    assert o['name'] == 'Clair de lune rain bed (highlight).mp3'
    with urllib.request.urlopen(base + o['url'] + '?dl=1', timeout=10) as r:
        assert o['name'] in r.headers['Content-Disposition']
        got = r.read()
    out = tmp_path / 'got.mp3'
    out.write_bytes(got)
    t = tags.read_tags(str(out))
    assert t['title'] == 'Clair de lune / rain bed (highlight)' and t['artist'] == 'ismail' and t['album'] == 'ismail live 10-06'
    assert t['url'] == tags.HOME_URL and tags.HOME_URL in t['comment'] and t['encoder'] == 'ismail'
    assert src.read_bytes() == before                                                   # their file is untouched


def test_the_piece_has_a_shape_and_its_start_survives_a_restart(phone):
    """Nate 10-06 09:12: where we are in the song, always on screen; and M139: a restart reset 'into_s'."""
    ph, base, _ = phone
    P.phone_now(now='chapter 9: sweet clair', length=324, into=40,
                sections=[{'at_s': 64, 'name': 'melody'}, {'at_s': 0, 'label': 'intro'}])
    s = get(base, '/api/state?since=0&wait=0')
    assert s['shape']['length_s'] == 324 and [x['label'] for x in s['shape']['sections']] == ['intro', 'melody']
    assert 40 <= s['into_s'] <= 45
    saved = json.loads((S.HOME / 'state.json').read_text(encoding='utf8'))
    assert saved['piece'][0] == 'chapter 9: sweet clair' and saved['shape']['length_s'] == 324
    P.phone_now(now='chapter 10: plume')
    assert get(base, '/api/state?since=0&wait=0')['shape'] == {}                        # a new piece clears it
