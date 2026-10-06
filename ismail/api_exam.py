"""exam_check: the pre-flight every exam runs before it reaches the person (ismail/exam_check.py has the checks)."""
from .api import OpError, op
from . import exam_check as EC


@op()
def exam_check(clips: list = None, page: str = None, key: dict = None, secrets: list = None,
               answers_path: str = None, submit_url: str = None, submit_body: dict = None,
               lufs_tol: float = 1.0) -> str:
    """Run before any exam page goes to the person; show it only on READY. Checks that every clip exists and decodes,
    that the clips sit within lufs_tol of one loudness, and that a blind exam cannot be told by anything but the
    sound: given key={clip label, file name or path: its class} and secrets=[source names, words that must not show],
    no class or secret in file names, URLs, metadata tags or the page source (or the scripts and styles it loads), no
    key file the page loads, no format, length, leading-silence or order that separates the classes. submit_url +
    answers_path: posts a test answer marked preflight and checks it lands where you read answers. clips: paths or
    [{label, path}]; page: the exam's HTML file or its URL (its clips are found when clips is none)."""
    try:
        ready, lines = EC.run(clips=clips, page=page, key=key, secrets=secrets, answers_path=answers_path,
                              submit_url=submit_url, submit_body=submit_body, lufs_tol=lufs_tol)
    except (OSError, ValueError) as e:
        raise OpError(f"exam_check: {e}")
    return '\n'.join(lines)


@op()
def exam_eye_crops(pairs: list, out: str, windows: list = None, n_windows: int = 3, seed: int = 0) -> str:
    """The blind crop check, step 1 (a gate before a real-vs-made exam): the same time window cut from the real and
    the made clip of each pair, as spectrogram images side by side ("1" and "2" in a random order), with the key
    hidden. pairs: [[real_path, made_path], ...]; windows: per pair, [[t0, t1], ...] in seconds (a word +-60 ms),
    else n_windows through each clip. Look at every out/q*.png and pick the side that looks real, WITHOUT opening
    out/key.json, then exam_eye_score(out, {1: '2', 2: '1', ...}). If you can tell from the picture, so can they."""
    from . import exam_check as EC
    try:
        n = EC.eye_crops(pairs, out, windows, n_windows, seed=seed)
    except (OSError, ValueError, RuntimeError) as e:
        raise OpError(f"exam_eye_crops: {e}")
    return (f"{n} crop pairs in {out} (q01.png ... q{n:02d}.png; questions.json says each one's pair and window). "
            f"Do not open key.json. Look at each and pick the side that looks real, then exam_eye_score(out, "
            f"{{1: '1' or '2', ...}}).")


@op()
def exam_eye_score(out: str, answers: dict) -> str:
    """The blind crop check, step 2: score your picks from exam_eye_crops against the hidden key. NOT READY when
    you beat chance (p < 0.05): the picture gives the real side away, so the person will likely hear it too."""
    from . import exam_check as EC
    try:
        ok, lines = EC.eye_score(out, answers)
    except (OSError, ValueError) as e:
        raise OpError(f"exam_eye_score: {e}")
    return '\n'.join(lines)
