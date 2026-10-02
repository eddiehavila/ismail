"""Intake for the migration loop (skills/ismail/references/development.md): what is new or changed in the songs'
handoff files since the dev agent last looked.

    python -m ismail.handoffs                 # every handoff section new or changed since the last mark, by title
    python -m ismail.handoffs --full          # the same with the new text (changed sections: added lines only)
    python -m ismail.handoffs --mark          # after triage: remember what was seen

A handoff file is HANDOFF*.md anywhere under songs/ (a song root, notes/, a video folder) or under the extra
folders listed in <songs>/_migration/roots.txt (one path per line). Sections are split on '#' headings and
compared by content; the state lives in <songs>/_migration/seen.json. Nothing in a song folder is written."""
import argparse
import difflib
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
            if not re.search(r'[\\/](backups?|_backups|renders|proj|node_modules|\.git)[\\/]', p):
                out.append(os.path.normpath(p))
    return sorted(set(out))


def _sections(text):
    """[(title, body)]: split on markdown headings; text before the first heading is '(top)'."""
    out, title, buf = [], '(top)', []
    for ln in text.splitlines():
        if re.match(r'#{1,4} ', ln):
            if buf and any(x.strip() for x in buf):
                out.append((title, '\n'.join(buf)))
            title, buf = ln.lstrip('#').strip(), []
        else:
            buf.append(ln)
    if buf and any(x.strip() for x in buf):
        out.append((title, '\n'.join(buf)))
    return out


def _digest(s):
    return hashlib.sha1(s.encode('utf8')).hexdigest()[:12]


def scan(songs=SONGS):
    """-> (report rows, new state). Row: (path, title, 'new'|'changed', body, old body or None)."""
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
        state[key] = {}
        for title, body in secs:
            d = _digest(body)
            state[key][title] = {'hash': d, 'body': body}
            if title not in old:
                rows.append((key, title, 'new', body, None))
            elif old[title]['hash'] != d:
                rows.append((key, title, 'changed', body, old[title]['body']))
    return rows, state, state_file


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--songs', default=SONGS)
    ap.add_argument('--full', action='store_true', help='print the new text, not only the titles')
    ap.add_argument('--mark', action='store_true', help='remember everything as seen (after triage)')
    a = ap.parse_args(argv)
    rows, state, state_file = scan(a.songs)
    if a.mark:
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        with open(state_file, 'w', encoding='utf8') as f:
            json.dump(state, f, indent=1)
        print(f"marked {sum(len(v) for v in state.values())} sections in {len(state)} handoff files as seen")
        return
    if not rows:
        print(f"nothing new in {len(state)} handoff files since the last mark")
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
    print(f"\n{len(rows)} sections new or changed. Triage them into {os.path.join(a.songs, '_migration', 'LEDGER.md')}, "
          f"then run with --mark.")


if __name__ == '__main__':
    sys.exit(main())
