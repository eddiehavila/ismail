"""Step-grid feature extraction: one row per grid step (default 16th note) for a whole file.

This is the shared perception layer: structure maps, comparisons and zoom views all read these arrays.
Arrays (n = number of steps from bar 1):
  level   (n,)     dB RMS, full band
  bands   (n, 6)   dB per band (sub bass lowmid mid himid air)
  hits    (n, 3)   drum-lane hit level in dB relative to the lane's loud hits (-120 = no hit); lanes low/snare/hat
  sal     (n, P)   pitch salience per semitone, dB rel. file max (P = 84 from C1)
  notes   (n, P)   harmonic-explained salience: the notes judged to be sounding (dB, -120 = not sounding)
  width   (n,)     side/mid energy ratio
  centroid(n,)     Hz
"""
import hashlib
import os

import numpy as np
import librosa

from . import analysis as A

VERSION = 7
LANES = ('low', 'snare', 'hat')
LANE_BANDS = {'low': (30, 120), 'snare': (1000, 5000), 'hat': (7000, 16000)}
PITCH_BASE = 24  # C1
NP = 84
BAND_NAMES = [b[0] for b in A.BANDS]


def _key(path, grid, spb):
    st = os.stat(path)
    blob = f"{os.path.abspath(path)}|{st.st_mtime}|{st.st_size}|{grid.bpm}|{grid.offset}|{grid.bpb}|{spb}|{VERSION}"
    return hashlib.sha1(blob.encode()).hexdigest()[:20]


def extract(path, grid, steps_per_beat=4, cache_dir=None):
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cp = os.path.join(cache_dir, 'feat_' + _key(path, grid, steps_per_beat) + '.npz')
        if os.path.exists(cp):
            with np.load(cp) as z:
                return {k: z[k] for k in z.files}
    sr = A.ASR
    y = A.load(path)
    ys = A.load(path, stereo=True)
    step_t = grid.spb / steps_per_beat
    dur = len(y) / sr
    n = int(np.floor((dur - grid.offset) / step_t))
    starts = grid.offset + np.arange(n) * step_t

    def to_steps(frame_times, values, how='mean'):
        """Aggregate per-frame values (frames, ...) into steps by frame time."""
        idx = np.floor((frame_times - grid.offset) / step_t).astype(int)
        ok = (idx >= 0) & (idx < n)
        idx, vals = idx[ok], values[ok]
        cnt = np.bincount(idx, minlength=n).astype(float)
        if vals.ndim == 1:
            s = np.bincount(idx, weights=vals, minlength=n)
            return s / np.maximum(cnt, 1)
        out = np.stack([np.bincount(idx, weights=vals[:, j], minlength=n) for j in range(vals.shape[1])], 1)
        return out / np.maximum(cnt, 1)[:, None]

    # --- levels, bands, centroid
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)) ** 2
    ft = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    bandp = np.stack([S[(freqs >= lo) & (freqs < hi)].sum(0) for _, lo, hi in A.BANDS], 1)
    totp = S.sum(0)
    cent = (freqs[:, None] * S).sum(0) / (totp + 1e-12)
    ref = S.shape[0]  # normalisation constant so dB values are comparable across files
    level = 10 * np.log10(to_steps(ft, totp) / ref + 1e-12)
    bands = 10 * np.log10(to_steps(ft, bandp) / ref + 1e-12)
    centroid = to_steps(ft, cent)

    # --- transient sharpness: mean positive dB rise per frame in 200 Hz - 6 kHz (hard synth attacks vs soft tails)
    Sm = S[(freqs > 200) & (freqs < 6000)]
    Ld = np.maximum(10 * np.log10(Sm / (Sm.max() + 1e-12) + 1e-12), -50.0)  # floor: digital silence is not a transient
    rise = np.r_[0.0, np.maximum(np.diff(Ld, axis=1), 0).mean(0)]
    idx = np.floor((ft - grid.offset) / step_t).astype(int)
    ok = (idx >= 0) & (idx < n)
    flux = np.zeros(n)
    np.maximum.at(flux, idx[ok], rise[ok])

    # --- stereo width
    mid = (ys[0] + ys[1]) / 2
    side = (ys[0] - ys[1]) / 2
    fr = 1024
    m2 = librosa.feature.rms(y=mid, frame_length=fr, hop_length=hop)[0] ** 2
    s2 = librosa.feature.rms(y=side, frame_length=fr, hop_length=hop)[0] ** 2
    wt = librosa.frames_to_time(np.arange(len(m2)), sr=sr, hop_length=hop)
    width = np.sqrt(to_steps(wt, s2) / (to_steps(wt, m2) + 1e-12))

    # --- drum lanes: onset peaks graded by band level
    h2 = 128
    S2 = np.abs(librosa.stft(y, n_fft=1024, hop_length=h2))
    f2 = librosa.fft_frequencies(sr=sr, n_fft=1024)
    fps2 = sr / h2
    hits = np.full((n, 3), -120.0)
    for li, lane in enumerate(LANES):
        lo, hi = LANE_BANDS[lane]
        m = (f2 >= lo) & (f2 < hi)
        env = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S2[m], ref=np.max), sr=sr, hop_length=h2,
                                           lag=1, max_size=3)
        lvl = librosa.amplitude_to_db(np.sqrt((S2[m] ** 2).mean(0)) + 1e-9, ref=np.max(S2) + 1e-9)
        pk = librosa.util.peak_pick(env, pre_max=3, post_max=3, pre_avg=10, post_avg=10,
                                    delta=float(np.std(env)) * 0.8, wait=int(fps2 * 0.06))
        if len(pk) == 0:
            continue
        w = int(0.03 * fps2)
        pl = np.array([lvl[p:p + w].max() for p in pk])
        refl = np.percentile(pl, 90)
        for p, l in zip(pk, pl):
            t = p / fps2
            s = int(round((t - grid.offset) / step_t))
            if 0 <= s < n and abs(t - starts[s]) < step_t * 0.45:
                hits[s, li] = max(hits[s, li], l - refl)

    # --- pitch salience and explained notes
    nocts = A._max_octaves('C1', 7)
    E = A._salience(y, 'C1', nocts, hop=hop)  # (semitones, frames)
    P = E.shape[0]
    et = librosa.frames_to_time(np.arange(E.shape[1]), sr=sr, hop_length=hop)
    Es = to_steps(et, E.T)  # (n, P) amplitude
    gmax = Es.max() + 1e-12
    sal = 20 * np.log10(Es / gmax + 1e-9)
    notes = np.full((n, P), -120.0)
    # a sounding note is a local peak standing >= 3 dB over its semitone neighbours; broadband smears
    # (kick sub, noise) fail this test
    pad_v = np.pad(Es, ((0, 0), (1, 1)), mode='edge')
    neigh = np.maximum(pad_v[:, :-2], pad_v[:, 2:])
    peaky = Es >= neigh * 1.41
    for s in range(n):
        v = Es[s]
        rem = np.where(peaky[s], v, 0.0)
        for _ in range(18):
            i = int(np.argmax(rem))
            d = 20 * np.log10(rem[i] / gmax + 1e-9)
            if d < -45:
                break
            notes[s, i] = d
            for hmul in (1, 2, 3, 4, 5, 6):
                j = int(round(i + 12 * np.log2(hmul)))
                if j < P:
                    rem[j] = 0.0 if hmul == 1 else max(0.0, rem[j] - v[i] * 0.6 / hmul)
                if hmul > 1:
                    for jj in (j - 1, j + 1):
                        if 0 <= jj < P:
                            rem[jj] *= 0.7
            if (notes[s] > -120).sum() >= 8:
                break
    if P < NP:
        pad = np.full((n, NP - P), -120.0)
        sal = np.concatenate([sal, np.full((n, NP - P), -120.0)], 1)
        notes = np.concatenate([notes, pad], 1)
    out = {'level': level, 'bands': bands, 'hits': hits, 'sal': sal, 'notes': notes, 'width': width,
           'centroid': centroid, 'flux': flux, 'meta': np.array([grid.bpm, grid.offset, grid.bpb, steps_per_beat, dur])}
    if cache_dir:
        np.savez_compressed(cp, **out)
    return out


def note_sets(F, rel_db=18.0, floor_db=-40.0):
    """Boolean (n, P): notes within rel_db of the step's loudest note and above floor_db (file-relative)."""
    nt = F['notes']
    top = nt.max(1, keepdims=True)
    return (nt > floor_db) & (nt >= top - rel_db)


def note_attacks(F, sets=None, rise_db=6.0):
    """Boolean (n, P): a note starts (not sounding before, or salience rose >= rise_db)."""
    """A note starts where it was not sounding on the previous step, or where it rises >= rise_db MORE than the
    overall level rose (so sidechain pumping, which lifts everything together, is not read as re-attacks)."""
    sets = note_sets(F) if sets is None else sets
    n = sets.shape[0]
    sal = F['sal'][:n]
    lvl = F['level'][:n]
    prev_set = np.vstack([np.zeros((1, sets.shape[1]), bool), sets[:-1]])
    prev_sal = np.vstack([np.full((1, sal.shape[1]), -120.0), sal[:-1]])
    dl = np.r_[0.0, np.diff(lvl)][:, None]
    return sets & (~prev_set | ((sal - prev_sal) - np.maximum(dl, 0) >= rise_db))


def hit_sets(F, thresh_db=-16.0):
    return F['hits'] > thresh_db


def steps_per_bar(F):
    m = F['meta']
    return int(m[2] * m[3])
