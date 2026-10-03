"""Sources and credits (M58): every recording in a song's ref/ has a SOURCES row, project_info and render say when
one is missing, and `credits` writes CREDITS.md from the rows, the tracks' models and the lineage."""
import os

import pytest

from ismail import api, sources
from ismail.api import OPS, OpError


def song(tmp_path):
    """A song laid out as the skill says: songs/<slug>/ with ref/ and proj/."""
    root = tmp_path / 'forest'
    (root / 'ref' / 'birds').mkdir(parents=True)
    (root / 'ref' / 'village' / 'stems' / 'abc').mkdir(parents=True)
    for f in ('ref/birds/Wren_XC1.mp3', 'ref/birds/Potoo_XC2.ogg', 'ref/village/abc.m4a', 'ref/village/abc.wav',
              'ref/village/stems/abc/vocals.wav', 'ref/notes.txt'):
        (root / f).write_bytes(b'')
    (root / 'ref' / 'birds' / 'SOURCES.md').write_text(
        "# Bird recordings (analysis only)\n\n"
        "| species | file | licence | recordist | source | approved by |\n|---|---|---|---|---|---|\n"
        "| wren | Wren_XC1.mp3 | CC BY-SA 4.0 | Niels Krabbe | https://commons.wikimedia.org/wiki/File%3AWren_XC1.mp3 | the user |\n"
        "| potoo | Potoo_XC2.ogg | CC BY 4.0 |  | https://commons.wikimedia.org/wiki/File%3APotoo_XC2.ogg | the user |\n",
        encoding='utf8')
    proj = str(root / 'proj')
    OPS['project_new'](proj, bpm=90, length_bars=2, name='Forest')
    OPS['track_add'](proj, 'wren', instrument='preset:pluck')
    OPS['track_model'](proj, 'wren', on='ref/birds/Wren_XC1.mp3 (a call profile)', by='song script')
    OPS['track_add'](proj, 'pad', instrument='preset:pad')
    OPS['track_model'](proj, 'pad', on='designed')
    OPS['track_add'](proj, 'hum', instrument='preset:pluck')
    return root, proj


def test_project_info_and_render_name_a_source_with_no_row(tmp_path):
    root, proj = song(tmp_path)
    s = sources.scan(proj)
    assert sources.song_root(proj) == str(root)
    assert sorted(s['files']) == ['ref/birds/Potoo_XC2.ogg', 'ref/birds/Wren_XC1.mp3', 'ref/village/abc.m4a',
                                  'ref/village/abc.wav']                          # stems and text files skipped
    assert sorted(s['unlisted']) == ['ref/village/abc.m4a', 'ref/village/abc.wav']
    assert s['incomplete'] == [('ref/birds/SOURCES.md', 'Potoo_XC2.ogg', ['author'])]
    info = OPS['project_info'](proj)
    assert 'sources: 4 files in ref/, 2 with a row' in info and 'no SOURCES row: ref/village/abc.m4a' in info
    assert '1 rows without a licence or an author: Potoo_XC2.ogg (author)' in info
    assert '2 reference files with no SOURCES row' in sources.summary(proj)[1]
    # a row for the video (by its id, as a SOURCES.txt of video ids does) lists its download and the wav made from it
    (root / 'ref' / 'village' / 'SOURCES.txt').write_text(
        "abc | 4:50 | Paolo Cogliati | SONKARI / a panpipe | https://www.youtube.com/watch?v=abc\n", encoding='utf8')
    assert sources.scan(proj)['unlisted'] == [] and sources.summary(proj)[1] == ''


def test_credits_are_written_from_the_rows_and_the_models(tmp_path):
    root, proj = song(tmp_path)
    (root / 'ref' / 'village' / 'SOURCES.txt').write_text(
        "abc | 4:50 | Paolo Cogliati | SONKARI / a panpipe | https://www.youtube.com/watch?v=abc\n", encoding='utf8')
    out = OPS['credits'](proj)
    assert f"wrote {root / 'CREDITS.md'}" in out and 'recorded audio in the piece: none' in out
    assert 'NOT CREDITED: 1 rows lack a licence or an author' in out and 'hum' in out   # hum has no model
    text = (root / 'CREDITS.md').read_text(encoding='utf8')
    assert text.startswith('# Forest: credits') and 'contains none of the audio below' in text
    assert '| species | file | licence | recordist | source |' in text and 'approved' not in text
    assert 'https://commons.wikimedia.org/wiki/File%3AWren_XC1.mp3' in text            # links stay whole
    assert '- abc | 4:50 | Paolo Cogliati | SONKARI / a panpipe | https://www.youtube.com/watch?v=abc' in text
    assert '| measured | modeled on ref/birds/Wren_XC1.mp3 (a call profile) by song script | wren |' in text
    assert '| designed | designed | pad |' in text and '| hum |' not in text
    with pytest.raises(OpError, match='overwrite=True'):
        OPS['credits'](proj)
    assert 'wrote' in OPS['credits'](proj, overwrite=True)


def test_credits_say_when_the_piece_plays_recorded_audio(tmp_path):
    root, proj = song(tmp_path)
    d = api._load(proj).d
    d['sounds'] = {'call': {'note': f"imported from {root / 'ref' / 'birds' / 'Wren_XC1.mp3'}"}}
    d['tracks']['wren']['instrument'] = {'type': 'sampler', 'sound': 'call'}
    assert sources.plays_source_audio(d) == [('wren', 'sample call, imported from Wren_XC1.mp3')]
    text, _ = sources.credits_md(proj, d)
    assert 'Parts of this piece play recorded audio: wren (sample call, imported from Wren_XC1.mp3)' in text
    assert 'contains none of the audio' not in text and str(tmp_path) not in text       # no local paths


def test_a_project_without_sources_says_nothing(tmp_path):
    proj = str(tmp_path / 'plain')
    OPS['project_new'](proj, bpm=120, length_bars=1)
    assert sources.summary(proj) == ([], '')
    assert 'sources:' not in OPS['project_info'](proj)


def test_track_model_takes_a_file_in_the_songs_ref_folder(tmp_path):
    # 'ref/birds/x.mp3' was read as the project reference ('ref') and refused; a path from the song folder was
    # looked for only under proj/
    root, proj = song(tmp_path)
    assert 'modeled on ref/birds/Potoo_XC2.ogg' in OPS['track_model'](proj, 'hum', on='ref/birds/Potoo_XC2.ogg')
    with pytest.raises(OpError, match='not found'):
        OPS['track_model'](proj, 'hum', on='ref/birds/missing.mp3')
    with pytest.raises(OpError, match='no reference'):
        OPS['track_model'](proj, 'hum', on='ref:drums')
