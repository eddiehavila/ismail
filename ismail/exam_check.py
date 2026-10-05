"""The exam pre-flight: what every agent runs before an exam page goes to the person (Nate, 2026-10-05: self-checks
live in tools). A blind exam that leaks its answer, a clip that does not play, a clip quieter than the rest, or a
Submit that lands nowhere wastes a round of the one instrument no metric replaces: the person's ear.

run(...) -> (ready, lines). Lines start with FAIL (never show the page), WARN (a likely tell: fix it or say why it
cannot be) or ok. The checks:
- clips: each exists, decodes, is not silent, and how near full scale it peaks;
- loudness: integrated loudness within lufs_tol of each other, and no class louder on average than another;
- blind leaks, given the key ({clip label, file name or path: its class}) and any secret strings: the key's classes
  or the secrets in clip file names and URLs, in their metadata tags, in the page source (and the scripts and styles
  it loads) next to a clip or in a label-to-class mapping, a key/answer file the page loads, formats (sample rate,
  channels, encoding) that differ by class, durations or leading silence that separate the classes, and a clip
  order that follows the key;
- submit: a marked test answer posted to submit_url lands in answers_path (where the asking agent reads it).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

import numpy as np

AUDIO = r'(?:wav|mp3|ogg|oga|flac|m4a|aac|webm|opus)'
KEYISH = re.compile(r'(key|answer|truth|solution|reveal)[\w.-]*\.(json|txt|csv|js)', re.I)


def _decode(path):
    import soundfile as sf
    try:
        info = sf.info(path)
        y, sr = sf.read(path, dtype='float32', always_2d=True)
        return y, sr, {'samplerate': info.samplerate, 'channels': info.channels, 'subtype': info.subtype,
                       'format': info.format}
    except Exception as first:
        ff = os.environ.get('ISMAIL_FFMPEG') or shutil.which('ffmpeg')
        if not ff:
            raise first
        r = subprocess.run([ff, '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '2', '-ar', '44100', 'pipe:1'],
                           capture_output=True, timeout=120)
        if r.returncode or not r.stdout:
            raise RuntimeError(r.stderr.decode('utf8', 'replace').strip()[:200] or str(first))
        y = np.frombuffer(r.stdout, dtype='<f4').reshape(-1, 2)
        return y, 44100, {'samplerate': None, 'channels': None, 'subtype': os.path.splitext(path)[1].lower(),
                          'format': 'ffmpeg'}


def _tags(path):
    """Metadata tags (title, artist, comment, encoder ...) from ffprobe, or {} without it."""
    fp = shutil.which('ffprobe') or (os.path.join(os.path.dirname(os.environ['ISMAIL_FFMPEG']), 'ffprobe')
                                     if os.environ.get('ISMAIL_FFMPEG') else None)
    if not fp:
        return {}
    try:
        r = subprocess.run([fp, '-v', 'quiet', '-print_format', 'json', '-show_format', path], capture_output=True,
                           text=True, timeout=30)
        return {k.lower(): str(v) for k, v in ((json.loads(r.stdout or '{}').get('format') or {}).get('tags') or {}).items()}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _loudness(y, sr):
    mono = y.mean(axis=1)
    try:
        import pyloudnorm as pyln
        if len(mono) >= int(0.45 * sr):
            v = float(pyln.Meter(sr).integrated_loudness(y if y.shape[1] <= 2 else mono))
            if np.isfinite(v):
                return v, 'LUFS'
    except Exception:
        pass
    rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-12)
    return 20 * np.log10(rms) - 0.691, 'dB RMS'


def _lead(y, sr):
    a = np.abs(y).max(axis=1)
    i = np.argmax(a > 10 ** (-50 / 20))
    return i / sr if a.max() > 10 ** (-50 / 20) else None


def _words(terms):
    return [t for t in dict.fromkeys(str(t).strip() for t in terms if t is not None) if len(t) >= 3]


def _hit(text, term):
    return re.search(r'(?<![A-Za-z0-9])' + re.escape(term) + r'(?![A-Za-z0-9])', text, re.I)


def _fetch(url, dest_dir):
    with urllib.request.urlopen(url, timeout=20) as r:
        data = r.read()
    name = os.path.basename(urllib.parse.urlparse(url).path) or 'index.html'
    p = os.path.join(dest_dir, f"{len(os.listdir(dest_dir))}_{name}")
    with open(p, 'wb') as f:
        f.write(data)
    return p, data


def _page(page, tmp):
    """-> (texts {name: source}, clips [{label, path, ref}]) from an exam page file or URL and what it loads."""
    is_url = re.match(r'https?://', page or '')
    texts, clips, seen = {}, [], set()

    def load(ref, base):
        loc = urllib.parse.urljoin(base, ref) if is_url else os.path.normpath(os.path.join(base, ref))
        if is_url:
            p, data = _fetch(loc, tmp)
            return loc, p, data
        with open(loc, 'rb') as f:
            return loc, loc, f.read()

    if is_url:
        loc, _, data = load(page, page)
        base = loc
    else:
        with open(page, 'rb') as f:
            data = f.read()
        loc, base = page, os.path.dirname(os.path.abspath(page))
    html = data.decode('utf8', 'replace')
    texts[os.path.basename(urllib.parse.urlparse(loc).path) or loc] = html
    for ref in re.findall(r'(?:src|href)\s*=\s*["\']([^"\'#?]+\.(?:js|mjs|css|json))', html, re.I):
        try:
            _, _, d = load(ref, base)
            texts[ref] = d.decode('utf8', 'replace')
        except (OSError, ValueError):
            texts[ref] = ''
    for name, src in list(texts.items()):
        for ref in re.findall(r'["\'(`]([^"\'()`\s]+\.' + AUDIO + r')(?:[?#][^"\'()`\s]*)?["\')`]', src, re.I):
            if ref in seen:
                continue
            seen.add(ref)
            try:
                loc2, p, _ = load(ref, base)
                clips.append({'label': ref, 'path': p, 'ref': ref})
            except (OSError, ValueError) as e:
                clips.append({'label': ref, 'path': None, 'ref': ref, 'error': str(e)})
    return texts, clips


def run(clips=None, page=None, key=None, secrets=None, answers_path=None, submit_url=None, submit_body=None,
        lufs_tol=1.0, texts=None):
    fails, warns, oks = [], [], []
    tmp = tempfile.mkdtemp(prefix='exam_check_')
    try:
        texts = dict(texts or {})
        found = []
        if page:
            try:
                t, found = _page(page, tmp)
                texts.update(t)
            except (OSError, ValueError) as e:
                fails.append(f"the page does not load: {page}: {e}")
        cl = []
        for i, c in enumerate(clips or found):
            c = dict(c) if isinstance(c, dict) else {'path': c}
            c.setdefault('label', c.get('ref') or (os.path.basename(c['path']) if c.get('path') else f'clip {i + 1}'))
            c.setdefault('ref', c.get('path') or '')
            cl.append(c)
        if not cl:
            fails.append("no clips: pass clips=[...] or a page whose audio can be found")
            return False, _report(fails, warns, oks, 0)

        # ---- the clips play
        for c in cl:
            p = c.get('path')
            if c.get('error') or not p or not os.path.isfile(p):
                fails.append(f"{c['label']}: missing ({c.get('error') or p})")
                continue
            try:
                y, sr, fmt = _decode(p)
            except Exception as e:
                fails.append(f"{c['label']}: does not decode ({type(e).__name__}: {str(e)[:120]})")
                continue
            peak = float(np.abs(y).max()) if len(y) else 0.0
            c.update(dur=len(y) / sr, fmt=fmt, peak_db=20 * np.log10(peak + 1e-12), lead=_lead(y, sr),
                     tags=_tags(p))
            c['loud'], c['unit'] = _loudness(y, sr) if peak > 0 else (-120.0, 'dB RMS')
            if peak < 10 ** (-60 / 20):
                fails.append(f"{c['label']}: silent (peak {c['peak_db']:.0f} dBFS)")
            elif c['peak_db'] > -0.1:
                warns.append(f"{c['label']}: peaks at {c['peak_db']:.2f} dBFS (it may clip on the person's player)")
        good = [c for c in cl if 'dur' in c]
        if len(good) == len(cl):
            oks.append(f"all {len(cl)} clips exist and decode (" + ', '.join(f"{c['label']} {c['dur']:.1f} s" for c in cl[:8])
                       + (' ...' if len(cl) > 8 else '') + ")")

        # ---- one listening level
        if len(good) >= 2:
            ls = [c['loud'] for c in good]
            spread = max(ls) - min(ls)
            line = ', '.join(f"{c['label']} {c['loud']:.1f}" for c in good[:10]) + f" {good[0]['unit']}"
            (fails if spread > lufs_tol else oks).append(
                f"loudness spread {spread:.1f} {'over' if spread > lufs_tol else 'within'} {lufs_tol:g}: {line}"
                + (": normalise every clip to one loudness" if spread > lufs_tol else ''))

        # ---- the key and what could leak it
        key = {str(k): str(v) for k, v in (key or {}).items()}

        def cls(c):
            for k in (c['label'], os.path.basename(c.get('path') or ''), c.get('path') or '', c.get('ref') or ''):
                if k and k in key:
                    return key[k]
            return None
        for c in cl:
            c['cls'] = cls(c)
        classes = sorted({c['cls'] for c in cl if c['cls']})
        terms = _words(list(classes) + list(secrets or []))
        if key and not classes:
            warns.append("the key matches no clip (key by the clip's label, file name or path): the leak checks "
                         "that need it were skipped")
        if not key and not secrets:
            warns.append("no key and no secrets given: the blind-leak checks are limited; pass key={clip: class} "
                         "(and secrets=[source names]) for the full check")

        for c in cl:                                            # names and urls
            for term in terms:
                for what in ('ref', 'path'):
                    v = os.path.basename(str(c.get(what) or ''))
                    if v and _hit(v, term):
                        fails.append(f"{c['label']}: its file name {v!r} says {term!r}")
                        break
            for k, v in (c.get('tags') or {}).items():
                for term in terms:
                    if _hit(v, term):
                        fails.append(f"{c['label']}: its metadata tag {k}={v!r} says {term!r}")
        for name, src in texts.items():                         # the page source
            for m in KEYISH.finditer(src):
                fails.append(f"the page ({name}) loads {m.group(0)!r}: an answer key the person's browser can read")
            refs = [os.path.basename(str(c.get('ref') or c.get('path') or '')) for c in cl]
            for term in terms:
                for m in re.finditer(r'(?<![A-Za-z0-9])' + re.escape(term) + r'(?![A-Za-z0-9])', src, re.I):
                    # a leak ties the word to one clip: the same tag or statement (no tag edge, ';' or line between),
                    # or a "label": "class" mapping; a question that names the classes for every clip is fine
                    tied = False
                    for r in filter(None, refs):
                        for rm in re.finditer(re.escape(r), src):
                            lo, hi = sorted((rm.end(), m.start())) if rm.start() < m.start() else (m.end(), rm.start())
                            if hi - lo <= 80 and not re.search(r'[<>;\n]', src[lo:hi]):
                                tied = True
                                break
                        if tied:
                            break
                    tied = tied or bool(re.search(r'["\']\s*:\s*["\']?$', src[max(0, m.start() - 8):m.start()]))
                    if tied:
                        near = src[max(0, m.start() - 70):m.end() + 70]
                        fails.append(f"the page ({name}) ties {term!r} to a clip: ...{' '.join(near.split())[:140]}...")
                        break
        if classes and len(classes) >= 2:
            by = {k: [c for c in good if c['cls'] == k] for k in classes}
            fmts = {k: {(c['fmt']['samplerate'], c['fmt']['channels'], c['fmt']['subtype'],
                         os.path.splitext(c.get('path') or '')[1].lower()) for c in v} for k, v in by.items()}
            if all(fmts.values()) and not set.intersection(*fmts.values()):
                fails.append("formats differ by class (sample rate, channels, encoding or file type): "
                             + '; '.join(f"{k}: {sorted(map(str, v))}" for k, v in fmts.items()))
            durs = {k: [c['dur'] for c in v] for k, v in by.items() if v}
            ks = sorted(durs, key=lambda k: min(durs[k]))
            for a, b in zip(ks, ks[1:]):
                lo_gap = min(durs[b]) - max(durs[a])
                if len(durs[a]) >= 2 and len(durs[b]) >= 2 and lo_gap > 0.05:
                    fails.append(f"durations separate the classes: {a} {min(durs[a]):.2f}-{max(durs[a]):.2f} s, "
                                 f"{b} {min(durs[b]):.2f}-{max(durs[b]):.2f} s (cut every clip the same way)")
                elif (len(durs[a]) == 1 or len(durs[b]) == 1) and lo_gap > 0.25:
                    warns.append(f"{a} and {b} differ in length by {lo_gap:.2f} s or more (a tell if the person notices)")
            leads = {k: [c['lead'] for c in v if c['lead'] is not None] for k, v in by.items()}
            means = {k: float(np.mean(v)) for k, v in leads.items() if v}
            if len(means) >= 2 and max(means.values()) - min(means.values()) > 0.04:
                warns.append("leading silence differs by class: " + ', '.join(f"{k} {v * 1000:.0f} ms" for k, v in
                                                                              means.items()))
            louds = {k: float(np.mean([c['loud'] for c in v])) for k, v in by.items() if v}
            if len(louds) >= 2 and max(louds.values()) - min(louds.values()) > 0.5:
                warns.append("one class is louder on average: " + ', '.join(f"{k} {v:.1f}" for k, v in louds.items()))
            seq = [c['cls'] for c in cl if c['cls']]
            pairs = [seq[i:i + len(classes)] for i in range(0, len(seq) - len(classes) + 1, len(classes))]
            if len(pairs) >= 2 and len({p[0] for p in pairs}) == 1:
                fails.append(f"the order follows the key: every trial starts with {pairs[0][0]!r} (shuffle per trial)")
            elif len(seq) >= 4 and seq == sorted(seq):
                fails.append("the clips are in key order (all of one class, then the next): shuffle them")
            if not any(f.startswith(('formats', 'durations', 'the order', 'the clips are')) for f in fails):
                oks.append(f"no tell by format, length or order across {len(classes)} classes")
        if terms and not any('says' in f or 'ties' in f or 'loads' in f for f in fails):
            oks.append(f"no leak of {', '.join(repr(t) for t in terms[:6])} in names, tags or the page")

        # ---- Submit lands where the agent reads
        if submit_url:
            before = os.path.getsize(answers_path) if answers_path and os.path.exists(answers_path) else 0
            body = submit_body or {'preflight': True, 'note': 'exam_check round trip: ignore this line'}
            try:
                req = urllib.request.Request(submit_url, data=json.dumps(body).encode(), method='POST',
                                             headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=15) as r:
                    status = r.status
            except Exception as e:
                status = None
                fails.append(f"Submit does not go through: POST {submit_url}: {type(e).__name__}: {e}")
            if status and answers_path:
                got = ''
                if os.path.exists(answers_path):
                    with open(answers_path, 'rb') as f:
                        f.seek(before)
                        got = f.read().decode('utf8', 'replace')
                if 'preflight' in got:
                    oks.append(f"Submit lands in {answers_path} (a test line marked preflight was added: skip it "
                               f"when scoring)")
                else:
                    fails.append(f"Submit answered {status} but nothing new reached {answers_path}: the person's "
                                 f"answers would be lost")
            elif status:
                warns.append(f"Submit answered {status}; pass answers_path to check it lands where you read it")
        elif answers_path:
            d = os.path.dirname(os.path.abspath(answers_path))
            up = d
            while not os.path.isdir(up) and os.path.dirname(up) != up:
                up = os.path.dirname(up)
            (oks if os.access(up, os.W_OK) else fails).append(
                f"answers go to {answers_path}" + ('' if os.path.isdir(d) else ' (its folder will be made)')
                + ('' if os.access(up, os.W_OK) else ': not writable'))
        else:
            warns.append("no submit_url or answers_path: the Submit round trip was not checked")
        return not fails, _report(fails, warns, oks, len(cl))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _report(fails, warns, oks, n):
    head = (f"NOT READY: {len(fails)} problem{'s' * (len(fails) != 1)}; do not show this exam until they are fixed"
            if fails else f"READY: {n} clips" + (f", {len(warns)} warning{'s' * (len(warns) != 1)} to read" if warns else ''))
    return [head] + [f"FAIL {x}" for x in dict.fromkeys(fails)] + [f"WARN {x}" for x in dict.fromkeys(warns)] + \
        [f"ok   {x}" for x in oks]
