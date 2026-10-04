"""Log a change landed in the stage, for the "N updates ready" card (updates.js reads updates.json).

    python update_note.py "Panels draw on top of the world" [--level normal|important|critical]

Levels: normal (green), important (amber: something Nate asked for or will notice), critical (orange: a fix for
something broken or sickening; he should take it soon). Write the note when the code lands, before the page sees it.
"""
import argparse
import json
import time
from pathlib import Path

LOG = Path(__file__).with_name('updates.json')

ap = argparse.ArgumentParser()
ap.add_argument('title')
ap.add_argument('--level', default='normal', choices=['normal', 'important', 'critical'])
a = ap.parse_args()
d = json.loads(LOG.read_text(encoding='utf-8')) if LOG.is_file() else {'updates': []}
d['updates'].append({'t_ms': int(time.time() * 1000), 'title': a.title, 'level': a.level})
LOG.write_text(json.dumps(d, indent=1), encoding='utf-8')
print(len(d['updates']), 'notes;', a.level, a.title)
