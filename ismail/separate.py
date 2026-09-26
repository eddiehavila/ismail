"""Source separation with demucs."""
import os

import numpy as np
import soundfile as sf


def separate(path, outdir, model='htdemucs_ft'):
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    m = get_model(model)
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    m.eval().to(dev)
    y, sr = sf.read(path, dtype='float32', always_2d=True)
    if sr != m.samplerate:
        import librosa
        y = librosa.resample(y.T, orig_sr=sr, target_sr=m.samplerate).T
        sr = m.samplerate
    if y.shape[1] == 1:
        y = np.repeat(y, 2, axis=1)
    x = torch.from_numpy(y.T.copy())[None].to(dev)
    ref = x.mean(1, keepdim=True)
    mu, sd = ref.mean(), ref.std()
    with torch.no_grad():
        out = apply_model(m, (x - mu) / sd, device=dev, split=True, overlap=0.25, progress=False)[0] * sd + mu
    os.makedirs(outdir, exist_ok=True)
    for name, s in zip(m.sources, out):
        sf.write(os.path.join(outdir, name + '.wav'), s.cpu().numpy().T, sr)
    return list(m.sources)
