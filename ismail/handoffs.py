"""Intake for the migration loop (skills/ismail/references/development.md): what is new or changed in the songs'
handoff files since the dev agent last looked.

    python -m ismail.handoffs                 # every handoff section new or changed since the last mark, by title
    python -m ismail.handoffs --full          # the same with the new text (changed sections: added lines only)
    python -m ismail.handoffs --mark          # after triage: remember what was seen

A handoff file is HANDOFF*.md anywhere under songs/ (a song root, notes/, a video folder; not in caches, backups,
renders or a generated proj/) or under the extra folders listed in <songs>/_migration/roots.txt (one path per
line). Sections are split on '#' headings, named by their heading path, and compared by content; a new heading
whose text was already in the file (a handoff reorganized) is listed only with --all. The state lives in
<songs>/_migration/seen.json. Nothing in a song folder is written."""
import argparse
import difflib
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = re.compile(r'[\\/](backups?|_backups|renders|proj|cache|history|history_src|node_modules|\.git)[\\/]')


def _songs_default():
    """$ISMAIL_SONGS, else songs/ of this checkout, else of the main checkout this worktree belongs to."""
    if os.environ.get('ISMAIL_SONGS'):
        return os.environ['ISMAIL_SONGS']
    git = os.path.join(HERE, '.git')
    if os.path.isfile(git):                          # a worktree: '.git' names <main>/.git/worktrees/<name>
        with open(git, encoding='utf8') as f:
            gitdir = f.read().split(':', 1)[1].strip()
        return os.path.join(gitdir.replace(os.sep, '/').split('/.git/')[0], 'songs')
    return os.path.join(HERE, 'songs')


SONGS = os.path.normpath(_songs_default())


def _files(songs):
    roots = [songs]
    extra = os.path.join(songs, '_migration', 'roots.txt')
    if os.path.exists(extra):
        with open(extra, encoding='utf8') as f:
            roots += [ln.strip() for ln in f if ln.strip() and not ln.startswith('#')]
    out = []
    for r in roots:
        for p in glob.glob(os.path.join(r, '**', 'HANDOFF*.md'), recursive=True):
            if not SKIP.search(p):
                out.append(os.path.normpath(p))
    return sorted(set(out))


def _sections(text):
    """[(title, body)]: split on markdown headings. A title is its heading path below the file's top heading
    ('Night-cam grade > Evidence'), so one subheading under two elements stays two sections; text before the first
    heading is '(top)'."""
    out, path, buf, title = [], [], [], '(top)'
    for ln in text.splitlines():
        m = re.match(r'(#{1,4}) (.*)', ln)
        if m:
            if buf and any(x.strip() for x in buf):
                out.append((title, '\n'.join(buf)))
            level = len(m.group(1))
            path = [h for h in path if h[0] < level] + [(level, m.group(2).strip())]
            title, buf = ' > '.join(h for lv, h in path if lv > 1) or path[-1][1], []
        else:
            buf.append(ln)
    if buf and any(x.strip() for x in buf):
        out.append((title, '\n'.join(buf)))
    return out


def _words(body):
    return re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", body.lower())


def _moved(body, known):
    """A section whose words (90% or more) were already in the file: reorganized, not new."""
    w = _words(body)
    return bool(w) and sum(x in known for x in w) >= 0.9 * len(w)


def _digest(s):
    return hashlib.sha1(s.encode('utf8')).hexdigest()[:12]


def scan(songs=SONGS):
    """-> (report rows, new state, state file). Row: (path, title, 'new'|'changed'|'moved', body, old body or None);
    'moved' is a new heading whose words were nearly all in the file already."""
    state_file = os.path.join(songs, '_migration', 'seen.json')
    try:
        with open(state_file, encoding='utf8') as f:
            seen = json.load(f)
    except (OSError, ValueError):
        seen = {}
    rows, state = [], {}
    for p in _files(songs):
        with open(p, encoding='utf8', errors='replace') as f:
            secs = _sections(f.read())
        key = os.path.relpath(p, songs) if p.startswith(os.path.normpath(songs)) else p
        old = seen.get(key, {})
        known = set().union(*(_words(t + ' ' + v['body']) for t, v in old.items())) if old else set()
        state[key] = {}
        for title, body in secs:
            d = _digest(body)
            state[key][title] = {'hash': d, 'body': body}
            if title not in old:
                rows.append((key, title, 'moved' if old and _moved(title + ' ' + body, known) else 'new', body, None))
            elif old[title]['hash'] != d:
                rows.append((key, title, 'changed', body, old[title]['body']))
    return rows, state, state_file


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--songs', default=SONGS)
    ap.add_argument('--full', action='store_true', help='print the new text, not only the titles')
    ap.add_argument('--all', action='store_true', help='also list sections whose text only moved')
    ap.add_argument('--mark', action='store_true', help='remember everything as seen (after triage)')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')     # handoffs quote symbols a Windows console code page lacks
    rows, state, state_file = scan(a.songs)
    if a.mark:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, 'w', encoding='utf8') as f:
            json.dump(state, f, indent=1)
        print(f"marked {sum(len(v) for v in state.values())} sections in {len(state)} handoff files as seen")
        return
    moved = [r for r in rows if r[2] == 'moved']
    if not a.all:
        rows = [r for r in rows if r[2] != 'moved']
    note = f" ({len(moved)} more only moved: their text was already in the file; --all lists them)" \
        if moved and not a.all else ''
    if not rows:
        print(f"nothing new in {len(state)} handoff files since the last mark{note}")
        return
    last = None
    for path, title, kind, body, old in rows:
        if path != last:
            print(f"\n== {path}")
            last = path
        n = len([x for x in body.splitlines() if x.strip()])
        print(f"  [{kind}] {title} ({n} lines)")
        if a.full:
            if old is None:
                text = body
            else:
                text = '\n'.join(x[2:] for x in difflib.ndiff(old.splitlines(), body.splitlines()) if x.startswith('+ '))
            print('\n'.join('      ' + x for x in text.splitlines() if x.strip()))
    print(f"\n{len(rows)} sections new or changed{note}. Triage them into "
          f"{os.path.join(a.songs, '_migration', 'LEDGER.md')}, then run with --mark.")


if __name__ == '__main__':
    sys.exit(main())
