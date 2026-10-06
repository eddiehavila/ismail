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
- **Windows:** one line per missing tool, each runnable as written:
  ```
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  winget install -e --id astral-sh.uv --accept-package-agreements --accept-source-agreements
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
  winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
  ```
  A new PATH does not reach a shell that is already open, and inside a desktop app "open a new shell" is not
  enough either. In PowerShell, reload it in place:
  `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')`,
  or call the tool by its full path.
- **macOS:** Homebrew (`brew install python@3.12 uv ffmpeg git`). If Homebrew is missing, installing it asks for
  their password: tell them before it asks.
- **Linux:** the distribution's packages (`apt install python3 python3-venv ffmpeg git`), then uv from astral.sh.

Before any prompt that only the person can answer (an admin password, a Windows "Do you want to allow this app"
box, your own harness asking to run a command), say in one line what will appear and what to press. One step at a
time. Don't ask "shall I continue?" between routine steps. Ask only for decisions: what to make, a download over
about 100 MB, anything that costs money.

## 3. Install ismail

**Tell them how long it takes before you start.** The first install downloads and builds the audio libraries:
about 5 minutes, and pip shows nothing while it works. Say "this takes about five minutes and looks frozen; it
isn't" so silence doesn't worry them. `uv pip install` is faster than pip and shows progress: prefer it when uv is
there.

Pick the first route that fits:
- **In Claude Code or the desktop app's Code tab:** the plugin brings the tools and this skill in one step.
  1. **Warm it up first.** The plugin starts its server with uvx, which builds the same libraries the first time
     it runs, and a first start that takes minutes can time out. Run the exact command once yourself before the
     plugin lines, and tell them it is the five-minute step:
     `uvx --python 3.12 --from git+https://github.com/newsbubbles/ismail ismail --help`.
  2. **The plugin lines.** Slash commands are typed by the person in the chat box: give them the exact lines to
     paste, one at a time: `/plugin marketplace add newsbubbles/ismail`, then `/plugin install ismail@ismail`.
  3. **The restart.** If ismail's tools aren't listed after the install, the app has to be closed and opened
     again. Say so before it happens, once: "I'll ask you to close this app and open it again; this conversation
     will still be here." Do the songs folder (below) first, so one restart covers both.
  4. **The Allow prompts.** The first time each ismail tool runs, the app asks whether to allow it. Tell them
     before the first one: "A box will ask to allow ismail. Press Allow (or Always allow, so it stops asking)."
- **Any MCP client:** register the server command
  `uvx --python 3.12 --from git+https://github.com/newsbubbles/ismail ismail mcp`, the way that client adds MCP
  servers, after warming it up as above.
- **Without MCP:** make a virtual environment in a folder of their choice and run
  `uv pip install "ismail[live] @ git+https://github.com/newsbubbles/ismail"` (or pip, which shows no progress).
  Then every op runs as `python -m ismail -p <project> <op> ...`, and each call takes 15 to 20 seconds to start.

**Make a home for their music**: a folder they can find again (Documents/ismail or Music/ismail). Tell them where
it is. Every song lives in its own subfolder there. Then point ismail at it with the `ISMAIL_SONGS` environment
variable, or ismail looks for songs next to the installed package: the first-session check (`guide`) and the
machine board (`machine`) won't see their songs.
- **Windows:** `setx ISMAIL_SONGS "%USERPROFILE%\Documents\ismail"` (new processes see it: the app restart
  above picks it up).
- **macOS and Linux:** `export ISMAIL_SONGS=~/Documents/ismail` in their shell profile; for an MCP client also put
  it in the server's `env` block, since desktop apps don't read shell profiles.

## 4. Prove it works, from their side

Call `guide`. Then make the smallest sound that proves the chain: `sketch` with their first words, or a 2-bar
project rendered with `mp3='also'`. Say that something is about to play, then open the file for them in their
default player: Windows `start "" "<file>.mp3"` (in PowerShell, `Invoke-Item "<file>.mp3"`), macOS
`open "<file>.mp3"`, Linux `xdg-open "<file>.mp3"`. It is
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

### Optional: the phone page

If they want to listen and talk back from their phone (`phone.md`), the phone and this computer need Tailscale,
signed in to the same account: install it on both (the person signs in; say what they will see), then
`phone_start` gives the address. Phones allow the microphone only on https pages, which Tailscale's address is.
Nothing is public.

## 6. Then the first session

`guide` says how the first session runs. Its first question can carry whether they play or read music ("what is
it for, and do you play?"), so they answer two questions, not three. Speak their language from then on
(`user-experience.md`).

If `machine` says WAIT while you set up or render (an antivirus scan, an update), wait quietly: tell someone new
"the computer is busy, one moment" and never ask them to close a program. A person who knows their instrument is the best judge ismail can have: what
they hear and how they name it are the data.
