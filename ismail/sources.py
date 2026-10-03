"""Where a song's sources came from: every recording, video, score or MIDI in its ref/ folders has a row in a
SOURCES file, and the credits of a public piece are written from those rows.

The skill asks for a SOURCES.md row before a source is used; this module makes the project say it back on every
project_info and render (files with no row, rows without a licence or an author), and `credits` writes CREDITS.md
from the rows, the tracks' models and the lineage, the way the first showcase credits page was written by hand.

A file counts as listed when its name, or its name without the extension, appears in any SOURCES file of the song
(SOURCES.md / SOURCES.txt anywhere under ref/, or at the song root). Derived files are skipped: stems, separations,
renders, and analysis projects (a folder with its own project.json).
"""
import os
import re
import urllib.parse

from . import provenance

MEDIA = {'.wav', '.mp3', '.flac', '.ogg', '.oga', '.opus', '.m4a', '.aac', '.aif', '.aiff', '.wma',
         '.mid', '.midi', '.mp4', '.webm', '.mkv', '.mov', '.avi'}
SKIP_DIRS = {'stems', 'separated', 'renders', 'backups', '__pycache__', 'cache'}
SOURCE_NAMES = ('sources.md', 'sources.txt')
LICENCE_KEYS = ('licen',)
AUTHOR_KEYS = ('recordist', 'author', 'artist', 'player', 'performer', 'creator', 'uploader', 'channel', 'by',
               'credit', 'composer', 'editor')
PRIVATE_KEYS = ('approv', 'path', 'local', 'date', 'note')     # columns left out of public credits
EMPTY = {'', '-', '?', 'unknown', 'n/a', 'none'}
ROW = ("title, link, who made or played it, licence, what was measured from it, who approved the download, date")


def song_root(root):
    """The song folder: the project's parent when the project is a song's proj/ (or the parent holds ref/)."""
    root = os.path.abspath(root)
    parent = os.path.dirname(root)
    if os.path.basename(root).lower() == 'proj' or (os.path.isdir(os.path.join(parent, 'ref'))
                                                    and not os.path.isdir(os.path.join(root, 'ref'))):
        return parent
    return root


def ref_dirs(root):
    out = []
    for base in dict.fromkeys([os.path.abspath(root), song_root(root)]):
        p = os.path.join(base, 'ref')
        if os.path.isdir(p):
            out.append(p)
    return out


def _walk(top):
    for dirpath, dirs, files in os.walk(top):
        if 'project.json' in files and dirpath != top:
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS and not x.startswith('.')]
        yield dirpath, files


def _source_files(root):
    found = []
    sr = song_root(root)
    for name in os.listdir(sr) if os.path.isdir(sr) else []:
        if name.lower() in SOURCE_NAMES:
            found.append(os.path.join(sr, name))
    for top in ref_dirs(root):
        for dirpath, files in _walk(top):
            found += [os.path.join(dirpath, f) for f in files if f.lower() in SOURCE_NAMES]
    return list(dict.fromkeys(found))


def _read(p):
    try:
        with open(p, 'rb') as f:
            raw = f.read()
    except OSError:
        return ''
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252', errors='replace')          # a SOURCES file written by Windows PowerShell 5.1


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def tables(text):
    """Markdown tables in a SOURCES file -> [(header cells, [row cells])]."""
    out, lines = [], text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith('|') and i + 1 < len(lines) and re.match(r'^\s*\|[\s:|-]+\|?\s*$', lines[i + 1]):
            head, rows = _cells(lines[i]), []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                rows.append(_cells(lines[i]))
                i += 1
            out.append((head, rows))
        else:
            i += 1
    return out


def _col(head, keys, avoid=('approv',)):
    for j, h in enumerate(head):
        hl = h.lower()
        words = set(re.findall(r'[a-z]+', hl))
        if any(a in hl for a in avoid):
            continue
        if any((k in words) if len(k) <= 3 else (k in hl) for k in keys):
            return j
    return None


def _label(head, row):
    for k in ('file', 'title', 'recording', 'name', 'work', 'species'):
        for j, h in enumerate(head):
            if k in h.lower() and j < len(row) and row[j].strip():
                return row[j].strip()
    return next((c for c in row if c.strip()), '?')


def scan(root, d=None):
    """-> {'files': [rel paths of source media], 'unlisted': [...], 'sources': [SOURCES paths],
    'incomplete': [(SOURCES rel path, row label, [missing fields])], 'reference': path or None,
    'reference_listed': bool}"""
    sr = song_root(root)
    srcs = _source_files(root)
    blob = '\n'.join(_read(p) for p in srcs)
    blob = (blob + '\n' + urllib.parse.unquote(blob)).lower()
    files, unlisted = [], []
    for top in ref_dirs(root):
        for dirpath, names in _walk(top):
            for f in sorted(names):
                stem, ext = os.path.splitext(f)
                if ext.lower() not in MEDIA:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), sr).replace(os.sep, '/')
                files.append(rel)
                if f.lower() not in blob and stem.lower() not in blob:
                    unlisted.append(rel)
    incomplete = []
    for p in srcs:
        for head, rows in tables(_read(p)):
            lic, who = _col(head, LICENCE_KEYS), _col(head, AUTHOR_KEYS)
            for r in rows:
                miss = [name for name, j in (('licence', lic), ('author', who))
                        if j is not None and (j >= len(r) or r[j].strip().lower() in EMPTY)]
                if miss:
                    incomplete.append((os.path.relpath(p, sr).replace(os.sep, '/'), _label(head, r), miss))
    ref = ((d or {}).get('reference') or {}).get('file')
    ref_listed = True
    if ref:
        b = os.path.basename(ref)
        ref_listed = b.lower() in blob or os.path.splitext(b)[0].lower() in blob
    return {'files': files, 'unlisted': unlisted, 'sources': srcs, 'incomplete': incomplete,
            'reference': ref, 'reference_listed': ref_listed}


def _few(xs, n=4):
    return ', '.join(xs[:n]) + (f" and {len(xs) - n} more" if len(xs) > n else '')


def summary(root, d=None):
    """-> (lines for project_info, one line for render or '' when every source has its row)."""
    s = scan(root, d)
    if not s['files'] and not s['reference']:
        return [], ''
    L = []
    n, un = len(s['files']), s['unlisted']
    if n:
        L.append(f"sources: {n} files in ref/, {n - len(un)} with a row in a SOURCES file "
                 f"({len(s['sources'])} SOURCES file{'s' if len(s['sources']) != 1 else ''})")
    if un:
        L.append(f"  no SOURCES row: {_few(un)}. Add one per source before using it ({ROW}): credits are "
                 f"written from these rows")
    if s['reference'] and not s['reference_listed']:
        L.append(f"  the reference {os.path.basename(s['reference'])} has no SOURCES row: add one in the song's "
                 f"ref/SOURCES.md")
    if s['incomplete']:
        L.append(f"  {len(s['incomplete'])} rows without a licence or an author: " +
                 _few([f"{lbl} ({'/'.join(m)})" for _, lbl, m in s['incomplete']], 3))
    short = ''
    missing = len(un) + (0 if s['reference_listed'] else 1)
    if missing:
        short = (f"  sources: {missing} reference file{'s' if missing != 1 else ''} with no SOURCES row "
                 f"(project_info lists them; credits are written from those rows)")
    return L, short


# ------------------------------------------------------------------ credits

_LOCAL = re.compile(r'^(?:[A-Za-z]:[\\/]|/(?!/))|\\')


def _public(text):
    """A local path becomes its file name; links stay whole."""
    out = []
    for tok in re.split(r'(\s+)', text):
        core = tok.strip('(),;\'"')
        segs = [x for x in re.split(r'[\\/]', core) if x]
        if len(segs) >= 2 and '://' not in core and _LOCAL.search(core):
            tok = tok.replace(core, segs[-1])
        out.append(tok)
    return ''.join(out)


def plays_source_audio(d):
    """[(track, why)] for tracks whose sound is audio from a recording (a sample imported or averaged from one,
    or placed audio clips), as opposed to a measurement rebuilt by synthesis."""
    out = []
    for name, tr in d.get('tracks', {}).items():
        if tr.get('audio'):
            out.append((name, f"{len(tr['audio'])} audio clips"))
        inst = tr.get('instrument') or {}
        insts = [inst] + list((inst.get('map') or {}).values()) if inst.get('type') == 'kit' else [inst]
        for i in insts:
            if i.get('type') == 'sampler':
                note = ((d.get('sounds') or {}).get(i.get('sound'), {}) or {}).get('note') or ''
                if note.startswith(('imported from', 'avg of')):
                    out.append((name, f"sample {i.get('sound')}, {_public(note)}"))
    return out


def credits_md(root, d):
    """-> (CREDITS.md text, warnings)."""
    s = scan(root, d)
    sr = song_root(root)
    title = d.get('name') if (d.get('name') or '').lower() not in ('', 'proj') else os.path.basename(sr)
    warn = []
    if s['unlisted']:
        warn.append(f"{len(s['unlisted'])} files in ref/ have no SOURCES row and are not credited: {_few(s['unlisted'])}")
    if s['reference'] and not s['reference_listed']:
        warn.append(f"the reference {os.path.basename(s['reference'])} has no SOURCES row and is not credited")
    if s['incomplete']:
        warn.append(f"{len(s['incomplete'])} rows lack a licence or an author")
    L = [f"# {title}: credits", '']
    audio = plays_source_audio(d)
    if audio:
        L += ["Parts of this piece play recorded audio: " + '; '.join(f"{t} ({why})" for t, why in audio) + ". "
              "The other sources below were measured, and their sound is rebuilt by synthesis.", '']
    elif s['files'] or s['sources']:
        L += ["This piece contains none of the audio below. ismail measured each source (a sound's pitch, "
              "harmonics and noise, an instrument's response, a player's timing and phrasing) and the piece "
              "rebuilds it with synthesis. These recordings, and the people who made and played them, are where "
              "its sounds come from.", '']
    for p in s['sources']:
        text = _read(p)
        head = next((ln.lstrip('#').strip() for ln in text.splitlines() if ln.startswith('#')), None)
        L += [f"## {head or os.path.relpath(os.path.dirname(p), sr).replace(os.sep, '/')}", '']
        tb = tables(text)
        if tb:
            for h, rows in tb:
                keep = [j for j, c in enumerate(h) if not any(k in c.lower() for k in PRIVATE_KEYS)]
                L.append('| ' + ' | '.join(h[j] for j in keep) + ' |')
                L.append('|' + '---|' * len(keep))
                for r in rows:
                    L.append('| ' + ' | '.join(_public(r[j]) if j < len(r) else '' for j in keep) + ' |')
                L.append('')
        else:
            for ln in text.splitlines():
                if ln.strip() and not ln.startswith('#'):
                    L.append(f"- {_public(ln.strip())}")
            L.append('')
    groups, open_ = {}, []
    for name, tr in d.get('tracks', {}).items():
        st, txt = provenance.of_track(tr, d, root)
        if st == provenance.UNSTATED:
            open_.append(name)
        else:
            groups.setdefault((st, _public(txt)), []).append(name)
    if groups:
        L += ['## How each part was made', '', '| how | from | parts |', '|---|---|---|']
        L += [f"| {st} | {txt} | {', '.join(names)} |" for (st, txt), names in groups.items()]
        L.append('')
    if open_:
        warn.append(f"{len(open_)} parts have no stated model and are left out of 'How each part was made' "
                    f"({_few(open_)}): track_model(track, on=<the source>) or on='designed'")
    lin = [a.get('name') or os.path.basename(a.get('project', '')) for a in d.get('lineage', [])]
    if lin:
        L += ['## Made from', '', 'A version of ' + ', itself a version of '.join(lin) + '.', '']
    L.append('Made with ismail (https://github.com/newsbubbles/ismail).')
    return '\n'.join(L) + '\n', warn
