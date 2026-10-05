# Setting ismail up for a person

The goal is that the person hears a sound made with ismail on their own machine, having done as little as
possible themselves. They may be on a phone call with someone helping them, so every instruction you give them
is short enough to read aloud. Setup errors are yours to solve, not theirs: an onboarding that hands a person a
stack trace has failed.

## 0. Can you run commands on their computer?

ismail runs on the person's machine. You need a terminal: a coding agent (the Code tab in Claude's desktop app,
Claude Code, Cursor, Codex, or any agent that runs commands and can call MCP tools). A chat assistant in a browser
cannot set it up. If that is you, say so plainly, and tell the person which app to install and what to type in it
first. Installing that app is the one step only they can do.

## 1. Look before you install

Find out what is there before you change anything:
- the operating system and its version;
- Python 3.10 or newer (`python --version`, or `python3`; on Windows also `py -0`);
- `uv`, `ffmpeg` (for mp3s) and `git`;
- free disk space (about 2 GB is plenty; the optional sample sets add 20 to 520 MB each).

Write what you found in one line to the person ("You have Python 3.12; I'll add ffmpeg and ismail"). Don't list
versions at them.

## 2. Install what is missing, yourself

Use the system's package manager:
- **Windows:** `winget install --id Python.Python.3.12`, `astral-sh.uv`, `Gyan.FFmpeg`, `Git.Git` (add
  `--accept-package-agreements --accept-source-agreements`). Open a new shell afterwards, or use the full path, so
  the new PATH applies.
- **macOS:** Homebrew (`brew install python@3.12 uv ffmpeg git`). If Homebrew is missing, installing it asks for
  their password: tell them before it asks.
- **Linux:** the distribution's packages (`apt install python3 python3-venv ffmpeg git`), then uv from astral.sh.

Before any prompt that only the person can answer (an admin password, a Windows "Do you want to allow this app"
box, your own harness asking to run a command), say in one line what will appear and what to press. One step at a
time. Don't ask "shall I continue?" between routine steps. Ask only for decisions: what to make, a download over
about 100 MB, anything that costs money.

## 3. Install ismail

Pick the first route that fits:
- **In Claude Code or the desktop app's Code tab:** the plugin brings the tools and this skill in one step:
  `/plugin marketplace add newsbubbles/ismail`, then `/plugin install ismail@ismail`. Slash commands are typed
  by the person in the chat box: give them the exact line to paste.
- **Any MCP client:** register the server command
  `uvx --from git+https://github.com/newsbubbles/ismail ismail mcp`, the way that client adds MCP servers.
- **Without MCP:** make a virtual environment in a folder of their choice and run
  `pip install "ismail[live] @ git+https://github.com/newsbubbles/ismail"`. Then every op runs as
  `python -m ismail -p <project> <op> ...`.

Make a home for their music: a folder they can find again (Music/ismail or Documents/ismail). Tell them where it
is. Every song lives in its own subfolder there.

## 4. Prove it works, from their side

Call `guide`. Then make the smallest sound that proves the chain: `sketch` with their first words, or a 2-bar
project rendered with `mp3='also'`. Say that something is about to play, then open the file for them. It is
verified when they say they heard it, not when the render returns. If they hear nothing, check the volume, the
output device and the file before anything else.

## 5. When something fails

- Read the error and fix the cause. Retry once with the fix. Don't retry the same command unchanged.
- After two failed attempts at one step, tell them in one plain sentence what is blocked and the one thing they
  could do (or that you will take another route).
- Never ask them to read a log, edit a file, or type a command you could run.
- A step that failed or confused them is a finding: write it down, with the error and the fix, in the song's
  `HANDOFF.md` under "Setup". The maintainer reads every handoff, and the next person's setup gets better from
  it.

## 6. Then the first session

`guide` says how the first session runs. Learn early whether they play or read music, and speak their language
from then on (`user-experience.md`). A person who knows their instrument is the best judge ismail can have: what
they hear and how they name it are the data.
