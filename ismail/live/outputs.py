"""Where the live engine's sound goes.

The default output: a speaker that connects after the engine started is not in this process's device list, so the
current default is asked of a fresh process.
"""
import subprocess
import sys


def default_output_name(timeout=5.0):
    """The system's default output as PortAudio names it now, asked of a fresh process (this one's device list was
    read when it started). None when it cannot tell."""
    code = "import sounddevice as sd; print(sd.query_devices(kind='output')['name'])"
    kw = {}
    if sys.platform == 'win32':
        kw['creationflags'] = 0x08000000 | 0x00004000        # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
    try:
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=timeout, **kw)
        name = r.stdout.strip()
        return name or None
    except (OSError, subprocess.SubprocessError):
        return None
