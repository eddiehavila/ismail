"""Fit a track's parameters in context: render the track's stem group over a bar window and score it against the
same window of the reference stem (CLAP perceptual similarity + band-level distance)."""
import copy
import os
import tempfile

import numpy as np
import soundfile as sf

from . import sounddesign as SD
from .render import Renderer, write_wav


def _path_get(tr, path):
    root, rest = path.split('.', 1) if '.' in path else (path, None)
    if root == 'inst':
        from .instruments import normalize
        return SD._get(normalize(tr['instrument']), rest)
    if root == 'fx':
        from .fx import normalize as fxn
        i, p = rest.split('.', 1)
        return SD._get(fxn(tr['fx'][int(i)]), p)
    return tr[path]  # volume_db, pan


def _path_set(tr, path, v):
    root, rest = path.split('.', 1) if '.' in path else (path, None)
    if root == 'inst':
        try:
            SD._set(tr['instrument'], rest, v)
        except (KeyError, IndexError):
            d = tr['instrument']
            ks = rest.split('.')
            for k in ks[:-1]:
                d = d[int(k)] if isinstance(d, list) else d.setdefault(k, {})
            d[ks[-1]] = v
    elif root == 'fx':
        i, p = rest.split('.', 1)
        tr['fx'][int(i)][p] = v
    else:
        tr[path] = v


def fit_track(project_dict, root, grid, track, params, bars, group, ref_path, iters=40, seed=0, w_perc=10.0,
              w_band=0.15, defaults=None):
    """params: {path: [lo, hi]} with paths 'inst.<...>', 'fx.<i>.<param>', 'volume_db'. Returns
    (best_values, best_score, start_score, best_parts, start_parts)."""
    from . import perceptual as PC
    rng = np.random.default_rng(seed)
    starts = list(range(bars[0], bars[1] + 1, 2))
    ref_emb = PC.embed_windows(ref_path, grid, starts, 2)
    yr, srr = sf.read(ref_path, always_2d=True, dtype='float64')
    a, b = int(max(grid.bar_time(bars[0]), 0) * srr), int(grid.bar_time(bars[1] + 1) * srr)
    ref_desc = SD.descriptor(yr[a:b].T)
    tmp = os.path.join(tempfile.gettempdir(), f"ismail_trackfit_{os.getpid()}.wav")
    keys = list(params)
    lo = np.array([params[k][0] for k in keys], float)
    hi = np.array([params[k][1] for k in keys], float)
    logk = np.array([lo[i] > 0 and hi[i] / lo[i] > 8 for i in range(len(keys))])

    def from_u(u):
        u = np.clip(u, 0, 1)
        return np.where(logk, np.exp(np.log(np.maximum(lo, 1e-12)) + u * (np.log(np.maximum(hi, 1e-12)) -
                                                                            np.log(np.maximum(lo, 1e-12)))),
                        lo + u * (hi - lo))

    def to_u(v):
        return np.where(logk, (np.log(v) - np.log(np.maximum(lo, 1e-12))) /
                        (np.log(np.maximum(hi, 1e-12)) - np.log(np.maximum(lo, 1e-12))), (v - lo) / (hi - lo))

    def evaluate(v):
        d = copy.deepcopy(project_dict)
        tr = d['tracks'][track]
        for k, x in zip(keys, v):
            _path_set(tr, k, float(x))
        R = Renderer(d, root, bars[0], bars[1] + 1, group, cache=True)
        y, _ = R.run()
        # the partial render starts at bars[0]; pad so bar times line up with the full-song grid
        lead = int(round(max(grid.bar_time(bars[0]), 0) * R.sr))
        full = np.zeros((2, lead + y.shape[1]))
        full[:, lead:] = y
        write_wav(tmp, full, R.sr)
        emb = PC.embed_windows(tmp, grid, starts, 2)
        perc = float(np.mean(np.sum(emb * ref_emb, 1)))
        dd, parts = SD.distance(SD.descriptor(y[:, :b - a] if y.shape[1] >= b - a else y), ref_desc,
                                w_env=0.0, w_width=5.0, w_peak=0.0)
        score = w_perc * (1 - perc) + w_band * parts['band_db'] + 0.5 * abs(parts['width'])
        return score, {'perceptual': perc, 'band_db': parts['band_db'], 'width_diff': parts['width']}

    start_v = np.clip(np.array([float(_path_get(project_dict['tracks'][track], k)) if _has(project_dict['tracks'][track], k)
                                else (defaults or {}).get(k, (params[k][0] + params[k][1]) / 2) for k in keys]), lo, hi)
    best_s, best_p = evaluate(start_v)
    s0, p0 = best_s, best_p
    best_u = to_u(start_v)
    sigma = 0.25
    for it in range(iters):
        u = rng.random(len(keys)) if it < max(4, iters // 5) else best_u + rng.normal(0, sigma, len(keys))
        s, p = evaluate(from_u(u))
        if s < best_s:
            best_s, best_p, best_u = s, p, np.clip(u, 0, 1)
            sigma = min(sigma * 1.3, 0.35)
        elif it >= max(4, iters // 5):
            sigma = max(sigma * 0.9, 0.03)
    if os.path.exists(tmp):
        os.remove(tmp)
    return {k: float(v) for k, v in zip(keys, from_u(best_u))}, best_s, s0, best_p, p0


def _has(tr, path):
    try:
        _path_get(tr, path)
        return True
    except (KeyError, IndexError, ValueError, TypeError):
        return False
