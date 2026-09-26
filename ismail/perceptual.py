"""Learned perceptual similarity (CLAP audio embeddings) per bar window.

Handcrafted features (notes, onsets, bands) can all match while the result still sounds different: timbre,
fusion of partials into one tone, texture. A pretrained audio model is the check against that self-deception.
The model (laion/clap-htsat-unfused, ~600 MB) is cached under <repo>/hf_cache unless HF_HOME is set.
"""
import os

import numpy as np

os.environ.setdefault('HF_HOME', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hf_cache'))

_MODEL = None
MODEL_ID = 'laion/clap-htsat-unfused'
SR = 48000


def available():
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _model():
    global _MODEL
    if _MODEL is None:
        import torch
        from transformers import ClapModel, ClapProcessor
        m = ClapModel.from_pretrained(MODEL_ID)
        dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        _MODEL = (m.to(dev).eval(), ClapProcessor.from_pretrained(MODEL_ID), dev)
    return _MODEL


def embed_windows(path, grid, starts, span_bars=2):
    """Unit-norm CLAP embeddings for windows [bar, bar + span_bars) at each start bar."""
    import torch
    import soundfile as sf
    import librosa
    m, proc, dev = _model()
    y, sr = sf.read(path, always_2d=True, dtype='float32')
    y = librosa.resample(y.mean(1), orig_sr=sr, target_sr=SR)
    segs = []
    for b in starts:
        a, e = int(max(grid.bar_time(b), 0) * SR), int(max(grid.bar_time(b + span_bars), 0) * SR)
        seg = y[a:e]
        if len(seg) < SR:
            seg = np.pad(seg, (0, SR - len(seg)))
        segs.append(seg)
    out = []
    for i in range(0, len(segs), 8):
        inp = proc(audio=segs[i:i + 8], sampling_rate=SR, return_tensors='pt')
        with torch.no_grad():
            e = m.get_audio_features(**{k: v.to(dev) for k, v in inp.items()})
        e = getattr(e, 'pooler_output', e)
        out.append(torch.nn.functional.normalize(e, dim=-1).cpu().numpy())
    return np.concatenate(out)


def compare(path_a, path_b, grid, n_bars, span_bars=2, loop_bars=8):
    """Per-window cosine similarity A vs B, plus B-vs-B baselines one loop later and half a loop off."""
    starts = list(range(1, n_bars - span_bars + 2, span_bars))
    A = embed_windows(path_a, grid, starts, span_bars)
    B = embed_windows(path_b, grid, starts, span_bars)
    sims = np.sum(A * B, 1)
    idx = {b: i for i, b in enumerate(starts)}

    def base(shift):
        v = [float(B[idx[b]] @ B[idx[b + shift]]) for b in starts if b + shift in idx and b > 16]
        return float(np.mean(v)) if v else None
    return {'starts': starts, 'sims': sims.tolist(), 'self_loop': base(loop_bars), 'half_loop': base(loop_bars // 2)}
