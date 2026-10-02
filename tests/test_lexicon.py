"""The lexicon: the person's words <-> ismail's terms, kept with outcomes, read both ways, and readable as a learning
curve; and a project's objectives, carried into every version made from it (intent provenance)."""
import json
import os

import pytest

from ismail import api, lexicon
from ismail.api import OpError


@pytest.fixture
def lex(tmp_path, monkeypatch):
    monkeypatch.setenv('ISMAIL_LEXICON', str(tmp_path / 'user' / 'lexicon.jsonl'))
    return tmp_path / 'user' / 'lexicon.jsonl'


def test_a_word_is_noted_mapped_later_and_found_both_ways(lex, tmp_path):
    song = str(tmp_path / 'tears')
    out = api.lexicon_note(song, said='the snare is boxy', craft='mixing engineer', where='exam 7')
    assert out.startswith('noted L0001 "the snare is boxy" -> (not mapped yet) | open | mixing engineer tears exam 7')
    assert 'not mapped yet: when you know' in out
    api.lexicon_note(id='L0001', means='fx eq peak 400 Hz -3 dB on snare; analyze_timbre centroid',
                     outcome='worked', why='exam 8 passed')
    by_word = api.lexicon_find(text='boxy')
    assert by_word.startswith('[said] L0001') and 'eq peak 400 Hz' in by_word and 'worked: exam 8 passed' in by_word
    by_term = api.lexicon_find(text='eq peak')
    assert by_term.startswith('[means] L0001') and 'boxy' in by_term
    assert 'no entries' in api.lexicon_find(text='glassy')


def test_the_same_words_again_show_what_they_meant_before(lex):
    api.lexicon_note(said='too clean', means=['pick scrape', 'amp hum'], craft='sound designer', outcome='worked')
    again = api.lexicon_note(said='still too clean on the lead', craft='sound designer')
    assert 'the same words before:' in again and 'pick scrape' in again


def test_the_words_never_change_and_bad_values_say_what_to_use(lex):
    api.lexicon_note(said='muddy')
    with pytest.raises(OpError, match='never change'):
        api.lexicon_note(id='L0001', said='murky')
    with pytest.raises(OpError, match='mixing engineer'):
        api.lexicon_note(said='wide', craft='vibe curator')
    with pytest.raises(OpError, match='worked'):
        api.lexicon_note(id='L0001', outcome='great')
    with pytest.raises(OpError, match='verbatim'):
        api.lexicon_note(said='  ')
    with pytest.raises(OpError, match='lexicon_find'):
        api.lexicon_note(id='L0099', outcome='worked')
    lines = [json.loads(x) for x in open(lex, encoding='utf8')]
    assert [x['id'] for x in lines] == ['L0001']                 # failed calls wrote nothing


def test_the_view_reads_as_a_learning_curve(lex):
    api.lexicon_note(said='it sounds too bright', craft='Mixing_Engineer')
    api.lexicon_note(said='cut the 3 kHz bump with a narrow eq', craft='mixing engineer', means='eq peak 3k -4')
    api.lexicon_note(said='the colours feel too warm', craft='colorist')
    v = api.lexicon_view()
    assert 'mixing engineer 2' in v and 'colourist 1' in v
    assert 'trade words' in v and 'new entries per week' in v and 'not mapped yet: L0001, L0003' in v
    assert lexicon.trade_share('cut the 3 kHz bump with a narrow eq') > lexicon.trade_share('it sounds too bright')
    assert 'mixing engineer 2' not in api.lexicon_view(craft='colourist')
    assert 'no entries' in api.lexicon_view(who='friend')


def test_each_person_has_their_own_words(lex):
    api.lexicon_note(said='needs more stank', who='dj friend', craft='dj')
    assert 'stank' in api.lexicon_find(text='stank', who='dj friend')
    assert 'no entries' in api.lexicon_find(text='stank')


def test_objectives_are_kept_with_their_history_and_carried_into_versions(tmp_path):
    a = str(tmp_path / 'night_water')
    api.project_new(a, bpm=60, length_bars=8, objective='keep a listener asleep for 3 hours')
    api.project_set(a, objective='asleep for 3 hours, no sudden highs after midnight')
    info = api.project_info(a)
    assert "objective: 'asleep for 3 hours, no sudden highs after midnight' (by user" in info and '1 earlier' in info
    b = str(tmp_path / 'night_water_v2')
    api.project_new(b, bpm=60, length_bars=8, derived_from=a)
    info_b = api.project_info(b)
    assert 'objective: none stated' in info_b and "derived from night_water, whose objective was 'asleep" in info_b
    d = json.load(open(os.path.join(b, 'project.json'), encoding='utf8'))
    assert [o['text'] for o in d['lineage'][0]['objectives']] == ['keep a listener asleep for 3 hours',
                                                                 'asleep for 3 hours, no sudden highs after midnight']
    c = str(tmp_path / 'v3')
    api.project_new(c, bpm=60, length_bars=8, derived_from=b, objective='a 20-minute nap version')
    assert [x['name'] for x in json.load(open(os.path.join(c, 'project.json'), encoding='utf8'))['lineage']] == \
        ['night_water_v2', 'night_water']
    with pytest.raises(OpError, match='project.json'):
        api.project_new(str(tmp_path / 'x'), bpm=60, length_bars=8, derived_from=str(tmp_path / 'nowhere'))
