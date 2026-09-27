"""The clock: a song's project.json -> frame-exact note events + per-frame loudness features.

Frame of a note = round(beat * fps * 60 / bpm). At 150 BPM and 30 fps a beat is 12 frames, a 16th 3, a bar 48:
every cut lands on a whole frame. Other tempos work, but check `frames_per_beat` in the output.

Notes on a track that plays the growl voice get `fam` (velocity // 10: yoi, wub, screech, metal, dive, zap, grind,
chop, talk, robot, howl); config.json "families" names any track's codes, e.g. {"gun": {"10": "bang"}} or talk
words {"growl": {"91": "name"}}.
"""
import json
import os

import numpy as np

from . import config, master_wav, video_dir

GROWL = {1: 'yoi', 2: 'wub', 3: 'screech', 4: 'metal', 5: 'dive', 6: 'zap', 7: 'grind', 8: 'chop', 9: 'talk',
         11: 'robot', 12: 'howl'}


def _is_growl(inst):
    if not isinstance(inst, dict) or inst.get('type') != 'code':
        return False
    return inst.get('voice') == 'growl' or 'def wub(' in (inst.get('code') or '')


def load_project(song):
    return json.load(open(os.path.join(song, 'proj', 'project.json')))


def events(song):
    p = load_project(song)
    c = config(song)
    fps, bpm = c['fps'], p['bpm']
    fpb = fps * 60.0 / bpm
    off = float(p.get('offset_sec') or 0.0) * fps
    names = c['families']
    out = {}
    for name, tr in p['tracks'].items():
        growl = _is_growl(tr.get('instrument'))
        fam_names = names.get(name, {})
        ev = []
        for beat, pitch, dur, vel in tr['notes']:
            e = {'f': int(round(beat * fpb + off)), 'beat': beat, 'pitch': pitch,
                 'len': max(1, int(round(dur * fpb))), 'vel': vel}
            fam = fam_names.get(str(vel))
            if fam is None and growl:
                fam = GROWL.get(vel // 10, 'other')
            if fam is not None:
                e['fam'] = fam
            ev.append(e)
        out[name] = sorted(ev, key=lambda e: e['f'])
    return {'fps': fps, 'bpm': bpm, 'frames_per_beat': fpb, 'beats_per_bar': p.get('beats_per_bar', 4),
            'offset_frames': off, 'length_bars': p['length_bars'], 'tracks': out}


def features(song, total):
    import soundfile as sf
    from scipy.signal import butter, sosfilt
    x, sr = sf.read(master_wav(song), dtype='float32')
    m = x.mean(1) if x.ndim > 1 else x
    fps = config(song)['fps']
    hop = sr / fps
    bands = {'full': m,
             'sub': sosfilt(butter(4, 90, 'low', fs=sr, output='sos'), m),
             'mid': sosfilt(butter(4, [250, 2500], 'band', fs=sr, output='sos'), m),
             'high': sosfilt(butter(4, 5000, 'high', fs=sr, output='sos'), m)}
    out = {}
    for k, sig in bands.items():
        v = np.zeros(total, np.float32)
        for i in range(total):
            seg = sig[int(i * hop):int((i + 1) * hop)]
            v[i] = np.sqrt(np.mean(seg ** 2)) if len(seg) else 0.0
        out[k] = v
        out[k + '_n'] = v / (np.percentile(v, 99) + 1e-9)
    return out


def run(song):
    import soundfile as sf
    vd = video_dir(song)
    os.makedirs(os.path.join(vd, 'build'), exist_ok=True)
    ev = events(song)
    fps = ev['fps']
    info = sf.info(master_wav(song))
    ev['total_frames'] = int(round(info.duration * fps))
    ev['master'] = master_wav(song)
    json.dump(ev, open(os.path.join(vd, 'build', 'events.json'), 'w'))
    np.savez(os.path.join(vd, 'build', 'features.npz'), **features(song, ev['total_frames']))
    fpb = ev['frames_per_beat']
    print(f"{ev['bpm']} BPM at {fps} fps: {fpb:g} frames per beat" + ('' if abs(fpb - round(fpb)) < 1e-9 else
          '  (NOT whole frames: cuts round to the nearest frame)'))
    print(f"master {os.path.basename(ev['master'])}: {info.duration:.2f} s = {ev['total_frames']} frames")
    for k, v in ev['tracks'].items():
        fams = sorted({e['fam'] for e in v if 'fam' in e})
        print(f"  {k:10s} {len(v):5d} events" + (f"  fam: {', '.join(fams)}" if fams else ''))
    return ev
