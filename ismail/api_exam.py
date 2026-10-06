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
