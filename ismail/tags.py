"""ID3 tags on every mp3 ismail writes: what it is, who made it, when, and that ismail made it, with the link back
(Nate, 2026-10-06: "make sure that we put ismail with the ismail GitHub link reference in the MP3 ID3 data, because
that's very important for provenance whenever we're shipping out MP3s"). Tags only: the audio is never re-encoded.
"""
import datetime
import os

HOME_URL = 'https://github.com/newsbubbles/ismail'
MADE_WITH = f'Made with ismail ({HOME_URL})'


def tag_mp3(path, title=None, artist=None, album=None, date=None, comment=None):
    """Write the tags into `path` (an mp3), keeping any other tags it has. title: what it is (default: the file
    name); artist: who made it (default 'ismail'); album: the song or set it belongs to; date: YYYY-MM-DD (default
    today); comment: added after the made-with line. -> the tags written, as a dict."""
    from mutagen.id3 import COMM, ID3, ID3NoHeaderError, TALB, TDRC, TENC, TIT2, TPE1, TSSE, WOAS, WXXX
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    title = title or os.path.splitext(os.path.basename(path))[0].replace('_', ' ')
    vals = {'title': title, 'artist': artist or 'ismail', 'album': album, 'date': date or datetime.date.today().isoformat(),
            'comment': MADE_WITH + (f'. {comment}' if comment else '')}
    tags.setall('TIT2', [TIT2(encoding=3, text=vals['title'])])
    tags.setall('TPE1', [TPE1(encoding=3, text=vals['artist'])])
    if album:
        tags.setall('TALB', [TALB(encoding=3, text=album)])
    tags.setall('TDRC', [TDRC(encoding=3, text=vals['date'])])
    tags.setall('TENC', [TENC(encoding=3, text='ismail')])
    tags.setall('TSSE', [TSSE(encoding=3, text=f'ismail ({HOME_URL})')])
    tags.setall('WOAS', [WOAS(url=HOME_URL)])
    tags.setall('WXXX', [WXXX(encoding=3, desc='ismail', url=HOME_URL)])
    tags.setall('COMM', [COMM(encoding=3, lang='eng', desc='', text=vals['comment'])])
    tags.save(path, v2_version=3)                  # ID3v2.3: what phones, players and SoundCloud read best
    return vals


def read_tags(path):
    """The tags ismail cares about, for checks: {title, artist, album, date, encoder, url, comment}."""
    from mutagen.id3 import ID3, ID3NoHeaderError
    try:
        t = ID3(path)
    except ID3NoHeaderError:
        return {}
    g = lambda k: str(t[k].text[0]) if k in t and getattr(t[k], 'text', None) else None   # noqa: E731
    url = t.getall('WOAS')
    comm = t.getall('COMM')
    return {'title': g('TIT2'), 'artist': g('TPE1'), 'album': g('TALB'), 'date': g('TDRC'), 'encoder': g('TENC'),
            'url': url[0].url if url else None, 'comment': str(comm[0].text[0]) if comm else None}
