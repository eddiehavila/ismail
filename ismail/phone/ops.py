"""phone_* ops: agents drive the phone page and read what the person sends from it (server.py says how it works)."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from ..api import OpError, op
from . import server as S


def _port():
    try:
        return int(json.loads((S.HOME / 'server.json').read_text(encoding='utf8'))['port'])
    except (OSError, ValueError, KeyError):
        return None


def _call(op_name, timeout=30, **args):
    port = _port()
    if port is None:
        raise OpError("the phone server is not running: phone_start() first (it relays the live set to the phone)")
    req = urllib.request.Request(f'http://127.0.0.1:{port}/agent', headers={'Content-Type': 'application/json'},
                                 data=json.dumps({'op': op_name, 'args': {k: v for k, v in args.items()
                                                                          if v is not None}}).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        res = json.loads(e.read() or b'{}')
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise OpError(f"the phone server does not answer ({e}): phone_start() again (log: {S.HOME / 'server.log'})")
    if not res.get('ok'):
        raise OpError(res.get('error', 'phone server error'))
    return res['result']


def _tailnet(port):
    """The tailnet https address for the port, when `tailscale serve` proxies it; else the command that would."""
    try:
        flags = 0x08000000 if os.name == 'nt' else 0
        st = json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=10,
                                       creationflags=flags).stdout or '{}')
        host = (st.get('Self') or {}).get('DNSName', '').rstrip('.')
        sv = subprocess.run(['tailscale', 'serve', 'status'], capture_output=True, text=True, timeout=10,
                            creationflags=flags).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, "tailscale is not installed or not running: the phone can only reach the page on this machine"
    if host and f'{host}:{port} ' in sv + ' ' and f'127.0.0.1:{port}' in sv:
        return f'https://{host}:{port}/', ''
    return None, (f"the tailnet does not reach it yet: run `tailscale serve --bg --https={port} http://127.0.0.1:{port}` "
                  f"once (it stays; tailnet only, never public), then the phone opens https://{host or '<this pc>'}:{port}/")


@op()
def phone_start(port: int = 8870, inbox: str = None) -> str:
    """Start the phone page server (idempotent): the live set in the person's pocket over the tailnet. It relays the
    newest live engine's master as an mp3 stream that keeps playing with the phone's screen off, and takes the
    person's taps and voice notes back, each stamped with the bar they heard. Never starts a set or plays sound here.
    inbox: also write what they send to this file (default: the playing engine's <project>/notes/phone_inbox.jsonl).
    Returns the address to give them. Read what they send with phone_listen, or watch the inbox file."""
    if _port():
        try:
            st = _call('status', timeout=5)
            if inbox:
                _call('route', inbox=inbox)
            url, hint = _tailnet(_port())
            return f"already running: {url or hint}\n{st}"
        except OpError:
            pass
    S.HOME.mkdir(parents=True, exist_ok=True)
    if not S.ffmpeg():
        raise OpError("ffmpeg is not on PATH (or $ISMAIL_FFMPEG): the phone stream needs it (winget install -e --id "
                      "Gyan.FFmpeg)")
    log = open(S.HOME / 'server.log', 'a', encoding='utf8')
    args = [sys.executable, '-m', 'ismail.phone.server', '--port', str(port)] + (['--inbox', inbox] if inbox else [])
    flags = (0x00000008 | 0x00000200 | 0x08000000) if os.name == 'nt' else 0   # detached, own group, no window
    subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags,
                     cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     start_new_session=os.name != 'nt')
    for _ in range(50):
        time.sleep(0.2)
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as r:
                if json.loads(r.read()).get('ok'):
                    break
        except (OSError, ValueError):
            continue
    else:
        raise OpError(f"the phone server did not come up on {port}: read {S.HOME / 'server.log'}")
    url, hint = _tailnet(port)
    return (f"phone page up: http://127.0.0.1:{port}/ here" + (f", {url} on the tailnet" if url else '') +
            (f"\n{hint}" if hint else '') +
            "\nTell the person: open it, press play, put the phone away; hold the mic to talk. Then phone_listen "
            "(or watch the inbox) for what they send.")


@op()
def phone_stop() -> str:
    """Stop the phone page server (the person's stream ends)."""
    port = _port()
    if port is None:
        return 'the phone server was not running'
    pid = json.loads((S.HOME / 'server.json').read_text(encoding='utf8')).get('pid')
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, timeout=10)
        else:
            os.kill(int(pid), 15)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        (S.HOME / 'server.json').unlink()
    except OSError:
        pass
    return f'stopped the phone server (pid {pid})'


@op()
def phone_status() -> str:
    """Who is listening on the phone, the bar they hear and how far behind the room, the engine, the inbox, voice
    notes waiting for transcription, and what the page shows."""
    return _call('status')


@op()
def phone_listen(who: str, since: int = None, wait: float = 25) -> str:
    """What the person sent from the phone, oldest first, as JSON {since, lines}: taps (love = cut a highlight,
    change = change it up now, energy_up/energy_down, louder/quieter, pause/resume, start_set), mood (calm, steady,
    lift, peak), voice (then voice_text with the words, same id), answer / exam (to phone_ask, phone_panel_show,
    phone_exam), button (phone_buttons). Every line carries heard {bar, beat, of} (what they actually heard, not the
    engine's now) and behind_s. who: your name (the page shows who is listening while you call at least every 90 s).
    since: the last call's `since` (default: only new lines); wait: seconds to wait for one."""
    return _call('listen', timeout=float(wait or 0) + 15, who=who, since=since, wait=wait)


@op()
def phone_say(text: str, speak: bool = False, pin: bool = False, buzz: bool = False, voice: str = None,
              sender: str = None) -> str:
    """A caption on the phone. speak=True also says it into the stream (Kokoro, the music ducked under it), so they
    hear it in their pocket: only to answer something they said, never unprompted. pin=True keeps it at the top
    (a "since you left" summary). buzz=True vibrates the phone if the page is open."""
    return _call('say', text=text, speak=speak, pin=pin, buzz=buzz, voice=voice, who=sender)


@op()
def phone_now(now: str = None, next: str = None, recording_why: str = None, mood: str = None,
              sender: str = None) -> str:
    """What the page shows as now playing and next up (default: read from the engine), and why recording is on or
    off (the page always shows whether it is). '' clears a field. mood: set the mood chip (calm, steady, lift, peak)."""
    return _call('now', now=now, next=next, recording_why=recording_why, mood=mood, who=sender)


@op()
def phone_panel_show(panel_id: str = None, title: str = '', text: str = '', image: str = None, buttons: list = None,
                     wait: float = 0, sender: str = None) -> str:
    """A panel over the phone page (the stage_panel_show shape): title, text, an image file, buttons (labels). The
    tap arrives in the inbox as kind 'answer' {id, answer}; wait=N blocks up to N seconds for it."""
    return _call('panel_show', timeout=float(wait or 0) + 15, panel_id=panel_id, title=title, text=text, image=image,
                 buttons=buttons, wait=wait, who=sender)


@op()
def phone_panel_close(panel_id: str) -> str:
    """Close a panel, question or exam on the phone."""
    return _call('panel_close', panel_id=panel_id)


@op()
def phone_ask(text: str, wait: float = 0, sender: str = None) -> str:
    """A yes/no question on the phone; the answer arrives as kind 'answer'; wait=N blocks up to N seconds for it."""
    return _call('ask', timeout=float(wait or 0) + 15, text=text, wait=wait, who=sender)


@op()
def phone_exam(title: str, clips: list, question: str = '', chips: list = None, choices: list = None,
               answers_path: str = None, exam_id: str = None, wait: float = 0, sender: str = None) -> str:
    """A blind exam on the phone: clips [{label, path, note?}] each with a play button (the live stream pauses while
    one plays, and rejoins live after), word chips to tick per clip, one choice (e.g. ['A is the record', 'B is the
    record', "can't tell"]), a note, and Submit. The answers arrive as kind 'exam' {id, answers}, and are appended
    to answers_path when given (the exam's own answers file, so no "done" is needed). Label clips blind (A, B)."""
    return _call('exam', timeout=float(wait or 0) + 15, title=title, clips=clips, question=question, chips=chips,
                 choices=choices, answers_path=answers_path, exam_id=exam_id, wait=wait, who=sender)


@op()
def phone_offer(path: str, label: str = None, auto: bool = False, sender: str = None) -> str:
    """Offer a file for download on the phone (a render, a take, a PDF). auto=True starts it at once if the page is
    open; otherwise it waits as a card with a Download button."""
    return _call('offer', path=os.path.abspath(path), label=label, auto=auto, who=sender)


@op()
def phone_buttons(buttons: list = None, sender: str = None) -> str:
    """Extra buttons on the page, as data: [{'id': 'darker', 'label': 'darker'}, ...] or plain labels; [] or none
    clears them. A tap arrives as kind 'button' {id, label, heard}."""
    return _call('buttons', buttons=buttons or [], who=sender)


@op()
def phone_buzz(pattern: list = None) -> str:
    """Vibrate the phone (if the page is open): pattern in ms, e.g. [200, 100, 200]."""
    return _call('buzz', pattern=pattern)


@op()
def phone_route(inbox: str = None) -> str:
    """Also write what the person sends to this file (a song's notes/phone_inbox.jsonl); none: back to the playing
    engine's project."""
    return _call('route', inbox=inbox)
