"""The migration loop's intake: handoff sections new or changed since the last mark, nothing written in songs."""
import os

from ismail import handoffs


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf8') as f:
        f.write(text)


def test_intake_reports_new_and_changed_sections_until_marked(tmp_path, capsys):
    songs = str(tmp_path / 'songs')
    h = os.path.join(songs, 'birds', 'HANDOFF.md')
    write(h, '# HANDOFF: birds\nintro\n## Call mode\nfirst version\n## Bug\nmono crash\n')
    write(os.path.join(songs, 'birds', 'proj', 'HANDOFF.md'), '# generated, ignored\n')
    rows, _, _ = handoffs.scan(songs)
    assert [(r[1], r[2]) for r in rows] == [('HANDOFF: birds', 'new'), ('Call mode', 'new'), ('Bug', 'new')]
    handoffs.main(['--songs', songs, '--mark'])
    assert handoffs.scan(songs)[0] == []
    write(h, '# HANDOFF: birds\nintro\n## Call mode\nfirst version\nnow with knocks\n## Bug\nmono crash\n## Offsets\nx\n')
    rows, _, _ = handoffs.scan(songs)
    assert [(r[1], r[2]) for r in rows] == [('Call mode', 'changed'), ('Offsets', 'new')]
    handoffs.main(['--songs', songs, '--full'])
    out = capsys.readouterr().out
    assert 'now with knocks' in out and 'first version' not in out     # a changed section shows its added lines
    assert sorted(os.listdir(os.path.join(songs, 'birds'))) == ['HANDOFF.md', 'proj']
