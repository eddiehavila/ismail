"""Sample sets for the sampled voices (rhodes, rusty, emily): nothing downloads by itself, a missing set says what
to fetch, how big and under what licence, and a fetch or a registered folder makes the voice play."""
import io
import json
import os
import zipfile

import numpy as np
import pytest
import soundfile as sf

from ismail import api, machine, samples


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_SAMPLES', str(tmp_path / 'store'))
    for v in ('RHODES_SAMPLES', 'RUSTY_SAMPLES', 'EMILY_SAMPLES'):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv('ISMAIL_MACHINE_DIR', str(tmp_path / 'board'))
    monkeypatch.setattr(machine, 'gpu', lambda: None)
    monkeypatch.setattr(machine, 'memory', lambda: (40.0, 70.0, 30.0))
    monkeypatch.setattr(machine, 'cpu_load', lambda: (12.0, []))
    monkeypatch.setattr(machine, 'disks', lambda *a: [])
    return tmp_path / 'store'


def _rhodes_folder(d):
    d.mkdir(parents=True)
    t = np.arange(4410) / 44100
    for i, m in enumerate(range(29, 97, 4)[:16]):
        for layer in range(1, 6):
            y = 0.3 * np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * t) * np.exp(-t * 3)
            sf.write(str(d / f"A_{m:03d}__X{i}_{layer}.flac"), y, 44100)
    for i in range(44):                                     # the set's size check counts files
        sf.write(str(d / f"A_{120 + i:03d}__Z_1.flac"), np.zeros(10), 44100)
    return d


def test_a_missing_set_says_what_to_fetch_and_its_licence():
    assert samples.path('jrhodes3d') is None
    with pytest.raises(FileNotFoundError) as e:
        samples.need('jrhodes3d')
    assert "samples_fetch('jrhodes3d')" in str(e.value) and '22 MB' in str(e.value) and 'CC BY-NC' in str(e.value)
    assert 'not fetched' in api.samples_list()


def test_a_repo_set_downloads_only_its_paths(store, monkeypatch):
    tree = {'truncated': False, 'tree': [
        {'type': 'blob', 'path': 'jRhodes3d-mono/A_029__F1_1.flac', 'size': 10},
        {'type': 'blob', 'path': 'jRhodes3d-wav/A_029__F1_1.wav', 'size': 10},
        {'type': 'blob', 'path': 'LICENSE', 'size': 5}]}
    got = []

    def fake_get(url, tries=3):
        got.append(url)
        return json.dumps(tree).encode() if 'api.github.com' in url else b'data'
    monkeypatch.setattr(samples, '_get', fake_get)
    monkeypatch.setitem(samples.SETS['jrhodes3d'], 'min_files', 1)
    p = samples.fetch('jrhodes3d', log=lambda m: None)
    assert p.endswith(os.path.join('jrhodes3d', 'jRhodes3d-mono'))
    assert os.listdir(p) == ['A_029__F1_1.flac'] and not any('wav' in u for u in got)
    assert 'Jeff Learman' in (store / 'jrhodes3d' / 'CREDIT.txt').read_text()


def test_a_release_zip_keeps_only_what_the_voice_reads(store, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('Karoryfer.Emilyguitar.v1.001/Emilyguitar/notes/a.wav', b'x')
        z.writestr('Karoryfer.Emilyguitar.v1.001/Emilyguitar/noises/n.wav', b'x')
        z.writestr('Karoryfer.Emilyguitar.v1.001/Emilyguitar/LICENSE', b'CC0')
    monkeypatch.setattr(samples, '_get', lambda url, tries=3: buf.getvalue())
    p = samples.fetch('emilyguitar', log=lambda m: None)
    assert sorted(os.listdir(p)) == ['LICENSE', 'notes']


def test_a_registered_folder_plays_the_rhodes(tmp_path):
    d = _rhodes_folder(tmp_path / 'mine' / 'jRhodes3d-mono')
    with pytest.raises(api.OpError):
        api.samples_fetch('jrhodes3d', path=str(tmp_path))       # not the set's folder
    assert 'registered' in api.samples_fetch('jrhodes3d', path=str(d))
    p = str(tmp_path / 'song')
    api.project_new(p, bpm=120, length_bars=1)
    api.track_add(p, 'ep', instrument={'type': 'code', 'voice': 'rhodes'})
    api.track_add(p, 'cr', instrument={'type': 'code', 'voice': 'crackle'})
    api.notes_write(p, 'ep', 1, '0 57,60,64 2 80')
    api.notes_write(p, 'cr', 1, '0 60 4 90')
    out = api.render(p, stems=True)
    assert 'SILENT' not in out
